"use client";

/**
 * Dashboard — the system's answer to "what is happening right now?"
 *
 * Three decisions shape this layout:
 *
 * 1. AGENT METRICS ARE THE HERO, HOST METRICS ARE CONTEXT. The previous
 *    version led with three large CPU / RAM / disk cards. Those describe the
 *    machine, not the work: an AI IDE is judged on throughput, latency and
 *    whether requests succeed. Host telemetry moved to a compact gauge strip
 *    where it stays checkable without dominating.
 *
 * 2. EVERY NUMBER CARRIES A TREND. The metrics store already buffers ~100
 *    snapshots; nothing read them. Each headline KPI now renders a sparkline
 *    and a delta derived from that buffer, so a value can be judged as rising
 *    or falling instead of merely existing.
 *
 * 3. DEPTH ENCODES HIERARCHY. Elevation is assigned by importance, not
 *    decoration — heroes sit highest, supporting widgets one step down, nested
 *    stats are recessed wells. Colours come from `nexus-*` tokens only, so the
 *    theme switcher actually retheme the page (the old literal `#13131f`
 *    fills ignored it entirely).
 */

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Activity,
  BrainCircuit,
  CheckCircle2,
  Clock,
  Command,
  Cpu,
  Gauge,
  HardDrive,
  Layers,
  MemoryStick,
  Play,
  Timer,
  Users,
  Zap,
} from "lucide-react";

import { useMetricsStore } from "../../stores/metricsStore";
import { useModeStore } from "../../stores/modeStore";
import { Surface, SurfaceHeader } from "../../components/ui/Surface";
import { KpiCard, GaugeCard } from "../../components/ui/KpiCard";
import { Card, CardEmpty, CardStat } from "../../components/ui/Card";
import UsageWidget from "../../components/dashboard/UsageWidget";
import ProviderStatusWidget from "../../components/dashboard/ProviderStatusWidget";
import MCPStatusWidget from "../../components/dashboard/MCPStatusWidget";
import SubagentsWidget from "../../components/dashboard/SubagentsWidget";
import AdvisorWidget from "../../components/dashboard/AdvisorWidget";
import MissionPanel from "../../components/dashboard/MissionPanel";
import InfinitySuiteWidget from "../../components/dashboard/InfinitySuiteWidget";
import {
  approxP95,
  deltaOf,
  seriesOf,
  successRate,
  totalTokens,
} from "../../lib/metricSeries";
import {
  EMPTY,
  formatCompact,
  formatLatency,
  formatPercent,
  formatUptime,
} from "../../lib/format";

/** Mode chips are tinted per strategy so the active one is identifiable at a
 *  glance; the border does the work, the fill stays near-neutral. */
const MODE_TONE: Record<string, string> = {
  auto: "var(--nx-accent)",
  coder: "var(--nx-cyan)",
  swarm: "var(--nx-rose)",
  auto_swarm: "var(--nx-amber)",
};

const MAIN_MODE_IDS = ["auto", "coder", "swarm", "auto_swarm"];

const PROMPT_SUGGESTIONS = [
  "Análise profunda do repositório",
  "Validar segurança dos endpoints",
  "Configurar Swarm automático",
];

type ConnectionTone = "success" | "warning" | "danger" | "neutral";

function connectionView(
  status: string,
  online: boolean,
): { label: string; tone: ConnectionTone; dot: string } {
  if (status === "degraded") {
    return { label: "Degradado", tone: "warning", dot: "bg-amber-400" };
  }
  if (online) return { label: "Ligado", tone: "success", dot: "bg-emerald-400" };
  if (status === "connecting") {
    return { label: "A ligar", tone: "neutral", dot: "bg-amber-400 animate-pulse-subtle" };
  }
  return { label: "Offline", tone: "danger", dot: "bg-rose-400" };
}

