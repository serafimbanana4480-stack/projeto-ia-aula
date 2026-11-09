/**
 * Fenced blocks the assistant can emit so the chat draws data instead of
 * dumping numbers into a paragraph. The renderer never computes a metric the
 * model did not write: a bar length comes from the given numbers, a stat card
 * prints the given string.
 */

export const RICH_ICONS = [
  "chart",
  "globe",
  "code",
  "image",
  "search",
  "bot",
  "file",
  "check",
  "alert",
  "database",
  "terminal",
  "spark",
  "list",
  "shield",
] as const;

export type RichIconName = (typeof RICH_ICONS)[number];

export type RichStatus = "ok" | "pending" | "warn" | "fail" | "info";
export type RichTone = "info" | "warning" | "success" | "danger";

export interface RichStatItem {
  value: string;
  label: string;
  hint?: string;
}

export interface RichChartBar {
  label: string;
  value: number;
}

export interface RichStatusRow {
  name: string;
  state: RichStatus;
  label: string;
}

export interface RichCardItem {
  icon: RichIconName;
  title: string;
  text?: string;
}

export interface RichSourceItem {
  title: string;
  url: string;
  note?: string;
}

export interface RichFlowNode {
  label: string;
  hint?: string;
}

export interface RichMeterPart {
  label: string;
  value: string;
}

export type RichBlock =
  | { kind: "stats"; items: RichStatItem[] }
  | { kind: "chart"; title: string; unit?: string; bars: RichChartBar[] }
  | { kind: "status"; title?: string; rows: RichStatusRow[] }
  | { kind: "cards"; items: RichCardItem[] }
  | { kind: "callout"; tone: RichTone; title?: string; text: string }
  | { kind: "sources"; items: RichSourceItem[] }
  | { kind: "flow"; title?: string; nodes: RichFlowNode[] }
  | { kind: "meter"; label: string; value: number; max: number; parts: RichMeterPart[] }
  | { kind: "table"; columns: string[]; rows: string[][] };

const LANG_KIND: Record<string, RichBlock["kind"]> = {
  stats: "stats",
  "nexus-stats": "stats",
  chart: "chart",
  "nexus-chart": "chart",
  status: "status",
  "nexus-status": "status",
  cards: "cards",
  "nexus-cards": "cards",
  callout: "callout",
  "nexus-callout": "callout",
  sources: "sources",
  "nexus-sources": "sources",
  flow: "flow",
  "nexus-flow": "flow",
  meter: "meter",
  "nexus-meter": "meter",
  table: "table",
  "nexus-table": "table",
};

const STATUSES = new Set<RichStatus>(["ok", "pending", "warn", "fail", "info"]);
const TONES = new Set<RichTone>(["info", "warning", "success", "danger"]);
const ICONS = new Set<string>(RICH_ICONS);

function record(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function clip(value: unknown, max: number): string | null {
  if (typeof value !== "string") return null;
  const trimmed = value.trim();
  if (!trimmed || trimmed.length > max) return null;
  return trimmed;
}

function amount(value: unknown): number | null {
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) return null;
  return value;
}

function list(value: unknown, min: number, max: number): unknown[] | null {
  if (!Array.isArray(value) || value.length < min || value.length > max) return null;
  return value;
}

function httpUrl(value: unknown): string | null {
  const raw = clip(value, 500);
  if (!raw) return null;
  try {
    const url = new URL(raw);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.toString();
  } catch {
    return null;
  }
}

function parseStats(data: Record<string, unknown>): RichBlock | null {
  const items = list(data.items, 1, 4);
  if (!items) return null;
  const parsed: RichStatItem[] = [];
  for (const item of items) {
    const row = record(item);
    if (!row) return null;
    const value = clip(row.value, 24);
    const label = clip(row.label, 80);
    if (!value || !label) return null;
    const hint = row.hint === undefined ? undefined : clip(row.hint, 80) ?? undefined;
    if (row.hint !== undefined && !hint) return null;
    parsed.push(hint ? { value, label, hint } : { value, label });
  }
  return { kind: "stats", items: parsed };
}

