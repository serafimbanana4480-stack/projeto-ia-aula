"use client";

/**
 * MissionPanel — what the orchestrator understood, planned, and did.
 *
 * The problem it exists to fix: the Orchestrator jumped from prompt straight to
 * agent spawn. The user saw activity and could not tell what was understood,
 * what state the project was in, why those agents, what the plan was, what each
 * agent touched, whether anything was verified, or what was left.
 *
 * Each tab is one of those questions, in the order they get asked:
 *
 *   Brief    → what was understood + the measured initial state
 *   Plano    → the five phases, declared before any spawn
 *   Agentes  → contracts: justification, dependencies, completion criteria
 *   Decisões → choices with reasons and the alternatives that lost
 *   Timeline → when everything happened
 *
 * The rule the design follows: **proposed is a visible state.** An agent card
 * appears before the agent runs, showing why it is going to exist. That is the
 * difference between supervising and watching.
 */

import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  Clock,
  FileText,
  GitBranch,
  ListChecks,
  Radar,
  ScrollText,
  XCircle,
} from "lucide-react";

import { apiUrl } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { CardEmpty, CardStat } from "../ui/Card";

// ── Types (mirror backend/orchestrator/mission_control.py) ─────────────────

interface Finding {
  id: string;
  title: string;
  severity: "critical" | "high" | "medium" | "low" | "info";
  category: string;
  detail: string;
  evidence: string;
}

interface Contract {
  id: string;
  name: string;
  objective: string;
  justification: string;
  phase: string;
  state: "proposed" | "ready" | "running" | "blocked" | "completed" | "failed" | "skipped";
  activity: string;
  dependencies: string[];
  tools: string[];
  completion_criteria: string[];
  discoveries: string[];
  files_changed: string[];
  commands_run: string[];
  confidence: number | null;
  error: string | null;
}

interface Wave {
  index: number;
  name: string;
  phase: string;
  state: string;
  contracts: Contract[];
}

interface PhasePlan {
  phase: string;
  label: string;
  steps: string[];
  rationale: string;
  skipped: boolean;
  skip_reason: string;
}

interface Decision {
  number: number;
  choice: string;
  reason: string;
  alternatives: string[];
  outcome: string;
  at: string;
}

interface Verification {
  command: string;
  exit_code: number | null;
  summary: string;
  duration_s: number;
  passed: boolean;
  skipped_reason: string | null;
}

interface Mission {
  id: string;
  title: string;
  state: string;
  phase_label: string;
  progress: number;
  active_agents: number;
  tasks_total: number;
  tasks_done: number;
  files_changed: string[];
  tests_passed: number;
  tests_failed: number;
  risks: string[];
  unresolved: string[];
  brief: {
    objective_raw: string;
    objective_interpreted: string;
    initial_state: string[];
    priorities: string[];
    assumptions: string[];
    out_of_scope: string[];
    snapshot: { findings: Finding[] };
  } | null;
  plan: { phases: PhasePlan[]; concurrency_limit: number } | null;
  waves: Wave[];
  decisions: Decision[];
  timeline: Array<{ at: string; label: string; detail: string }>;
  verifications: Verification[];
}

const POLL_MS = 5_000;

const TABS = [
  { id: "brief", label: "Brief", icon: Radar },
  { id: "plan", label: "Plano", icon: ClipboardList },
  { id: "agents", label: "Agentes", icon: GitBranch },
  { id: "decisions", label: "Decisões", icon: ScrollText },
  { id: "timeline", label: "Timeline", icon: Clock },
] as const;

type TabId = (typeof TABS)[number]["id"];