export default function DashboardClient() {
  const router = useRouter();
  const metrics = useMetricsStore((s) => s.metrics);
  const history = useMetricsStore((s) => s.history);
  const backendOnline = useMetricsStore((s) => s.backendOnline);
  const connectionStatus = useMetricsStore((s) => s.connectionStatus);
  const connectionMode = useMetricsStore((s) => s.connectionMode);
  const lastUpdate = useMetricsStore((s) => s.lastUpdate);

  const { currentMode, setMode, modes, loadModes } = useModeStore();
  const [promptInput, setPromptInput] = useState("");

  useEffect(() => {
    loadModes();
  }, [loadModes]);

  const m = metrics;
  // Nothing has arrived yet — render skeletons rather than a page of dashes,
  // which reads as "broken" instead of "loading".
  const loading = m == null && backendOnline === false && connectionStatus === "connecting";

  const conn = connectionView(connectionStatus, backendOnline);

  // ── Derived series. One pass over the buffer, memoised on it. ──────────
  const series = useMemo(() => {
    const throughput = seriesOf(history, (s) => s.tokens_per_second);
    const latency = seriesOf(history, (s) => s.avg_latency_ms);
    const sessions = seriesOf(history, (s) => s.active_sessions);
    const success = seriesOf(history, (s) =>
      s.requests_total > 0 ? (s.requests_successful ?? 0) / s.requests_total : null,
    );
    return { throughput, latency, sessions, success };
  }, [history]);

  const rate = successRate(m);
  const p95 = approxP95(series.latency);
  const tokens = totalTokens(m);

  const agentActivity = m?.agent_activity ?? [];
  const activeAgents = agentActivity.filter((a) => a.status === "active").length;
  const erroringAgents = agentActivity.filter((a) => a.status === "error").length;

  const mainModes = useMemo(
    () => modes.filter((mode) => MAIN_MODE_IDS.includes(mode.id)),
    [modes],
  );

  const launchPrompt = () => {
    const isSwarm = currentMode === "swarm" || currentMode === "auto_swarm";
    const destination = isSwarm ? "/swarm" : "/";
    const prompt = promptInput.trim();
    if (!prompt) {
      router.push(destination);
      return;
    }
    router.push(`${destination}?prompt=${encodeURIComponent(prompt)}`);
  };

  return (
    // No `nx-ambient` here: `AppShell` already owns it. Its aurora and grid
    // are `position: fixed` pseudo-elements, so a second instance would stack
    // on the first and double the opacity of both.
    <div className="min-h-full pb-10">
      {/* ── HERO ─────────────────────────────────────────────────────────
          A status band, not a marketing banner. It answers: is the system
          up, what is it running on, and how fresh is what I am looking at. */}
      <header className="relative border-b border-nexus-border/60 px-6 py-7 sm:px-8">
        <div className="pointer-events-none absolute inset-0 bg-nx-mesh opacity-70" />

        <div className="relative mx-auto flex max-w-7xl flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${conn.dot}`} />
              <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-nexus-muted">
                Sistema {conn.label}
                {connectionMode !== "none" ? (
                  <span className="text-nexus-faint"> · {connectionMode.toUpperCase()}</span>
                ) : null}
              </span>
            </div>
            <h1 className="nx-title text-[28px] font-bold leading-tight sm:text-[32px]">
              Painel de Operações
            </h1>
            <p className="max-w-xl text-[13px] leading-relaxed text-nexus-muted">
              Débito, latência e fiabilidade dos agentes em tempo real. Orquestre
              o Swarm e lance objetivos sem sair desta página.
            </p>
          </div>

          <div className="grid grid-cols-2 gap-2.5 sm:flex sm:items-stretch">
            <Surface elevation={2} padding="sm" glass rounded="md" className="min-w-[150px]">
              <div className="text-[10px] uppercase tracking-wider text-nexus-faint">
                Modelo ativo
              </div>
              <div className="mt-1 truncate font-mono text-[13px] font-semibold text-nexus-accent-bright">
                {m?.active_model || EMPTY}
              </div>
            </Surface>
            <Surface elevation={2} padding="sm" glass rounded="md" className="min-w-[130px]">
              <div className="text-[10px] uppercase tracking-wider text-nexus-faint">
                Tempo ativo
              </div>
              <div className="mt-1 font-mono text-[13px] font-semibold tabular-nums text-nexus-text">
                {formatUptime(m?.uptime_seconds)}
              </div>
            </Surface>
            <Surface elevation={2} padding="sm" glass rounded="md" className="min-w-[130px]">
              <div className="text-[10px] uppercase tracking-wider text-nexus-faint">
                Atualizado
              </div>
              <div className="mt-1 font-mono text-[13px] font-semibold tabular-nums text-nexus-text">
                {lastUpdate}
              </div>
            </Surface>
          </div>
        </div>
      </header>

      <div className="mx-auto max-w-7xl space-y-6 px-6 py-6 sm:px-8">
        {/* ── HERO KPIs ─────────────────────────────────────────────────
            The four numbers that describe the product's behaviour. Each is
            paired with the trend that makes it interpretable. */}
        <section aria-label="Indicadores principais">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              emphasis
              label="Débito"
              value={m?.tokens_per_second != null ? `${m.tokens_per_second.toFixed(1)} T/s` : EMPTY}
              icon={<Zap className="h-4 w-4" />}
              color="var(--nx-accent)"
              history={series.throughput}
              delta={deltaOf(series.throughput)}
              goodDirection="up"
              hint="tokens por segundo"
              loading={loading}
            />
            <KpiCard
              emphasis
              label="Latência p95"
              value={formatLatency(p95)}
              icon={<Timer className="h-4 w-4" />}
              color="var(--nx-cyan)"
              history={series.latency}
              delta={deltaOf(series.latency)}
              goodDirection="down"
              hint={`média ${formatLatency(m?.avg_latency_ms)}`}
              loading={loading}
            />
            <KpiCard
              emphasis
              label="Taxa de sucesso"
              value={rate != null ? formatPercent(rate) : EMPTY}
              icon={<CheckCircle2 className="h-4 w-4" />}
              color="var(--nx-emerald)"
              history={series.success}
              delta={deltaOf(series.success)}
              goodDirection="up"
              hint={
                m?.requests_total
                  ? `${formatCompact(m.requests_total)} pedidos`
                  : "sem pedidos ainda"
              }
              loading={loading}
            />
            <KpiCard
              emphasis
              label="Sessões ativas"
              value={m?.active_sessions != null ? String(m.active_sessions) : EMPTY}
              icon={<Layers className="h-4 w-4" />}
              color="var(--nx-amber)"
              history={series.sessions}
              delta={deltaOf(series.sessions)}
              goodDirection="neutral"
              hint={m?.queue_depth ? `${m.queue_depth} em fila` : "fila vazia"}
              loading={loading}
            />
          </div>
        </section>

        {/* ── HOST TELEMETRY ────────────────────────────────────────────
            Deliberately small. Present for diagnosis, silent otherwise. */}
        <section aria-label="Recursos do anfitrião">
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            <GaugeCard
              label="Processador"
              percent={m?.cpu_percent}
              icon={<Cpu className="h-3.5 w-3.5" />}
              color="var(--nx-cyan)"
            />
            <GaugeCard
              label="Memória"
              percent={m?.ram_percent}
              icon={<MemoryStick className="h-3.5 w-3.5" />}
              color="var(--nx-accent)"
            />
            <GaugeCard
              label="Disco"
              percent={m?.disk_percent}
              icon={<HardDrive className="h-3.5 w-3.5" />}
              color="var(--nx-emerald)"
            />
            {/* Not a percentage, so not a gauge — same footprint and density
                as its neighbours, but an absolute counter with no fake bar. */}
            <Card padding="sm" variant="subtle">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-medium uppercase tracking-wider text-nexus-faint">
                  Tokens processados
                </span>
                <BrainCircuit className="h-3.5 w-3.5 shrink-0 text-nexus-accent" />
              </div>
              <div className="mt-1.5 text-lg font-semibold tabular-nums text-nexus-text">
                {tokens != null ? formatCompact(tokens) : EMPTY}
              </div>
              <div className="mt-2 text-[10px] text-nexus-faint">
                {m?.message_stats?.total_messages != null
                  ? `${formatCompact(m.message_stats.total_messages)} mensagens`
                  : "acumulado da sessão"}
              </div>
            </Card>
          </div>
        </section>

        {/* ── COMPOSER ──────────────────────────────────────────────────
            Below the metrics: you read the state of the system, then act on
            it. Leading with an input asked for a decision before showing the
            information the decision depends on. */}
        <Surface elevation={2} padding="lg" tone="accent" spotlight>
          <SurfaceHeader
            icon={<Command className="h-4 w-4" />}
            title="Lançar objetivo"
            subtitle="Envia diretamente para os agentes ativos ou para o Swarm"
            action={
              <span className="rounded-full bg-[rgba(124,106,251,0.12)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-nexus-accent-bright shadow-rim">
                Modo {currentMode}
              </span>
            }
          />

          <form
            className="relative mt-4"
            onSubmit={(event) => {
              event.preventDefault();
              launchPrompt();
            }}
          >
            <label htmlFor="dashboard-objective" className="sr-only">
              Objetivo para os agentes
            </label>
            <input
              id="dashboard-objective"
              type="text"
              value={promptInput}
              onChange={(e) => setPromptInput(e.target.value)}
              placeholder="ex.: Criar um scraper de imobiliário e validar os endpoints"
              className="nx-inset w-full rounded-xl px-4 py-3.5 pr-28 text-sm text-nexus-text placeholder-nexus-faint outline-none transition-colors focus:border-[rgba(124,106,251,0.5)]"
            />
            <button
              type="submit"
              className="absolute right-2 top-1/2 flex -translate-y-1/2 items-center gap-1.5 rounded-lg bg-nx-accent px-3.5 py-2 text-xs font-semibold text-white shadow-nx-accent transition-transform duration-200 hover:scale-[1.03] active:scale-100"
            >
              Executar
              <Play className="h-3 w-3" />
            </button>
          </form>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-[11px] text-nexus-faint">Sugestões:</span>
            {PROMPT_SUGGESTIONS.map((suggestion) => (
              <button
                key={suggestion}
                type="button"
                onClick={() => setPromptInput(suggestion)}
                className="rounded-full border border-nexus-border px-2.5 py-1 text-[11px] text-nexus-muted shadow-rim transition-colors hover:border-[rgba(124,106,251,0.4)] hover:text-nexus-text"
              >
                {suggestion}
              </button>
            ))}
          </div>
        </Surface>

        {/* ── MISSION CONTROL ───────────────────────────────────────────
            Directly under the composer, because it answers what happened to
            the objective just launched: what was understood, what the plan is,
            which agents exist and why. Full width — this is the narrative of
            the run, not a side metric. */}
        <MissionPanel />

        {/* ── INFINITY SUITE ────────────────────────────────────────────
            Eleven modes that had no dashboard presence at all: the only entry
            point was a floating button in the bottom-left corner. */}
        <InfinitySuiteWidget />

        {/* ── COST / PROVIDERS / CONNECTORS ─────────────────────────────── */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <UsageWidget />
          <ProviderStatusWidget />
          <MCPStatusWidget />
        </div>

        {/* ── SUBAGENTS + ADVISOR ─────────────────────────────────────
            Telemetria das fases autónomas e do governador Advisor Infinity.
            Two children in a three-column grid left a hole on the right; the
            advisor now takes the two columns its session list needs. */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <SubagentsWidget />
          <div className="lg:col-span-2">
            <AdvisorWidget />
          </div>
        </div>

        {/* ── SWARM + MODES ─────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Surface
            elevation={1}
            padding="lg"
            live={backendOnline}
            className="flex flex-col lg:col-span-2"
          >
            <SurfaceHeader
              icon={<Users className="h-4 w-4" />}
              tone={erroringAgents > 0 ? "danger" : "accent"}
              title="Orquestração multi-agente"
              subtitle="Estado do Swarm e atividade recente"
              action={
                <Link
                  href="/swarm"
                  className="rounded-lg border border-nexus-border px-2.5 py-1 text-[11px] font-medium text-nexus-accent-bright shadow-rim transition-colors hover:border-[rgba(124,106,251,0.45)]"
                >
                  Abrir Swarm
                </Link>
              }
            />

            <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
              <CardStat
                label="Agentes ativos"
                value={agentActivity.length ? activeAgents : EMPTY}
                hint="Agentes a executar trabalho neste momento"
              />
              <CardStat
                label="Com atividade"
                value={agentActivity.length || EMPTY}
                hint="Agentes que reportaram atividade na janela recente"
              />
              <CardStat
                label="Em erro"
                value={agentActivity.length ? erroringAgents : EMPTY}
                hint="Agentes cujo último ciclo falhou"
              />
              <CardStat
                label="Profundidade da fila"
                value={m?.queue_depth != null ? m.queue_depth : EMPTY}
                hint="Pedidos à espera de um agente livre"
              />
            </div>

            <div className="mt-5 flex-1 space-y-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
                Atividade recente
              </div>
              {agentActivity.length > 0 ? (
                agentActivity.slice(0, 5).map((agent) => (
                  <div
                    key={agent.agent}
                    className="nx-inset flex items-center justify-between gap-3 rounded-lg px-3 py-2"
                  >
                    <div className="flex min-w-0 items-center gap-2.5">
                      <span
                        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                          agent.status === "active"
                            ? "bg-emerald-400"
                            : agent.status === "error"
                              ? "bg-rose-400"
                              : "bg-nexus-faint"
                        }`}
                      />
                      <span className="truncate text-[12px] font-medium text-nexus-text">
                        {agent.agent}
                      </span>
                    </div>
                    <div className="flex shrink-0 items-center gap-3 text-[11px] tabular-nums text-nexus-muted">
                      <span>{agent.tasks_completed} ok</span>
                      {agent.tasks_failed > 0 ? (
                        <span className="text-rose-400">{agent.tasks_failed} falhas</span>
                      ) : null}
                      <span className="text-nexus-faint">
                        {formatLatency(agent.avg_latency_ms)}
                      </span>
                    </div>
                  </div>
                ))
              ) : (
                <CardEmpty icon={<Activity className="h-3.5 w-3.5" />}>
                  {backendOnline
                    ? "Nenhum agente reportou atividade ainda."
                    : "Sem ligação ao backend — atividade indisponível."}
                </CardEmpty>
              )}
            </div>

            <div className="mt-5 flex items-center justify-between border-t border-nexus-border/60 pt-3 text-[11px] text-nexus-faint">
              <span className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5" />
                Ativo há {formatUptime(m?.uptime_seconds)}
              </span>
              <span className="flex items-center gap-1.5">
                <Gauge className="h-3.5 w-3.5" />
                {m?.requests_failed
                  ? `${formatCompact(m.requests_failed)} pedidos falhados`
                  : "Sem falhas registadas"}
              </span>
            </div>
          </Surface>

          <Surface elevation={1} padding="lg">
            <SurfaceHeader
              icon={<BrainCircuit className="h-4 w-4" />}
              title="Modo de execução"
              subtitle="Define a estratégia dos agentes"
            />

            <div
              className="mt-4 space-y-2.5"
              role="radiogroup"
              aria-label="Modo de execução"
            >
              {mainModes.length > 0 ? (
                mainModes.map((mode) => {
                  const isActive = mode.id === currentMode;
                  const tone = MODE_TONE[mode.id] ?? "var(--nx-accent)";
                  return (
                    <button
                      key={mode.id}
                      type="button"
                      role="radio"
                      aria-checked={isActive}
                      onClick={() => setMode(mode.id)}
                      className={`nx-surface w-full rounded-xl p-3.5 text-left transition-all duration-200 ${
                        isActive ? "nx-elev-2" : "nx-elev-0 nx-lift"
                      }`}
                      style={
                        isActive
                          ? {
                              borderColor: `color-mix(in srgb, ${tone} 45%, transparent)`,
                              boxShadow: `inset 0 1px 0 0 var(--nx-rim-strong), 0 6px 18px -8px ${tone}`,
                            }
                          : undefined
                      }
                    >
                      <div className="flex items-center justify-between gap-2">
                        <span
                          className="font-mono text-[11px] font-bold uppercase tracking-wider"
                          style={{ color: isActive ? tone : "var(--nx-text)" }}
                        >
                          {mode.id}
                        </span>
                        {isActive ? (
                          <CheckCircle2 className="h-4 w-4" style={{ color: tone }} />
                        ) : null}
                      </div>
                      <p className="mt-1 text-[11px] leading-relaxed text-nexus-muted">
                        {mode.description}
                      </p>
                    </button>
                  );
                })
              ) : (
                <CardEmpty>Modos indisponíveis — verifica a ligação ao backend.</CardEmpty>
              )}
            </div>
          </Surface>
        </div>
      </div>
    </div>
  );
}