function parseChart(data: Record<string, unknown>): RichBlock | null {
  const title = clip(data.title, 80);
  const bars = list(data.bars, 1, 8);
  if (!title || !bars) return null;
  const parsed: RichChartBar[] = [];
  for (const bar of bars) {
    const row = record(bar);
    if (!row) return null;
    const label = clip(row.label, 40);
    const value = amount(row.value);
    if (!label || value === null) return null;
    parsed.push({ label, value });
  }
  const unit = data.unit === undefined ? undefined : clip(data.unit, 40) ?? undefined;
  if (data.unit !== undefined && !unit) return null;
  return { kind: "chart", title, bars: parsed, ...(unit ? { unit } : {}) };
}

function parseStatus(data: Record<string, unknown>): RichBlock | null {
  const rows = list(data.rows, 1, 12);
  if (!rows) return null;
  const parsed: RichStatusRow[] = [];
  for (const row of rows) {
    const item = record(row);
    if (!item) return null;
    const name = clip(item.name, 80);
    const label = clip(item.label, 32);
    const state = clip(item.state, 16);
    if (!name || !label || !state || !STATUSES.has(state as RichStatus)) return null;
    parsed.push({ name, label, state: state as RichStatus });
  }
  const title = data.title === undefined ? undefined : clip(data.title, 80) ?? undefined;
  if (data.title !== undefined && !title) return null;
  return { kind: "status", rows: parsed, ...(title ? { title } : {}) };
}

function parseCards(data: Record<string, unknown>): RichBlock | null {
  const items = list(data.items, 1, 6);
  if (!items) return null;
  const parsed: RichCardItem[] = [];
  for (const item of items) {
    const row = record(item);
    if (!row) return null;
    const icon = clip(row.icon, 16);
    const title = clip(row.title, 40);
    if (!icon || !ICONS.has(icon) || !title) return null;
    const text = row.text === undefined ? undefined : clip(row.text, 160) ?? undefined;
    if (row.text !== undefined && !text) return null;
    parsed.push({ icon: icon as RichIconName, title, ...(text ? { text } : {}) });
  }
  return { kind: "cards", items: parsed };
}

function parseCallout(data: Record<string, unknown>): RichBlock | null {
  const text = clip(data.text, 400);
  const tone = clip(data.tone, 16);
  if (!text || !tone || !TONES.has(tone as RichTone)) return null;
  const title = data.title === undefined ? undefined : clip(data.title, 80) ?? undefined;
  if (data.title !== undefined && !title) return null;
  return { kind: "callout", tone: tone as RichTone, text, ...(title ? { title } : {}) };
}

function parseSources(data: Record<string, unknown>): RichBlock | null {
  const items = list(data.items, 1, 6);
  if (!items) return null;
  const parsed: RichSourceItem[] = [];
  for (const item of items) {
    const row = record(item);
    if (!row) return null;
    const title = clip(row.title, 120);
    const url = httpUrl(row.url);
    if (!title || !url) return null;
    const note = row.note === undefined ? undefined : clip(row.note, 80) ?? undefined;
    if (row.note !== undefined && !note) return null;
    parsed.push({ title, url, ...(note ? { note } : {}) });
  }
  return { kind: "sources", items: parsed };
}

function parseFlow(data: Record<string, unknown>): RichBlock | null {
  const nodes = list(data.nodes, 2, 8);
  if (!nodes) return null;
  const parsed: RichFlowNode[] = [];
  for (const node of nodes) {
    const row = record(node);
    if (!row) return null;
    const label = clip(row.label, 48);
    if (!label) return null;
    const hint = row.hint === undefined ? undefined : clip(row.hint, 80) ?? undefined;
    if (row.hint !== undefined && !hint) return null;
    parsed.push({ label, ...(hint ? { hint } : {}) });
  }
  const title = data.title === undefined ? undefined : clip(data.title, 80) ?? undefined;
  if (data.title !== undefined && !title) return null;
  return { kind: "flow", nodes: parsed, ...(title ? { title } : {}) };
}

