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

// Nexus design system — color tokens aligned with tailwind.config.ts (nexus.*)
const NEXUS = {
  accent: "#7c6afb",
  accent2: "#5eead4",
  accent3: "#fbbf24",
  accent4: "#f87171",
  bg: "#0b0b14",
  panel: "#13131f",
  border: "#1e1e2d",
  muted: "#8a8a9a",
  text: "#e8e8ed",
} as const;

// Chart palette anchored on the nexus accent ramp so every chart stays on-theme.
export const CHART_COLORS = [
  NEXUS.accent, // nexus.accent  #7c6afb
  NEXUS.accent2, // nexus.accent2 #5eead4
  NEXUS.accent3, // nexus.accent3 #fbbf24
  NEXUS.accent4, // nexus.accent4 #f87171
  "#a78bfa", // nexus gradient end
  "#2dd4bf", // teal (complements accent2)
  "#f472b6", // pink
  "#fb923c", // orange
] as const;

// Kept for backward-compat with any external callers importing the old name.
const DEFAULT_COLORS = CHART_COLORS;

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
      className="rounded-lg border px-3 py-2 shadow-lg"
      style={{
        background: NEXUS.panel,
        borderColor: NEXUS.border,
        color: NEXUS.text,
      }}
      role="status"
    >
      <p className="mb-1 text-xs font-semibold" style={{ color: NEXUS.text }}>
        {label}
      </p>
      {payload.map((entry, idx) => (
        <div key={idx} className="flex items-center gap-2 text-xs">
          <span
            className="inline-block h-2 w-2 rounded-full"
            style={{ background: entry.color }}
          />
          <span style={{ color: NEXUS.muted }}>{entry.name}:</span>
          <span className="font-mono" style={{ color: NEXUS.text }}>
            {entry.value}
          </span>
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
              <CartesianGrid strokeDasharray="3 3" stroke={NEXUS.border} />
            )}
            <XAxis dataKey={xKey} tick={{ fill: NEXUS.muted, fontSize: 12 }} />
            <YAxis tick={{ fill: NEXUS.muted, fontSize: 12 }} />
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend
                wrapperStyle={{ color: NEXUS.muted, fontSize: 12 }}
              />
            )}
            {series.map((s, i) => (
              <Line
                key={s.key}
                type={s.type ?? "monotone"}
                dataKey={s.key}
                name={s.name}
                stroke={s.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
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
              <CartesianGrid strokeDasharray="3 3" stroke={NEXUS.border} />
            )}
            <XAxis dataKey={xKey} tick={{ fill: NEXUS.muted, fontSize: 12 }} />
            <YAxis tick={{ fill: NEXUS.muted, fontSize: 12 }} />
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend wrapperStyle={{ color: NEXUS.muted, fontSize: 12 }} />
            )}
            {series.map((s, i) => {
              const color = s.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length];
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
              <CartesianGrid strokeDasharray="3 3" stroke={NEXUS.border} />
            )}
            <XAxis dataKey={xKey} tick={{ fill: NEXUS.muted, fontSize: 12 }} />
            <YAxis tick={{ fill: NEXUS.muted, fontSize: 12 }} />
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend wrapperStyle={{ color: NEXUS.muted, fontSize: 12 }} />
            )}
            {series.map((s, i) => {
              const baseColor =
                s.color ?? CHART_COLORS[i % CHART_COLORS.length];
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
              <Legend wrapperStyle={{ color: NEXUS.muted, fontSize: 12 }} />
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
                  fill={DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
                />
              ))}
            </Pie>
          </PieChart>
        );
      }

      case "radar":
        return (
          <RadarChart data={data} cx="50%" cy="50%" outerRadius="70%">
            <PolarGrid stroke={NEXUS.border} />
            <PolarAngleAxis
              dataKey={xKey}
              tick={{ fill: NEXUS.muted, fontSize: 11 }}
            />
            <PolarRadiusAxis
              tick={{ fill: NEXUS.muted, fontSize: 10 }}
              stroke={NEXUS.border}
            />
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend wrapperStyle={{ color: NEXUS.muted, fontSize: 12 }} />
            )}
            {series.map((s, i) => (
              <Radar
                key={s.key}
                name={s.name}
                dataKey={s.key}
                stroke={s.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
                fill={s.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
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
      <ResponsiveContainer width="100%" height={height}>
        {chartContent()}
      </ResponsiveContainer>
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
