"use client";

/**
 * MissionPanel — what the orchestrator understood, planned, and did.
 *
 * Reads two sources and folds them into one truthful view:
 *
 *   * ``GET /api/mission/current`` — the full mission payload (brief, plan,
 *     waves, decisions, timeline). Cheap to poll on a 5 s cadence.
 *   * ``useMissionStore().envelope`` — the execution envelope. The envelope
 *     carries the canonical execution_state, the provider/model/quota/
 *     simulation/cost telemetry, the structured error, and the proven
 *     evidence set. The panel derives its display state from the envelope
 *     first, never from a missing error field.
 *
 * Truthful states (Task 10): queued · routing · planning · executing ·
 * verifying · blocked · failed · cancelled · interrupted · completed.
 * "Completed" is only shown when the envelope explicitly proves it — never
 * inferred from the absence of failures.
 */
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AlertTriangle,
  Ban,
  CheckCircle2,
  ClipboardList,
  Clock,
  FileText,
  GitBranch,
  ListChecks,
  Pause,
  Play,
  Radar,
  RotateCcw,
  ScrollText,
  Search,
  Sparkles,
  Terminal as TerminalIcon,
  XCircle,
} from "lucide-react";

import { apiUrl, authHeaders, cancelMission as apiCancelMission, replanMission as apiReplanMission, resumeMission as apiResumeMission } from "../../lib/api";
import {
  EXECUTION_ERROR_LABEL_PT,
  EXECUTION_MODE_LABEL_PT,
  EXECUTION_STATE_LABEL_PT,
  type ExecutionEnvelope,
  type ExecutionError,
  type ExecutionErrorCategory,
  type ExecutionState,
  type MissionPayload,
  type ProviderHealth,
  deriveDisplayState,
  isTerminalExecutionState,
} from "../../lib/executionTypes";
import { useMissionStore } from "../../stores/missionStore";
import { CardEmpty, CardStat } from "../ui/Card";
import { Surface, SurfaceHeader } from "../ui/Surface";

/* ────────────────────────────────────────────────────────────────────────
 * Polling + WebSocket wiring
 * ──────────────────────────────────────────────────────────────────────── */

const POLL_MS = 5_000;

interface MissionResponse {
  active: boolean;
  mission: MissionPayload | null;
}

async function fetchMission(): Promise<MissionResponse | null> {
  try {
    const res = await fetch(apiUrl("/api/mission/current"), {
      headers: authHeaders(),
    });
    if (res.status === 401) throw new Error("auth");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as MissionResponse;
  } catch {
    return null;
  }
}

/* ────────────────────────────────────────────────────────────────────────
 * Visual tokens — single source of truth for state tones
 * ──────────────────────────────────────────────────────────────────────── */

const STATE_TONE: Record<ExecutionState, { dot: string; pill: string; text: string; label: string }> = {
  queued:      { dot: "bg-nexus-muted",  pill: "bg-[rgba(148,163,184,0.16)] text-nexus-muted",          text: "text-nexus-muted",   label: "Em fila" },
  routing:     { dot: "bg-sky-300",      pill: "bg-[rgba(56,189,248,0.16)] text-sky-300",              text: "text-sky-300",       label: "A decidir rota" },
  planning:    { dot: "bg-sky-300",      pill: "bg-[rgba(56,189,248,0.16)] text-sky-300",              text: "text-sky-300",       label: "A planear" },
  executing:   { dot: "bg-emerald-400 animate-pulse-subtle", pill: "bg-[rgba(52,211,153,0.16)] text-emerald-300", text: "text-emerald-300", label: "A executar" },
  verifying:   { dot: "bg-amber-300 animate-pulse-subtle",   pill: "bg-[rgba(251,191,36,0.16)] text-amber-300",   text: "text-amber-300",   label: "A verificar" },
  completed:   { dot: "bg-emerald-400",  pill: "bg-[rgba(52,211,153,0.18)] text-emerald-300",          text: "text-emerald-300",   label: "Concluída" },
  failed:      { dot: "bg-rose-400",     pill: "bg-[rgba(251,113,133,0.18)] text-rose-300",            text: "text-rose-300",      label: "Falhou" },
  blocked:     { dot: "bg-amber-400",    pill: "bg-[rgba(251,191,36,0.18)] text-amber-300",            text: "text-amber-300",     label: "Bloqueada" },
  cancelled:   { dot: "bg-nexus-faint",  pill: "bg-[rgba(100,116,139,0.18)] text-nexus-faint",         text: "text-nexus-faint",   label: "Cancelada" },
  interrupted: { dot: "bg-orange-300",   pill: "bg-[rgba(251,146,60,0.18)] text-orange-300",           text: "text-orange-300",    label: "Interrompida" },
};

/* ────────────────────────────────────────────────────────────────────────
 * Helpers
 * ──────────────────────────────────────────────────────────────────────── */

function clock(iso: string): string {
  return iso.length > 19 ? iso.slice(11, 19) : iso;
}

function shortId(id: string): string {
  return id.length > 10 ? id.slice(0, 10) : id;
}

function uniq<T>(items: T[]): T[] {
  return Array.from(new Set(items));
}

/** True when the user-typed query is a substring of any item's haystack. */
function matches(query: string, haystack: string): boolean {
  if (!query.trim()) return true;
  return haystack.toLowerCase().includes(query.trim().toLowerCase());
}

/* ────────────────────────────────────────────────────────────────────────
 * Main component
 * ──────────────────────────────────────────────────────────────────────── */

