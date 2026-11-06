"use client";

import React from "react";
import {
  LineChart,
  Line,
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
} from "recharts";

import { useChartTokens, chartPalette } from "../hooks/useChartTokens";

export type ChartKind = "line" | "area" | "bar" | "pie" | "radar";

export interface ChartSeries {
  key: string;
  name: string;
  color?: string;
  type?: "monotone" | "linear" | "step";
  /** Per-data-point colors (e.g. one color per bar). Optional, keeps API stable. */
  cells?: string[];
}

export interface DashboardChartsProps {
  data: Record<string, any>[];
  kind: ChartKind;
  xKey: string;
  series: ChartSeries[];
  title?: string;
  subtitle?: string;
  height?: number;
  className?: string;
  showGrid?: boolean;
  showLegend?: boolean;
  showTooltip?: boolean;
  pieInnerRadius?: number;
  pieOuterRadius?: number;
}

/**
 * Resolved design tokens, re-read whenever the theme changes.
 *
 * Recharts writes these into SVG presentation attributes, where `var(--nx-*)`
 * is not resolved — so a hardcoded fallback used to silently win. See
 * `hooks/useChartTokens.ts`.
 */
function useChartTheme() {
  const tokens = useChartTokens();
  return { tokens, palette: chartPalette(tokens) };
}

/**
 * Static ramp for callers outside React (legend swatches, series headers).
 * Anchored on the dark-theme tokens — light-theme callers should prefer
 * `useChartTokens()` so the swatch matches the chart.
 */
export const CHART_COLORS: readonly string[] = [
  "#7c6afb",
  "#22d3ee",
  "#34d399",
  "#fbbf24",
  "#9b8cff",
  "#fb7185",
  "color-mix(in srgb, #7c6afb 55%, #22d3ee)",
  "color-mix(in srgb, #fb7185 45%, #fbbf24)",
];


function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: any[];
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div
      className="nx-elev-2 rounded-lg px-3 py-2"
      role="status"
    >
      <p className="mb-1 text-xs font-semibold text-nexus-text">{label}</p>
      {payload.map((entry, idx) => (
        <div key={idx} className="flex items-center gap-2 text-xs">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ background: entry.color }}
          />
          <span className="text-nexus-muted">{entry.name}:</span>
          <span className="font-mono text-nexus-text">{entry.value}</span>
        </div>
      ))}
    </div>
  );
}

