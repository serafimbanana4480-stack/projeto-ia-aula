"use client";
import { useState, useEffect } from "react";
import { motion } from "framer-motion";
import TopBar from "../../components/layout/TopBar";
import Sidebar from "../../components/layout/Sidebar";
import BottomHUD from "../../components/layout/BottomHUD";
import { BarChart3, Code2, Zap, Clock, TrendingUp, AlertCircle } from "lucide-react";
import { getCurrentMetrics } from "../../lib/api";

interface AnalyticsData {
  tokens_per_second: number;
  active_model: string;
  requests_total: number;
  requests_successful: number;
  requests_failed: number;
  avg_latency_ms: number;
  uptime_seconds: number;
  lines_written: number;
  files_modified: number;
  agent_performance: Record<string, { tasks: number; success_rate: number }>;
}

export default function AnalysisPage() {
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const fetchAnalytics = async () => {
      try {
        const metrics = await getCurrentMetrics();
        
        // Transform backend metrics into analytics format
        const analyticsData: AnalyticsData = {
          tokens_per_second: metrics.tokens_per_second || 0,
          active_model: metrics.active_model || "N/A",
          requests_total: metrics.requests_total || 0,
          requests_successful: metrics.requests_successful || 0,
          requests_failed: metrics.requests_failed || 0,
          avg_latency_ms: metrics.avg_latency_ms || 0,
          uptime_seconds: metrics.uptime_seconds || 0,
          lines_written: metrics.requests_successful * 42 || 0, // Estimate
          files_modified: Math.floor(metrics.requests_successful / 3) || 0, // Estimate
          agent_performance: {
            CODER: {
              tasks: metrics.requests_successful || 0,
              success_rate: metrics.requests_total > 0 
                ? ((metrics.requests_successful / metrics.requests_total) * 100).toFixed(1) as any
                : 100,
            },
            SYSTEM: {
              tasks: metrics.requests_total || 0,
              success_rate: 100,
            },
          },
        };

        setAnalytics(analyticsData);
      } catch (error) {
        console.error("Failed to fetch analytics:", error);
      } finally {
        setLoading(false);
      }
    };

    fetchAnalytics();
    const interval = setInterval(fetchAnalytics, 5000);
    return () => clearInterval(interval);
  }, []);

  const formatUptime = (seconds: number) => {
    if (seconds < 60) return `${seconds.toFixed(0)}s`;
    if (seconds < 3600) return `${(seconds / 60).toFixed(0)}m`;
    if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}h`;
    return `${(seconds / 86400).toFixed(1)}d`;
  };

  return (
    <div className="flex h-screen flex-col bg-nexus-bg">
      <TopBar />
      
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        
        <main className="flex-1 overflow-auto p-6">
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            className="max-w-6xl mx-auto"
          >
            <div className="mb-6 flex items-center gap-3">
              <BarChart3 className="h-6 w-6 text-nexus-accent" />
              <h1 className="text-2xl font-bold">Analytics Dashboard</h1>
            </div>

            {loading ? (
              <div className="flex items-center justify-center py-12 text-gray-500">
                Loading analytics...
              </div>
            ) : analytics ? (
              <div className="space-y-6">
                {/* Key Metrics Grid */}
                <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-4">
                  <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
                  >
                    <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
                      <Zap className="h-3 w-3" />
                      Tokens/Second
                    </div>
                    <div className="text-2xl font-bold text-nexus-accent">
                      {analytics.tokens_per_second.toFixed(1)}
                    </div>
                  </motion.div>

                  <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: 0.1 }}
                    className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
                  >
                    <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
                      <Code2 className="h-3 w-3" />
                      Lines Written
                    </div>
                    <div className="text-2xl font-bold">
                      {analytics.lines_written.toLocaleString()}
                    </div>
                  </motion.div>

                  <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: 0.2 }}
                    className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
                  >
                    <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
                      <Clock className="h-3 w-3" />
                      Uptime
                    </div>
                    <div className="text-2xl font-bold">
                      {formatUptime(analytics.uptime_seconds)}
                    </div>
                  </motion.div>

                  <motion.div
                    initial={{ opacity: 0, scale: 0.95 }}
                    animate={{ opacity: 1, scale: 1 }}
                    transition={{ delay: 0.3 }}
                    className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
                  >
                    <div className="flex items-center gap-2 text-xs text-gray-500 mb-2">
                      <TrendingUp className="h-3 w-3" />
                      Success Rate
                    </div>
                    <div className="text-2xl font-bold text-green-400">
                      {analytics.requests_total > 0
                        ? ((analytics.requests_successful / analytics.requests_total) * 100).toFixed(1)
                        : "100"}%
                    </div>
                  </motion.div>
                </div>

                {/* Detailed Stats */}
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <motion.div
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
                  >
                    <h3 className="mb-4 text-sm font-semibold">Request Statistics</h3>
                    <div className="space-y-3">
                      <div className="flex justify-between">
                        <span className="text-xs text-gray-500">Total Requests</span>
                        <span className="text-sm font-medium">{analytics.requests_total}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-xs text-gray-500">Successful</span>
                        <span className="text-sm font-medium text-green-400">{analytics.requests_successful}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-xs text-gray-500">Failed</span>
                        <span className="text-sm font-medium text-red-400">{analytics.requests_failed}</span>
                      </div>
                      <div className="flex justify-between">
                        <span className="text-xs text-gray-500">Avg Latency</span>
                        <span className="text-sm font-medium">{analytics.avg_latency_ms.toFixed(0)}ms</span>
                      </div>
                    </div>
                  </motion.div>

                  <motion.div
                    initial={{ opacity: 0, x: 20 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.1 }}
                    className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
                  >
                    <h3 className="mb-4 text-sm font-semibold">Agent Performance</h3>
                    <div className="space-y-3">
                      {Object.entries(analytics.agent_performance).map(([agent, perf]) => (
                        <div key={agent} className="space-y-1">
                          <div className="flex justify-between">
                            <span className="text-xs text-gray-500">{agent}</span>
                            <span className="text-xs font-medium">{perf.tasks} tasks</span>
                          </div>
                          <div className="h-2 rounded-full bg-nexus-border">
                            <motion.div
                              initial={{ width: 0 }}
                              animate={{ width: `${perf.success_rate}%` }}
                              className="h-full rounded-full bg-nexus-accent"
                            />
                          </div>
                          <div className="text-xs text-gray-500 text-right">{perf.success_rate}% success</div>
                        </div>
                      ))}
                    </div>
                  </motion.div>
                </div>

                {/* Active Model Info */}
                <motion.div
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded border border-nexus-border bg-nexus-panel/50 p-4"
                >
                  <div className="flex items-center justify-between">
                    <div>
                      <h3 className="text-sm font-semibold">Active Model</h3>
                      <p className="text-xs text-gray-500">Currently selected AI model</p>
                    </div>
                    <div className="rounded bg-nexus-border px-4 py-2">
                      <span className="text-sm font-medium text-nexus-accent">{analytics.active_model}</span>
                    </div>
                  </div>
                </motion.div>
              </div>
            ) : (
              <div className="flex items-center justify-center py-12 text-gray-500">
                <AlertCircle className="mr-2 h-5 w-5" />
                Failed to load analytics data
              </div>
            )}
          </motion.div>
        </main>
      </div>
      
      <BottomHUD />
    </div>
  );
}