function parseTable(data: Record<string, unknown>): RichBlock | null {
  const columns = list(data.columns, 2, 8);
  const rows = list(data.rows, 1, 20);
  if (!columns || !rows) return null;
  const heads: string[] = [];
  for (const column of columns) {
    const name = clip(column, 40);
    if (!name) return null;
    heads.push(name);
  }
  const body: string[][] = [];
  for (const row of rows) {
    if (!Array.isArray(row) || row.length !== heads.length) return null;
    const cells: string[] = [];
    for (const cell of row) {
      if (typeof cell !== "string" || cell.trim().length > 120) return null;
      cells.push(cell.trim());
    }
    body.push(cells);
  }
  return { kind: "table", columns: heads, rows: body };
}

function parseMeter(data: Record<string, unknown>): RichBlock | null {
  const label = clip(data.label, 80);
  const value = amount(data.value);
  const max = amount(data.max);
  if (!label || value === null || max === null || max <= 0 || value > max) return null;
  if (data.parts !== undefined && (!Array.isArray(data.parts) || data.parts.length > 3)) return null;
  const rawParts = data.parts === undefined ? [] : (data.parts as unknown[]);
  const parts: RichMeterPart[] = [];
  for (const part of rawParts ?? []) {
    const row = record(part);
    if (!row) return null;
    const partLabel = clip(row.label, 32);
    const partValue = clip(row.value, 24);
    if (!partLabel || !partValue) return null;
    parts.push({ label: partLabel, value: partValue });
  }
  return { kind: "meter", label, value, max, parts };
}

const PARSERS: Record<RichBlock["kind"], (data: Record<string, unknown>) => RichBlock | null> = {
  stats: parseStats,
  chart: parseChart,
  status: parseStatus,
  cards: parseCards,
  callout: parseCallout,
  sources: parseSources,
  flow: parseFlow,
  meter: parseMeter,
  table: parseTable,
};

/** Language tag of a fenced block, or null when it is ordinary code. */
export function richKindForLang(lang: string): RichBlock["kind"] | null {
  return LANG_KIND[lang.trim().toLowerCase()] ?? null;
}

/**
 * Turn a fenced payload into a block. Returns null when the language is not a
 * data block or the JSON does not match the shape — the caller then shows the
 * fence as code.
 */
function splitTableRow(line: string): string[] | null {
  const trimmed = line.trim();
  if (!trimmed.includes("|")) return null;
  const body = trimmed.replace(/^\|/, "").replace(/\|$/, "");
  const cells = body.split("|").map((cell) => cell.trim());
  if (cells.length < 2 || cells.length > 8) return null;
  if (cells.some((cell) => cell.length > 120)) return null;
  return cells;
}

function isTableSeparator(line: string): boolean {
  const cells = splitTableRow(line);
  if (!cells) return false;
  return cells.every((cell) => /^:?-+:?$/.test(cell));
}

/**
 * Turn a GitHub-style markdown table into a `table` fence so the chat draws
 * it as a real table. Fences already in the message are left alone.
 */
export function promoteMarkdownTables(markdown: string): string {
  const lines = markdown.split("\n");
  const out: string[] = [];
  let inFence = false;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index] ?? "";
    if (/^\s*```/.test(line)) {
      inFence = !inFence;
      out.push(line);
      continue;
    }
    const separator = lines[index + 1];
    if (!inFence && separator !== undefined && isTableSeparator(separator)) {
      const header = splitTableRow(line);
      const separatorCells = splitTableRow(separator);
      if (header && separatorCells && separatorCells.length === header.length && header.every((cell) => cell.length > 0)) {
        const rows: string[][] = [];
        let cursor = index + 2;
        while (cursor < lines.length) {
          const row = splitTableRow(lines[cursor] ?? "");
          if (!row || row.length !== header.length || isTableSeparator(lines[cursor] ?? "")) break;
          rows.push(row);
          cursor += 1;
        }
        if (rows.length > 0 && rows.length <= 20) {
          out.push("```table", JSON.stringify({ columns: header, rows }), "```");
          index = cursor - 1;
          continue;
        }
      }
    }
    out.push(line);
  }
  return out.join("\n");
}

export function parseRichBlock(lang: string, code: string): RichBlock | null {
  const kind = richKindForLang(lang);
  if (!kind) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(code);
  } catch {
    return null;
  }
  const data = record(parsed);
  if (!data) return null;
  return PARSERS[kind](data);
}