export default function DashboardCharts({
  data,
  kind,
  xKey,
  series,
  title,
  subtitle,
  height = 300,
  className = "",
  showGrid = true,
  showLegend = true,
  showTooltip = true,
  pieInnerRadius = 50,
  pieOuterRadius = 80,
}: DashboardChartsProps) {
  const { tokens, palette } = useChartTheme();
  const finitePoints = Array.isArray(data)
    ? data.filter(
        (row) =>
          row &&
          typeof row === "object" &&
          series.some((item) => typeof row[item.key] === "number" && Number.isFinite(row[item.key])),
      ).length
    : 0;
  const minPoints = kind === "line" || kind === "area" ? 2 : 1;
  const chartContent = () => {
    const commonProps = {
      data,
      margin: { top: 10, right: 20, left: 0, bottom: 0 },
    };

    switch (kind) {
      case "line":
        return (
          <LineChart {...commonProps}>
            {showGrid && (
              <CartesianGrid strokeDasharray="3 3" stroke={tokens.border} />
            )}
            <XAxis dataKey={xKey} tick={{ fill: tokens.textFaint, fontSize: 12 }} />
            <YAxis tick={{ fill: tokens.textFaint, fontSize: 12 }} />
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend
                wrapperStyle={{ color: tokens.textFaint, fontSize: 12 }}
              />
            )}
            {series.map((s, i) => (
              <Line
                key={s.key}
                type={s.type ?? "monotone"}
                dataKey={s.key}
                name={s.name}
                stroke={s.color ?? palette[i % palette.length]}
                strokeWidth={2}
                dot={{ r: 3 }}
                activeDot={{ r: 5 }}
              />
            ))}
          </LineChart>
        );

      case "area":
        return (
          <AreaChart {...commonProps}>
            {showGrid && (
              <CartesianGrid strokeDasharray="3 3" stroke={tokens.border} />
            )}
            <XAxis dataKey={xKey} tick={{ fill: tokens.textFaint, fontSize: 12 }} />
            <YAxis tick={{ fill: tokens.textFaint, fontSize: 12 }} />
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend wrapperStyle={{ color: tokens.textFaint, fontSize: 12 }} />
            )}
            {series.map((s, i) => {
              const color = s.color ?? palette[i % palette.length];
              return (
                <Area
                  key={s.key}
                  type={s.type ?? "monotone"}
                  dataKey={s.key}
                  name={s.name}
                  stroke={color}
                  fill={color}
                  fillOpacity={0.2}
                  strokeWidth={2}
                />
              );
            })}
          </AreaChart>
        );

      case "bar":
        return (
          <BarChart {...commonProps}>
            {showGrid && (
              <CartesianGrid strokeDasharray="3 3" stroke={tokens.border} />
            )}
            <XAxis dataKey={xKey} tick={{ fill: tokens.textFaint, fontSize: 12 }} />
            <YAxis tick={{ fill: tokens.textFaint, fontSize: 12 }} />
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend wrapperStyle={{ color: tokens.textFaint, fontSize: 12 }} />
            )}
            {series.map((s, i) => {
              const baseColor =
                s.color ?? palette[i % palette.length];
              return (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.name}
                  fill={baseColor}
                  radius={[4, 4, 0, 0]}
                >
                  {s.cells?.map((c, ci) => (
                    <Cell key={ci} fill={c} />
                  ))}
                </Bar>
              );
            })}
          </BarChart>
        );

      case "pie": {
        const pieData = data.map((item) => ({
          name: item[xKey],
          value: item[series[0]?.key ?? "value"],
        }));
        return (
          <PieChart>
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend wrapperStyle={{ color: tokens.textFaint, fontSize: 12 }} />
            )}
            <Pie
              data={pieData}
              cx="50%"
              cy="50%"
              innerRadius={pieInnerRadius}
              outerRadius={pieOuterRadius}
              paddingAngle={3}
              dataKey="value"
              nameKey="name"
              label={({ name, percent }) =>
                `${name}: ${(percent * 100).toFixed(0)}%`
              }
              labelLine={false}
            >
              {pieData.map((_, i) => (
                <Cell
                  key={i}
                  fill={palette[i % palette.length]}
                />
              ))}
            </Pie>
          </PieChart>
        );
      }

      case "radar":
        return (
          <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
            <PolarGrid stroke={tokens.border} />
            <PolarAngleAxis
              dataKey={xKey}
              tick={{ fill: tokens.textFaint, fontSize: 11 }}
            />
            <PolarRadiusAxis
              tick={{ fill: tokens.textFaint, fontSize: 10 }}
              stroke={tokens.border}
            />
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend wrapperStyle={{ color: tokens.textFaint, fontSize: 12 }} />
            )}
            {series.map((s, i) => (
              <Radar
                key={s.key}
                name={s.name}
                dataKey={s.key}
                stroke={s.color ?? palette[i % palette.length]}
                fill={s.color ?? palette[i % palette.length]}
                fillOpacity={0.3}
              />
            ))}
          </RadarChart>
        );
    }
  };

  const ariaLabel =
    title ?? subtitle ?? `Gráfico nexus (${kind})`;

  return (
    <div
      className={`min-w-0 rounded-xl border border-nexus-border bg-nexus-panel p-4 ${className}`}
      data-testid="dashboard-charts"
      role="figure"
      aria-label={ariaLabel}
    >
      {(title || subtitle) && (
        <div className="mb-4">
          {title && (
            <h3 className="text-base font-semibold text-nexus-text">
              {title}
            </h3>
          )}
          {subtitle && (
            <p className="mt-0.5 text-sm text-nexus-muted">{subtitle}</p>
          )}
        </div>
      )}
      {finitePoints < minPoints ? (
        <p className="py-6 text-sm text-nexus-muted">Sem pontos nesta série.</p>
      ) : (
        <ResponsiveContainer width="100%" height={height}>
          {chartContent()}
        </ResponsiveContainer>
      )}
    </div>
  );
}

/*
Usage examples:

1. Line chart:
<DashboardCharts
  kind="line"
  data={[
    { day: "Mon", requests: 120, errors: 4 },
    { day: "Tue", requests: 200, errors: 8 },
    { day: "Wed", requests: 150, errors: 2 },
  ]}
  xKey="day"
  series={[
    { key: "requests", name: "Requests" },
    { key: "errors", name: "Errors", color: "#f87171" },
  ]}
  title="API Traffic"
/>

2. Pie chart:
<DashboardCharts
  kind="pie"
  data={[
    { lang: "Python", lines: 4500 },
    { lang: "TypeScript", lines: 3200 },
    { lang: "Rust", lines: 1200 },
  ]}
  xKey="lang"
  series={[{ key: "lines", name: "Lines of Code" }]}
  title="Code Distribution"
/>
*/
