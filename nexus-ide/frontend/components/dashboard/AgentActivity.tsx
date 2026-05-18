"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { getCurrentMetrics } from "../../lib/api";

export interface AgentActivityData {
  agent: string;
  status: "idle" | "active" | "error";
  tasks_completed: number;
  tasks_failed: number;
  avg_latency_ms: number;
  last_activity: string;
}

export default function AgentActivity() {
  const [activities, setActivities] = useState<AgentActivityData[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasData, setHasData] = useState(false);
  const [backendOnline, setBackendOnline] = useState(false);

  useEffect(() => {
    const fetchActivities = async () => {
      try {
        const metrics = await getCurrentMetrics();
        const agentMetrics = Array.isArray(metrics.agent_activity) ? metrics.agent_activity : [];
        if (agentMetrics.length > 0) {
          setActivities(agentMetrics as AgentActivityData[]);
          setHasData(true);
          setBackendOnline(true);
        } else {
          setActivities([]);
          setHasData(false);
          setBackendOnline(true);
        }
      } catch {
        setActivities([]);
        setHasData(false);
        setBackendOnline(false);
      } finally {
        setLoading(false);
      }
    };

    fetchActivities();
    const interval = setInterval(fetchActivities, 30000);
    return () => clearInterval(interval);
  }, []);

  const getStatusColor = (status: AgentActivityData["status"]) => {
    switch (status) {
      case "active": return "bg-green-500/20 text-green-400";
      case "idle": return "bg-gray-500/20 text-gray-400";
      case "error": return "bg-red-500/20 text-red-400";
    }
  };

  const getStatusDot = (status: AgentActivityData["status"]) => {
    switch (status) {
      case "active": return "●";
      case "idle": return "○";
      case "error": return "✗";
    }
  };

  const formatLatency = (ms: number) => ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;

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
      {!backendOnline && (
        <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} className="mb-2 rounded border border-yellow-500/30 bg-yellow-500/10 px-3 py-1.5 text-xs text-yellow-400">
          OFFLINE — Dados de exemplo (backend desconectado)
        </motion.div>
      )}
      <div className="mb-2 flex items-center justify-between">
        <div className="text-sm font-semibold">Atividade dos Agentes</div>
        {!hasData && !loading && (
          <span className="text-xs text-gray-600">indisponível</span>
        )}
      </div>

      {loading ? (
        <div className="flex h-40 items-center justify-center text-xs text-gray-500">
          Carregando...
        </div>
      ) : !hasData ? (
        <div className="flex h-40 flex-col items-center justify-center text-xs text-gray-500">
          <span className="text-gray-400">Sem atividade de agentes</span>
          <span className="text-gray-600">Backend offline ou sem sessões ativas</span>
        </div>
      ) : (
        <div className="space-y-1.5">
          {activities.map((activity, index) => (
            <motion.div
              key={activity.agent}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.05 }}
              className="flex items-center justify-between rounded border border-nexus-border/50 px-2.5 py-1.5 hover:bg-nexus-border/20"
            >
              <div className="flex items-center gap-2">
                <span className={`text-sm ${getStatusColor(activity.status)}`}>
                  {getStatusDot(activity.status)}
                </span>
                <div>
                  <span className="text-xs font-medium">{activity.agent}</span>
                  <span className="ml-2 text-xs text-gray-500">
                    {activity.tasks_completed} ok, {activity.tasks_failed} fail
                  </span>
                </div>
              </div>
              <div className="flex items-center gap-3 text-xs text-gray-400">
                <span>{formatLatency(activity.avg_latency_ms)}</span>
                <span className="text-gray-500">{formatTimeAgo(activity.last_activity)}</span>
              </div>
            </motion.div>
          ))}
        </div>
      )}
    </motion.div>
  );
}
