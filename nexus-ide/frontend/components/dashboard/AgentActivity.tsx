"use client";
import { useEffect, useMemo, useState } from "react";
import { useMetricsStore } from "../../stores/metricsStore";
import { Bot, CheckCircle2, XCircle, Zap, Clock } from "lucide-react";
import DashboardCharts, { CHART_COLORS } from "../dashboard-charts";

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

// Cores das barras (uma por agente) alinhadas ao tema nexus.
const AGENT_BAR_COLORS: Record<string, string> = {
  CODER: CHART_COLORS[0],
  ARCHITECT: CHART_COLORS[4],
  DEBUGGER: CHART_COLORS[3],
  ANALYZER: CHART_COLORS[1],
  RESEARCHER: CHART_COLORS[2],
  DOCUMENTER: "#f472b6",
  OPTIMIZER: "#fb923c",
  ROUTER: CHART_COLORS[5],
  DASHBOARD: "#2dd4bf",
  MICRO: "#a78bfa",
};

const STATUS_LABEL: Record<AgentActivityData["status"], string> = {
  active: "ativo",
  idle: "inativo",
  error: "erro",
};

/** Returns true on >= sm breakpoint (640px) for responsive chart height. */
function useIsSm(): boolean {
  const [isSm, setIsSm] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const mq = window.matchMedia("(min-width: 640px)");
    const update = () => setIsSm(mq.matches);
    update();
    mq.addEventListener("change", update);
    return () => mq.removeEventListener("change", update);
  }, []);
  return isSm;
}

export default function AgentActivity() {
  const metrics = useMetricsStore((s) => s.metrics);
  const backendOnline = useMetricsStore((s) => s.backendOnline);
  const isSm = useIsSm();

  const activities = useMemo<AgentActivityData[]>(() => {
    if (!metrics || !Array.isArray(metrics.agent_activity)) return [];
    return metrics.agent_activity as AgentActivityData[];
  }, [metrics]);

  const loading = !metrics;

  const activeCount = useMemo(
    () => activities.filter((a) => a.status === "active").length,
    [activities],
  );
  const totalTasks = useMemo(
    () => activities.reduce((acc, a) => acc + a.tasks_completed + a.tasks_failed, 0),
    [activities],
  );

  // Dados para o gráfico de barras: tasks_completed por agente.
  const chartData = useMemo(
    () =>
      activities.map((a) => ({
        agent: a.agent,
        tasks_completed: a.tasks_completed,
        tasks_failed: a.tasks_failed,
      })),
    [activities],
  );

  const chartCells = useMemo(
    () =>
      activities.map(
        (a) => AGENT_BAR_COLORS[a.agent] ?? CHART_COLORS[0],
      ),
    [activities],
  );

  const chartHeight = isSm ? 220 : 180;

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
    const label = STATUS_LABEL[status];
    switch (status) {
      case "active":
        return (
          <span
            className="h-2 w-2 rounded-full bg-green-400 animate-pulse"
            role="img"
            aria-label={label}
          />
        );
      case "idle":
        return (
          <span
            className="h-2 w-2 rounded-full bg-gray-500"
            role="img"
            aria-label={label}
          />
        );
      case "error":
        return (
          <span
            className="h-2 w-2 rounded-full bg-red-400"
            role="img"
            aria-label={label}
          />
        );
    }
  };

  const formatLatency = (ms: number) =>
    ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;

  const formatTimeAgo = (timestamp: string) => {
    const diff = Date.now() - new Date(timestamp).getTime();
    if (Number.isNaN(diff)) return "—";
    if (diff < 60000) return `há ${Math.floor(diff / 1000)}s`;
    if (diff < 3600000) return `há ${Math.floor(diff / 60000)}m`;
    return `há ${Math.floor(diff / 3600000)}h`;
  };

  const summaryText = `Agentes ativos: ${activeCount} · ${totalTasks} tarefas`;

  return (
    <div className="min-w-0 rounded border border-nexus-border bg-nexus-panel p-3">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bot className="h-4 w-4 text-nexus-accent" />
          <div className="text-sm font-semibold">Atividade de Agentes</div>
          {!backendOnline && !loading && (
            <span className="rounded bg-yellow-500/10 px-1.5 py-0.5 text-[10px] text-yellow-400">
              offline
            </span>
          )}
        </div>
        <div
          className="flex items-center gap-3 text-[10px] text-gray-500"
          aria-live="polite"
          aria-atomic="true"
        >
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-green-400" aria-hidden="true" />
            {summaryText}
          </span>
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
        <div className="space-y-3">
          <div>
            <div className="mb-1 text-[11px] font-medium text-nexus-muted">
              Tarefas concluídas por agente
            </div>
            <DashboardCharts
              kind="bar"
              data={chartData}
              xKey="agent"
              height={chartHeight}
              showLegend={false}
              showGrid={false}
              series={[
                {
                  key: "tasks_completed",
                  name: "Concluídas",
                  cells: chartCells,
                },
              ]}
              className="!border-nexus-border !bg-nexus-card !p-2"
            />
          </div>

          <div className="space-y-1" role="list">
            {activities.map((activity) => (
              <div
                key={activity.agent}
                role="listitem"
                className={`flex items-center justify-between rounded border px-2.5 py-2 transition-colors hover:bg-nexus-border/10 ${getStatusColor(
                  activity.status,
                )}`}
              >
                <div className="flex items-center gap-2.5">
                  {getStatusDot(activity.status)}
                  <span className="text-xs sm:text-sm" aria-hidden="true">
                    {AGENT_ICONS[activity.agent] || "🤖"}
                  </span>
                  <div className="min-w-0">
                    <span
                      className={`block truncate text-xs font-semibold sm:text-sm ${
                        AGENT_COLORS[activity.agent] || "text-gray-300"
                      }`}
                    >
                      {activity.agent}
                    </span>
                    <div className="mt-0.5 flex items-center gap-2">
                      <span
                        className="flex items-center gap-1 text-[10px] text-gray-500"
                        title="Concluídas"
                      >
                        <CheckCircle2 className="h-3 w-3 text-green-400" aria-hidden="true" />
                        <span aria-label="Concluídas">
                          {activity.tasks_completed}
                        </span>
                      </span>
                      {activity.tasks_failed > 0 && (
                        <span
                          className="flex items-center gap-1 text-[10px] text-gray-500"
                          title="Falhadas"
                        >
                          <XCircle className="h-3 w-3 text-red-400" aria-hidden="true" />
                          <span aria-label="Falhadas">
                            {activity.tasks_failed}
                          </span>
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex items-center gap-3 text-[10px] text-gray-400">
                  <span
                    className="flex items-center gap-1"
                    title="Latência média"
                  >
                    <Zap className="h-3 w-3" aria-hidden="true" />
                    {formatLatency(activity.avg_latency_ms)}
                  </span>
                  <span
                    className="flex items-center gap-1 text-gray-500"
                    title="Última atividade"
                  >
                    <Clock className="h-3 w-3" aria-hidden="true" />
                    {formatTimeAgo(activity.last_activity)}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
