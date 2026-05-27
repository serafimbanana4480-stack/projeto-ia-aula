"use client";
import { useMemo } from "react";
import { useMetricsStore } from "../../stores/metricsStore";
import { Bot, CheckCircle2, XCircle, Zap, Clock } from "lucide-react";

interface AgentActivityData {
  agent: string;
  status: "idle" | "active" | "error";
  tasks_completed: number;
  tasks_failed: number;
  avg_latency_ms: number;
  last_activity: string;
}

const AGENT_ICONS: Record<string, string> = {
  CODER: "💻",
  ARCHITECT: "🏗️",
  DEBUGGER: "🐛",
  ANALYZER: "📊",
  RESEARCHER: "🔍",
  DOCUMENTER: "📝",
  OPTIMIZER: "⚡",
  ROUTER: "🧭",
  DASHBOARD: "📈",
  MICRO: "🔬",
};

const AGENT_COLORS: Record<string, string> = {
  CODER: "text-blue-400",
  ARCHITECT: "text-purple-400",
  DEBUGGER: "text-red-400",
  ANALYZER: "text-green-400",
  RESEARCHER: "text-yellow-400",
  DOCUMENTER: "text-pink-400",
  OPTIMIZER: "text-orange-400",
  ROUTER: "text-cyan-400",
  DASHBOARD: "text-teal-400",
  MICRO: "text-gray-400",
};

export default function AgentActivity() {
  const metrics = useMetricsStore((s) => s.metrics);
  const backendOnline = useMetricsStore((s) => s.backendOnline);

  const activities = useMemo<AgentActivityData[]>(() => {
    if (!metrics || !Array.isArray(metrics.agent_activity)) return [];
    return metrics.agent_activity as AgentActivityData[];
  }, [metrics]);

  const loading = !metrics;

  const activeCount = useMemo(() => activities.filter((a) => a.status === "active").length, [activities]);
  const totalTasks = useMemo(
    () => activities.reduce((acc, a) => acc + a.tasks_completed + a.tasks_failed, 0),
    [activities]
  );

  const getStatusColor = (status: AgentActivityData["status"]) => {
    switch (status) {
      case "active":
        return "bg-green-500/15 text-green-400 border-green-500/30";
      case "idle":
        return "bg-gray-500/10 text-gray-400 border-gray-500/20";
      case "error":
        return "bg-red-500/15 text-red-400 border-red-500/30";
    }
  };

  const getStatusDot = (status: AgentActivityData["status"]) => {
    switch (status) {
      case "active":
        return <span className="h-2 w-2 rounded-full bg-green-400 animate-pulse" />;
      case "idle":
        return <span className="h-2 w-2 rounded-full bg-gray-500" />;
      case "error":
        return <span className="h-2 w-2 rounded-full bg-red-400" />;
    }
  };

  const formatLatency = (ms: number) => (ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`);

  const formatTimeAgo = (timestamp: string) => {
    const diff = Date.now() - new Date(timestamp).getTime();
    if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
    if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
    return `${Math.floor(diff / 3600000)}h ago`;
  };

  return (
    <div className="rounded border border-nexus-border bg-nexus-panel p-3">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bot className="h-4 w-4 text-nexus-accent" />
          <div className="text-sm font-semibold">Atividade dos Agentes</div>
          {!backendOnline && !loading && (
            <span className="rounded bg-yellow-500/10 px-1.5 py-0.5 text-[10px] text-yellow-400">offline</span>
          )}
        </div>
        <div className="flex items-center gap-3 text-[10px] text-gray-500">
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-green-400" />
            {activeCount} active
          </span>
          <span>{totalTasks} tasks</span>
        </div>
      </div>

      {loading ? (
        <div className="flex h-40 items-center justify-center text-xs text-gray-500">
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
            Carregando...
          </div>
        </div>
      ) : activities.length === 0 ? (
        <div className="flex h-40 flex-col items-center justify-center gap-1 text-xs text-gray-500">
          <span className="text-gray-400">Sem atividade de agentes</span>
          <span className="text-gray-600">Nenhuma sessão ativa no momento</span>
        </div>
      ) : (
        <div className="space-y-1">
          {activities.map((activity) => (
            <div
              key={activity.agent}
              className={`flex items-center justify-between rounded border px-2.5 py-2 hover:bg-nexus-border/10 transition-colors ${getStatusColor(activity.status)}`}
            >
              <div className="flex items-center gap-2.5">
                {getStatusDot(activity.status)}
                <span className="text-sm">{AGENT_ICONS[activity.agent] || "🤖"}</span>
                <div>
                  <span className={`text-xs font-semibold ${AGENT_COLORS[activity.agent] || "text-gray-300"}`}>
                    {activity.agent}
                  </span>
                  <div className="flex items-center gap-2 mt-0.5">
                    <span className="flex items-center gap-1 text-[10px] text-gray-500">
                      <CheckCircle2 className="h-3 w-3 text-green-400" />
                      {activity.tasks_completed}
                    </span>
                    {activity.tasks_failed > 0 && (
                      <span className="flex items-center gap-1 text-[10px] text-gray-500">
                        <XCircle className="h-3 w-3 text-red-400" />
                        {activity.tasks_failed}
                      </span>
                    )}
                  </div>
                </div>
              </div>
              <div className="flex items-center gap-3 text-[10px] text-gray-400">
                <span className="flex items-center gap-1">
                  <Zap className="h-3 w-3" />
                  {formatLatency(activity.avg_latency_ms)}
                </span>
                <span className="flex items-center gap-1 text-gray-500">
                  <Clock className="h-3 w-3" />
                  {formatTimeAgo(activity.last_activity)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
