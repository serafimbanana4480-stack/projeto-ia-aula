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

const TREND_ARROW: Record<"up" | "down" | "neutral", string> = {
  up: "↑",
  down: "↓",
  neutral: "→",
};

function trendLabel(trend: MetricCell["trend"]): string {
  return TREND_ARROW[trend ?? "neutral"];
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
      active_model: metrics.active_model || "nenhum",
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
      return `${sign}${percent}% vs base`;
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
      { key: "active_model", label: "Modelo ativo", value: displayValues.active_model || "—" },
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
        label: "Fila",
        value: displayValues.queue_depth || "—",
        trend: getTrend("queue_depth"),
        warning: metrics.queue_depth > 5,
        critical: metrics.queue_depth > 10,
      },
      {
        key: "requests_total",
        label: "Pedidos",
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
      { key: "uptime_seconds", label: "Tempo de atividade", value: displayValues.uptime || "—" },
    ];
  }, [metrics, displayValues, getTrend, getSparkline]);

  const renderSparkline = (data: number[], ariaLabel: string) => {
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
      <svg
        className="h-8 w-full"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        role="img"
        aria-label={ariaLabel}
      >
        <title>{ariaLabel}</title>
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" className="opacity-70" />
      </svg>
    );
  };

  const getCellBorderColor = (cell: MetricCell) => {
    if (cell.critical) return "border-red-500/50 bg-gradient-to-br from-red-500/10 to-red-500/5";
    if (cell.warning) return "border-yellow-500/50 bg-gradient-to-br from-yellow-500/10 to-yellow-500/5";
    if (selectedMetric === cell.key) return "border-nexus-accent/50 bg-gradient-to-br from-nexus-accent/10 to-nexus-accent/5";
    return "border-nexus-border bg-gradient-to-br from-nexus-panel to-nexus-bg hover:border-nexus-border/80";
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

  const handleCellKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLDivElement>, key: string) => {
      if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
        e.preventDefault();
        setSelectedMetric(key);
      }
    },
    []
  );

  if (!backendOnline && !metrics) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="rounded border border-yellow-500/30 bg-yellow-500/10 px-3 py-2 text-xs text-yellow-400"
      >
        Backend offline — a aguardar ligação…
      </div>
    );
  }

  const selectedCell = cells.find((c) => c.key === selectedMetric);

  return (
    <div className="space-y-3" aria-label="Grelha de Métricas" role="group">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
        {cells.map((cell) => {
          const sparklineAria = `${cell.label}: ${cell.value}, tendência ${trendLabel(cell.trend)}`;
          const cellAria = `${cell.label}: ${cell.value}${
            cell.critical ? ", Crítico" : cell.warning ? ", Aviso" : ""
          }${cell.trend ? `, tendência ${trendLabel(cell.trend)}` : ""}`;
          return (
            <div
              key={cell.key}
              role="button"
              tabIndex={0}
              aria-pressed={selectedMetric === cell.key}
              aria-label={cellAria}
              title={`${cell.label}: ${cell.value} | Histórico: ${cell.sparkline?.slice(-5).join(", ") ?? "N/A"}`}
              onClick={() => setSelectedMetric(cell.key)}
              onKeyDown={(e) => handleCellKeyDown(e, cell.key)}
              className={`min-w-0 cursor-pointer rounded border p-2.5 transition-all duration-200 hover:scale-[1.02] hover:shadow-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent ${getCellBorderColor(cell)}`}
            >
              <div className="mb-1 flex items-center justify-between gap-1">
                <span className="truncate text-[10px] uppercase tracking-wider text-gray-500 sm:text-xs">
                  {cell.label}
                </span>
                <span className="flex shrink-0 items-center gap-1">
                  {(cell.critical || cell.warning) && (
                    <span className="text-[10px] font-semibold sm:text-xs">
                      {cell.critical ? (
                        <span className="text-red-400" aria-label="Crítico">Crítico</span>
                      ) : (
                        <span className="text-yellow-400" aria-label="Aviso">Aviso</span>
                      )}
                    </span>
                  )}
                  {cell.trend && (
                    <span className={`text-[10px] sm:text-xs ${getTrendColor(cell.trend, cell.key)}`} aria-hidden="true">
                      {getTrendIcon(cell.trend)}
                    </span>
                  )}
                </span>
              </div>
              <div className={`truncate text-sm font-bold sm:text-base ${getCellTextColor(cell)}`}>
                {cell.value}
              </div>
              {cell.sparkline && (
                <div className="mt-1 text-nexus-accent">{renderSparkline(cell.sparkline, sparklineAria)}</div>
              )}
            </div>
          );
        })}
      </div>

      {metrics && selectedCell && (
        <div
          className="rounded border border-nexus-accent/30 bg-gradient-to-br from-nexus-accent/8 to-nexus-accent/3 p-3"
          aria-label="Detalhe da métrica selecionada"
        >
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs sm:text-sm">
            <span className="flex items-center gap-2 min-w-0 truncate text-gray-400">
              <span className="font-medium text-gray-300">{selectedCell.label}</span>
              <span className="rounded bg-nexus-accent/15 px-1.5 py-0.5 text-[10px] font-semibold text-nexus-accent">
                {getBaselineComparison(selectedMetric)}
              </span>
            </span>
            <span className="text-gray-500">{history.length} amostras</span>
          </div>
          <div className="mt-2 h-16 text-nexus-accent">
            {renderSparkline(
              getSparkline(selectedMetric as keyof typeof metrics),
              `${selectedCell.label}: ${selectedCell.value}, tendência ${trendLabel(selectedCell.trend)}`
            )}
          </div>
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
