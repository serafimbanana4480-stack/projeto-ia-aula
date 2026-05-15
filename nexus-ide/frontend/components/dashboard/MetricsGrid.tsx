"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { apiUrl, getCurrentMetrics } from "../../lib/api";
import { MOCK_METRICS, type MetricsSnapshot } from "../../lib/mock-data";

interface MetricCell {
  key: keyof MetricsSnapshot;
  label: string;
  value: string;
  trend?: "up" | "down" | "neutral";
  sparkline?: number[];
  color?: string;
}

export default function MetricsGrid() {
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(MOCK_METRICS);
  const [displayValues, setDisplayValues] = useState<Record<string, string>>({});
  const [history, setHistory] = useState<MetricsSnapshot[]>([MOCK_METRICS]);
  const [baseline, setBaseline] = useState<MetricsSnapshot | null>(MOCK_METRICS);
  const [selectedMetric, setSelectedMetric] = useState<keyof MetricsSnapshot>("tokens_per_second");
  const [backendOnline, setBackendOnline] = useState(false);

  useEffect(() => {
    let mounted = true;
    let fallbackTimer: ReturnType<typeof setInterval> | null = null;

    const applyMetrics = (data: MetricsSnapshot) => {
      if (!mounted) return;
      setMetrics(data);
      setHistory((prev) => [...prev.slice(-49), data]);
      if (!baseline) setBaseline(data);
    };

    const startPollingFallback = () => {
      if (fallbackTimer) return;
      setBackendOnline(false);
      fallbackTimer = setInterval(async () => {
        try {
          const data = await getCurrentMetrics();
          applyMetrics(data as MetricsSnapshot);
          setBackendOnline(true);
        } catch {
          setBackendOnline(false);
        }
      }, 2000);
    };

    // Try SSE first
    try {
      const eventSource = new EventSource(apiUrl("/api/dashboard/stream"));

      eventSource.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as MetricsSnapshot;
          applyMetrics(data);
          setBackendOnline(true);
        } catch { /* ignore parse errors */ }
      };

      eventSource.onerror = () => {
        setBackendOnline(false);
        eventSource.close();
        startPollingFallback();
      };
    } catch {
      startPollingFallback();
    }

    return () => {
      mounted = false;
      if (fallbackTimer) clearInterval(fallbackTimer);
    };
  }, []);

  // Animate number changes
  useEffect(() => {
    if (!metrics) return;
    const updateDisplay = () => {
      setDisplayValues({
        tokens_per_second: metrics.tokens_per_second.toFixed(1),
        active_model: metrics.active_model,
        active_sessions: metrics.active_sessions.toLocaleString(),
        queue_depth: metrics.queue_depth.toString(),
        ram_used: `${(metrics.ram_used_bytes / 1e9).toFixed(2)} GB`,
        cpu_percent: `${metrics.cpu_percent.toFixed(1)}%`,
        uptime: formatUptime(metrics.uptime_seconds),
        requests_total: metrics.requests_total.toLocaleString(),
        avg_latency: `${metrics.avg_latency_ms.toFixed(0)} ms`,
      });
    };
    updateDisplay();
    const interval = setInterval(updateDisplay, 1000);
    return () => clearInterval(interval);
  }, [metrics]);

  const getTrend = (metric: keyof MetricsSnapshot): "up" | "down" | "neutral" => {
    if (history.length < 2) return "neutral";
    const current = metrics?.[metric] as number;
    const previous = history[history.length - 2][metric] as number;
    if (current > previous) return "up";
    if (current < previous) return "down";
    return "neutral";
  };

  const getSparkline = (metric: keyof MetricsSnapshot): number[] => {
    return history.slice(-20).map((h) => h[metric] as number);
  };

  const getBaselineComparison = (metric: keyof MetricsSnapshot): string => {
    if (!baseline || typeof metrics?.[metric] !== "number" || typeof baseline[metric] !== "number") return "—";
    const current = metrics[metric] as number;
    const base = baseline[metric] as number;
    const diff = current - base;
    const percent = base !== 0 ? ((diff / base) * 100).toFixed(1) : "0.0";
    const sign = diff >= 0 ? "+" : "";
    return `${sign}${percent}% vs baseline`;
  };

  const getTrendIcon = (trend: "up" | "down" | "neutral") => {
    if (trend === "up") return "↑";
    if (trend === "down") return "↓";
    return "—";
  };

  const getTrendColor = (trend: "up" | "down" | "neutral") => {
    if (trend === "up") return "text-green-400";
    if (trend === "down") return "text-red-400";
    return "text-gray-500";
  };

  const cells: MetricCell[] = [
    { key: "tokens_per_second", label: "Tokens/s", value: displayValues.tokens_per_second || "—", trend: getTrend("tokens_per_second"), sparkline: getSparkline("tokens_per_second"), color: "text-nexus-accent" },
    { key: "active_model", label: "Modelo Ativo", value: displayValues.active_model || "—" },
    { key: "active_sessions", label: "Sessões", value: displayValues.active_sessions || "—", trend: getTrend("active_sessions") },
    { key: "cpu_percent", label: "CPU", value: displayValues.cpu_percent || "—", trend: getTrend("cpu_percent"), color: metrics?.cpu_percent && metrics.cpu_percent > 80 ? "text-red-400" : undefined },
    { key: "ram_used_bytes", label: "RAM", value: displayValues.ram_used || "—", trend: getTrend("ram_used_bytes"), color: metrics?.ram_percent && metrics.ram_percent > 80 ? "text-red-400" : undefined },
    { key: "queue_depth", label: "Queue", value: displayValues.queue_depth || "—" },
    { key: "requests_total", label: "Requests", value: displayValues.requests_total || "—", trend: getTrend("requests_total") },
    { key: "avg_latency_ms", label: "Latência", value: displayValues.avg_latency || "—", trend: getTrend("avg_latency_ms"), color: metrics?.avg_latency_ms && metrics.avg_latency_ms > 1000 ? "text-red-400" : undefined },
    { key: "uptime_seconds", label: "Uptime", value: displayValues.uptime || "—" },
  ];

  const formatUptime = (seconds: number): string => {
    if (seconds < 60) return `${Math.floor(seconds)}s`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.floor(seconds % 60)}s`;
    if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
    return `${(seconds / 86400).toFixed(1)}d`;
  };

  const renderSparkline = (data: number[]) => {
    if (!data || data.length < 2) return null;
    const min = Math.min(...data);
    const max = Math.max(...data);
    const range = max - min || 1;
    const points = data.map((val, i) => {
      const x = (i / (data.length - 1)) * 100;
      const y = 100 - ((val - min) / range) * 100;
      return `${x},${y}`;
    }).join(" ");
    return (
      <svg className="h-4 w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
        <polyline points={points} fill="none" stroke="currentColor" strokeWidth="2" className="opacity-50" />
      </svg>
    );
  };

  return (
    <div className="space-y-3">
      {!backendOnline && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mb-2 rounded border border-yellow-500/30 bg-yellow-500/10 px-3 py-1.5 text-xs text-yellow-400">
          Backend offline — showing demo data
        </motion.div>
      )}
      <div className="grid grid-cols-3 gap-3 sm:grid-cols-5 lg:grid-cols-9">
        {cells.map((cell, index) => (
          <motion.div
            key={cell.key}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: index * 0.03 }}
            onClick={() => setSelectedMetric(cell.key)}
            className={`cursor-pointer rounded border p-3 transition-colors ${
              selectedMetric === cell.key
                ? "border-nexus-accent/50 bg-nexus-accent/5"
                : "border-nexus-border bg-nexus-panel hover:border-nexus-border/80"
            }`}
          >
            <div className="mb-1 text-xs text-gray-500">{cell.label}</div>
            <div className={`text-lg font-bold ${cell.color || "text-white"}`}>
              {cell.value}
            </div>
            <div className="mt-1 flex items-center gap-1">
              {cell.trend && (
                <span className={`text-xs ${getTrendColor(cell.trend)}`}>
                  {getTrendIcon(cell.trend)}
                </span>
              )}
              {cell.sparkline && renderSparkline(cell.sparkline)}
            </div>
          </motion.div>
        ))}
      </div>

      {/* Detail panel for selected metric */}
      {metrics && (
        <motion.div
          key={selectedMetric}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="rounded border border-nexus-border bg-nexus-panel p-3"
        >
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-400">
              {cells.find((c) => c.key === selectedMetric)?.label} — {getBaselineComparison(selectedMetric)}
            </span>
            <span className="text-gray-500">
              {history.length} samples
            </span>
          </div>
          <div className="mt-2">
            {renderSparkline(getSparkline(selectedMetric))}
          </div>
        </motion.div>
      )}
    </div>
  );
}
