"use client";
import { useMemo } from "react";
import { useMetricsStore } from "../../stores/metricsStore";
import { motion } from "framer-motion";
import { Clock, Zap, Activity } from "lucide-react";

interface SessionStats {
  tokens_used: number;
  latency_ms: number;
  throughput_tps: number;
}

export default function SessionStats() {
  const metrics = useMetricsStore((s) => s.metrics);
  const backendOnline = useMetricsStore((s) => s.backendOnline);

  const stats: SessionStats = useMemo(() => {
    return {
      tokens_used: metrics?.message_stats?.tokens_out_total ?? 0,
      latency_ms:
        metrics?.message_stats?.avg_latency_ms ?? metrics?.avg_latency_ms ?? 0,
      throughput_tps: metrics?.tokens_per_second ?? 0,
    };
  }, [metrics]);

  const isLoading = !metrics && backendOnline;
  const error = !backendOnline ? "Backend offline" : null;

  const formatLatency = (ms: number) => {
    if (ms < 1) return `${(ms * 1000).toFixed(0)}μs`;
    if (ms < 1000) return `${ms.toFixed(0)}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  return (
    <motion.div
      initial={{ x: 20, opacity: 0 }}
      animate={{ x: 0, opacity: 1 }}
      className="rounded border border-nexus-border bg-nexus-panel/50 p-3"
    >
      <div className="mb-3 text-sm font-semibold">Session Stats</div>

      {isLoading && (
        <div className="flex items-center justify-center py-4">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
        </div>
      )}

      {error && (
        <div className="rounded border border-red-500/50 bg-red-500/10 p-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {!isLoading && !error && (
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <Clock className="h-3 w-3" />
              <span>Latency</span>
            </div>
            <span className="text-xs font-medium">
              {formatLatency(stats.latency_ms)}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <Zap className="h-3 w-3" />
              <span>Tokens</span>
            </div>
            <span className="text-xs font-medium">
              {stats.tokens_used.toLocaleString()}
            </span>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <Activity className="h-3 w-3" />
              <span>Throughput</span>
            </div>
            <span className="text-xs font-medium">
              {stats.throughput_tps.toFixed(1)} t/s
            </span>
          </div>
        </div>
      )}
    </motion.div>
  );
}
