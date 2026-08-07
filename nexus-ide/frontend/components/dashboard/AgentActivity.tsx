"use client";
import { useEffect, useMemo, useState } from "react";
import { useMetricsStore } from "../../stores/metricsStore";
import { Bot, CheckCircle2, XCircle, Zap, Clock } from "lucide-react";
import DashboardCharts, { CHART_COLORS } from "../dashboard-charts";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { Badge, StatusDot, EmptyState } from "../ui/Primitives";

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

// Per-agent identity colour — matches the bar chart legend. This is distinct
// from status colour (StatusDot below) and is intentionally not touched by
// the emerald/amber/rose status palette.
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

const STATUS_TONE: Record<AgentActivityData["status"], "success" | "neutral" | "danger"> = {
  active: "success",
  idle: "neutral",
  error: "danger",
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

  const formatLatency = (ms: number) =>
    ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;

  const formatTimeAgo = (timestamp: string) => {
    const diff = Date.now() - new Date(timestamp).getTime();
    if (Number.isNaN(diff)) return "—";
    if (diff < 60000) return `há ${Math.floor(diff / 1000)}s`;
    if (diff < 3600000) return `há ${Math.floor(diff / 60000)}m`;
    return `há ${Math.floor(diff / 3600000)}h`;
  };

  return (
    <Surface elevation={1} padding="sm" live={backendOnline}>
      <SurfaceHeader
        icon={<Bot className="h-4 w-4" />}
        title="Atividade de Agentes"
        subtitle="Tarefas concluídas e falhadas por agente"
        action={
          <div className="flex items-center gap-1.5" aria-live="polite" aria-atomic="true">
            {!backendOnline && !loading && <Badge tone="warning">offline</Badge>}
            <Badge tone={activeCount > 0 ? "success" : "neutral"} icon={<StatusDot tone={activeCount > 0 ? "success" : "neutral"} pulse={activeCount > 0} size={6} />}>
              {activeCount} ativo{activeCount === 1 ? "" : "s"}
            </Badge>
          </div>
        }
      />

      {loading ? (
        <div
          className="mt-3 space-y-2"
          role="status"
          aria-label="A carregar atividade de agentes"
          aria-live="polite"
        >
          <div className="nx-shimmer h-[180px] rounded-lg" />
          <div className="nx-shimmer h-8 rounded-lg" />
          <div className="nx-shimmer h-8 rounded-lg" />
        </div>
      ) : activities.length === 0 ? (
        <div className="mt-3">
          <EmptyState
            compact
            icon={<Bot className="h-5 w-5" />}
            title="Sem atividade de agentes"
            hint="Nenhuma sessão ativa no momento — inicia uma conversa para veres os agentes a trabalhar."
          />
        </div>
      ) : (
        <div className="mt-3 space-y-3">
          <div>
            <div className="mb-1 flex items-center justify-between text-[11px] font-medium text-nexus-muted">
              <span>Tarefas concluídas por agente</span>
              <span className="tabular-nums text-nexus-faint">{totalTasks} no total</span>
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
              className="!border-[var(--nx-line)] !bg-[var(--nx-surface-1)] !p-2"
            />
          </div>

          <ul role="list" className="nx-inset divide-y divide-[var(--nx-line)] overflow-hidden rounded-lg">
            {activities.map((activity) => (
              <li
                key={activity.agent}
                role="listitem"
                className="flex items-center justify-between gap-2 px-2.5 py-2 transition-colors hover:bg-white/[0.03]"
              >
                <div className="flex min-w-0 items-center gap-2">
                  <StatusDot tone={STATUS_TONE[activity.status]} pulse={activity.status === "active"} label={STATUS_LABEL[activity.status]} />
                  <span className="text-xs" aria-hidden="true">
                    {AGENT_ICONS[activity.agent] || "🤖"}
                  </span>
                  <div className="min-w-0">
                    <span
                      className={`block truncate text-xs font-semibold ${AGENT_COLORS[activity.agent] || "text-nexus-text"}`}
                      title={activity.agent}
                    >
                      {activity.agent}
                    </span>
                    <div className="mt-0.5 flex items-center gap-2">
                      <span className="flex items-center gap-1 text-[10px] text-nexus-faint" title="Concluídas">
                        <CheckCircle2 className="h-3 w-3 text-emerald-400" aria-hidden="true" />
                        <span className="tabular-nums" aria-label="Concluídas">
                          {activity.tasks_completed}
                        </span>
                      </span>
                      {activity.tasks_failed > 0 && (
                        <span className="flex items-center gap-1 text-[10px] text-nexus-faint" title="Falhadas">
                          <XCircle className="h-3 w-3 text-rose-400" aria-hidden="true" />
                          <span className="tabular-nums" aria-label="Falhadas">
                            {activity.tasks_failed}
                          </span>
                        </span>
                      )}
                    </div>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2.5 text-[10px] text-nexus-muted">
                  <span className="flex items-center gap-1 tabular-nums" title="Latência média">
                    <Zap className="h-3 w-3" aria-hidden="true" />
                    {formatLatency(activity.avg_latency_ms)}
                  </span>
                  <span className="flex items-center gap-1 text-nexus-faint" title="Última atividade">
                    <Clock className="h-3 w-3" aria-hidden="true" />
                    {formatTimeAgo(activity.last_activity)}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Surface>
  );
}
