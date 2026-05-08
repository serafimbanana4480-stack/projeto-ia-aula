"use client";
import { useState, useEffect } from "react";
import { getCurrentMetrics } from "../../lib/api";
import { motion } from "framer-motion";
import { Clock, Zap, DollarSign, Activity } from "lucide-react";

interface SessionStats {
  tokens_used: number;
  latency_ms: number;
  cost_estimated: number;
  throughput_tps: number;
}

export default function SessionStats() {
  const [stats, setStats] = useState<SessionStats>({
    tokens_used: 0,
    latency_ms: 0,
    cost_estimated: 0,
    throughput_tps: 0,
  });

  useEffect(() => {
    // Fetch session stats from backend
    const fetchStats = async () => {
      try {
        const data = await getCurrentMetrics();
        setStats({
          tokens_used: data.tokens_per_second * 60 || 0,
          latency_ms: data.avg_latency_ms || 0,
          cost_estimated: (data.tokens_per_second * 0.0001) || 0,
          throughput_tps: data.tokens_per_second || 0,
        });
      } catch (error) {
        console.error("Failed to fetch stats:", error);
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
      
      <div className="space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <Clock className="h-3 w-3" />
            <span>Latency</span>
          </div>
          <span className="text-xs font-medium">{formatLatency(stats.latency_ms)}</span>
        </div>
        
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <Zap className="h-3 w-3" />
            <span>Tokens</span>
          </div>
          <span className="text-xs font-medium">{stats.tokens_used.toLocaleString()}</span>
        </div>
        
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <DollarSign className="h-3 w-3" />
            <span>Cost</span>
          </div>
          <span className="text-xs font-medium">${stats.cost_estimated.toFixed(4)}</span>
        </div>
        
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-gray-400">
            <Activity className="h-3 w-3" />
            <span>Throughput</span>
          </div>
          <span className="text-xs font-medium">{stats.throughput_tps.toFixed(1)} t/s</span>
        </div>
      </div>
    </motion.div>
  );
}
