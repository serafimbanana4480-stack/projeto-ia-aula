/**
 * Chooses how an expanded tool result should be drawn.
 *
 * A line chart needs a real series: every row is an object with the same
 * x key and the same y key, both present, and at least two finite y values.
 * A missing number is skipped by rejecting the series — it is never filled
 * with zero. A table uses only keys that exist on every row and hold a
 * scalar. Anything else stays plain text.
 */

export interface SeriesPoint {
  x: string | number;
  y: number;
}

export interface ToolResultSeries {
  kind: "series";
  points: SeriesPoint[];
  /** Present only when the payload itself carries a non-empty string unit. */
  unit?: string;
  summary: string;
}

export interface ToolResultTable {
  kind: "table";
  columns: string[];
  rows: Array<Record<string, string | number | boolean | null>>;
}

export interface ToolResultNone {
  kind: "none";
}

export type ToolResultView = ToolResultSeries | ToolResultTable | ToolResultNone;

const SERIES_ARRAY_KEYS = ["series", "points", "data", "values", "timeline", "samples", "rows"] as const;
const Y_KEYS = ["y", "value", "v"] as const;
const X_KEYS = ["x", "t", "time", "timestamp", "date", "label"] as const;

const NONE: ToolResultNone = { kind: "none" };

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function readUnit(source: Record<string, unknown> | null): string | undefined {
  if (!source) return undefined;
  const unit = source.unit ?? source.y_unit ?? source.yUnit;
  return typeof unit === "string" && unit.trim() !== "" ? unit : undefined;
}

function axisKey(row: Record<string, unknown>, keys: readonly string[]): string | null {
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(row, key)) return key;
  }
  return null;
}

/**
 * Every row must carry a real x and a finite y on the same keys.
 * A hole, a stringified number, or a null does not become a point.
 */
function readSeries(rows: unknown[]): SeriesPoint[] | null {
  if (rows.length < 2 || rows.some((row) => !isRecord(row))) return null;
  const records = rows as Record<string, unknown>[];
  const xKey = axisKey(records[0], X_KEYS);
  const yKey = axisKey(records[0], Y_KEYS);
  if (!xKey || !yKey) return null;

  const points: SeriesPoint[] = [];
  for (const row of records) {
    if (axisKey(row, X_KEYS) !== xKey || axisKey(row, Y_KEYS) !== yKey) return null;
    const y = finiteNumber(row[yKey]);
    const rawX = row[xKey];
    const x =
      typeof rawX === "number" && Number.isFinite(rawX)
        ? rawX
        : typeof rawX === "string" && rawX.trim() !== ""
          ? rawX
          : null;
    if (y === null || x === null) return null;
    points.push({ x, y });
  }
  return points.length >= 2 ? points : null;
}

function scalar(value: unknown): string | number | boolean | null | undefined {
  if (value === null) return null;
  if (typeof value === "string" || typeof value === "boolean") return value;
  if (typeof value === "number" && Number.isFinite(value)) return value;
  return undefined;
}

/** Columns are the keys shared by every row whose values are all scalars. */
function readTable(rows: unknown[]): ToolResultTable | null {
  if (rows.length < 2 || rows.some((row) => !isRecord(row))) return null;
  const records = rows as Record<string, unknown>[];
  const firstKeys = Object.keys(records[0]);
  const columns = firstKeys.filter((key) =>
    records.every((row) => Object.prototype.hasOwnProperty.call(row, key) && scalar(row[key]) !== undefined),
  );
  if (columns.length === 0) return null;
  return {
    kind: "table",
    columns,
    rows: records.map((row) => {
      const shaped: Record<string, string | number | boolean | null> = {};
      for (const key of columns) shaped[key] = scalar(row[key]) as string | number | boolean | null;
      return shaped;
    }),
  };
}

export function describeSeries(points: readonly SeriesPoint[], unit?: string): string {
  const first = String(points[0]?.x ?? "");
  const last = String(points[points.length - 1]?.x ?? "");
  const base = `${points.length} pontos, de ${first} a ${last}`;
  return unit ? `${base} (${unit})` : base;
}

function classifyArray(rows: unknown[], unitSource: Record<string, unknown> | null): ToolResultView {
  const points = readSeries(rows);
  if (points) {
    const unit = readUnit(unitSource);
    return { kind: "series", points, unit, summary: describeSeries(points, unit) };
  }
  return readTable(rows) ?? NONE;
}

function classifyRecord(record: Record<string, unknown>): ToolResultView {
  for (const key of SERIES_ARRAY_KEYS) {
    const candidate = record[key];
    if (!Array.isArray(candidate)) continue;
    const view = classifyArray(candidate, record);
    if (view.kind !== "none") return view;
  }
  if (isRecord(record.result)) {
    const nested = classifyRecord(record.result);
    if (nested.kind !== "none") return nested;
  } else if (Array.isArray(record.result)) {
    return classifyArray(record.result, record);
  }
  return NONE;
}

export function classifyToolResult(value: unknown): ToolResultView {
  if (Array.isArray(value)) return classifyArray(value, null);
  if (!isRecord(value)) return NONE;
  return classifyRecord(value);
}
