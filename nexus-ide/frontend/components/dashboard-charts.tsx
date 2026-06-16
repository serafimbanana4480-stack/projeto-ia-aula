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

const DEFAULT_COLORS = [
  "#38bdf8", // sky-400
  "#34d399", // emerald-400
  "#fbbf24", // amber-400
  "#f87171", // red-400
  "#a78bfa", // violet-400
  "#fb923c", // orange-400
  "#2dd4bf", // teal-400
  "#f472b6", // pink-400
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
    <div className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-2 shadow-lg">
      <p className="text-slate-200 text-xs font-semibold mb-1">{label}</p>
      {payload.map((entry, idx) => (
        <div key={idx} className="flex items-center gap-2 text-xs">
          <span
            className="inline-block w-2 h-2 rounded-full"
            style={{ background: entry.color }}
          />
          <span className="text-slate-300">{entry.name}:</span>
          <span className="text-white font-mono">{entry.value}</span>
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
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            )}
            <XAxis dataKey={xKey} tick={{ fill: "#94a3b8", fontSize: 12 }} />
            <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} />
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend
                wrapperStyle={{ color: "#94a3b8", fontSize: 12 }}
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
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            )}
            <XAxis dataKey={xKey} tick={{ fill: "#94a3b8", fontSize: 12 }} />
            <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} />
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 12 }} />
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
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
            )}
            <XAxis dataKey={xKey} tick={{ fill: "#94a3b8", fontSize: 12 }} />
            <YAxis tick={{ fill: "#94a3b8", fontSize: 12 }} />
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 12 }} />
            )}
            {series.map((s, i) => (
              <Bar
                key={s.key}
                dataKey={s.key}
                name={s.name}
                fill={s.color ?? DEFAULT_COLORS[i % DEFAULT_COLORS.length]}
                radius={[4, 4, 0, 0]}
              />
            ))}
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
              <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 12 }} />
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
            <PolarGrid stroke="#334155" />
            <PolarAngleAxis
              dataKey={xKey}
              tick={{ fill: "#94a3b8", fontSize: 11 }}
            />
            <PolarRadiusAxis
              tick={{ fill: "#94a3b8", fontSize: 10 }}
              stroke="#334155"
            />
            {showTooltip && <Tooltip content={<CustomTooltip />} />}
            {showLegend && (
              <Legend wrapperStyle={{ color: "#94a3b8", fontSize: 12 }} />
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

  return (
    <div
      className={`rounded-xl border border-slate-700 bg-slate-900 p-4 ${className}`}
      data-testid="dashboard-charts"
    >
      {(title || subtitle) && (
        <div className="mb-4">
          {title && (
            <h3 className="text-base font-semibold text-white">{title}</h3>
          )}
          {subtitle && (
            <p className="text-sm text-slate-400 mt-0.5">{subtitle}</p>
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
