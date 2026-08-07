"use client";
import { useMemo, useState, useCallback } from "react";
import { useMetricsStore } from "../../stores/metricsStore";
import { Surface } from "../ui/Surface";
import { Badge, StatusDot, AnimatedNumber } from "../ui/Primitives";
import { Sparkline } from "../ui/Sparkline";

interface MetricCell {
  key: string;
  label: string;
  value: string;
  /** Raw numeric value for cells that can be eased with AnimatedNumber. */
  rawValue?: number;
  decimals?: number;
  unit?: string;
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

function sparkColor(cell: MetricCell): string {
  if (cell.critical) return "#fb7185";
  if (cell.warning) return "#fbbf24";
  return "#9b8cff";
}

function cellTone(cell: MetricCell, selected: boolean): "danger" | "warning" | "accent" | "neutral" {
  if (cell.critical) return "danger";
  if (cell.warning) return "warning";
  if (selected) return "accent";
  return "neutral";
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
        rawValue: metrics.tokens_per_second,
        decimals: 1,
        trend: getTrend("tokens_per_second"),
        sparkline: getSparkline("tokens_per_second"),
        color: "text-nexus-accent",
      },
      { key: "active_model", label: "Modelo ativo", value: displayValues.active_model || "—" },
      {
        key: "active_sessions",
        label: "Sessões",
        value: displayValues.active_sessions || "—",
        rawValue: metrics.active_sessions,
        decimals: 0,
        trend: getTrend("active_sessions"),
        sparkline: getSparkline("active_sessions"),
      },
      {
        key: "cpu_percent",
        label: "CPU",
        value: displayValues.cpu_percent || "—",
        rawValue: metrics.cpu_percent,
        decimals: 1,
        unit: "%",
        trend: getTrend("cpu_percent"),
        sparkline: getSparkline("cpu_percent"),
        warning: metrics.cpu_percent > 70,
        critical: metrics.cpu_percent > 90,
      },
      {
        key: "ram_percent",
        label: "RAM",
        value: displayValues.ram_percent || "—",
        rawValue: metrics.ram_percent,
        decimals: 1,
        unit: "%",
        trend: getTrend("ram_percent"),
        sparkline: getSparkline("ram_percent"),
        warning: metrics.ram_percent > 75,
        critical: metrics.ram_percent > 90,
      },
      {
        key: "disk_percent",
        label: "Disco",
        value: displayValues.disk_percent || "—",
        rawValue: metrics.disk_percent,
        decimals: 1,
        unit: "%",
        trend: getTrend("disk_percent"),
        sparkline: getSparkline("disk_percent"),
        warning: metrics.disk_percent > 80,
        critical: metrics.disk_percent > 90,
      },
      {
        key: "queue_depth",
        label: "Fila",
        value: displayValues.queue_depth || "—",
        rawValue: metrics.queue_depth,
        decimals: 0,
        trend: getTrend("queue_depth"),
        sparkline: getSparkline("queue_depth"),
        warning: metrics.queue_depth > 5,
        critical: metrics.queue_depth > 10,
      },
      {
        key: "requests_total",
        label: "Pedidos",
        value: displayValues.requests_total || "—",
        rawValue: metrics.requests_total,
        decimals: 0,
        trend: getTrend("requests_total"),
        sparkline: getSparkline("requests_total"),
      },
      {
        key: "avg_latency_ms",
        label: "Latência",
        value: displayValues.avg_latency || "—",
        rawValue: metrics.avg_latency_ms,
        decimals: 0,
        unit: " ms",
        trend: getTrend("avg_latency_ms"),
        sparkline: getSparkline("avg_latency_ms"),
        warning: metrics.avg_latency_ms > 500,
        critical: metrics.avg_latency_ms > 1000,
      },
      { key: "uptime_seconds", label: "Tempo de atividade", value: displayValues.uptime || "—" },
    ];
  }, [metrics, displayValues, getTrend, getSparkline]);

  const getTrendColor = (trend: string | undefined, key: string) => {
    const badUp = ["avg_latency_ms", "queue_depth", "requests_failed", "cpu_percent", "ram_percent", "disk_percent"];
    const isBadUp = badUp.includes(key);
    if (trend === "up") return isBadUp ? "text-rose-400" : "text-emerald-400";
    if (trend === "down") return isBadUp ? "text-emerald-400" : "text-rose-400";
    return "text-nexus-faint";
  };

  if (!backendOnline && !metrics) {
    return (
      <Surface elevation={1} padding="sm" tone="warning">
        <div role="status" aria-live="polite" className="flex items-center gap-2 text-xs text-amber-300">
          <StatusDot tone="warning" pulse />
          Backend offline — a aguardar ligação…
        </div>
      </Surface>
    );
  }

  const selectedCell = cells.find((c) => c.key === selectedMetric);

  return (
    <div className="space-y-3" aria-label="Grelha de Métricas" role="group">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5">
        {cells.map((cell) => {
          const selected = selectedMetric === cell.key;
          const cellAria = `${cell.label}: ${cell.value}${
            cell.critical ? ", Crítico" : cell.warning ? ", Aviso" : ""
          }${cell.trend ? `, tendência ${trendLabel(cell.trend)}` : ""}`;
          return (
            <div
              key={cell.key}
              role="button"
              tabIndex={0}
              aria-pressed={selected}
              aria-label={cellAria}
              title={`${cell.label}: ${cell.value} | Histórico: ${cell.sparkline?.slice(-5).join(", ") ?? "N/A"}`}
              onClick={() => setSelectedMetric(cell.key)}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  setSelectedMetric(cell.key);
                }
              }}
              className="min-w-0 cursor-pointer rounded-lg focus:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
            >
              <Surface elevation={0} tone={cellTone(cell, selected)} interactive padding="xs" className="h-full">
                <div className="mb-1 flex items-center justify-between gap-1">
                  <span className="truncate text-[10px] uppercase tracking-wider text-nexus-faint">
                    {cell.label}
                  </span>
                  <span className="flex shrink-0 items-center gap-1">
                    {(cell.critical || cell.warning) && (
                      <Badge tone={cell.critical ? "danger" : "warning"}>
                        {cell.critical ? "Crítico" : "Aviso"}
                      </Badge>
                    )}
                    {cell.trend && (
                      <span className={`text-[10px] ${getTrendColor(cell.trend, cell.key)}`} aria-hidden="true">
                        {trendLabel(cell.trend)}
                      </span>
                    )}
                  </span>
                </div>
                <div
                  className={`truncate font-mono text-sm font-bold tabular-nums sm:text-base ${
                    cell.critical ? "text-rose-400" : cell.warning ? "text-amber-400" : cell.color || "text-nexus-text"
                  }`}
                >
                  {cell.rawValue != null ? (
                    <>
                      <AnimatedNumber value={cell.rawValue} decimals={cell.decimals ?? 0} />
                      {cell.unit}
                    </>
                  ) : (
                    cell.value
                  )}
                </div>
                {cell.sparkline && cell.sparkline.length > 1 && (
                  <Sparkline
                    data={cell.sparkline}
                    color={sparkColor(cell)}
                    width={100}
                    height={28}
                    filled={false}
                    className="mt-1 h-7 w-full"
                  />
                )}
              </Surface>
            </div>
          );
        })}
      </div>

      {metrics && selectedCell && (
        <div aria-label="Detalhe da métrica selecionada">
          <Surface elevation={0} tone="accent" padding="sm" as="section">
            <div className="flex flex-wrap items-center justify-between gap-2 text-xs sm:text-sm">
              <span className="flex min-w-0 items-center gap-2 truncate text-nexus-muted">
                <span className="font-medium text-nexus-text">{selectedCell.label}</span>
                <Badge tone="accent">{getBaselineComparison(selectedMetric)}</Badge>
              </span>
              <span className="text-nexus-faint">{history.length} amostras</span>
            </div>
            <div className="mt-2 h-16">
              {(() => {
                const series = getSparkline(selectedMetric);
                return series.length > 1 ? (
                  <Sparkline data={series} color="#9b8cff" width={600} height={64} className="h-16 w-full" />
                ) : (
                  <div className="flex h-full items-center justify-center text-[11px] text-nexus-faint">
                    Sem histórico suficiente
                  </div>
                );
              })()}
            </div>
          </Surface>
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