export default function MissionPanel() {
  const [mission, setMission] = useState<MissionPayload | null>(null);
  const [active, setActive] = useState<boolean | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("brief");
  const [query, setQuery] = useState("");
  const [actionPending, setActionPending] = useState<null | "cancel" | "resume" | "replan">(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const envelope = useMissionStore((s) => s.envelope);
  const envelopePending = useMissionStore((s) => s.envelopePending);

  const load = useCallback(async () => {
    const data = await fetchMission();
    if (!data) {
      setError("Sem ligação ao backend");
      return;
    }
    setActive(data.active);
    setMission(data.mission);
    setError(null);
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  // The envelope is the source of truth for execution state. The REST poll
  // fills the rich mission payload. Both must agree before we show anything.
  const displayState = useMemo(() => deriveDisplayState(envelope), [envelope]);
  const effectiveState: ExecutionState =
    envelope?.state ??
    (mission ? (mission.state as ExecutionState) : "queued");
  const tone = STATE_TONE[effectiveState] ?? STATE_TONE.queued;

  const handleCancel = useCallback(async () => {
    if (!mission) return;
    setActionPending("cancel");
    setActionError(null);
    try {
      await apiCancelMission(mission.id);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Falha a cancelar");
    } finally {
      setActionPending(null);
      void load();
    }
  }, [mission, load]);

  const handleResume = useCallback(async () => {
    if (!mission) return;
    setActionPending("resume");
    setActionError(null);
    try {
      await apiResumeMission(mission.id);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Falha a retomar");
    } finally {
      setActionPending(null);
      void load();
    }
  }, [mission, load]);

  const handleReplan = useCallback(async () => {
    if (!mission) return;
    setActionPending("replan");
    setActionError(null);
    try {
      await apiReplanMission(mission.id);
    } catch (err) {
      setActionError(err instanceof Error ? err.message : "Falha a replanejar");
    } finally {
      setActionPending(null);
      void load();
    }
  }, [mission, load]);

  // ── Empty / error states ──────────────────────────────────────────────
  if (error && !mission && !envelope) {
    return (
      <Surface elevation={1} padding="lg">
        <SurfaceHeader
          icon={<Radar className="h-4 w-4" />}
          title="Mission Control"
          subtitle="Planeamento, execução supervisionada, verificação e relatório"
        />
        <div className="mt-4">
          <CardEmpty icon={<AlertTriangle className="h-3.5 w-3.5" />}>
            {error}
         </CardEmpty>
       </div>
     </Surface>
    );
  }

  if (active === false || (!mission && !envelope)) {
    return (
      <Surface elevation={1} padding="lg">
        <SurfaceHeader
          icon={<Radar className="h-4 w-4" />}
          title="Mission Control"
          subtitle="Planeamento, execução supervisionada, verificação e relatório"
        />
        <div className="mt-4">
          <CardEmpty icon={<Radar className="h-3.5 w-3.5" />}>
            Nenhuma missão em curso. Lança um objetivo — o brief e o plano aparecem aqui
            <em> antes</em>
            de qualquer agente ser criado.
         </CardEmpty>
       </div>
     </Surface>
    );
  }

  // Once we know something is live, prefer the envelope's mission payload —
  // it's the same shape the REST endpoint returns but carries the latest
  // checkpoint data.
  const view: MissionPayload | null = envelope?.mission ?? mission;
  const pct = Math.round(((view?.progress ?? 0) * 100) || 0);

  return (
    <Surface
      elevation={2}
      padding="lg"
      tone="accent"
      live={effectiveState === "executing" || effectiveState === "verifying"}
      className="overflow-hidden"
    >
      <SurfaceHeader
        icon={<Radar className="h-4 w-4" />}
        tone={
          effectiveState === "failed"
            ? "danger"
            : effectiveState === "completed"
              ? "success"
              : effectiveState === "blocked" || effectiveState === "interrupted"
                ? "warning"
                : "accent"
        }
        title="Mission Control"
        subtitle={view?.title || EXECUTION_STATE_LABEL_PT[effectiveState]}
        action={
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <EnvelopeBadge envelope={envelope} state={effectiveState} />
            <button
              type="button"
              onClick={handleCancel}
              disabled={!displayState.canCancel || actionPending !== null || !view}
              aria-label="Cancelar missão em curso"
              title="Cancelar"
              className="flex items-center gap-1 rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-rose-200 transition-colors hover:bg-rose-500/20 focus:outline-none focus:ring-2 focus:ring-rose-400/40 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Ban className="h-3 w-3" aria-hidden /> Cancelar
           </button>
            <button
              type="button"
              onClick={handleResume}
              disabled={!displayState.canResume || actionPending !== null || !view}
              aria-label="Retomar missão interrompida"
              title="Retomar"
              className="flex items-center gap-1 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-emerald-200 transition-colors hover:bg-emerald-500/20 focus:outline-none focus:ring-2 focus:ring-emerald-400/40 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Play className="h-3 w-3" aria-hidden /> Retomar
           </button>
            <button
              type="button"
              onClick={handleReplan}
              disabled={!displayState.canReplan || actionPending !== null || !view}
              aria-label="Replanear waves da missão"
              title="Replanear"
              className="flex items-center gap-1 rounded-md border border-sky-500/30 bg-sky-500/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-sky-200 transition-colors hover:bg-sky-500/20 focus:outline-none focus:ring-2 focus:ring-sky-400/40 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <RotateCcw className="h-3 w-3" aria-hidden /> Replanear
           </button>
         </div>
        }
      />

      {/* ── Live status region — announced to assistive tech ──────────── */}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-nexus-muted"
      >
        <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} aria-hidden />
        <span className={tone.text}>{tone.label}
        <span className="text-nexus-faint" aria-hidden>·</span>
        <span className="text-nexus-faint">
          {envelope ? EXECUTION_MODE_LABEL_PT[envelope.context.mode] : "Missão"}
       </span>
        {envelope?.provider ? (
          <>
            <span className="text-nexus-faint" aria-hidden>·</span>
            <span className="font-mono text-[10px] text-nexus-accent-bright">
              {envelope.provider}
              {envelope.model ? ` · ${envelope.model}` : ""}
           </span>
          </>
        ) : null}
        {envelope?.simulation ? (
          <span
            className="ml-1 rounded-md bg-amber-400/12 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-amber-300"
            title="A completar com provider de simulação — não é trabalho real"
          >
            simulação
         </span>
        ) : null}
     </div>

      {actionError ? (
        <div
          role="alert"
          className="mt-2 flex items-center gap-2 rounded-md border border-rose-500/30 bg-rose-500/10 px-2.5 py-1.5 text-[11px] text-rose-200"
        >
          <AlertTriangle className="h-3 w-3" aria-hidden />
          {actionError}
       </div>
      ) : null}

      {/* ── Search ──────────────────────────────────────────────────── */}
      <div className="mt-3 flex items-center gap-2 rounded-lg nx-inset px-2.5 py-1.5">
        <Search className="h-3 w-3 text-nexus-faint" aria-hidden />
        <label htmlFor="mission-search" className="sr-only">
          Pesquisar na missão
       </label>
        <input
          id="mission-search"
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Pesquisar no brief, plano, waves, decisões e timeline…"
          className="min-w-0 flex-1 bg-transparent text-[11px] text-nexus-text placeholder:text-nexus-faint focus:outline-none"
        />
        {query ? (
          <button
            type="button"
            onClick={() => setQuery("")}
            aria-label="Limpar pesquisa"
            className="rounded text-[10px] text-nexus-faint hover:text-nexus-text focus:outline-none focus:ring-2 focus:ring-nexus-accent/40"
          >
            limpar
         </button>
        ) : null}
     </div>

      {/* ── The eight numbers ─────────────────────────────────────────── */}
      <dl
        aria-label="Métricas da missão"
        className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-7"
      >
        <CardStat
          label="Progresso"
          value={`${pct}%`}
          hint="Contratos concluídos ou dispensados"
        />
        <CardStat
          label="Agentes ativos"
          value={view?.active_agents ?? 0}
          hint="A executar agora"
        />
        <CardStat
          label="Tarefas"
          value={`${view?.tasks_done ?? 0}/${view?.tasks_total ?? 0}`}
          hint="Contratos resolvidos face ao total"
        />
        <CardStat
          label="Ficheiros"
          value={view?.files_changed?.length ?? 0}
          hint="Ficheiros alterados nesta missão"
        />
        <CardStat
          label="Testes ok"
          value={view?.tests_passed ?? 0}
          hint="Verificações cujo comando saiu com código 0"
        />
        <CardStat
          label="Testes falhados"
          value={view?.tests_failed ?? 0}
          hint="Verificações com código de saída diferente de 0"
        />
        <CardStat
          label="Riscos"
          value={view?.risks?.length ?? 0}
          hint="Riscos técnicos registados"
        />
     </dl>

      <div
        className="mt-3 h-1 overflow-hidden rounded-full bg-[rgba(148,163,184,0.12)]"
        role="progressbar"
        aria-valuenow={pct}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Progresso da missão"
      >
        <div
          className="h-full rounded-full bg-nx-accent transition-[width] duration-500"
          style={{ width: `${pct}%` }}
        />
     </div>

      {/* ── Execution state strip — truthful, never inferred ─────────── */}
      <ExecutionStrip envelope={envelope} />

      {/* ── Tabs ─────────────────────────────────────────────────────── */}
      <div
        className="mt-5 flex flex-wrap gap-1.5 border-b border-nexus-border/60 pb-2"
        role="tablist"
        aria-label="Secções da missão"
      >
        {TABS.map(({ id, label, icon: Icon }) => (
          <button
            key={id}
            id={`mission-tab-${id}`}
            type="button"
            role="tab"
            aria-selected={tab === id}
            aria-controls={`mission-tabpanel-${id}`}
            tabIndex={tab === id ? 0 : -1}
            onClick={() => setTab(id)}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-nexus-accent/40 ${
              tab === id
                ? "bg-[rgba(124,106,251,0.14)] text-nexus-accent-bright shadow-rim"
                : "text-nexus-muted hover:text-nexus-text"
            }`}
          >
            <Icon className="h-3.5 w-3.5" aria-hidden />
            {label}
         </button>
        ))}
     </div>

      <div
        className="mt-4 max-h-[460px] space-y-3 overflow-y-auto pr-1"
        id={`mission-tabpanel-${tab}`}
        role="tabpanel"
        aria-labelledby={`mission-tab-${tab}`}
      >
        {tab === "brief" && <BriefTab mission={view} query={query} />}
        {tab === "plan" && <PlanTab mission={view} query={query} />}
        {tab === "agents" && <AgentsTab waves={view?.waves ?? []} query={query} />}
        {tab === "evidence" && <EvidenceTab envelope={envelope} mission={view} />}
        {tab === "decisions" && <DecisionsTab decisions={view?.decisions ?? []} query={query} />}
        {tab === "timeline" && (
          <TimelineTab
            timeline={view?.timeline ?? []}
            verifications={view?.verifications ?? []}
            query={query}
          />
        )}
     </div>

      {view && view.waves.length > 0 ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-nexus-border/60 pt-3 text-[11px] text-nexus-faint">
          <span>
            {view.waves.flatMap((w) => w.contracts).filter((c) => c.state === "proposed").length} propostos ·{" "}
            {view.waves.flatMap((w) => w.contracts).filter((c) => c.state === "skipped").length} dispensados ·{" "}
            {view.waves.flatMap((w) => w.contracts).filter((c) => c.state === "failed").length} falhados
         </span>
          {view.plan ? (
            <span>Máx. {view.plan.concurrency_limit} agentes concorrentes</span>
          ) : null}
       </div>
      ) : null}

      {envelopePending ? (
        <div role="status" aria-live="polite" className="sr-only">
          A propagar ação…
       </div>
      ) : null}
   </Surface>
  );
}

/* ────────────────────────────────────────────────────────────────────────
 * Tabs
 * ──────────────────────────────────────────────────────────────────────── */

const TABS = [
  { id: "brief", label: "Brief", icon: Radar },
  { id: "plan", label: "Plano", icon: ClipboardList },
  { id: "agents", label: "Agentes", icon: GitBranch },
  { id: "evidence", label: "Evidência", icon: Sparkles },
  { id: "decisions", label: "Decisões", icon: ScrollText },
  { id: "timeline", label: "Timeline", icon: Clock },
] as const;

type TabId = (typeof TABS)[number]["id"];

function BriefTab({ mission, query }: { mission: MissionPayload | null; query: string }) {
  const b = mission?.brief ?? null;
  if (!b) return <CardEmpty>Sem brief registado</CardEmpty>;
  const findings = b.snapshot?.findings ?? [];

  const filteredPriorities = b.priorities.filter((p) => matches(query, p));
  const filteredInitial = b.initial_state.filter((line) => matches(query, line));
  const filteredFindings = findings.filter(
    (f) => matches(query, `${f.title} ${f.detail} ${f.evidence}`),
  );
  const filteredAssumptions = b.assumptions.filter((a) => matches(query, a));
  const filteredScope = b.out_of_scope.filter((a) => matches(query, a));

  if (
    filteredPriorities.length === 0 &&
    filteredInitial.length === 0 &&
    filteredFindings.length === 0 &&
    filteredAssumptions.length === 0 &&
    filteredScope.length === 0 &&
    !matches(query, `${b.objective_raw} ${b.objective_interpreted}`)
  ) {
    return <CardEmpty>Sem resultados para a pesquisa</CardEmpty>;
  }

  return (
    <>
      <Accordion title="Objetivo interpretado" icon={<FileText className="h-3 w-3" />}>
        <p className="text-[12px] leading-relaxed text-nexus-text">
          {b.objective_interpreted}
       </p>
        <p className="mt-2 text-[11px] italic leading-relaxed text-nexus-faint">
          Pedido original: “{b.objective_raw}”
       </p>
     </Accordion>

      <Accordion title="Estado inicial medido" icon={<Radar className="h-3 w-3" />}>
        {filteredInitial.length === 0 ? (
          <p className="text-[11px] italic text-nexus-faint">Sem linhas correspondentes</p>
        ) : (
          <ul className="space-y-1">
            {filteredInitial.map((line) => (
              <li key={line} className="text-[11px] leading-relaxed text-nexus-muted">
                · {line}
             </li>
            ))}
         </ul>
        )}
     </Accordion>

      {findings.length > 0 ? (
        <Accordion title="Problemas detetados" icon={<AlertTriangle className="h-3 w-3" />}>
          {filteredFindings.length === 0 ? (
            <p className="text-[11px] italic text-nexus-faint">Sem problemas correspondentes</p>
          ) : (
            <ul className="space-y-1.5">
              {filteredFindings.map((f) => (
                <li key={f.id} className="text-[11px] leading-relaxed">
                  <span
                    className={`font-mono text-[10px] font-semibold uppercase ${
                      SEVERITY_TEXT[f.severity]
                    }`}
                  >
                    [{f.severity}]
                 </span>{" "}
                  <span className="text-nexus-text">{f.title}
                  {f.evidence ? (
                    <span className="ml-1 font-mono text-[10px] text-nexus-faint">
                      ({f.evidence.slice(0, 90)})
                   </span>
                  ) : null}
               </li>
              ))}
           </ul>
          )}
       </Accordion>
      ) : null}

      <Accordion title="Prioridades propostas" icon={<ListChecks className="h-3 w-3" />}>
        {filteredPriorities.length === 0 ? (
          <p className="text-[11px] italic text-nexus-faint">Sem prioridades correspondentes</p>
        ) : (
          <ol className="space-y-1">
            {filteredPriorities.map((p, i) => (
              <li key={p} className="text-[11px] leading-relaxed text-nexus-muted">
                {i + 1}. {p}
             </li>
            ))}
         </ol>
        )}
     </Accordion>

      {filteredAssumptions.length > 0 ? (
        <Accordion
          title="Pressupostos"
          icon={<AlertTriangle className="h-3 w-3" />}
          tone="warning"
        >
          <ul className="space-y-1">
            {filteredAssumptions.map((a) => (
              <li key={a} className="text-[11px] leading-relaxed text-amber-200/80">
                · {a}
             </li>
            ))}
         </ul>
       </Accordion>
      ) : null}

      {filteredScope.length > 0 ? (
        <Accordion title="Fora do âmbito" icon={<XCircle className="h-3 w-3" />}>
          <ul className="space-y-1">
            {filteredScope.map((a) => (
              <li key={a} className="text-[11px] leading-relaxed text-nexus-faint">
                · {a}
             </li>
            ))}
         </ul>
       </Accordion>
      ) : null}
    </>
  );
}

function PlanTab({ mission, query }: { mission: MissionPayload | null; query: string }) {
  if (!mission?.plan) return <CardEmpty>Nenhum plano publicado</CardEmpty>;
  const filtered = mission.plan.phases.filter(
    (ph) =>
      matches(query, ph.label) ||
      matches(query, ph.rationale) ||
      ph.steps.some((s) => matches(query, s)),
  );
  if (filtered.length === 0) {
    return <CardEmpty>Sem fases correspondentes à pesquisa</CardEmpty>;
  }
  return (
    <>
      {filtered.map((ph) => (
        <Accordion
          key={ph.phase}
          title={ph.label}
          icon={<ClipboardList className="h-3 w-3" />}
          tone={ph.skipped ? "warning" : "neutral"}
          defaultOpen
        >
          {ph.skipped ? (
            <p className="text-[11px] leading-relaxed text-amber-200/70">{ph.skip_reason</p>
          ) : (
            <>
              <ul className="space-y-1">
                {ph.steps
                  .filter((s) => matches(query, s))
                  .map((s) => (
                    <li key={s} className="text-[11px] leading-relaxed text-nexus-muted">
                      · {s}
                   </li>
                  ))}
             </ul>
              {ph.rationale ? (
                <p className="mt-2 border-t border-nexus-border/50 pt-2 text-[10px] italic leading-relaxed text-nexus-faint">
                  {ph.rationale}
               </p>
              ) : null}
            </>
          )}
       </Accordion>
      ))}
    </>
  );
}

function AgentsTab({ waves, query }: { waves: MissionPayload["waves"]; query: string }) {
  if (waves.length === 0) return <CardEmpty>Nenhum agente proposto ainda</CardEmpty>;
  const filteredWaves = waves.filter(
    (w) =>
      matches(query, w.name) ||
      matches(query, w.phase) ||
      w.contracts.some(
        (c) =>
          matches(query, c.name) ||
          matches(query, c.objective) ||
          matches(query, c.activity),
      ),
  );
  if (filteredWaves.length === 0) {
    return <CardEmpty>Sem agentes correspondentes à pesquisa</CardEmpty>;
  }
  return (
    <>
      {filteredWaves.map((w) => {
        const filteredContracts = w.contracts.filter(
          (c) =>
            matches(query, c.name) ||
            matches(query, c.objective) ||
            matches(query, c.activity),
        );
        return (
          <section key={w.index} aria-label={`Wave ${w.name}`}>
            <div className="mb-2 flex items-center gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-nexus-faint">
                {w.name}
             </span>
              <span className="h-px flex-1 bg-nexus-border/60" aria-hidden />
              <span className="font-mono text-[10px] text-nexus-faint">{w.state}
           </div>
            <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-2">
              {filteredContracts.map((c) => (
                <ContractCard key={c.id} contract={c} query={query} />
              ))}
           </div>
         </section>
        );
      })}
    </>
  );
}

function ContractCard({
  contract: c,
  query,
}: {
  contract: MissionPayload["waves"][number]["contracts"][number];
  query: string;
}) {
  const skipped = c.state === "skipped";
  const unproven =
    c.completion_criteria.length > 0 &&
    (c.confidence === null || c.confidence < 0.5) &&
    c.state !== "completed";

  return (
    <Accordion
      title={c.name}
      defaultOpen={false}
      badge={
        <span
          className={`rounded-md px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${STATE_STYLE[c.state]}`}
        >
          {c.state}
       </span>
      }
      tone={skipped ? "warning" : "neutral"}
    >
      <p className="text-[11px] leading-relaxed text-nexus-muted">{c.objective</p>

      <p className="mt-2 border-l-2 border-nexus-border pl-2 text-[10px] leading-relaxed text-nexus-faint">
        <strong className="text-nexus-muted">Motivo</strong> {c.justification}
     </p>

      {c.dependencies.length > 0 && !skipped ? (
        <p className="mt-1.5 text-[10px] leading-relaxed text-nexus-faint">
          <strong className="text-nexus-muted">Depende de</strong> {c.dependencies.join(", ")}
       </p>
      ) : null}

      {c.activity && matches(query, c.activity) ? (
        <p className="mt-2 rounded-md bg-[rgba(52,211,153,0.08)] px-2 py-1 font-mono text-[10px] text-emerald-300">
          {c.activity}
       </p>
      ) : null}

      {c.discoveries.length > 0 ? (
        <div className="mt-2">
          <span className="text-[9px] font-semibold uppercase tracking-wider text-nexus-faint">
            Descobertas
         </span>
          <ul className="mt-0.5 space-y-0.5">
            {c.discoveries.slice(0, 4).map((d) => (
              <li key={d} className="text-[10px] leading-snug text-nexus-muted">
                · {d}
             </li>
            ))}
         </ul>
       </div>
      ) : null}

      {c.files_changed.length > 0 ? (
        <div className="mt-2">
          <span className="text-[9px] font-semibold uppercase tracking-wider text-nexus-faint">
            Alterações
         </span>
          <ul className="mt-0.5 space-y-0.5">
            {c.files_changed.slice(0, 5).map((f) => (
              <li key={f} className="truncate font-mono text-[10px] text-nexus-accent-bright">
                {f}
             </li>
            ))}
         </ul>
       </div>
      ) : null}

      {c.completion_criteria.length > 0 && !skipped ? (
        <div className="mt-2 border-t border-nexus-border/50 pt-2">
          <span className="flex items-center gap-1 text-[9px] font-semibold uppercase tracking-wider text-nexus-faint">
            <ListChecks className="h-3 w-3" aria-hidden /> Critérios de conclusão
         </span>
          <ul className="mt-0.5 space-y-0.5">
            {c.completion_criteria.map((cc) => (
              <li key={cc} className="text-[10px] leading-snug text-nexus-faint">
                · {cc}
             </li>
            ))}
         </ul>
       </div>
      ) : null}

      {c.confidence !== null ? (
        <div className="mt-2 text-[10px] tabular-nums text-nexus-muted">
          Confiança: {Math.round(c.confidence * 100)}%
       </div>
      ) : null}

      {c.error ? (
        <p className="mt-2 text-[10px] leading-relaxed text-rose-300/80">{c.error</p>
      ) : null}

      {unproven ? (
        <p
          className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-[10px] leading-snug text-amber-200"
          role="note"
        >
          Critérios de conclusão não comprovados — confiança{" "}
          {Math.round((c.confidence ?? 0) * 100)}%.
       </p>
      ) : null}
   </Accordion>
  );
}

function EvidenceTab({
  envelope,
  mission,
}: {
  envelope: ExecutionEnvelope | null;
  mission: MissionPayload | null;
}) {
  const files = uniq([...(envelope?.files_changed ?? []), ...(mission?.files_changed ?? [])]);
  const commands = uniq([...(envelope?.commands_run ?? []), ...(mission?.verifications?.map((v) => v.command) ?? [])]);
  const failedTasks = uniq([
    ...(envelope?.failed_tasks ?? []),
    ...(mission?.waves?.flatMap((w) => w.contracts).filter((c) => c.state === "failed").map((c) => c.id) ?? []),
  ]);

  return (
    <>
      <Accordion
        title="Provider & execução"
        icon={<Sparkles className="h-3 w-3" />}
        defaultOpen
      >
        <ProviderStrip envelope={envelope} />
     </Accordion>

      <Accordion
        title="Evidência verificada"
        icon={<CheckCircle2 className="h-3 w-3" />}
        tone={envelope?.completion_proven ? "success" : "neutral"}
      >
        <EvidenceList envelope={envelope} />
     </Accordion>

      <Accordion title="Tarefas" icon={<ListChecks className="h-3 w-3" />}>
        <ul className="space-y-1">
          <li className="text-[11px] leading-relaxed text-nexus-muted">
            Concluídas:{" "}
            <span className="font-mono text-nexus-text">{mission?.tasks_done ?? 0} de{" "}
            <span className="font-mono text-nexus-text">{mission?.tasks_total ?? 0}
         </li>
          <li className="text-[11px] leading-relaxed text-rose-300">
            Falhadas:{" "}
            <span className="font-mono">{failedTasks.length}
         </li>
          {failedTasks.length > 0 ? (
            <ul className="ml-4 mt-1 space-y-0.5">
              {failedTasks.slice(0, 8).map((id) => (
                <li key={id} className="font-mono text-[10px] text-rose-200/80">
                  · {shortId(id)}
               </li>
              ))}
           </ul>
          ) : null}
       </ul>
     </Accordion>

      <Accordion title="Ficheiros alterados" icon={<FileText className="h-3 w-3" />}>
        {files.length === 0 ? (
          <p className="text-[11px] italic text-nexus-faint">Nenhum ficheiro alterado</p>
        ) : (
          <ul className="space-y-0.5">
            {files.slice(0, 20).map((f) => (
              <li key={f} className="truncate font-mono text-[10px] text-nexus-accent-bright">
                {f}
             </li>
            ))}
            {files.length > 20 ? (
              <li className="text-[10px] text-nexus-faint">
                … mais {files.length - 20} ficheiros
             </li>
            ) : null}
         </ul>
        )}
     </Accordion>

      <Accordion title="Comandos executados" icon={<TerminalIcon className="h-3 w-3" />}>
        {commands.length === 0 ? (
          <p className="text-[11px] italic text-amber-200/80">
            Nenhum comando foi executado. Mudanças nesta missão não estão testadas.
         </p>
        ) : (
          <ul className="space-y-0.5">
            {commands.slice(0, 12).map((c, i) => (
              <li key={`${c}-${i}`} className="truncate font-mono text-[10px] text-nexus-text">
                {c}
             </li>
            ))}
            {commands.length > 12 ? (
              <li className="text-[10px] text-nexus-faint">
                … mais {commands.length - 12} comandos
             </li>
            ) : null}
         </ul>
        )}
     </Accordion>

      <Accordion
        title="Testes"
        icon={<CheckCircle2 className="h-3 w-3" />}
        tone={
          (mission?.tests_failed ?? 0) > 0
            ? "danger"
            : (mission?.tests_passed ?? 0) > 0
              ? "success"
              : "warning"
        }
      >
        {(mission?.tests_passed ?? 0) + (mission?.tests_failed ?? 0) === 0 ? (
          <p className="text-[11px] leading-relaxed text-amber-200/80">
            Sem testes registados. Esta missão <strong>não está validada</strong>.
         </p>
        ) : (
          <ul className="space-y-1.5">
            <li className="text-[11px] text-emerald-300">
              ✓ Passou: <span className="font-mono">{mission?.tests_passed ?? 0}
           </li>
            <li className="text-[11px] text-rose-300">
              ✗ Falhou: <span className="font-mono">{mission?.tests_failed ?? 0}
           </li>
         </ul>
        )}
     </Accordion>

      <Accordion
        title="Critérios não comprovados"
        icon={<AlertTriangle className="h-3 w-3" />}
        tone="warning"
      >
        <UnprovenCriteria mission={mission} envelope={envelope} />
     </Accordion>
    </>
  );
}

function ProviderStrip({ envelope }: { envelope: ExecutionEnvelope | null }) {
  const provider = envelope?.provider ?? null;
  const model = envelope?.model ?? null;
  const cost = envelope?.cost_usd ?? null;
  const error = envelope?.error ?? null;
  const health = envelope?.provider_health ?? null;
  const retryAfter = error?.retry_after ?? null;
  const quota = health?.quota_available ?? null;
  const isSimulation = envelope?.simulation ?? health?.simulation ?? false;

  if (!provider && !model && !cost && !error && !health) {
    return (
      <p className="text-[11px] italic text-nexus-faint">
        Sem telemetria de provider ainda — fica disponível assim que o envelope chegar.
     </p>
    );
  }

  return (
    <dl className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-3">
      <Stat label="Provider" value={provider ?? "—"} mono />
      <Stat label="Modelo" value={model ?? "—"} mono />
      <Stat label="Custo" value={cost == null ? "—" : `$${cost.toFixed(4)}`} mono />
      <Stat
        label="Quota"
        value={quota == null ? "—" : quota.toLocaleString("pt-PT")}
        mono
      />
      <Stat
        label="Retry após"
        value={retryAfter == null ? "—" : `${retryAfter}s`}
        mono
      />
      <Stat
        label="Modo"
        value={
          isSimulation
            ? "simulação"
            : (health?.free_only ? "free only" : "real")
        }
        mono
        tone={isSimulation ? "warning" : "neutral"}
      />
   </dl>
  );
}

function EvidenceList({ envelope }: { envelope: ExecutionEnvelope | null }) {
  const evidence = envelope?.evidence ?? [];
  if (evidence.length === 0) {
    return (
      <p className="text-[11px] leading-relaxed text-amber-200/80">
        Sem evidência verificada — não podemos afirmar que esta missão terminou.
     </p>
    );
  }
  return (
    <ul className="space-y-1.5">
      {evidence.map((item, i) => (
        <li key={item.id ?? `${item.label}-${i}`} className="flex items-start gap-2">
          {item.verified ? (
            <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400" aria-hidden />
          ) : (
            <XCircle className="mt-0.5 h-3 w-3 shrink-0 text-rose-400" aria-hidden />
          )}
          <div className="min-w-0 flex-1">
            <p className="text-[11px] text-nexus-text">{item.label ?? item.description ?? "Evidência"}</p>
            {item.description && item.label ? (
              <p className="text-[10px] text-nexus-faint">{item.description</p>
            ) : null}
         </div>
       </li>
      ))}
   </ul>
  );
}

function UnprovenCriteria({
  mission,
  envelope,
}: {
  mission: MissionPayload | null;
  envelope: ExecutionEnvelope | null;
}) {
  const unproven: { id: string; label: string }[] = [];
  for (const wave of mission?.waves ?? []) {
    for (const c of wave.contracts) {
      if (c.state === "completed" && c.confidence !== null && c.confidence < 0.5) {
        for (const cc of c.completion_criteria) {
          unproven.push({ id: c.id, label: `${c.name}: ${cc}` });
        }
      }
    }
  }
  if (!envelope?.completion_proven && envelope?.state === "completed") {
    unproven.push({
      id: "global",
      label: "Backend marcou o estado como concluído mas não provou a evidência.",
    });
  }
  if (envelope?.simulation) {
    unproven.push({
      id: "simulation",
      label: "Provider em modo simulação — a conclusão nunca é trabalho real.",
    });
  }
  if (unproven.length === 0) {
    return (
      <p className="text-[11px] leading-relaxed text-emerald-300">
        Todos os critérios estão comprovados pela evidência registada.
     </p>
    );
  }
  return (
    <ul className="space-y-1">
      {unproven.map((u) => (
        <li key={u.id + u.label} className="text-[11px] leading-relaxed text-amber-200/80">
          · {u.label}
       </li>
      ))}
   </ul>
  );
}

function DecisionsTab({ decisions, query }: { decisions: MissionPayload["decisions"]; query: string }) {
  const filtered = decisions.filter(
    (d) =>
      matches(query, d.choice) ||
      matches(query, d.reason) ||
      matches(query, d.outcome) ||
      d.alternatives.some((a) => matches(query, a)),
  );
  if (filtered.length === 0) {
    if (decisions.length === 0) {
      return (
        <CardEmpty icon={<ScrollText className="h-3.5 w-3.5" />}>
          Nenhuma decisão registada. Aqui aparecem escolhas com a sua razão e as alternativas rejeitadas — não o raciocínio interno em bruto.
       </CardEmpty>
      );
    }
    return <CardEmpty>Sem decisões correspondentes à pesquisa</CardEmpty>;
  }
  return (
    <>
      {filtered.map((d) => (
        <Accordion
          key={d.number}
          title={`Decisão #${d.number}`}
          defaultOpen
          icon={<ScrollText className="h-3 w-3" />}
        >
          <div className="flex items-baseline justify-between gap-2">
            <span className="text-[12px] font-medium leading-relaxed text-nexus-text">{d.choice}
            <span className="font-mono text-[10px] text-nexus-faint">{clock(d.at)}</span>
         </div>
          <p className="mt-2 text-[11px] leading-relaxed text-nexus-muted">
            <strong className="text-nexus-text">Razão</strong> {d.reason}
         </p>
          {d.alternatives.length > 0 ? (
            <div className="mt-2">
              <span className="text-[9px] font-semibold uppercase tracking-wider text-nexus-faint">
                Alternativas consideradas
             </span>
              <ul className="mt-0.5 space-y-0.5">
                {d.alternatives.map((a) => (
                  <li key={a} className="text-[10px] leading-snug text-nexus-faint">
                    · {a}
                 </li>
                ))}
             </ul>
           </div>
          ) : null}
          {d.outcome ? (
            <p className="mt-2 border-t border-nexus-border/50 pt-2 text-[10px] leading-relaxed text-nexus-accent-bright">
              → {d.outcome}
           </p>
          ) : null}
       </Accordion>
      ))}
    </>
  );
}

function TimelineTab({
  timeline,
  verifications,
  query,
}: {
  timeline: MissionPayload["timeline"];
  verifications: MissionPayload["verifications"];
  query: string;
}) {
  const filteredTimeline = timeline.filter(
    (t) => matches(query, t.label) || matches(query, t.detail),
  );
  const filteredVerifs = verifications.filter(
    (v) => matches(query, v.command) || matches(query, v.summary),
  );

  return (
    <>
      <Accordion
        title="Verificações executadas"
        icon={<CheckCircle2 className="h-3 w-3" />}
        tone={
          verifications.length === 0
            ? "warning"
            : verifications.every((v) => v.passed)
              ? "success"
              : "danger"
        }
      >
        {verifications.length === 0 ? (
          <p className="text-[11px] leading-relaxed text-amber-200/80">
            Nenhuma verificação foi executada. Quaisquer alterações desta missão{" "}
            <strong>não estão testadas</strong>.
         </p>
        ) : filteredVerifs.length === 0 ? (
          <p className="text-[11px] italic text-nexus-faint">Sem verificações correspondentes</p>
        ) : (
          <ul className="space-y-1.5">
            {filteredVerifs.map((v, i) => (
              <li key={`${v.command}-${i}`} className="flex items-start gap-2">
                {v.passed ? (
                  <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400" aria-hidden />
                ) : (
                  <XCircle className="mt-0.5 h-3 w-3 shrink-0 text-rose-400" aria-hidden />
                )}
                <div className="min-w-0 flex-1">
                  <code className="block truncate font-mono text-[10px] text-nexus-text">{v.command}
                  <span className="text-[10px] text-nexus-faint">
                    exit {v.exit_code ?? "—"} · {v.duration_s}s
                    {v.skipped_reason ? ` · ${v.skipped_reason}` : ""}
                 </span>
               </div>
             </li>
            ))}
         </ul>
        )}
     </Accordion>

      {filteredTimeline.length === 0 ? (
        timeline.length === 0 ? (
          <CardEmpty icon={<Clock className="h-3.5 w-3.5" />}>Sem eventos registados</CardEmpty>
        ) : (
          <CardEmpty>Sem eventos correspondentes à pesquisa</CardEmpty>
        )
      ) : (
        <Accordion title="Eventos" icon={<Clock className="h-3 w-3" />} defaultOpen>
          <ol className="relative space-y-2 pl-4">
            <span
              className="absolute bottom-1 left-[5px] top-1 w-px bg-nexus-border/60"
              aria-hidden
            />
            {filteredTimeline.map((t, i) => (
              <li key={`${t.at}-${i}`} className="relative">
                <span
                  className="absolute -left-4 top-1.5 h-[7px] w-[7px] rounded-full bg-nexus-accent shadow-nx-accent"
                  aria-hidden
                />
                <div className="flex items-baseline gap-2">
                  <span className="font-mono text-[10px] tabular-nums text-nexus-faint">
                    {clock(t.at)}
                 </span>
                  <span className="text-[11px] text-nexus-text">{t.label}
               </div>
                {t.detail ? (
                  <p className="text-[10px] leading-snug text-nexus-faint">{t.detail</p>
                ) : null}
             </li>
            ))}
         </ol>
       </Accordion>
      )}
    </>
  );
}

/* ────────────────────────────────────────────────────────────────────────
 * Execution strip — never infers completion from missing fields
 * ──────────────────────────────────────────────────────────────────────── */

function ExecutionStrip({ envelope }: { envelope: ExecutionEnvelope | null }) {
  if (!envelope) {
    return (
      <div
        className="mt-3 rounded-lg nx-inset px-3 py-2 text-[11px] text-nexus-faint"
        role="note"
      >
        Sem envelope de execução recebido. O estado atual reflete apenas a última snapshot REST.
     </div>
    );
  }
  const state = envelope.state;
  const isComplete = envelope.completion_proven && state === "completed";
  const error = envelope.error;

  return (
    <section
      className="mt-3 rounded-lg nx-inset px-3 py-2 text-[11px] text-nexus-muted"
      aria-label="Resumo de execução"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
          Execução
       </span>
        <span className={`rounded-md px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${STATE_TONE[state].pill}`}>
          {STATE_TONE[state].label}
       </span>
        {isComplete ? (
          <span className="rounded-md bg-emerald-400/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-emerald-300">
            comprovada
         </span>
        ) : state === "completed" ? (
          <span
            className="rounded-md bg-amber-400/15 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-amber-300"
            title="Estado terminal mas evidência não comprovada"
          >
            não comprovada
         </span>
        ) : null}
        {error ? <ErrorChip error={error} /> : null}
     </div>
      <p className="mt-1.5 text-[10px] text-nexus-faint">
        Sessão <span className="font-mono">{shortId(envelope.context.session_id)}</span>
        {" · "}Run <span className="font-mono">{shortId(envelope.context.run_id)}</span>
        {envelope.context.mission_id ? (
          <>
            {" · "}Missão{" "}
            <span className="font-mono">{shortId(envelope.context.mission_id)}</span>
          </>
        ) : null}
     </p>
   </section>
  );
}

function ErrorChip({ error }: { error: ExecutionError }) {
  const tone: Record<ExecutionErrorCategory, string> = {
    provider: "bg-rose-500/15 text-rose-300",
    model: "bg-rose-500/15 text-rose-300",
    tool: "bg-rose-500/15 text-rose-300",
    validation: "bg-amber-400/15 text-amber-300",
    verification: "bg-amber-400/15 text-amber-300",
    project_context: "bg-amber-400/15 text-amber-300",
    planning: "bg-amber-400/15 text-amber-300",
    disk_pressure: "bg-rose-500/15 text-rose-300",
    timeout: "bg-rose-500/15 text-rose-300",
    cancellation: "bg-nexus-muted/15 text-nexus-muted",
    internal: "bg-rose-500/15 text-rose-300",
    unknown: "bg-rose-500/15 text-rose-300",
  };
  return (
    <span
      className={`rounded-md px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${tone[error.category]}`}
      title={error.message}
    >
      {EXECUTION_ERROR_LABEL_PT[error.category]} · {shortMessage(error.message)}
   </span>
  );
}

function shortMessage(message: string): string {
  return message.length > 40 ? `${message.slice(0, 37)}…` : message;
}

function EnvelopeBadge({
  envelope,
  state,
}: {
  envelope: ExecutionEnvelope | null;
  state: ExecutionState;
}) {
  const label = envelope
    ? isTerminalExecutionState(state)
      ? EXECUTION_STATE_LABEL_PT[state]
      : `${EXECUTION_STATE_LABEL_PT[state]} · ${envelope.context.mode}`
    : "Aguardando envelope";
  return (
    <span className="flex items-center gap-1.5 rounded-full bg-[rgba(124,106,251,0.12)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-nexus-accent-bright shadow-rim">
      {label}
   </span>
  );
}

/* ────────────────────────────────────────────────────────────────────────
 * Shared visual primitives
 * ──────────────────────────────────────────────────────────────────────── */

const STATE_STYLE: Record<string, string> = {
  proposed: "bg-[rgba(148,163,184,0.12)] text-nexus-muted",
  ready: "bg-[rgba(56,189,248,0.14)] text-sky-300",
  running: "bg-[rgba(52,211,153,0.14)] text-emerald-300",
  blocked: "bg-[rgba(251,191,36,0.14)] text-amber-300",
  completed: "bg-[rgba(124,106,251,0.14)] text-nexus-accent-bright",
  failed: "bg-[rgba(251,113,133,0.16)] text-rose-300",
  skipped: "bg-[rgba(100,116,139,0.12)] text-nexus-faint",
};

const SEVERITY_TEXT: Record<string, string> = {
  critical: "text-rose-300",
  high: "text-rose-300",
  medium: "text-amber-300",
  low: "text-sky-300",
  info: "text-nexus-faint",
};

function Stat({
  label,
  value,
  mono = false,
  tone = "neutral",
}: {
  label: string;
  value: string;
  mono?: boolean;
  tone?: "neutral" | "warning" | "danger" | "success";
}) {
  const valueClass = {
    neutral: "text-nexus-text",
    warning: "text-amber-300",
    danger: "text-rose-300",
    success: "text-emerald-300",
  }[tone];
  return (
    <div className="rounded-md nx-inset px-2 py-1.5">
      <dt className="text-[9px] font-semibold uppercase tracking-wider text-nexus-faint">
        {label}
     </dt>
      <dd
        className={`mt-0.5 truncate text-[12px] ${mono ? "font-mono" : ""} ${valueClass}`}
        title={value}
      >
        {value}
     </dd>
   </div>
  );
}

/* ────────────────────────────────────────────────────────────────────────
 * Accordion — accessible, single-open by default per row
 * ──────────────────────────────────────────────────────────────────────── */

function Accordion({
  title,
  icon,
  badge,
  tone = "neutral",
  defaultOpen = false,
  children,
}: {
  title: string;
  icon?: React.ReactNode;
  badge?: React.ReactNode;
  tone?: "neutral" | "warning" | "success" | "danger";
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const contentRef = useRef<HTMLDivElement | null>(null);
  const toneRing = {
    neutral: "",
    warning: "border-amber-400/30",
    success: "border-emerald-400/30",
    danger: "border-rose-400/30",
  }[tone];

  return (
    <section className={`nx-inset rounded-xl border ${toneRing}`}>
      <h4 className="m-0">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          aria-controls={`accordion-${title.replace(/\s+/g, "-")}`}
          className="flex w-full items-center justify-between gap-2 rounded-xl px-3 py-2 text-left transition-colors hover:bg-white/[0.04] focus:outline-none focus:ring-2 focus:ring-nexus-accent/40"
        >
          <span className="flex min-w-0 items-center gap-1.5">
            {icon ? <span className="text-nexus-faint">{icon} : null}
            <FileText className="h-3 w-3 text-nexus-faint" aria-hidden />
            <span className="truncate text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
              {title}
           </span>
         </span>
          <span className="flex items-center gap-1.5">
            {badge}
            <span
              className={`text-nexus-faint transition-transform ${open ? "rotate-90" : ""}`}
              aria-hidden
            >
              ▸
           </span>
         </span>
       </button>
     </h4>
      {open ? (
        <div
          ref={contentRef}
          id={`accordion-${title.replace(/\s+/g, "-")}`}
          className="border-t border-nexus-border/40 px-3 pb-3 pt-2"
        >
          {children}
       </div>
      ) : null}
   </section>
  );
}
