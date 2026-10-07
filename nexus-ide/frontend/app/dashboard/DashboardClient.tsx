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

import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
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
  MessageSquare,
  ListTodo,
  ArrowRight,
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
import RuntimeReadinessBanner from "../../components/dashboard/RuntimeReadinessBanner";
import WorkspaceLaunchpad from "../../components/dashboard/WorkspaceLaunchpad";
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
const MODE_LABEL: Record<string, string> = {
  auto: "Automático",
  coder: "Código",
  swarm: "Swarm",
  auto_swarm: "Swarm automático",
};

const PROMPT_SUGGESTIONS = [
  "Análise profunda do repositório",
  "Validar segurança dos endpoints",
  "Configurar Swarm automático",
];

const DASHBOARD_SECTIONS = [
  { href: "#novo-objetivo", label: "Novo objetivo" },
  { href: "#resumo", label: "Resumo" },
  { href: "#execucao", label: "Execução" },
  { href: "#integracoes", label: "Integrações" },
  { href: "#agentes", label: "Agentes" },
  { href: "#orquestracao", label: "Swarm" },
] as const;

type ConnectionTone = "success" | "warning" | "danger" | "neutral";

function SectionHeading({ title, description }: { title: string; description: string }) {
  return (
    <div className="nx-dashboard-section-heading mb-4 flex flex-wrap items-end justify-between gap-2">
      <div>
        <h2 className="text-base font-semibold tracking-tight text-nexus-text sm:text-lg">{title}</h2>
        <p className="mt-1 text-xs leading-relaxed text-nexus-muted">{description}</p>
      </div>
    </div>
  );
}