/** Proposed is deliberately muted, not hidden — it is information, not noise. */
const STATE_STYLE: Record<Contract["state"], string> = {
  proposed: "bg-[rgba(148,163,184,0.12)] text-nexus-muted",
  ready: "bg-[rgba(56,189,248,0.14)] text-sky-300",
  running: "bg-[rgba(52,211,153,0.14)] text-emerald-300",
  blocked: "bg-[rgba(251,191,36,0.14)] text-amber-300",
  completed: "bg-[rgba(124,106,251,0.14)] text-nexus-accent-bright",
  failed: "bg-[rgba(251,113,133,0.16)] text-rose-300",
  skipped: "bg-[rgba(100,116,139,0.12)] text-nexus-faint",
};

const SEVERITY_STYLE: Record<Finding["severity"], string> = {
  critical: "text-rose-300",
  high: "text-rose-300",
  medium: "text-amber-300",
  low: "text-sky-300",
  info: "text-nexus-faint",
};

function clock(iso: string): string {
  return iso.length > 19 ? iso.slice(11, 19) : iso;
}

// ── Component ──────────────────────────────────────────────────────────────

export default function MissionPanel() {
  const [mission, setMission] = useState<Mission | null>(null);
  const [active, setActive] = useState<boolean | null>(null);
  const [tab, setTab] = useState<TabId>("brief");
  const [error, setError] = useState<string | null>(null);
  const [unauthorized, setUnauthorized] = useState(false);
  const [loading, setLoading] = useState(true);
  const requestInFlight = useRef(false);
  const tabButtonRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const load = useCallback(async () => {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    try {
      const res = await authenticatedFetch(apiUrl("/api/mission/current"), {
        signal: AbortSignal.timeout(8000),
      });
      if (res.status === 401) {
        setUnauthorized(true);
        setMission(null);
        setActive(null);
        setError(null);
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = (await res.json()) as { active: boolean; mission: Mission | null };
      setActive(data.active);
      setMission(data.mission);
      setUnauthorized(false);
      setError(null);
    } catch (cause) {
      setUnauthorized(false);
      setError(
        cause instanceof Error && cause.message.startsWith("HTTP ")
          ? `Não foi possível carregar Mission Control (${cause.message}).`
          : "Não foi possível contactar Mission Control.",
      );
    } finally {
      requestInFlight.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = setInterval(() => void load(), POLL_MS);
    return () => clearInterval(timer);
  }, [load]);

  const allContracts = useMemo(
    () => (mission?.waves ?? []).flatMap((w) => w.contracts),
    [mission],
  );

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, currentIndex: number) => {
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      nextIndex = (currentIndex + 1) % TABS.length;
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      nextIndex = (currentIndex - 1 + TABS.length) % TABS.length;
    } else if (event.key === "Home") {
      nextIndex = 0;
    } else if (event.key === "End") {
      nextIndex = TABS.length - 1;
    }
    if (nextIndex === null) return;

    event.preventDefault();
    setTab(TABS[nextIndex].id);
    tabButtonRefs.current[nextIndex]?.focus();
  };

  // ── Empty / error ────────────────────────────────────────────────────────
  if (loading && !mission) {
    return (
      <Surface elevation={1} padding="lg" className="nx-dashboard-widget">
        <SurfaceHeader
          icon={<Radar className="h-4 w-4" />}
          title="Mission Control"
          subtitle="Planeamento, execução supervisionada, verificação e relatório"
        />
        <div className="mt-4">
          <CardEmpty icon={<Radar className="h-3.5 w-3.5" />}>
            A carregar Mission Control…
          </CardEmpty>
        </div>
      </Surface>
    );
  }

  if (unauthorized) {
    return (
      <Surface elevation={1} padding="lg" className="nx-dashboard-widget">
        <SurfaceHeader
          icon={<Radar className="h-4 w-4" />}
          title="Mission Control"
          subtitle="Planeamento, execução supervisionada, verificação e relatório"
        />
        <div className="mt-5 rounded-xl border border-dashed border-nexus-border/70 bg-nexus-card/20 px-2 py-3">
          <CardEmpty icon={<AlertTriangle className="h-3.5 w-3.5" />}>
            Autenticação necessária para ver Mission Control.
          </CardEmpty>
        </div>
      </Surface>
    );
  }

  if (error && !mission) {
    return (
      <Surface elevation={1} padding="lg">
        <SurfaceHeader
          icon={<Radar className="h-4 w-4" />}
          title="Mission Control"
          subtitle="Planeamento, execução supervisionada, verificação e relatório"
        />
        <div className="mt-4">
          <CardEmpty icon={<AlertTriangle className="h-3.5 w-3.5" />}>{error}</CardEmpty>
        </div>
      </Surface>
    );
  }

  if (active === false || !mission) {
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
            <em> antes </em>
            de qualquer agente ser criado.
          </CardEmpty>
        </div>
      </Surface>
    );
  }

  const pct = Math.round((mission.progress ?? 0) * 100);

  return (
    <Surface
      elevation={2}
      padding="lg"
      tone="accent"
      live={mission.state === "executing"}
      className="nx-dashboard-widget"
    >
      <SurfaceHeader
        icon={<Radar className="h-4 w-4" />}
        tone={mission.state === "failed" ? "danger" : "accent"}
        title="Mission Control"
        subtitle={mission.title || "Missão em curso"}
        action={
          <span className="flex items-center gap-1.5 rounded-full bg-[rgba(124,106,251,0.12)] px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wider text-nexus-accent-bright shadow-rim">
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                mission.state === "executing"
                  ? "bg-emerald-400 animate-pulse-subtle"
                  : mission.state === "failed"
                    ? "bg-rose-400"
                    : "bg-nexus-accent"
              }`}
            />
            {mission.phase_label}
          </span>
        }
      />

      {error ? (
        <div
          role="alert"
          className="mt-3 flex items-start gap-2 rounded-lg border border-amber-400/25 bg-amber-400/[0.06] px-3 py-2 text-[11px] text-amber-200"
        >
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>{error} A mostrar os últimos dados recebidos, que podem estar desatualizados.</span>
        </div>
      ) : null}

      {/* ── The eight numbers ─────────────────────────────────────────── */}
      <div className="mt-4 grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-7">
        <CardStat label="Progresso" value={`${pct}%`} hint="Contratos concluídos ou dispensados" />
        <CardStat label="Agentes ativos" value={mission.active_agents} hint="A executar agora" />
        <CardStat
          label="Tarefas"
          value={`${mission.tasks_done}/${mission.tasks_total}`}
          hint="Contratos resolvidos face ao total"
        />
        <CardStat
          label="Ficheiros"
          value={mission.files_changed.length}
          hint="Ficheiros alterados nesta missão"
        />
        <CardStat
          label="Testes ok"
          value={mission.tests_passed}
          hint="Verificações cujo comando saiu com código 0"
        />
        <CardStat
          label="Testes falhados"
          value={mission.tests_failed}
          hint="Verificações com código de saída diferente de 0"
        />
        <CardStat label="Riscos" value={mission.risks.length} hint="Riscos técnicos registados" />
      </div>

      <div className="mt-3 h-1 overflow-hidden rounded-full bg-[rgba(148,163,184,0.12)]">
        <div
          className="h-full rounded-full bg-nx-accent transition-[width] duration-500"
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* ── Tabs ─────────────────────────────────────────────────────── */}
      <div
        className="mt-5 flex gap-1.5 overflow-x-auto border-b border-nexus-border/60 pb-2"
        role="tablist"
        aria-label="Secções da missão"
      >
        {TABS.map(({ id, label, icon: Icon }, index) => (
          <button
            key={id}
            id={`mission-tab-${id}`}
            type="button"
            role="tab"
            aria-selected={tab === id}
            aria-controls="mission-tabpanel"
            tabIndex={tab === id ? 0 : -1}
            ref={(node) => {
              tabButtonRefs.current[index] = node;
            }}
            onClick={() => setTab(id)}
            onKeyDown={(event) => handleTabKeyDown(event, index)}
            className={`flex min-h-10 shrink-0 items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent ${
              tab === id
                ? "bg-[rgba(124,106,251,0.14)] text-nexus-accent-bright shadow-rim"
                : "text-nexus-muted hover:text-nexus-text"
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>

      <div
        id="mission-tabpanel"
        role="tabpanel"
        aria-labelledby={`mission-tab-${tab}`}
        tabIndex={0}
        className="mt-4 max-h-[460px] space-y-3 overflow-y-auto pr-1 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
      >
        {tab === "brief" && <BriefTab mission={mission} />}
        {tab === "plan" && <PlanTab mission={mission} />}
        {tab === "agents" && <AgentsTab waves={mission.waves} />}
        {tab === "decisions" && <DecisionsTab decisions={mission.decisions} />}
        {tab === "timeline" && (
          <TimelineTab timeline={mission.timeline} verifications={mission.verifications} />
        )}
      </div>

      {allContracts.length > 0 ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-nexus-border/60 pt-3 text-[11px] text-nexus-faint">
          <span>
            {allContracts.filter((c) => c.state === "proposed").length} propostos ·{" "}
            {allContracts.filter((c) => c.state === "skipped").length} dispensados ·{" "}
            {allContracts.filter((c) => c.state === "failed").length} falhados
          </span>
          {mission.plan ? (
            <span>Máx. {mission.plan.concurrency_limit} agentes concorrentes</span>
          ) : null}
        </div>
      ) : null}
    </Surface>
  );
}
// ── Tabs ───────────────────────────────────────────────────────────────────

