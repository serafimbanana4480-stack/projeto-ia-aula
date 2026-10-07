"use client";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useMetricsStore } from "../../stores/metricsStore";
import { getMetricsFlow } from "../../lib/api";
import {
  GitBranch,
  CheckCircle2,
  XCircle,
  Timer,
  Gauge,
  User,
  Router,
  Bot,
  Brain,
  MessageSquare,
  ArrowRight,
  Power,
  Users,
} from "lucide-react";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { Meter, AnimatedNumber, StatusDot, EmptyState } from "../ui/Primitives";

interface FlowSummary {
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  avg_latency_ms: number;
  throughput_tps: number;
}

type AgentStatus = "idle" | "active" | "error";

interface AgentActivity {
  agent: string;
  status: AgentStatus;
  tasks_completed: number;
  tasks_failed: number;
  avg_latency_ms: number;
  last_activity: string;
}

const STATUS_TONE: Record<AgentStatus, "success" | "danger" | "neutral"> = {
  active: "success",
  error: "danger",
  idle: "neutral",
};

const fmtLatency = (ms: number): string => {
  if (!Number.isFinite(ms)) return "—";
  if (ms < 1) return `${(ms * 1000).toFixed(0)}μs`;
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
};

const fmtNum = (n: number): string => {
  if (!Number.isFinite(n)) return "0";
  if (Math.abs(n) >= 1000) return n.toLocaleString("pt-PT");
  return Number.isInteger(n) ? String(n) : n.toFixed(1);
};

