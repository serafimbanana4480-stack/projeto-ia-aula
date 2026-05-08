"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { apiUrl, getCurrentMetrics } from "../../lib/api";

interface MetricsSnapshot {
  tokens_per_second: number;
  active_model: string;
  active_sessions: number;
  queue_depth: number;
  ram_used_bytes: number;
  ram_total_bytes: number;
  ram_percent: number;
  cpu_percent: number;
  disk_used_bytes: number;
  disk_total_bytes: number;
  disk_percent: number;
  uptime_seconds: number;
  requests_total: number;
  requests_successful: number;
  requests_failed: number;
  avg_latency_ms: number;
  timestamp: number;
}

interface MetricCell {
  key: keyof MetricsSnapshot;
  label: string;
  value: string;
  trend?: "up" | "down" | "neutral";
  sparkline?: number[];
  color?: string;
}

export default function MetricsGrid() {
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);
  const [displayValues, setDisplayValues] = useState<Record<string, string>>({});
  const [history, setHistory] = useState<MetricsSnapshot[]>([]);
  const [baseline, setBaseline] = useState<MetricsSnapshot | null>(null);
  const [selectedMetric, setSelectedMetric] = useState<keyof MetricsSnapshot>("tokens_per_second");

  useEffect(() => {
    let mounted = true;
    let fallbackTimer: ReturnType<typeof setInterval> | null = null;
    // SSE connection to /api/metrics/dashboard/stream
    const eventSource = new EventSource(apiUrl("/api/metrics/dashboard/stream"));

    const applyMetrics = (data: MetricsSnapshot) => {
      if (!mounted) return;
      setMetrics(data);
      setHistory((prev) => [...prev.slice(-49), data]); // Keep last 50 samples
      if (!baseline) setBaseline(data); // Set baseline on first sample
    };

    const startPollingFallback = () => {
      if (fallbackTimer) return;
      fallbackTimer = setInterval(async () => {
        try {
          const data = await getCurrentMetrics();
          applyMetrics(data as MetricsSnapshot);
        } catch (error) {
          console.error("Polling fallback failed:", error);
        }
      }, 2000);
    };
    
    eventSource.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as MetricsSnapshot;
        applyMetrics(data);
      } catch (error) {
        console.error("Failed to parse metrics:", error);
      }
    };

    eventSource.onerror = (error) => {
      console.error("SSE error:", error);
      eventSource.close();
      startPollingFallback();
    };

    return () => {
      mounted = false;
      if (fallbackTimer) clearInterval(fallbackTimer);
      eventSource.close();
    };
  }, []);

  // Animate number changes (count-up effect)
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
    return history.slice(-20).map((h) => h[metric] as number); // Show last 20 samples
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
    {
      key: "tokens_per_second",
      label: "Tokens/s",
      value: displayValues.tokens_per_second || "—",
      trend: getTrend("tokens_per_second"),
      sparkline: getSparkline("tokens_per_second"),
      color: "text-nexus-accent",
    },
    {
      key: "active_model",
      label: "Modelo Ativo",
      value: displayValues.active_model || "—",
    },
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
      color: metrics?.cpu_percent && metrics.cpu_percent > 80 ? "text-red-400" : undefined,
    },
    {
      key: "ram_used_bytes",
      label: "RAM",
      value: displayValues.ram_used || "—",
      trend: getTrend("ram_used_bytes"),
      color: metrics?.ram_percent && metrics.ram_percent > 80 ? "text-red-400" : undefined,
    },
    {
      key: "queue_depth",
      label: "Queue",
      value: displayValues.queue_depth || "—",
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
      color: metrics?.avg_latency_ms && metrics.avg_latency_ms > 1000 ? "text-red-400" : undefined,
    },
    {
      key: "uptime_seconds",
      label: "Uptime",
      value: displayValues.uptime || "—",
    },
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
        <polyline
          points={points}
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          className="opacity-50"
        />
      </svg>
    );
  };

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4 xl:grid-cols-9">
        {cells.map((cell, index) => (
          <motion.button
            key={cell.label}
            type="button"
            onClick={() => setSelectedMetric(cell.key)}
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.3, delay: index * 0.05 }}
            whileHover={{ scale: 1.03, transition: { duration: 0.2 } }}
            className={`rounded-xl border p-3 text-left transition-colors ${
              selectedMetric === cell.key
                ? "border-nexus-accent bg-nexus-accent/10"
                : "border-nexus-border bg-nexus-panel hover:bg-nexus-border/30"
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="text-xs text-gray-500">{cell.label}</div>
              {cell.trend && (
                <motion.span
                  initial={{ scale: 0 }}
                  animate={{ scale: 1 }}
                  className={`text-xs ${getTrendColor(cell.trend)}`}
                >
                  {getTrendIcon(cell.trend)}
                </motion.span>
              )}
            </div>
            <motion.div
              initial={{ opacity: 0, y: 5 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.2 }}
              className={`mt-1 text-sm font-semibold ${cell.color || ""}`}
            >
              {cell.value}
            </motion.div>
            {cell.sparkline && renderSparkline(cell.sparkline)}
          </motion.button>
        ))}
      </div>

      {metrics && (
        <div className="rounded-xl border border-nexus-border bg-nexus-panel p-4">
          <div className="mb-2 flex items-center justify-between">
            <div>
              <div className="text-xs uppercase tracking-wide text-gray-500">Metric drill-down</div>
              <div className="text-sm font-semibold text-gray-100">{selectedMetric.replaceAll("_", " ")}</div>
            </div>
            <div className="text-xs text-gray-500">Live</div>
          </div>
          <div className="grid gap-4 md:grid-cols-3">
            <motion.div
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              transition={{ duration: 0.2 }}
            >
              <div className="text-xs text-gray-500">Current value</div>
              <div className="mt-1 text-xl font-semibold text-nexus-accent">
                {typeof metrics[selectedMetric] === "number" 
                  ? (selectedMetric.includes("percent") || selectedMetric.includes("latency")
                      ? `${(metrics[selectedMetric] as number).toFixed(selectedMetric.includes("latency") ? 0 : 1)}`
                      : (metrics[selectedMetric] as number).toLocaleString())
                  : String(metrics[selectedMetric] ?? "—")}
              </div>
            </motion.div>
            <motion.div
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2, delay: 0.1 }}
            >
              <div className="text-xs text-gray-500">Trend</div>
              <div className="mt-1 text-sm text-gray-200">
                {history.length >= 2 && typeof metrics[selectedMetric] === "number"
                  ? `${getTrend(selectedMetric)} vs previous sample`
                  : "Waiting for more samples"}
              </div>
            </motion.div>
            <motion.div
              initial={{ opacity: 0, x: 10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.2, delay: 0.15 }}
            >
              <div className="text-xs text-gray-500">Baseline</div>
              <div className="mt-1 text-sm text-gray-200">
                {getBaselineComparison(selectedMetric)}
              </div>
            </motion.div>
          </div>
          <div className="mt-4 pt-4 border-t border-nexus-border">
            <div className="text-xs text-gray-500">Context</div>
            <div className="mt-1 text-sm text-gray-200">
              {selectedMetric === "avg_latency_ms" && "Measures backend responsiveness."}
              {selectedMetric === "tokens_per_second" && "Tracks generation throughput across the active model."}
              {selectedMetric === "requests_total" && "Counts observed requests in this session."}
              {selectedMetric === "cpu_percent" && "System load indicator for the host."}
              {selectedMetric === "ram_used_bytes" && "Current memory pressure of the process host."}
              {selectedMetric === "active_sessions" && "Live chat sessions currently known to the backend."}
              {selectedMetric === "queue_depth" && "Requests waiting for orchestration or tools."}
              {selectedMetric === "uptime_seconds" && "Backend process lifetime since the last restart."}
              {selectedMetric === "active_model" && "Most active model observed by the collector."}
            </div>
          </div>
          {selectedMetric !== "active_model" && selectedMetric !== "active_sessions" && (
            <div className="mt-4 text-nexus-accent">
              {renderSparkline(getSparkline(selectedMetric as keyof MetricsSnapshot))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