function BriefTab({ mission }: { mission: Mission }) {
  const b = mission.brief;
  if (!b) return <CardEmpty>Sem brief registado.</CardEmpty>;
  const findings = b.snapshot?.findings ?? [];

  return (
    <>
      <Block title="Objetivo interpretado">
        <p className="text-[12px] leading-relaxed text-nexus-text">{b.objective_interpreted}</p>
        <p className="mt-2 text-[11px] italic leading-relaxed text-nexus-faint">
          Pedido original: “{b.objective_raw}”
        </p>
      </Block>

      <Block title="Estado inicial medido">
        <ul className="space-y-1">
          {b.initial_state.map((line) => (
            <li key={line} className="text-[11px] leading-relaxed text-nexus-muted">
              · {line}
            </li>
          ))}
        </ul>
      </Block>

      {findings.length > 0 ? (
        <Block title="Problemas detetados">
          <ul className="space-y-1.5">
            {findings.map((f) => (
              <li key={f.id} className="text-[11px] leading-relaxed">
                <span
                  className={`font-mono text-[10px] font-semibold uppercase ${SEVERITY_STYLE[f.severity]}`}
                >
                  [{f.severity}]
                </span>{" "}
                <span className="text-nexus-text">{f.title}</span>
                {f.evidence ? (
                  <span className="ml-1 font-mono text-[10px] text-nexus-faint">
                    ({f.evidence.slice(0, 90)})
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        </Block>
      ) : null}

      <Block title="Prioridades propostas">
        <ol className="space-y-1">
          {b.priorities.map((p, i) => (
            <li key={p} className="text-[11px] leading-relaxed text-nexus-muted">
              {i + 1}. {p}
            </li>
          ))}
        </ol>
      </Block>

      {b.assumptions.length > 0 ? (
        <Block title="Pressupostos" tone="warning">
          <ul className="space-y-1">
            {b.assumptions.map((a) => (
              <li key={a} className="text-[11px] leading-relaxed text-amber-200/80">
                · {a}
              </li>
            ))}
          </ul>
        </Block>
      ) : null}
    </>
  );
}

function PlanTab({ mission }: { mission: Mission }) {
  if (!mission.plan) return <CardEmpty>Nenhum plano publicado.</CardEmpty>;
  return (
    <>
      {mission.plan.phases.map((ph) => (
        <div
          key={ph.phase}
          className={`nx-inset rounded-xl p-3.5 ${ph.skipped ? "opacity-60" : ""}`}
        >
          <div className="flex items-center justify-between gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-nexus-text">
              {ph.label}
            </span>
            {ph.skipped ? (
              <span className="rounded-md bg-[rgba(100,116,139,0.14)] px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider text-nexus-faint">
                ignorada
              </span>
            ) : null}
          </div>
          {ph.skipped ? (
            <p className="mt-1.5 text-[11px] leading-relaxed text-amber-200/70">{ph.skip_reason}</p>
          ) : (
            <ul className="mt-2 space-y-1">
              {ph.steps.map((s) => (
                <li key={s} className="text-[11px] leading-relaxed text-nexus-muted">
                  · {s}
                </li>
              ))}
            </ul>
          )}
          {ph.rationale && !ph.skipped ? (
            <p className="mt-2 border-t border-nexus-border/50 pt-2 text-[10px] italic leading-relaxed text-nexus-faint">
              {ph.rationale}
            </p>
          ) : null}
        </div>
      ))}
    </>
  );
}

function AgentsTab({ waves }: { waves: Wave[] }) {
  if (waves.length === 0) return <CardEmpty>Nenhum agente proposto ainda.</CardEmpty>;
  return (
    <>
      {waves.map((w) => (
        <div key={w.index}>
          <div className="mb-2 flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-nexus-faint">
              {w.name}
            </span>
            <span className="h-px flex-1 bg-nexus-border/60" />
            <span className="font-mono text-[10px] text-nexus-faint">{w.state}</span>
          </div>
          <div className="grid grid-cols-1 gap-2.5 lg:grid-cols-2">
            {w.contracts.map((c) => (
              <ContractCard key={c.id} contract={c} />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}

function ContractCard({ contract: c }: { contract: Contract }) {
  const skipped = c.state === "skipped";
  return (
    <div className={`nx-inset min-w-0 rounded-xl p-4 ${skipped ? "opacity-55" : ""}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className="min-w-0 break-words text-xs font-semibold tracking-wide text-nexus-text">
          {c.name}
        </span>
        <span
          className={`shrink-0 rounded-md px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wider ${STATE_STYLE[c.state]}`}
        >
          {c.state}
        </span>
      </div>

      <p className="mt-2 text-xs leading-relaxed text-nexus-muted">{c.objective}</p>

      <p className="mt-3 border-l-2 border-nexus-border pl-3 text-[11px] leading-relaxed text-nexus-faint">
        <strong className="text-nexus-muted">Motivo:</strong> {c.justification}
      </p>

      {c.dependencies.length > 0 && !skipped ? (
        <p className="mt-1.5 text-[10px] leading-relaxed text-nexus-faint">
          <strong className="text-nexus-muted">Depende de:</strong> {c.dependencies.join(", ")}
        </p>
      ) : null}

      {c.activity ? (
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
            <ListChecks className="h-3 w-3" /> Critérios de conclusão
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
        <p className="mt-2 text-[10px] leading-relaxed text-rose-300/80">{c.error}</p>
      ) : null}
    </div>
  );
}

function DecisionsTab({ decisions }: { decisions: Decision[] }) {
  if (decisions.length === 0) {
    return (
      <CardEmpty icon={<ScrollText className="h-3.5 w-3.5" />}>
        Nenhuma decisão registada. Aqui aparecem escolhas com a sua razão e as alternativas
        rejeitadas — não o raciocínio interno em bruto.
      </CardEmpty>
    );
  }
  return (
    <>
      {decisions.map((d) => (
        <div key={d.number} className="nx-inset rounded-xl p-3.5">
          <div className="flex items-baseline justify-between gap-2">
            <span className="font-mono text-[10px] font-semibold text-nexus-accent-bright">
              Decisão #{d.number}
            </span>
            <span className="font-mono text-[10px] text-nexus-faint">{clock(d.at)}</span>
          </div>
          <p className="mt-1.5 text-[12px] font-medium leading-relaxed text-nexus-text">
            {d.choice}
          </p>
          <p className="mt-2 text-[11px] leading-relaxed text-nexus-muted">
            <strong className="text-nexus-text">Razão:</strong> {d.reason}
          </p>
          {d.alternatives.length > 0 ? (
            <div className="mt-2">
              <span className="text-[9px] font-semibold uppercase tracking-wider text-nexus-faint">
                Alternativas consideradas
              </span>
              <ul className="mt-0.5 space-y-0.5">
                {d.alternatives.map((a) => (
                  <li key={a} className="text-[10px] leading-snug text-nexus-faint line-through/0">
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
        </div>
      ))}
    </>
  );
}

function TimelineTab({
  timeline,
  verifications,
}: {
  timeline: Array<{ at: string; label: string; detail: string }>;
  verifications: Verification[];
}) {
  return (
    <>
      {verifications.length > 0 ? (
        <Block title="Verificações executadas">
          <ul className="space-y-1.5">
            {verifications.map((v, i) => (
              <li key={`${v.command}-${i}`} className="flex items-start gap-2">
                {v.passed ? (
                  <CheckCircle2 className="mt-0.5 h-3 w-3 shrink-0 text-emerald-400" />
                ) : (
                  <XCircle className="mt-0.5 h-3 w-3 shrink-0 text-rose-400" />
                )}
                <div className="min-w-0 flex-1">
                  <code className="block truncate font-mono text-[10px] text-nexus-text">
                    {v.command}
                  </code>
                  <span className="text-[10px] text-nexus-faint">
                    exit {v.exit_code ?? "—"} · {v.duration_s}s
                    {v.skipped_reason ? ` · ${v.skipped_reason}` : ""}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        </Block>
      ) : (
        <Block title="Verificações executadas" tone="warning">
          <p className="text-[11px] leading-relaxed text-amber-200/80">
            Nenhuma verificação foi executada. Quaisquer alterações desta missão{" "}
            <strong>não estão testadas</strong>.
          </p>
        </Block>
      )}

      {timeline.length === 0 ? (
        <CardEmpty icon={<Clock className="h-3.5 w-3.5" />}>Sem eventos registados.</CardEmpty>
      ) : (
        <div className="relative space-y-2 pl-4">
          <span className="absolute bottom-1 left-[5px] top-1 w-px bg-nexus-border/60" />
          {timeline.map((t, i) => (
            <div key={`${t.at}-${i}`} className="relative">
              <span className="absolute -left-4 top-1.5 h-[7px] w-[7px] rounded-full bg-nexus-accent shadow-nx-accent" />
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[10px] tabular-nums text-nexus-faint">
                  {clock(t.at)}
                </span>
                <span className="text-[11px] text-nexus-text">{t.label}</span>
              </div>
              {t.detail ? (
                <p className="text-[10px] leading-snug text-nexus-faint">{t.detail}</p>
              ) : null}
            </div>
          ))}
        </div>
      )}
    </>
  );
}

// ── Shared ────────────────────────────────────────────────────────────────

function Block({
  title,
  tone = "neutral",
  children,
}: {
  title: string;
  tone?: "neutral" | "warning";
  children: React.ReactNode;
}) {
  return (
    <div
      className={`nx-inset rounded-xl p-3.5 ${
        tone === "warning" ? "border-[rgba(251,191,36,0.24)]" : ""
      }`}
    >
      <div className="mb-2 flex items-center gap-1.5">
        <FileText className="h-3 w-3 text-nexus-faint" />
        <span className="text-xs font-medium text-nexus-muted">
          {title}
        </span>
      </div>
      {children}
    </div>
  );
}