export default function RequestFlow() {
  const metrics = useMetricsStore((s) => s.metrics);
  const backendOnline = useMetricsStore((s) => s.backendOnline);
  const connectionStatus = useMetricsStore((s) => s.connectionStatus);

  const [flowThroughput, setFlowThroughput] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    getMetricsFlow()
      .then((data) => {
        if (cancelled || !data) return;
        const summary = data.summary as
          | { throughput_tps?: unknown }
          | undefined;
        const tpsRaw = summary?.throughput_tps;
        const tps = typeof tpsRaw === "number" ? tpsRaw : Number(tpsRaw);
        if (Number.isFinite(tps)) setFlowThroughput(tps);
      })
      .catch(() => {
        /* fallback ao store — sem polling */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const summary = useMemo<FlowSummary | null>(() => {
    if (!metrics) return null;
    const tps = flowThroughput ?? metrics.tokens_per_second;
    return {
      total_requests: metrics.requests_total,
      successful_requests: metrics.requests_successful,
      failed_requests: metrics.requests_failed,
      avg_latency_ms: metrics.avg_latency_ms,
      throughput_tps: tps,
    };
  }, [metrics, flowThroughput]);

  const agents = useMemo<AgentActivity[]>(() => {
    return (metrics?.agent_activity ?? []) as AgentActivity[];
  }, [metrics]);

  const activeProfiles = useMemo(
    () => agents.filter((a) => a.status === "active"),
    [agents],
  );
  const idleProfiles = useMemo(
    () => agents.filter((a) => a.status === "idle"),
    [agents],
  );
  const profilesWithSessionErrors = useMemo(
    () => agents.filter((a) => a.status === "error"),
    [agents],
  );
  const activeCount = activeProfiles.length;
  const idleCount = idleProfiles.length;
  const primaryProfile = activeProfiles[0]?.agent ?? null;
  const tokensPerSecond = summary?.throughput_tps ?? 0;
  const hasTraffic = tokensPerSecond > 0;

  const successRate = useMemo(() => {
    if (!summary || summary.total_requests === 0) return 0;
    return (summary.successful_requests / summary.total_requests) * 100;
  }, [summary]);

  const successTone: "success" | "warning" | "danger" =
    successRate >= 95 ? "success" : successRate >= 70 ? "warning" : "danger";
  const successLabel =
    successRate >= 95 ? "excelente" : successRate >= 70 ? "aceitável" : "crítico";

  const diagramLabel = useMemo(() => {
    if (!summary) return "Fluxo de pedidos indisponível.";
    const parts = [
      "Fluxo de pedidos: Utilizador → Router",
      activeCount > 0
        ? `→ ${activeCount} perfil(is) em execução`
        : "→ sem perfis em execução",
      "→ LLM → Resposta.",
      `${fmtNum(summary.total_requests)} pedidos totais, ${successRate.toFixed(
        1,
      )}% de sucesso, ${fmtNum(summary.failed_requests)} falhas.`,
    ];
    if (primaryProfile) parts.push(`Perfil em execução: ${primaryProfile}.`);
    return parts.join(" ");
  }, [summary, activeCount, successRate, primaryProfile]);

  return (
    <section aria-label="Fluxo de Pedidos">
      <Surface elevation={1} padding="sm" live={backendOnline && hasTraffic}>
        <SurfaceHeader
          icon={<GitBranch className="h-4 w-4" />}
          title="Fluxo de Pedidos"
          subtitle="Utilizador → Router → perfis de execução → LLM → Resposta"
          action={
            summary ? (
              <div className="flex items-center gap-2" aria-label={`Taxa de sucesso: ${successRate.toFixed(1)} por cento, ${successLabel}`}>
                <Meter value={successRate} tone={successTone} showThresholds={false} height={5} className="w-16" />
                <span className="flex items-center gap-1 text-[10px] font-medium text-nexus-muted">
                  <CheckCircle2 className="h-3 w-3 text-emerald-400" aria-hidden />
                  <AnimatedNumber value={successRate} decimals={1} />%
                </span>
              </div>
            ) : undefined
          }
        />

        {backendOnline === false && (
          <div
            role="status"
            aria-live="polite"
            className="mt-3 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-300"
          >
            <Power className="h-3.5 w-3.5 shrink-0" aria-hidden />
            <span>Backend offline — os dados apresentados podem estar desatualizados.</span>
          </div>
        )}

        {!summary ? (
          <div className="mt-3">
            <EmptyState
              icon={<GitBranch className="h-6 w-6" />}
              title="Dados de fluxo indisponíveis"
              hint="O backend não está a fornecer métricas de fluxo de pedidos."
            />
          </div>
        ) : (
          <div className="mt-3 min-w-0">
            {/* Diagrama de fluxo dinâmico */}
            <div role="img" aria-label={diagramLabel} className="overflow-x-auto">
              <div className="flex min-w-max items-stretch justify-center gap-1 py-4 sm:gap-2 sm:min-w-0 sm:flex-wrap">
                <FlowNode icon={<User className="h-5 w-5" aria-hidden />} label="Utilizador" color="#60a5fa" />
                <FlowLink active={hasTraffic} />
                <FlowNode
                  icon={<Router className="h-5 w-5" aria-hidden />}
                  label="Router"
                  color="#7c6afb"
                  badge={
                    connectionStatus === "connected"
                      ? "online"
                      : connectionStatus === "degraded"
                        ? "degradado"
                        : connectionStatus === "offline"
                          ? "offline"
                          : "a ligar"
                  }
                  badgeTone={
                    connectionStatus === "connected" ? "success" : connectionStatus === "degraded" ? "warning" : "neutral"
                  }
                />
                <FlowLink active={hasTraffic} />
                <FlowNode
                  icon={<Bot className="h-5 w-5" aria-hidden />}
                  label="Perfis"
                  color="#5eead4"
                  pulse={activeCount > 0}
                  badge={`${activeCount} em execução`}
                  badgeTone={activeCount > 0 ? "success" : "neutral"}
                  sub={
                    idleCount > 0
                      ? `${idleCount} sem execução`
                      : profilesWithSessionErrors.length > 0
                        ? `${profilesWithSessionErrors.length} com falha na sessão`
                        : primaryProfile ?? undefined
                  }
                />
                <FlowLink active={hasTraffic} />
                <FlowNode
                  icon={<Brain className="h-5 w-5" aria-hidden />}
                  label="LLM"
                  color="#fbbf24"
                  badge={hasTraffic ? `${fmtNum(tokensPerSecond)} tok/s` : "ocioso"}
                  badgeTone={hasTraffic ? "success" : "neutral"}
                />
                <FlowLink active={hasTraffic} />
                <FlowNode icon={<MessageSquare className="h-5 w-5" aria-hidden />} label="Resposta" color="#34d399" />
              </div>
            </div>

            {/* Respostas recentes agrupadas pelo perfil/tier */}
            {agents.length > 0 && (
              <ul role="list" aria-label="Estado dos perfis de execução" className="mb-3 flex flex-wrap gap-2 text-[11px]">
                {agents.map((a) => (
                  <li
                    key={a.agent}
                    className="nx-elev-0 flex items-center gap-1.5 rounded-lg px-2 py-1"
                    title={`${a.tasks_completed} respostas · latência média: ${fmtLatency(a.avg_latency_ms)}${a.status === "error" ? " · falha de ferramenta na sessão" : ""}`}
                  >
                    <StatusDot tone={STATUS_TONE[a.status]} pulse={a.status === "active"} />
                    <span className="font-medium text-nexus-text">{a.agent}</span>
                    <span className="text-nexus-faint">
                      {a.status === "active" ? "em execução" : a.status === "error" ? "falha na sessão" : "sem execução"}
                    </span>
                  </li>
                ))}
              </ul>
            )}

            {/* Sumário de métricas */}
            <dl
              aria-label="Resumo das métricas de fluxo"
              className="nx-inset mt-2 grid grid-cols-2 gap-2 rounded-lg px-3 py-2 text-xs text-nexus-muted sm:grid-cols-3 lg:grid-cols-5"
            >
              <MetricItem
                icon={<GitBranch className="h-3 w-3" aria-hidden />}
                label="Total"
                ariaLabel={`Pedidos totais: ${fmtNum(summary.total_requests)}`}
                value={fmtNum(summary.total_requests)}
                tone="neutral"
              />
              <MetricItem
                icon={<CheckCircle2 className="h-3 w-3" aria-hidden />}
                label="Sucesso"
                ariaLabel={`Pedidos com sucesso: ${fmtNum(summary.successful_requests)}`}
                value={fmtNum(summary.successful_requests)}
                tone="success"
              />
              <MetricItem
                icon={<XCircle className="h-3 w-3" aria-hidden />}
                label="Falhas"
                ariaLabel={`Pedidos falhados: ${fmtNum(summary.failed_requests)}`}
                value={fmtNum(summary.failed_requests)}
                tone="danger"
              />
              <MetricItem
                icon={<Timer className="h-3 w-3" aria-hidden />}
                label="Latência média"
                ariaLabel={`Latência média: ${fmtLatency(summary.avg_latency_ms)}`}
                value={fmtLatency(summary.avg_latency_ms)}
                tone="neutral"
              />
              <MetricItem
                icon={<Gauge className="h-3 w-3" aria-hidden />}
                label="Tokens/s"
                ariaLabel={`Tokens por segundo: ${fmtNum(summary.throughput_tps)}`}
                value={fmtNum(summary.throughput_tps)}
                tone="neutral"
              />
            </dl>

            {/* Resumo textual de agentes (acessível, sem depender só de cor) */}
            <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-nexus-faint">
              <span className="flex items-center gap-1">
                <Users className="h-3 w-3" aria-hidden />
                {activeCount} perfil(is) em execução
              </span>
              <span className="flex items-center gap-1">
                <Bot className="h-3 w-3" aria-hidden />
                {idleCount} perfil(is) sem execução
              </span>
              {profilesWithSessionErrors.length > 0 && (
                <span className="flex items-center gap-1 text-rose-400">
                  <XCircle className="h-3 w-3" aria-hidden />
                  {profilesWithSessionErrors.length} perfil(is) em sessão com falha
                </span>
              )}
            </p>
          </div>
        )}
      </Surface>
    </section>
  );
}

interface FlowNodeProps {
  icon: ReactNode;
  label: string;
  color: string;
  pulse?: boolean;
  badge?: string;
  badgeTone?: "success" | "warning" | "neutral";
  sub?: string;
}

const FLOW_BADGE_TONE: Record<"success" | "warning" | "neutral", string> = {
  success: "text-emerald-400 border-emerald-400/40",
  warning: "text-amber-300 border-amber-400/40",
  neutral: "text-nexus-faint border-[var(--nx-line-strong)]",
};

function FlowNode({ icon, label, color, pulse, badge, badgeTone = "success", sub }: FlowNodeProps) {
  return (
    <div className="flex min-w-0 flex-col items-center gap-1 px-1">
      <div
        className={`nx-surface flex h-11 w-11 items-center justify-center rounded-full text-sm transition-all duration-300 sm:h-12 sm:w-12 ${
          pulse ? "animate-pulse ring-2 ring-offset-2 ring-offset-nexus-panel" : ""
        }`}
        style={{
          backgroundColor: `${color}20`,
          border: `2px solid ${color}66`,
          boxShadow: pulse ? `0 0 0 2px ${color}, 0 4px 12px -4px ${color}` : `0 2px 8px -4px ${color}`,
        }}
      >
        <span style={{ color }} aria-hidden>
          {icon}
        </span>
      </div>
      <span className="text-[10px] font-medium text-nexus-muted sm:text-[11px]">{label}</span>
      {badge && (
        <span className={`rounded border px-1 text-[9px] leading-tight tabular-nums ${FLOW_BADGE_TONE[badgeTone]}`}>
          {badge}
        </span>
      )}
      {sub && <span className="max-w-[80px] truncate text-[9px] text-nexus-faint">{sub}</span>}
    </div>
  );
}

interface FlowLinkProps {
  active: boolean;
}

function FlowLink({ active }: FlowLinkProps) {
  return (
    <div className="flex shrink-0 items-center self-center text-nexus-faint" aria-hidden>
      <span className={`flex items-center transition-colors duration-300 ${active ? "text-emerald-400" : "text-nexus-faint/50"}`}>
        <ArrowRight className={`h-4 w-4 ${active ? "animate-pulse" : ""}`} aria-hidden />
      </span>
    </div>
  );
}

interface MetricItemProps {
  icon: ReactNode;
  label: string;
  ariaLabel: string;
  value: string;
  tone: "success" | "danger" | "neutral";
}

const METRIC_VALUE_TONE: Record<"success" | "danger" | "neutral", string> = {
  success: "text-emerald-400",
  danger: "text-rose-400",
  neutral: "text-nexus-text",
};

function MetricItem({ icon, label, ariaLabel, value, tone }: MetricItemProps) {
  return (
    <div className="flex min-w-0 flex-col items-center justify-center gap-0.5 text-center" aria-label={ariaLabel}>
      <dt className="flex items-center justify-center gap-1 text-[10px] text-nexus-faint">
        <span aria-hidden>{icon}</span>
        {label}
      </dt>
      <dd className={`font-semibold tabular-nums ${METRIC_VALUE_TONE[tone]}`}>{value}</dd>
    </div>
  );
}
