"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { getCurrentMetrics } from "../../lib/api";

interface AgentActivity {
  agent: string;
  status: "idle" | "active" | "error";
  tasks_completed: number;
  tasks_failed: number;
  avg_latency_ms: number;
  last_activity: string;
}

export default function AgentActivity() {
  const [activities, setActivities] = useState<AgentActivity[]>([]);
  const [loading, setLoading] = useState(true);
  const [unavailableReason, setUnavailableReason] = useState<string | null>(
    null,
  );

  useEffect(() => {
    const fetchActivities = async () => {
      try {
        const metrics = await getCurrentMetrics();
        const agentMetrics = Array.isArray(metrics.agent_activity)
          ? metrics.agent_activity
          : [];
        setActivities(agentMetrics as AgentActivity[]);
        setUnavailableReason(
          agentMetrics.length === 0
            ? "Per-agent runtime metrics are not instrumented yet."
            : null,
        );
      } catch (error) {
        console.error("Failed to fetch agent activities:", error);
        setActivities([]);
        setUnavailableReason("Agent activity endpoint is unavailable.");
      } finally {
        setLoading(false);
      }
    };

    fetchActivities();

    // Refresh every 30 seconds
    const interval = setInterval(fetchActivities, 30000);
    return () => clearInterval(interval);
  }, []);

  const getStatusColor = (status: AgentActivity["status"]) => {
    switch (status) {
      case "active":
        return "bg-green-500/20 text-green-400";
      case "idle":
        return "bg-gray-500/20 text-gray-400";
      case "error":
        return "bg-red-500/20 text-red-400";
    }
  };

  const getStatusDot = (status: AgentActivity["status"]) => {
    switch (status) {
      case "active":
        return "●";
      case "idle":
        return "○";
      case "error":
        return "✗";
    }
  };

  const formatLatency = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  const formatTimeAgo = (timestamp: string) => {
    const diff = Date.now() - new Date(timestamp).getTime();
    if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    return `${Math.floor(diff / 3600000)}h ago`;
  };

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3 }}
      className="rounded border border-nexus-border bg-nexus-panel p-3"
    >
      <div className="mb-2 text-sm font-semibold">Atividade dos Agentes</div>

      {loading ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex h-40 items-center justify-center text-xs text-gray-500"
        >
          Carregando...
        </motion.div>
      ) : activities.length > 0 ? (
        <div className="space-y-2">
          {activities.map((activity, index) => (
            <motion.div
              key={activity.agent}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.1 }}
              whileHover={{ scale: 1.02 }}
              className="flex items-center justify-between rounded border border-nexus-border/50 p-2 hover:bg-nexus-border/20"
            >
              <div className="flex items-center gap-3">
                <motion.span
                  initial={{ scale: 0, rotate: -180 }}
                  animate={{ scale: 1, rotate: 0 }}
                  transition={{ delay: index * 0.1 + 0.2 }}
                  className={`text-lg ${getStatusColor(activity.status)}`}
                >
                  {getStatusDot(activity.status)}
                </motion.span>
                <div>
                  <div className="text-sm font-medium">{activity.agent}</div>
                  <div className="text-xs text-gray-500">
                    {activity.tasks_completed} tasks, {activity.tasks_failed}{" "}
                    failed
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-4 text-xs text-gray-400">
                <div>
                  <span className="text-gray-500">Lat:</span>{" "}
                  {formatLatency(activity.avg_latency_ms)}
                </div>
                <div>{formatTimeAgo(activity.last_activity)}</div>
              </div>
            </motion.div>
          ))}
        </div>
      ) : (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex h-40 flex-col items-center justify-center gap-2 text-center text-xs text-gray-500"
        >
          <div>Agent telemetry unavailable</div>
          <div className="max-w-sm text-gray-600">
            {unavailableReason ??
              "No real per-agent activity samples were returned by the backend."}
          </div>
        </motion.div>
      )}
    </motion.div>
  );
}