function connectionView(
  status: string,
  online: boolean,
): { label: string; tone: ConnectionTone; dot: string } {
  if (status === "auth_required") {
    return { label: "Sessão expirada", tone: "warning", dot: "bg-amber-400" };
  }
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

  const {
    currentMode,
    setMode,
    modes,
    modesLoaded,
    modesLoading,
    modesError,
    loadModes,
  } = useModeStore();
  const [promptInput, setPromptInput] = useState("");
  const [activeDashboardSection, setActiveDashboardSection] = useState("novo-objetivo");
  const modeButtonRefs = useRef(new Map<string, HTMLButtonElement>());

  useEffect(() => {
    const scrollContainer = document.querySelector("main");
    if (!scrollContainer) return;
    const sectionElements = DASHBOARD_SECTIONS
      .map((section) => document.getElementById(section.href.slice(1)))
      .filter((element): element is HTMLElement => element instanceof HTMLElement);
    const updateActiveSection = () => {
      const containerTop = scrollContainer.getBoundingClientRect().top;
      const activationLine = scrollContainer.scrollTop + Math.min(180, Math.max(112, scrollContainer.clientHeight * 0.18));
      let currentSection = sectionElements[0];
      for (const section of sectionElements) {
        const sectionTop = section.getBoundingClientRect().top - containerTop + scrollContainer.scrollTop;
        if (sectionTop <= activationLine) currentSection = section;
      }
      if (currentSection) setActiveDashboardSection(currentSection.id);
    };

    scrollContainer.addEventListener("scroll", updateActiveSection, { passive: true });
    window.addEventListener("resize", updateActiveSection);
    updateActiveSection();
    return () => {
      scrollContainer.removeEventListener("scroll", updateActiveSection);
      window.removeEventListener("resize", updateActiveSection);
    };
  }, []);

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

  const agentActivity = m?.agent_activity;
  const agentRecords = agentActivity ?? [];
  const activeProfiles = agentRecords.filter((a) => a.status === "active").length;
  const erroringProfiles = agentRecords.filter((a) => a.status === "error").length;

  const mainModes = useMemo(
    () => modes.filter((mode) => MAIN_MODE_IDS.includes(mode.id)),
    [modes],
  );

  const handleModeKeyDown = (event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
    if (mainModes.length === 0) return;

    let nextIndex: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % mainModes.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + mainModes.length) % mainModes.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = mainModes.length - 1;
    }
    if (nextIndex === null) return;

    event.preventDefault();
    const nextMode = mainModes[nextIndex];
    setMode(nextMode.id);
    modeButtonRefs.current.get(nextMode.id)?.focus();
  };

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
  const targetIsSwarm = currentMode === "swarm" || currentMode === "auto_swarm";

  return (
    // No `nx-ambient` here: `AppShell` already owns it. Its aurora and grid
    // are `position: fixed` pseudo-elements, so a second instance would stack
    // on the first and double the opacity of both.
    <div className="nx-dashboard min-h-full pb-10">
      {/* ── HERO ─────────────────────────────────────────────────────────
          A status band, not a marketing banner. It answers: is the system
          up, what is it running on, and how fresh is what I am looking at. */}
      <header className="nx-dashboard-hero relative overflow-hidden border-b border-nexus-border/60 px-4 py-6 sm:px-6 sm:py-7 lg:px-8">
        <div className="pointer-events-none absolute inset-0 bg-nx-mesh opacity-30" />

        <div className="relative mx-auto flex max-w-7xl flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
          <div className="space-y-2.5">
            <div className="flex items-center gap-2">
              <span className={`h-2 w-2 rounded-full ${conn.dot}`} />
              <span className="text-[11px] font-medium tracking-wide text-nexus-muted">
                Sistema {conn.label}
                {connectionMode !== "none" ? (
                  <span className="text-nexus-faint"> · {connectionMode.toUpperCase()}</span>
                ) : null}
              </span>
            </div>
            <h1 className="nx-title text-[30px] font-semibold leading-tight tracking-tight sm:text-[38px]">
              Painel de Operações
            </h1>
            <p className="max-w-xl text-[13px] leading-relaxed text-nexus-muted">
              Os teus objetivos, agentes e ferramentas. Tudo à vista.
            </p>
            <div className="flex flex-wrap items-center gap-2 pt-1">
              <Link href="/" className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-nexus-accent/25 bg-nexus-accent/10 px-3.5 text-xs font-medium text-nexus-accent-bright transition-colors hover:bg-nexus-accent/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">
                <MessageSquare className="h-3.5 w-3.5" /> Abrir chat
                <ArrowRight className="h-3 w-3" />
              </Link>
              <Link href="/dashboard/tasks" className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-nexus-border/70 bg-nexus-card/50 px-3.5 text-xs font-medium text-nexus-muted transition-colors hover:bg-nexus-card hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">
                <ListTodo className="h-3.5 w-3.5" /> Ver tarefas
              </Link>
            </div>
          </div>

          <dl className="grid grid-cols-2 overflow-hidden rounded-2xl border border-nexus-border/60 bg-nexus-card/60 min-[380px]:grid-cols-3 sm:min-w-[410px]">
            <div className="col-span-2 min-w-0 border-b border-nexus-border/50 px-3 py-2.5 min-[380px]:col-span-1 min-[380px]:border-b-0 min-[380px]:border-r">
              <dt className="text-[10px] uppercase tracking-wider text-nexus-faint">
                Modelo ativo
              </dt>
              <dd className="mt-1 truncate font-mono text-[11px] font-semibold text-nexus-accent-bright sm:text-[13px]">
                {m?.active_model && m.active_model !== "none" ? m.active_model : "Por selecionar"}
              </dd>
            </div>
            <div className="min-w-0 border-r border-nexus-border/50 px-3 py-2.5">
              <dt className="text-[10px] uppercase tracking-wider text-nexus-faint">
                Tempo ativo
              </dt>
              <dd className="mt-1 truncate font-mono text-[11px] font-semibold tabular-nums text-nexus-text sm:text-[13px]">
                {formatUptime(m?.uptime_seconds)}
              </dd>
            </div>
            <div className="min-w-0 px-3 py-2.5">
              <dt className="text-[10px] uppercase tracking-wider text-nexus-faint">
                Atualizado
              </dt>
              <dd
                title={lastUpdate}
                className="mt-1 truncate font-mono text-[11px] font-semibold tabular-nums text-nexus-text sm:text-[13px]"
              >
                {lastUpdate}
              </dd>
            </div>
          </dl>
        </div>
      </header>

      <nav
        aria-label="Navegação rápida da dashboard"
        className="nx-dashboard-nav sticky top-0 z-20 border-b border-nexus-border/70 bg-nexus-bg/95 px-4 py-2 backdrop-blur-xl sm:px-6 lg:px-8"
      >
        <div className="mx-auto flex max-w-7xl gap-1.5 overflow-x-auto">
          {DASHBOARD_SECTIONS.map((section) => {
            const sectionId = section.href.slice(1);
            const active = activeDashboardSection === sectionId;
            return (
              <a
                key={section.href}
                href={section.href}
                onClick={() => setActiveDashboardSection(sectionId)}
                aria-current={active ? "location" : undefined}
                className={
                  "inline-flex min-h-10 shrink-0 items-center rounded-lg px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent focus-visible:ring-offset-2 focus-visible:ring-offset-nexus-bg " +
                  (active
                    ? "bg-nexus-accent/12 text-nexus-accent-bright"
                    : "text-nexus-muted hover:bg-nexus-card hover:text-nexus-text")
                }
              >
                {section.label}
              </a>
            );
          })}
        </div>
      </nav>

      <div className="mx-auto max-w-7xl space-y-8 px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
        <RuntimeReadinessBanner />
        <WorkspaceLaunchpad />
        <section id="novo-objetivo" aria-label="Lançar objetivo" className="scroll-mt-28 sm:scroll-mt-16">
          <Surface elevation={2} padding="lg" tone="accent" className="nx-dashboard-objective">
            <SurfaceHeader
              icon={<Command className="h-4 w-4" />}
              title="Lançar objetivo"
              subtitle="Escreve o pedido e continua no chat ou no Swarm."
              className="flex-col items-stretch gap-2 sm:flex-row sm:items-center"
              action={
                <span className="rounded-full bg-[rgba(124,106,251,0.12)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-nexus-accent-bright shadow-rim">
                  {MODE_LABEL[currentMode] ?? currentMode}
                </span>
              }
            />

            <form
              className="mt-4 flex flex-col gap-2.5 sm:relative sm:block"
              onSubmit={(event) => {
                event.preventDefault();
                launchPrompt();
              }}
            >
              <label htmlFor="dashboard-objective" className="sr-only">
                O que queres fazer?
              </label>
              <input
                id="dashboard-objective"
                type="text"
                value={promptInput}
                onChange={(e) => setPromptInput(e.target.value)}
                placeholder="Ex.: Analisar o repositório e sugerir correções"
                className="nx-inset w-full rounded-xl px-4 py-3.5 text-sm text-nexus-text placeholder-nexus-faint outline-none transition-colors focus:border-[rgba(124,106,251,0.5)] sm:pr-40"
              />
              <button
                type="submit"
                className="flex min-h-11 w-full items-center justify-center gap-2 rounded-lg bg-nx-accent px-3.5 py-2 text-xs font-semibold text-white shadow-nx-accent transition-colors hover:bg-nexus-accent-bright focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent-bright focus-visible:ring-offset-2 focus-visible:ring-offset-nexus-bg sm:absolute sm:right-2 sm:top-1/2 sm:min-h-0 sm:w-auto sm:-translate-y-1/2"
              >
                {targetIsSwarm ? "Preparar no SWARM" : "Preparar no chat"}
                <ArrowRight className="h-3 w-3" />
              </button>
            </form>

            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="text-[11px] text-nexus-faint">Sugestões:</span>
              {PROMPT_SUGGESTIONS.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => setPromptInput(suggestion)}
                  className="inline-flex min-h-10 items-center rounded-full border border-nexus-border px-3 py-1.5 text-left text-[11px] leading-snug text-nexus-muted shadow-rim transition-colors hover:border-[rgba(124,106,251,0.4)] hover:text-nexus-text"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </Surface>
        </section>

        {/* ── HERO KPIs ─────────────────────────────────────────────────
            The four numbers that describe the product's behaviour. Each is
            paired with the trend that makes it interpretable. */}
        <section id="resumo" aria-label="Resumo do sistema" className="scroll-mt-28 space-y-6 sm:scroll-mt-16">
          <SectionHeading title="Visão geral" description="Desempenho das execuções e recursos da máquina." />
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
                label="P95 aprox. das médias"
                value={formatLatency(p95)}
                icon={<Timer className="h-4 w-4" />}
                color="var(--nx-cyan)"
                history={series.latency}
                delta={deltaOf(series.latency)}
                goodDirection="down"
                hint={`estimativa sobre médias recentes; não mede latências individuais · média atual ${formatLatency(m?.avg_latency_ms)}`}
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
                  m?.requests_total != null
                    ? m.requests_total > 0
                      ? `${formatCompact(m.requests_total)} pedidos`
                      : "Nenhum pedido ainda"
                    : "Pedidos sem dados"
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
                hint={
                  m?.queue_depth != null
                    ? m.queue_depth > 0
                      ? `${m.queue_depth} em fila`
                      : "fila vazia"
                    : "fila sem dados"
                }
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
                    : m
                      ? "Mensagens sem dados"
                      : "Sem dados disponíveis"}
                </div>
              </Card>
            </div>
          </section>
        </section>

        {/* ── MISSION CONTROL ───────────────────────────────────────────
            The live narrative of the current run: what was understood, what
            the plan is, and which agents are involved. */}
        <section id="execucao" aria-label="Execução e modos avançados" className="scroll-mt-28 space-y-6 sm:scroll-mt-16">
          <SectionHeading title="Execução e capacidades" description="Acompanha a missão atual e os modos disponíveis." />
          <MissionPanel />

          {/* ── INFINITY SUITE ────────────────────────────────────────────
              Eleven modes that had no dashboard presence at all: the only entry
              point was a floating button in the bottom-left corner. */}
          <InfinitySuiteWidget />
        </section>

        {/* ── COST / PROVIDERS / CONNECTORS ─────────────────────────────── */}
        <section id="integracoes" aria-label="Consumo e integrações" className="scroll-mt-28 sm:scroll-mt-16">
          <SectionHeading title="Consumo e ligações" description="Tokens, custos e estado dos serviços externos." />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2 2xl:grid-cols-3">
            <UsageWidget />
            <ProviderStatusWidget />
            <MCPStatusWidget />
          </div>
        </section>

        {/* ── SUBAGENTS + ADVISOR ─────────────────────────────────────
            Telemetria das fases autónomas e do governador Advisor Infinity.
            `SubagentsWidget` brings its own `lg:col-span-2`: its run rows carry
            a phase chip, up to three badges and four numeric columns, so it
            needs the wide track. Spanning the Advisor wrapper as well put four
            columns of span into a three-column grid — the row wrapped and left
            a hole in the right-hand track. The advisor takes the single
            remaining column, which its three short stats and five session rows
            fit comfortably in. */}
        <section id="agentes" aria-label="Agentes e consultor" className="scroll-mt-28 sm:scroll-mt-16">
          <SectionHeading title="Equipa de agentes" description="Execuções autónomas e supervisão do consultor." />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
            <SubagentsWidget />
            <AdvisorWidget />
          </div>
        </section>

        {/* ── SWARM + MODES ─────────────────────────────────────────────── */}
        <section id="orquestracao" aria-label="Orquestração e modo de execução" className="scroll-mt-28 sm:scroll-mt-16">
          <SectionHeading title="Estratégia de execução" description="Atividade dos perfis e modo de trabalho dos agentes." />
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Surface
            elevation={1}
            padding="lg"
            live={backendOnline}
            className="flex flex-col lg:col-span-2"
          >
            <SurfaceHeader
              icon={<Users className="h-4 w-4" />}
              tone={erroringProfiles > 0 ? "danger" : "accent"}
              title="Atividade por perfil"
              subtitle="Respostas recentes, execuções e fila do sistema"
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
                label="Perfis em execução"
                value={agentActivity != null ? activeProfiles : EMPTY}
                hint="Perfis associados a uma execução ativa"
              />
              <CardStat
                label="Com respostas recentes"
                value={agentActivity != null ? agentActivity.length : EMPTY}
                hint="Perfis com respostas nos últimos 30 minutos"
              />
              <CardStat
                label="Em sessão com falha"
                value={agentActivity != null ? erroringProfiles : EMPTY}
                hint="Perfis associados a sessões com falhas de ferramenta"
              />
              <CardStat
                label="Profundidade da fila"
                value={m?.queue_depth != null ? m.queue_depth : EMPTY}
                hint="Pedidos à espera de um agente livre"
              />
            </div>

            <div className="mt-5 flex-1 space-y-2">
              <div className="text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
                Respostas recentes por perfil
              </div>
              {agentRecords.length > 0 ? (
                agentRecords.slice(0, 5).map((agent) => (
                  <div
                    key={agent.agent}
                    className="nx-inset flex flex-wrap items-center justify-between gap-3 rounded-xl px-3.5 py-3"
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
                      <span>{agent.tasks_completed} respostas</span>
                      {agent.status === "error" ? (
                        <span className="text-rose-400">falha na sessão</span>
                      ) : null}
                      <span className="text-nexus-faint">
                        {formatLatency(agent.avg_latency_ms)}
                      </span>
                    </div>
                  </div>
                ))
              ) : (
                <CardEmpty icon={<Activity className="h-3.5 w-3.5" />}>
                  {agentActivity != null
                    ? "Nenhum perfil reportou respostas nesta janela."
                    : backendOnline
                      ? "Atividade dos agentes sem dados."
                      : "Sem ligação ao backend — atividade indisponível."}
                </CardEmpty>
              )}
            </div>

            <div className="mt-5 flex flex-wrap items-center justify-between gap-2 border-t border-nexus-border/60 pt-3 text-[11px] text-nexus-faint">
              <span className="flex items-center gap-1.5">
                <Clock className="h-3.5 w-3.5" />
                Ativo há {formatUptime(m?.uptime_seconds)}
              </span>
              <span className="flex items-center gap-1.5">
                <Gauge className="h-3.5 w-3.5" />
                {m?.requests_failed != null
                  ? m.requests_failed > 0
                    ? `${formatCompact(m.requests_failed)} pedidos falhados`
                    : "Sem falhas registadas"
                  : "Falhas sem dados"}
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
                mainModes.map((mode, index) => {
                  const isActive = mode.id === currentMode;
                  const tone = MODE_TONE[mode.id] ?? "var(--nx-accent)";
                  return (
                    <button
                      key={mode.id}
                      type="button"
                      role="radio"
                      aria-checked={isActive}
                      tabIndex={isActive ? 0 : -1}
                      ref={(node) => {
                        if (node) modeButtonRefs.current.set(mode.id, node);
                        else modeButtonRefs.current.delete(mode.id);
                      }}
                      onClick={() => setMode(mode.id)}
                      onKeyDown={(event) => handleModeKeyDown(event, index)}
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
                          className="text-xs font-semibold tracking-wide"
                          style={{ color: isActive ? tone : "var(--nx-text)" }}
                        >
                          {MODE_LABEL[mode.id] ?? mode.id}
                        </span>
                        {isActive ? (
                          <CheckCircle2 className="h-4 w-4" style={{ color: tone }} />
                        ) : null}
                      </div>
                      <p className="mt-1.5 text-xs leading-relaxed text-nexus-muted">
                        {mode.description}
                      </p>
                    </button>
                  );
                })
              ) : !modesLoaded || modesLoading ? (
                <CardEmpty>A carregar modos de execução…</CardEmpty>
              ) : (
                <CardEmpty>{modesError ?? "Nenhum dos modos principais está disponível."}</CardEmpty>
              )}
            </div>
          </Surface>
          </div>
        </section>
      </div>
    </div>
  );
}
