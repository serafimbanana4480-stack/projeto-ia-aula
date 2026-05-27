"use client";
import { useMemo, useState, useCallback } from "react";
import { useMetricsStore } from "../../stores/metricsStore";

interface MetricCell {
  key: string;
  label: string;
  value: string;
  trend?: "up" | "down" | "neutral";
  sparkline?: number[];
  color?: string;
  warning?: boolean;
  critical?: boolean;
}

export default function MetricsGrid() {
  const metrics = useMetricsStore((s) => s.metrics);
  const history = useMetricsStore((s) => s.history);
  const backendOnline = useMetricsStore((s) => s.backendOnline);
  const [selectedMetric, setSelectedMetric] = useState<string>("tokens_per_second");

  const baseline = useMemo(() => history[0] ?? metrics, [history, metrics]);

  const displayValues = useMemo(() => {
    if (!metrics) return {} as Record<string, string>;
    return {
      tokens_per_second: metrics.tokens_per_second.toFixed(1),
      active_model: metrics.active_model || "none",
      active_sessions: metrics.active_sessions.toLocaleString(),
      queue_depth: metrics.queue_depth.toString(),
      ram_used: `${(metrics.ram_used_bytes / 1e9).toFixed(2)} GB`,
      ram_percent: `${metrics.ram_percent.toFixed(1)}%`,
      cpu_percent: `${metrics.cpu_percent.toFixed(1)}%`,
      disk_percent: `${metrics.disk_percent.toFixed(1)}%`,
      uptime: formatUptime(metrics.uptime_seconds),
      requests_total: metrics.requests_total.toLocaleString(),
      avg_latency: `${metrics.avg_latency_ms.toFixed(0)} ms`,
    };
  }, [metrics]);

  const getTrend = useCallback(
    (metric: string): "up" | "down" | "neutral" => {
      if (history.length < 2) return "neutral";
      const current = ((metrics as unknown as Record<string, number>)?.[metric]) ?? 0;
      const previous = ((history[history.length - 2] as unknown as Record<string, number>)?.[metric]) ?? 0;
      if (current > previous) return "up";
      if (current < previous) return "down";
      return "neutral";
    },
    [history, metrics]
  );

  const getSparkline = useCallback(
    (metric: string): number[] => {
      return history.slice(-20).map((h) => ((h as unknown as Record<string, number>)[metric]) ?? 0);
    },
    [history]
  );

  const getBaselineComparison = useCallback(
    (metric: string): string => {
      if (!metrics || !baseline) return "—";
      const current = (metrics as unknown as Record<string, number>)[metric] ?? 0;
      const base = (baseline as unknown as Record<string, number>)[metric] ?? 0;
      if (typeof current !== "number" || typeof base !== "number") return "—";
      const diff = current - base;
      const percent = base !== 0 ? ((diff / base) * 100).toFixed(1) : "0.0";
      const sign = diff >= 0 ? "+" : "";
      return `${sign}${percent}% vs baseline`;
    },
    [metrics, baseline]
  );

  const cells: MetricCell[] = useMemo(() => {
    if (!metrics) return [];
    return [
      {
        key: "tokens_per_second",
        label: "Tokens/s",
        value: displayValues.tokens_per_second || "—",
        trend: getTrend("tokens_per_second"),
        sparkline: getSparkline("tokens_per_second"),
        color: "text-nexus-accent",
      },
      { key: "active_model", label: "Modelo Ativo", value: displayValues.active_model || "—" },
      {
        key: "active_sessions",
        label: "Sessões",
        value: displayValues.active_sessions || "—",
        trend: getTrend("active_sessions"),
      },
      {
        key: "cpu_percent",
        label: "CPU",
        value: displayValues.cpu_percent || "—",
        trend: getTrend("cpu_percent"),
        warning: metrics.cpu_percent > 70,
        critical: metrics.cpu_percent > 90,
      },
      {
        key: "ram_percent",
        label: "RAM",
        value: displayValues.ram_percent || "—",
        trend: getTrend("ram_percent"),
        warning: metrics.ram_percent > 75,
        critical: metrics.ram_percent > 90,
      },
      {
        key: "disk_percent",
        label: "Disco",
        value: displayValues.disk_percent || "—",
        trend: getTrend("disk_percent"),
        warning: metrics.disk_percent > 80,
        critical: metrics.disk_percent > 90,
      },
      {
        key: "queue_depth",
        label: "Queue",
        value: displayValues.queue_depth || "—",
        trend: getTrend("queue_depth"),
        warning: metrics.queue_depth > 5,
        critical: metrics.queue_depth > 10,
      },
      {
        key: "requests_total",
        label: "Requests",
        value: displayValues.requests_total || "—",
        trend: getTrend("requests_total"),
      },
      {
        key: "avg_latency_ms",
        label: "Latência",
        value: displayValues.avg_latency || "—",
        trend: getTrend("avg_latency_ms"),
        warning: metrics.avg_latency_ms > 500,
        critical: metrics.avg_latency_ms > 1000,
      },
      { key: "uptime_seconds", label: "Uptime", value: displayValues.uptime || "—" },
    ];
  }, [metrics, displayValues, getTrend, getSparkline]);

  const renderSparkline = (data: number[]) => {
    if (!data || data.length < 2) return null;
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const points = data
      .map((val, i) => {
        const x = (i / (data.length - 1)) * 100;
        const y = 100 - ((val - min) / range) * 100;
        return `${x},${y}`;
      })
      .join(" ");
    return (
      <svg className="h-6 w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" className="opacity-70" />
      </svg>
    );
  };

  const getCellBorderColor = (cell: MetricCell) => {
    if (cell.critical) return "border-red-500/50 bg-red-500/5";
    if (cell.warning) return "border-yellow-500/50 bg-yellow-500/5";
    if (selectedMetric === cell.key) return "border-nexus-accent/50 bg-nexus-accent/5";
    return "border-nexus-border bg-nexus-panel hover:border-nexus-border/80";
  };

  const getCellTextColor = (cell: MetricCell) => {
    if (cell.critical) return "text-red-400";
    if (cell.warning) return "text-yellow-400";
    if (cell.color) return cell.color;
    return "text-white";
  };

  const getTrendIcon = (trend?: string) => {
    if (trend === "up") return "▲";
    if (trend === "down") return "▼";
    return "—";
  };

  const getTrendColor = (trend: string | undefined, key: string) => {
    const badUp = ["avg_latency_ms", "queue_depth", "requests_failed", "cpu_percent", "ram_percent", "disk_percent"];
    const isBadUp = badUp.includes(key);
    if (trend === "up") return isBadUp ? "text-red-400" : "text-green-400";
    if (trend === "down") return isBadUp ? "text-green-400" : "text-red-400";
    return "text-gray-500";
  };

  if (!backendOnline && !metrics) {
    return (
      <div className="rounded border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-400">
        Backend offline — aguardando conexão...
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-5 lg:grid-cols-10">
        {cells.map((cell) => (
          <div
            key={cell.key}
            onClick={() => setSelectedMetric(cell.key)}
            className={`cursor-pointer rounded border p-2.5 transition-all duration-200 ${getCellBorderColor(cell)}`}
          >
            <div className="mb-1 flex items-center justify-between">
              <span className="text-[10px] uppercase tracking-wider text-gray-500">{cell.label}</span>
              {cell.trend && (
                <span className={`text-[10px] ${getTrendColor(cell.trend, cell.key)}`}>
                  {getTrendIcon(cell.trend)}
                </span>
              )}
            </div>
            <div className={`text-base font-bold ${getCellTextColor(cell)}`}>{cell.value}</div>
            {cell.sparkline && <div className="mt-1 text-nexus-accent">{renderSparkline(cell.sparkline)}</div>}
          </div>
        ))}
      </div>

      {metrics && (
        <div className="rounded border border-nexus-border bg-nexus-panel p-3">
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">
              {cells.find((c) => c.key === selectedMetric)?.label} — {getBaselineComparison(selectedMetric)}
            </span>
            <span className="text-gray-500">{history.length} samples</span>
          </div>
          <div className="mt-2 h-16 text-nexus-accent">{renderSparkline(getSparkline(selectedMetric as keyof typeof metrics))}</div>
        </div>
      )}
    </div>
  );
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
  return `${(seconds / 86400).toFixed(1)}d`;
}
