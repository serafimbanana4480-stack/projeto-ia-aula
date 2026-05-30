"use client";
import { useState, useEffect } from "react";
import { getCurrentMetrics } from "../../lib/api";
import { motion } from "framer-motion";
import { Clock, Zap, Activity } from "lucide-react";
import { log } from "../../lib/log";

interface SessionStats {
  tokens_used: number;
  latency_ms: number;
  throughput_tps: number;
}

export default function SessionStats() {
  const [stats, setStats] = useState<SessionStats>({
    tokens_used: 0,
    latency_ms: 0,
    throughput_tps: 0,
  });
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    // Fetch session stats from backend
    const fetchStats = async () => {
      try {
        setError(null);
        const data = await getCurrentMetrics();
        setStats({
          tokens_used: data.message_stats?.tokens_out_total ?? 0,
          latency_ms:
            data.message_stats?.avg_latency_ms ?? data.avg_latency_ms ?? 0,
          throughput_tps: data.tokens_per_second ?? 0,
        });
        setIsLoading(false);
      } catch (error) {
        log.error("Failed to fetch stats:", error);
        setError(
          error instanceof Error ? error.message : "Failed to fetch stats",
        );
        setIsLoading(false);
      }
    };

    fetchStats();
    const interval = setInterval(fetchStats, 5000);
    return () => clearInterval(interval);
  }, []);

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
