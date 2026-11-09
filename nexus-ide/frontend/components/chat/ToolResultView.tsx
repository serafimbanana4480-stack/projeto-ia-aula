"use client";

import { useReducedMotion } from "framer-motion";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { useChartTokens } from "../../hooks/useChartTokens";
import type { ToolResultSeries, ToolResultTable } from "../../lib/toolResultView";

function cellText(value: string | number | boolean | null): string {
  if (value === null) return "";
  if (typeof value === "boolean") return value ? "sim" : "não";
  return String(value);
}

function ResultTable({ view }: { view: ToolResultTable }) {
  return (
    <div className="overflow-x-auto" data-testid="tool-result-table">
      <table className="w-full border-collapse text-left text-[11px] text-nexus-text">
        <caption className="sr-only">
          {view.rows.length} linhas, {view.columns.length} colunas
        </caption>
        <thead>
          <tr className="border-b border-nexus-border/70 text-nexus-muted">
            {view.columns.map((column) => (
              <th key={column} scope="col" className="px-2 py-1.5 font-medium">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {view.rows.map((row, index) => (
            <tr key={index} className="border-b border-nexus-border/40">
              {view.columns.map((column) => (
                <td key={column} className="px-2 py-1.5 font-mono tabular-nums">
                  {cellText(row[column])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SeriesTooltip({
  active,
  label,
  value,
  unit,
}: {
  active?: boolean;
  label?: string | number;
  value?: number;
  unit?: string;
}) {
  if (!active || value === undefined) return null;
  return (
    <div className="nx-elev-2 rounded-lg px-2.5 py-1.5 text-xs">
      <p className="text-nexus-muted">{String(label)}</p>
      <p className="font-mono text-nexus-text">{unit ? `${value} ${unit}` : String(value)}</p>
    </div>
  );
}

function ResultSeries({ view }: { view: ToolResultSeries }) {
  const tokens = useChartTokens();
  const reduced = useReducedMotion();
  const animate = reduced === false;
  const numericX = view.points.every((point) => typeof point.x === "number");
  const unit = view.unit;

  return (
    <figure className="space-y-1.5" data-testid="tool-result-series">
      <figcaption className="text-[11px] leading-relaxed text-nexus-muted">{view.summary}</figcaption>
      <div className="h-40 w-full min-w-0">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={view.points} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid stroke={tokens.border} strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="x"
              type={numericX ? "number" : "category"}
              domain={numericX ? ["dataMin", "dataMax"] : undefined}
              tick={{ fill: tokens.textFaint, fontSize: 11 }}
              stroke={tokens.border}
            />
            <YAxis
              domain={["dataMin", "dataMax"]}
              tick={{ fill: tokens.textFaint, fontSize: 11 }}
              stroke={tokens.border}
              width={unit ? 56 : 36}
              tickFormatter={unit ? (value: number) => `${value} ${unit}` : undefined}
            />
            <Tooltip
              content={({ active, label, payload }) => (
                <SeriesTooltip
                  active={active}
                  label={label}
                  value={typeof payload?.[0]?.value === "number" ? payload[0].value : undefined}
                  unit={unit}
                />
              )}
            />
            <Line
              type="linear"
              dataKey="y"
              stroke={tokens.accent}
              strokeWidth={2}
              dot={{ r: 3, fill: tokens.accent }}
              isAnimationActive={animate}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </figure>
  );
}

export default function ToolResultView({ view }: { view: ToolResultSeries | ToolResultTable }) {
  if (view.kind === "table") return <ResultTable view={view} />;
  return <ResultSeries view={view} />;
}
