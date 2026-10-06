"use client";
import { useEffect, useMemo, useState, useCallback, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import { Users, Brain, Sparkles, Loader2, CheckCircle2, XCircle, Clock, Send, Search, BookOpen, Hammer, Bug, ClipboardList, Lightbulb, FlaskConical, Activity, Gauge, Shield, AlertTriangle, MessageSquare, History, Layers, Wrench, Library, Database, GitBranch, GitPullRequest, ArrowRight, Siren, Book, Scissors, Play } from "lucide-react";
import { authHeaders } from "../../lib/auth";
import { sanitizeSwarmAnswer, swarmReasoningText } from "../../lib/swarmReasoning";

/**
 * Publishes the run's reasoning to the swarm page, which renders it in a
 * `ThinkingBlock`.
 *
 * `app/swarm/page.tsx` listens for `nexus:swarm-thinking`; without this
 * dispatch the block could only ever render null. A `CustomEvent` is used
 * because `SwarmPanel` and the page are siblings with no shared owner, and
 * the page is the only component that decides where the text is shown.
 */
function publishSwarmThinking(reasoning: string) {
  if (typeof window === "undefined") return;
  window.dispatchEvent(
    new CustomEvent<string>("nexus:swarm-thinking", { detail: reasoning }),
  );
}

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  shield: Shield,
  scissors: Scissors,
  flask: FlaskConical,
  "git-pull-request": GitPullRequest,
  rss: Activity,
  database: Database,
  "git-branch": GitBranch,
  "arrow-right": ArrowRight,
  book: Book,
  "alert-triangle": AlertTriangle,
  library: Library,
  lightbulb: Lightbulb,
  bug: Bug,
  workflow: Wrench,
  wrench: Wrench,
  layers: Layers,
  "siren": Siren,
};

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Catalogue
//
// The backend is the source of truth (backend/swarm/modes/mode_registry.py and
// backend/swarm/core/agents.py). The constants below are only a fallback for
// when /api/swarm/modes and /api/swarm/agents are unreachable — they must stay
// in sync with the `AgentRole` / `OperationalMode` StrEnums, which are
// lowercase. Posting the NEXUS agent names (ARCHITECT, ANALYZER, CODER, …)
// here is what produced `HTTP 422: Input should be 'coordinator', ...`.
// ---------------------------------------------------------------------------

type OperationalMode =
  | "architecture"
  | "investigation"
  | "implementation"
  | "review"
  | "bugfix"
  | "planning"
  | "research";

type SwarmStrategy = "adaptive" | "divide" | "ensemble" | "pipeline" | "debate";

/** Canonical SWARM roles — must match backend `AgentRole`. */
type AgentRole =
  | "coordinator"
  | "architect"
  | "researcher"
  | "investigator"
  | "implementer"
  | "reviewer";

interface ModeSpec {
  id: OperationalMode;
  label: string;
  description: string;
  icon: React.ComponentType<{ className?: string }>;
  color: string;
  defaultStrategy: SwarmStrategy;
  agents: AgentRole[];
  gradient: string;
}

const MODE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  architecture: Brain,
  investigation: Search,
  implementation: Hammer,
  review: Shield,
  bugfix: Bug,
  planning: ClipboardList,
  research: FlaskConical,
};

const MODE_COLORS: Record<string, string> = {
  architecture: "text-violet-400",
  investigation: "text-sky-400",
  implementation: "text-emerald-400",
  review: "text-amber-400",
  bugfix: "text-red-400",
  planning: "text-indigo-400",
  research: "text-cyan-400",
};

const MODE_GRADIENTS: Record<string, string> = {
  architecture: "from-violet-500/20 to-fuchsia-500/10 border-violet-500/40",
  investigation: "from-sky-500/20 to-cyan-500/10 border-sky-500/40",
  implementation: "from-emerald-500/20 to-teal-500/10 border-emerald-500/40",
  review: "from-amber-500/20 to-orange-500/10 border-amber-500/40",
  bugfix: "from-red-500/20 to-rose-500/10 border-red-500/40",
  planning: "from-indigo-500/20 to-blue-500/10 border-indigo-500/40",
  research: "from-cyan-500/20 to-blue-500/10 border-cyan-500/40",
};

const FALLBACK_MODES: ModeSpec[] = [
  {
    id: "architecture",
    label: "Architecture",
    description: "Design system structure and trade-offs.",
    icon: Brain,
    color: MODE_COLORS.architecture,
    defaultStrategy: "debate",
    agents: ["coordinator", "investigator", "architect", "reviewer"],
    gradient: MODE_GRADIENTS.architecture,
  },
  {
    id: "investigation",
    label: "Investigation",
    description: "Read the codebase via RAG, surface constraints.",
    icon: Search,
    color: MODE_COLORS.investigation,
    defaultStrategy: "ensemble",
    agents: ["coordinator", "investigator", "architect"],
    gradient: MODE_GRADIENTS.investigation,
  },
  {
    id: "implementation",
    label: "Implementation",
    description: "Plan and emit a proposal for code changes.",
    icon: Hammer,
    color: MODE_COLORS.implementation,
    defaultStrategy: "pipeline",
    agents: ["coordinator", "investigator", "architect", "implementer", "reviewer"],
    gradient: MODE_GRADIENTS.implementation,
  },
  {
    id: "review",
    label: "Review",
    description: "Independent code/output review with 8-axis findings.",
    icon: Shield,
    color: MODE_COLORS.review,
    defaultStrategy: "ensemble",
    agents: ["coordinator", "investigator", "reviewer"],
    gradient: MODE_GRADIENTS.review,
  },
  {
    id: "bugfix",
    label: "Bugfix",
    description: "Investigate → propose a fix → reviewer validates.",
    icon: Bug,
    color: MODE_COLORS.bugfix,
    defaultStrategy: "pipeline",
    agents: ["coordinator", "investigator", "implementer", "reviewer"],
    gradient: MODE_GRADIENTS.bugfix,
  },
  {
    id: "planning",
    label: "Planning",
    description: "Structured execution plan, no code changes.",
    icon: ClipboardList,
    color: MODE_COLORS.planning,
    defaultStrategy: "divide",
    agents: ["coordinator", "investigator", "architect"],
    gradient: MODE_GRADIENTS.planning,
  },
  {
    id: "research",
    label: "Research",
    description: "Multi-source external research with citations.",
    icon: FlaskConical,
    color: MODE_COLORS.research,
    defaultStrategy: "ensemble",
    agents: ["coordinator", "researcher", "architect"],
    gradient: MODE_GRADIENTS.research,
  },
];

const STRATEGIES: { id: SwarmStrategy; label: string; description: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: "adaptive", label: "Adaptive", description: "Coordinator picks per objective.", icon: Sparkles },
  { id: "divide", label: "Divide", description: "Split into parallel subtasks.", icon: Layers },
  { id: "ensemble", label: "Ensemble", description: "All agents solve, then synthesise.", icon: Users },
  { id: "pipeline", label: "Pipeline", description: "Chain agents (output N → input N+1).", icon: Activity },
  { id: "debate", label: "Debate", description: "Propose + moderator integrates.", icon: MessageSquare },
];

interface AgentSpec {
  id: AgentRole;
  label: string;
  objective: string;
  mapsTo: string;
}

const FALLBACK_AGENTS: AgentSpec[] = [
  { id: "coordinator", label: "Coordinator", objective: "Picks the mode and keeps the run on track.", mapsTo: "ARCHITECT" },
  { id: "architect", label: "Architect", objective: "Designs structure and trade-offs.", mapsTo: "ARCHITECT" },
  { id: "researcher", label: "Researcher", objective: "Gathers external sources with citations.", mapsTo: "RESEARCHER" },
  { id: "investigator", label: "Investigator", objective: "Reads the codebase and surfaces constraints.", mapsTo: "ANALYZER" },
  { id: "implementer", label: "Implementer", objective: "Emits a reviewable change proposal.", mapsTo: "CODER" },
  { id: "reviewer", label: "Reviewer", objective: "Reviews output across 8 axes.", mapsTo: "REVIEWER" },
];

const STATE_COLORS: Record<string, string> = {
  proposed: "text-slate-400",
  discussed: "text-sky-400",
  validated: "text-amber-400",
  approved: "text-emerald-400",
  implementing: "text-blue-400",
  implemented: "text-emerald-400",
  reviewing: "text-amber-400",
  completed: "text-emerald-400",
  rejected: "text-red-400",
  failed: "text-red-400",
};

const STATE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  proposed: Clock,
  discussed: MessageSquare,
  validated: Shield,
  approved: CheckCircle2,
  implementing: Loader2,
  implemented: CheckCircle2,
  reviewing: Shield,
  completed: CheckCircle2,
  rejected: XCircle,
  failed: AlertTriangle,
};

// ---------------------------------------------------------------------------
// Score helpers
// ---------------------------------------------------------------------------

function ScoreBar({ value, label, color = "bg-nexus-accent" }: { value: number; label: string; color?: string }) {
  const pct = Math.max(0, Math.min(1, value));
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-20 text-nexus-muted">{label}</span>
      <div className="relative h-2 flex-1 overflow-hidden rounded-full bg-nexus-bg/60">
        <motion.div
          className={`h-full ${color}`}
          initial={{ width: 0 }}
          animate={{ width: `${pct * 100}%` }}
          transition={{ duration: 0.6, ease: "easeOut" }}
        />
      </div>
      <span className="w-10 text-right font-mono text-nexus-text">{pct.toFixed(2)}</span>
    </div>
  );
}

function StateBadge({ state }: { state: string }) {
  const Icon = STATE_ICONS[state] ?? Clock;
  const color = STATE_COLORS[state] ?? "text-nexus-muted";
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border border-current/30 bg-current/10 px-2 py-0.5 text-[10px] font-medium ${color}`}>
      <Icon className="h-3 w-3" />
      {state}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

interface SwarmPanelProps {
  sessionId: string;
  onInsertIntoChat?: (text: string) => void;
  /** Project root the run should index + reason over. */
  projectPath?: string;
}

/** Turn a raw `HTTP 422: {json}` body into something a human can act on. */
function humaniseError(status: number, body: string): string {
  try {
    const parsed = JSON.parse(body);
    const detail = parsed?.detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d: any) => {
          const field = Array.isArray(d?.loc) ? d.loc.filter((p: any) => p !== "body").join(".") : "";
          return field ? `${field}: ${d?.msg ?? "invalid"}` : (d?.msg ?? "invalid");
        })
        .join("\n");
    }
  } catch {
    // not JSON — fall through
  }
  const trimmed = body.trim();
  return trimmed ? `HTTP ${status}: ${trimmed.slice(0, 500)}` : `HTTP ${status}`;
}

interface SkillSummary {
  id: string;
  name: string;
  description: string;
  category: string;
  icon: string;
  mode: string;
  strategy: string;
  agents: string[];
  variables: { name: string; label: string; description: string; required: boolean; default: string; multiline: boolean }[];
  tags: string[];
  max_iterations: number;
  estimated_seconds: number;
}

export default function SwarmPanel({ sessionId, onInsertIntoChat, projectPath = "" }: SwarmPanelProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const handoffPrompt = searchParams.get("prompt");
  const [mode, setLocalMode] = useState<OperationalMode>("architecture");
  const [strategy, setStrategy] = useState<SwarmStrategy>("adaptive");
  const [agents, setAgents] = useState<AgentRole[]>([]);
  const [objective, setObjective] = useState("");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<any[]>([]);
  const [activeTab, setActiveTab] = useState<"answer" | "trace" | "scores">("answer");
  const [, setOpenSettings] = useState(false);

  // Catalogue (backend-driven, with a static fallback)
  const [modeCatalogue, setModeCatalogue] = useState<ModeSpec[]>(FALLBACK_MODES);
  const [agentCatalogue, setAgentCatalogue] = useState<AgentSpec[]>(FALLBACK_AGENTS);

  // Skills
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [selectedSkill, setSelectedSkill] = useState<SkillSummary | null>(null);
  const [skillVars, setSkillVars] = useState<Record<string, string>>({});
  const [skillCategory, setSkillCategory] = useState<string>("all");

  // One in-flight run at a time; abort it on unmount so the component never
  // calls setState after being torn down.
  const abortRef = useRef<AbortController | null>(null);
  const appliedHandoffPromptRef = useRef<string | null>(null);
  useEffect(() => () => abortRef.current?.abort(), []);

  // The dashboard hands objectives over in the URL. Prefill the editor, then
  // remove the query so a later visit to /swarm cannot restore stale text.
  // This only fills the field; launching a run still requires an explicit click.
  useEffect(() => {
    if (!handoffPrompt?.trim()) {
      appliedHandoffPromptRef.current = null;
      return;
    }
    if (appliedHandoffPromptRef.current === handoffPrompt) return;

    appliedHandoffPromptRef.current = handoffPrompt;
    setObjective(handoffPrompt);
    const remainingParams = new URLSearchParams(searchParams.toString());
    remainingParams.delete("prompt");
    const remainingQuery = remainingParams.toString();
    router.replace(remainingQuery ? `/swarm?${remainingQuery}` : "/swarm", { scroll: false });
  }, [handoffPrompt, router, searchParams]);

  const modeSpec = useMemo(
    () => modeCatalogue.find((m) => m.id === mode) ?? modeCatalogue[0] ?? FALLBACK_MODES[0],
    [modeCatalogue, mode]
  );

  // Sync strategy + agents when the mode (or the catalogue) changes
  useEffect(() => {
    setStrategy(modeSpec.defaultStrategy);
    setAgents(modeSpec.agents);
  }, [modeSpec]);

  // ---- data loading --------------------------------------------------

  const refreshHistory = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/swarm/runs?limit=20`, {
        headers: authHeaders(),
      });
      if (res.ok) {
        const data = await res.json();
        setHistory(data.runs || []);
      }
    } catch {
      // ignore — backend offline
    }
  }, []);

  const refreshSkills = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/swarm/skills`, { headers: authHeaders() });
      if (res.ok) {
        const data = await res.json();
        setSkills(data.skills || []);
      }
    } catch {
      // ignore
    }
  }, []);

  /**
   * Pull the mode + agent catalogue from the backend so the two never drift
   * apart again. Anything the backend does not describe keeps its local
   * icon/colour, and a failed fetch silently keeps the fallback.
   */
  const refreshCatalogue = useCallback(async () => {
    try {
      const [modesRes, agentsRes] = await Promise.all([
        fetch(`${API_BASE}/api/swarm/modes`, { headers: authHeaders() }),
        fetch(`${API_BASE}/api/swarm/agents`, { headers: authHeaders() }),
      ]);

      if (modesRes.ok) {
        const data = await modesRes.json();
        const entries = Object.entries<any>(data.modes ?? {});
        if (entries.length > 0) {
          setModeCatalogue(
            entries.map(([id, spec]) => ({
              id: id as OperationalMode,
              label: spec.label ?? id,
              description: spec.description ?? "",
              icon: MODE_ICONS[id] ?? Brain,
              color: MODE_COLORS[id] ?? "text-nexus-accent",
              defaultStrategy: (spec.default_strategy ?? "adaptive") as SwarmStrategy,
              agents: (spec.agents ?? []) as AgentRole[],
              gradient:
                MODE_GRADIENTS[id] ?? "from-nexus-accent/20 to-nexus-accent/5 border-nexus-accent/40",
            }))
          );
        }
      }

      if (agentsRes.ok) {
        const data = await agentsRes.json();
        const entries = Object.entries<any>(data.agents ?? {});
        if (entries.length > 0) {
          setAgentCatalogue(
            entries.map(([id, spec]) => ({
              id: id as AgentRole,
              label: spec.label ?? id,
              objective: spec.objective ?? "",
              mapsTo: spec.maps_to ?? "",
            }))
          );
        }
      }
    } catch {
      // keep the fallback catalogue
    }
  }, []);

  useEffect(() => {
    refreshCatalogue();
    refreshHistory();
    refreshSkills();
  }, [refreshCatalogue, refreshHistory, refreshSkills]);

  // ---- runs ----------------------------------------------------------

  /** Shared POST + result handling for both `/run` and `/skills/{id}/run`. */
  const postRun = useCallback(
    async (url: string, payload: Record<string, unknown>, header: (d: any) => string) => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;

      setRunning(true);
      setError(null);
      setResult(null);
      setActiveTab("answer");
      // Clear the previous run's reasoning up front, otherwise the page keeps
      // showing a stale trace next to a run that has not reported yet.
      publishSwarmThinking("");
      try {
        const res = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...authHeaders() },
          body: JSON.stringify(payload),
          signal: controller.signal,
        });
        if (!res.ok) {
          throw new Error(humaniseError(res.status, await res.text()));
        }
        const data = await res.json();
        if (controller.signal.aborted) return;
        setResult(data);
        if (data.error) setError(data.error);
        refreshHistory();
        publishSwarmThinking(swarmReasoningText(data));
        // `final_answer` is sanitised, not printed raw: the new swarm lane
        // does not strip `<thinking>` markup (only the legacy lane does), so
        // the chat box must not inherit the transport tags.
        const answer = sanitizeSwarmAnswer(data);
        if (answer && onInsertIntoChat) {
          onInsertIntoChat(`${header(data)}\n\n${answer}`);
        }
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        if (abortRef.current === controller) abortRef.current = null;
        if (!controller.signal.aborted) setRunning(false);
      }
    },
    [onInsertIntoChat, refreshHistory]
  );

  const runSkill = useCallback(
    async (skill: SkillSummary) => {
      if (running) return;
      // Validate here too so the user sees the missing field inline instead of
      // a 422 round-trip.
      const missing = skill.variables
        .filter((v) => v.required && !(skillVars[v.name] ?? "").trim())
        .map((v) => v.label || v.name);
      if (missing.length > 0) {
        setError(`Missing required field(s): ${missing.join(", ")}`);
        return;
      }
      await postRun(
        `${API_BASE}/api/swarm/skills/${encodeURIComponent(skill.id)}/run`,
        {
          variables: skillVars,
          session_id: sessionId,
          project_path: projectPath,
        },
        (d) => `## ${d.skill_name} (${d.mode} · ${d.strategy})`
      );
    },
    [running, skillVars, sessionId, projectPath, postRun]
  );

  /**
   * `/runs` returns lightweight summaries, so fetch the full payload before
   * showing a past run (otherwise the Answer/Trace tabs render empty).
   */
  const openRun = useCallback(async (summary: any) => {
    setResult(summary);
    setActiveTab("answer");
    if (!summary?.run_id) return;
    try {
      const res = await fetch(
        `${API_BASE}/api/swarm/runs/${encodeURIComponent(summary.run_id)}`,
        { headers: authHeaders() }
      );
      if (res.ok) setResult(await res.json());
    } catch {
      // keep the summary
    }
  }, []);

  const toggleAgent = (agent: AgentRole) => {
    setAgents((prev) =>
      prev.includes(agent) ? prev.filter((a) => a !== agent) : [...prev, agent]
    );
  };

  const run = useCallback(async () => {
    if (!objective.trim() || running) return;
    await postRun(
      `${API_BASE}/api/swarm/run`,
      {
        objective: objective.trim(),
        session_id: sessionId,
        mode,
        strategy,
        agents: agents.length > 0 ? agents : undefined,
        project_path: projectPath,
        max_iterations: 5,
      },
      (d) => `## SWARM (${d.mode} · ${d.strategy})`
    );
  }, [objective, mode, strategy, agents, sessionId, projectPath, running, postRun]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="shrink-0 border-b border-nexus-border bg-gradient-to-r from-fuchsia-500/10 via-violet-500/5 to-transparent px-5 py-3">
        <div className="flex items-center gap-2">
          <motion.div
            animate={{ rotate: running ? 360 : 0 }}
            transition={{ duration: 6, repeat: running ? Infinity : 0, ease: "linear" }}
            className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-fuchsia-500/30 to-violet-500/20 text-fuchsia-400 shadow-lg shadow-fuchsia-500/10"
          >
            <Users className="h-4 w-4" />
          </motion.div>
          <div>
            <h2 className="text-sm font-bold tracking-tight text-nexus-text">SWARM</h2>
            <p className="text-[10px] text-nexus-muted">Professional multi-agent orchestration</p>
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            {running && (
              <span className="flex items-center gap-1.5 rounded-full bg-blue-500/15 px-2 py-0.5 text-[10px] font-medium text-blue-400">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-blue-400" />
                Running
              </span>
            )}
            <button
              onClick={() => setOpenSettings((o) => !o)}
              className="rounded-md border border-nexus-border p-1.5 text-nexus-muted hover:bg-nexus-bg hover:text-nexus-text"
              title="Advanced settings"
            >
              <Gauge className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto thin-scrollbar px-5 py-4">
        {/* Objective input */}
        <div className="mb-4">
          <label htmlFor="swarm-objective" className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
            <Lightbulb className="h-3 w-3" /> Objective
          </label>
          <textarea
            id="swarm-objective"
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
            placeholder="Describe what you want the swarm to do…"
            rows={3}
            className="w-full resize-none rounded-lg border border-nexus-border bg-nexus-bg/60 px-3 py-2 text-sm text-nexus-text placeholder-nexus-muted outline-none transition-colors focus:border-fuchsia-500/50"
          />
        </div>

        {/* Mode picker */}
        <div className="mb-4">
          <label className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
            <Brain className="h-3 w-3" /> Operational mode
          </label>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {modeCatalogue.map((m) => {
              const Icon = m.icon;
              const active = m.id === mode;
              return (
                <motion.button
                  key={m.id}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.97 }}
                  onClick={() => setLocalMode(m.id)}
                  className={`flex flex-col items-start gap-1 rounded-lg border px-2.5 py-2 text-left transition-all duration-200 ${
                    active
                      ? `bg-gradient-to-br ${m.gradient} shadow-md`
                      : "border-nexus-border bg-nexus-card/40 text-nexus-muted hover:border-nexus-accent/30 hover:text-nexus-text"
                  }`}
                >
                  <div className="flex items-center gap-1.5">
                    <Icon className={`h-3.5 w-3.5 ${active ? m.color : ""}`} />
                    <span className="text-[11px] font-semibold">{m.label}</span>
                  </div>
                  <span className="line-clamp-2 text-[10px] text-nexus-muted">{m.description}</span>
                </motion.button>
              );
            })}
          </div>
        </div>

        {/* Strategy + agents */}
        <div className="mb-4 grid grid-cols-1 gap-3 lg:grid-cols-2">
          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
              <Activity className="h-3 w-3" /> Strategy
            </label>
            <div className="flex flex-wrap gap-1.5">
              {STRATEGIES.map((s) => {
                const Icon = s.icon;
                const active = s.id === strategy;
                return (
                  <motion.button
                    key={s.id}
                    whileTap={{ scale: 0.95 }}
                    onClick={() => setStrategy(s.id)}
                    title={s.description}
                    className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors ${
                      active
                        ? "border-fuchsia-500/40 bg-fuchsia-500/10 text-fuchsia-300"
                        : "border-nexus-border bg-nexus-card/40 text-nexus-muted hover:border-nexus-accent/30 hover:text-nexus-text"
                    }`}
                  >
                    <Icon className="h-3 w-3" />
                    {s.label}
                  </motion.button>
                );
              })}
            </div>
          </div>

          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
              <Users className="h-3 w-3" /> Agents ({agents.length})
            </label>
            <div className="flex flex-wrap gap-1.5">
              {agentCatalogue.map((a) => {
                const active = agents.includes(a.id);
                return (
                  <motion.button
                    key={a.id}
                    whileTap={{ scale: 0.95 }}
                    onClick={() => toggleAgent(a.id)}
                    title={a.mapsTo ? `${a.objective} (runs as ${a.mapsTo})` : a.objective}
                    aria-pressed={active}
                    className={`rounded-md border px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide transition-colors ${
                      active
                        ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300"
                        : "border-nexus-border bg-nexus-card/40 text-nexus-muted hover:border-nexus-accent/30 hover:text-nexus-text"
                    }`}
                  >
                    {a.label}
                  </motion.button>
                );
              })}
            </div>
            {agents.length === 0 && (
              <p className="mt-1 text-[10px] text-amber-400/80">
                No agents selected — the mode&apos;s default team will be used.
              </p>
            )}
          </div>
        </div>

        {/* Run button */}
        <button
          onClick={run}
          disabled={!objective.trim() || running}
          className="group flex w-full items-center justify-center gap-2 rounded-lg bg-gradient-to-r from-fuchsia-500 to-violet-500 px-4 py-2.5 text-sm font-semibold text-white shadow-lg shadow-fuchsia-500/20 transition-all hover:shadow-fuchsia-500/40 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {running ? (
            <>
              <Loader2 className="h-4 w-4 animate-spin" /> Running swarm…
            </>
          ) : (
            <>
              <Send className="h-4 w-4 transition-transform group-hover:translate-x-0.5" /> Launch SWARM run
            </>
          )}
        </button>

        {error && (
          <div className="mt-3 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span className="whitespace-pre-wrap">{error}</span>
          </div>
        )}

        {/* Result */}
        {result && (
          <div className="mt-4">
            {/* Tabs */}
            <div className="mb-2 flex items-center gap-1 border-b border-nexus-border">
              {[
                { id: "answer", label: "Answer", icon: BookOpen },
                { id: "trace", label: "Trace", icon: MessageSquare },
                { id: "scores", label: "Scores", icon: Gauge },
              ].map((t) => {
                const Icon = t.icon;
                return (
                  <button
                    key={t.id}
                    onClick={() => setActiveTab(t.id as any)}
                    className={`flex items-center gap-1 border-b-2 px-3 py-1.5 text-[11px] font-medium transition-colors ${
                      activeTab === t.id
                        ? "border-fuchsia-500 text-fuchsia-300"
                        : "border-transparent text-nexus-muted hover:text-nexus-text"
                    }`}
                  >
                    <Icon className="h-3 w-3" />
                    {t.label}
                  </button>
                );
              })}
              <span className="ml-auto">
                <StateBadge state={result.state} />
              </span>
            </div>

            <AnimatePresence mode="wait">
              {activeTab === "answer" && (
                <motion.div
                  key="answer"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  className="prose prose-sm prose-invert max-w-none whitespace-pre-wrap rounded-lg border border-nexus-border bg-nexus-card/40 p-3 text-xs leading-relaxed"
                >
                  {sanitizeSwarmAnswer(result) || "_(empty)_"}
                </motion.div>
              )}

              {activeTab === "trace" && (
                <motion.div
                  key="trace"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  className="space-y-2"
                >
                  <div className="flex items-center gap-2 text-[10px] text-nexus-muted">
                    <span>{result.message_count} messages</span>
                    <span>·</span>
                    <span>{result.decisions?.length ?? 0} decisions</span>
                    <span>·</span>
                    <span>{result.proposals?.length ?? 0} proposals</span>
                    <span>·</span>
                    <span>{result.reviews?.length ?? 0} reviews</span>
                    <span>·</span>
                    <span>{result.duration_ms}ms</span>
                  </div>
                  <div className="max-h-72 overflow-y-auto thin-scrollbar rounded-lg border border-nexus-border bg-nexus-bg/40 p-2 text-[11px]">
                    {result.proposals?.map((p: any) => (
                      <div key={p.proposal_id} className="mb-2 border-b border-nexus-border/30 pb-2 last:border-b-0">
                        <div className="flex items-center gap-2 font-mono">
                          <StateBadge state={p.state} />
                          <span className="text-nexus-text">{p.title}</span>
                        </div>
                        <div className="ml-1 mt-1 text-nexus-muted">{p.description?.slice(0, 200)}</div>
                        {p.evidence_refs?.length > 0 && (
                          <div className="ml-1 mt-1 text-[10px] text-emerald-400">
                            Evidence: {p.evidence_refs.slice(0, 3).join(", ")}
                            {p.evidence_refs.length > 3 && ` (+${p.evidence_refs.length - 3} more)`}
                          </div>
                        )}
                      </div>
                    ))}
                    {result.reviews?.map((r: any) => (
                      <div key={r.review_id} className="mb-2 rounded border border-amber-500/20 bg-amber-500/5 p-2">
                        <div className="flex items-center gap-2 font-mono text-[10px]">
                          {r.passed ? (
                            <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                          ) : (
                            <XCircle className="h-3 w-3 text-red-400" />
                          )}
                          <span className="text-nexus-text">Review {r.review_id.slice(0, 8)}</span>
                        </div>
                        <div className="ml-5 mt-1 whitespace-pre-wrap text-[10px] text-nexus-muted">{r.summary}</div>
                      </div>
                    ))}
                    {result.decisions?.map((d: any) => (
                      <div key={d.decision_id} className="mb-1 flex items-center gap-2 text-[10px]">
                        <span className="rounded bg-indigo-500/15 px-1.5 py-0.5 text-indigo-400">ADR</span>
                        <span className="font-mono text-nexus-muted">{d.decided_by}</span>
                        <span className="text-nexus-text">{d.title}</span>
                        <span className="ml-auto text-nexus-muted">c={d.confidence}</span>
                      </div>
                    ))}
                  </div>
                </motion.div>
              )}

              {activeTab === "scores" && (
                <motion.div
                  key="scores"
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -8 }}
                  className="space-y-3 rounded-lg border border-nexus-border bg-nexus-card/40 p-3"
                >
                  <div className="text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
                    Final quality scores
                  </div>
                  <ScoreBar value={result.scores?.quality ?? 0} label="Quality" color="bg-emerald-500" />
                  <ScoreBar value={result.scores?.confidence ?? 0} label="Confidence" color="bg-sky-500" />
                  <ScoreBar value={result.scores?.risk ?? 0} label="Risk" color="bg-red-500" />
                  <ScoreBar value={result.scores?.complexity ?? 0} label="Complexity" color="bg-amber-500" />
                  {result.evidence_used?.length > 0 && (
                    <div className="mt-2 border-t border-nexus-border/40 pt-2 text-[10px]">
                      <div className="mb-1 text-nexus-muted">
                        RAG evidence ({result.evidence_used.length}):
                      </div>
                      <ul className="space-y-0.5 text-nexus-text">
                        {result.evidence_used.slice(0, 3).map((e: any) => (
                          <li key={e.chunk_id} className="font-mono">
                            {e.source_path}:{e.start_line}-{e.end_line}{" "}
                            <span className="text-nexus-muted">score={e.score.toFixed(2)}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        )}

        {/* History */}
        {history.length > 0 && (
          <div className="mt-4">
            <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
              <History className="h-3 w-3" /> Recent runs
            </div>
            <div className="space-y-1">
              {history.slice(0, 5).map((r: any) => (
                <button
                  key={r.run_id}
                  onClick={() => openRun(r)}
                  className="flex w-full items-center gap-2 rounded-md border border-nexus-border/60 bg-nexus-card/30 px-2 py-1.5 text-left text-[11px] hover:border-fuchsia-500/30"
                >
                  <span className="font-mono text-nexus-muted">{String(r.run_id ?? "").slice(0, 6)}</span>
                  <span className="text-nexus-text">{r.objective?.slice(0, 40)}</span>
                  <span className="ml-auto">
                    <StateBadge state={r.state} />
                  </span>
                </button>
              ))}
            </div>
          </div>
        )}

        {/* Skills */}
        {skills.length > 0 && (
          <div className="mt-4">
            <div className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
              <Wrench className="h-3 w-3" /> Skills ({skills.length})
            </div>
            <div className="mb-2 flex flex-wrap gap-1">
              {["all", ...Array.from(new Set(skills.map((s) => s.category)))].map((c) => (
                <button
                  key={c}
                  onClick={() => setSkillCategory(c)}
                  className={`rounded px-2 py-0.5 text-[10px] font-medium transition-colors ${
                    skillCategory === c
                      ? "bg-fuchsia-500/20 text-fuchsia-300"
                      : "bg-nexus-card/40 text-nexus-muted hover:text-nexus-text"
                  }`}
                >
                  {c}
                </button>
              ))}
            </div>
            <div className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
              {skills
                .filter((s) => skillCategory === "all" || s.category === skillCategory)
                .map((s) => {
                  const Icon = ICON_MAP[s.icon] ?? Wrench;
                  return (
                    <button
                      key={s.id}
                      onClick={() => {
                        setSelectedSkill(s);
                        setSkillVars(
                          Object.fromEntries(
                            s.variables.map((v) => [v.name, v.default])
                          )
                        );
                      }}
                      className={`flex items-start gap-2 rounded-md border p-2 text-left text-[11px] transition-colors ${
                        selectedSkill?.id === s.id
                          ? "border-fuchsia-500/40 bg-fuchsia-500/10"
                          : "border-nexus-border/60 bg-nexus-card/30 hover:border-fuchsia-500/30"
                      }`}
                    >
                      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0 text-fuchsia-400" />
                      <div className="min-w-0 flex-1">
                        <div className="font-semibold text-nexus-text">{s.name}</div>
                        <div className="line-clamp-2 text-[10px] text-nexus-muted">{s.description}</div>
                        <div className="mt-0.5 flex flex-wrap gap-1">
                          <span className="rounded bg-nexus-bg/60 px-1 text-[9px] text-nexus-muted">
                            {s.category}
                          </span>
                          <span className="rounded bg-nexus-bg/60 px-1 text-[9px] text-nexus-muted">
                            ~{s.estimated_seconds}s
                          </span>
                        </div>
                      </div>
                    </button>
                  );
                })}
            </div>

            {selectedSkill && (
              <div className="mt-3 rounded-lg border border-fuchsia-500/30 bg-fuchsia-500/5 p-3">
                <div className="mb-2 flex items-center gap-2">
                  <span className="text-sm font-semibold text-fuchsia-300">
                    {selectedSkill.name}
                  </span>
                  <span className="text-[10px] text-nexus-muted">
                    mode={selectedSkill.mode} · strategy={selectedSkill.strategy}
                  </span>
                </div>
                <div className="space-y-2">
                  {selectedSkill.variables.map((v) => (
                    <div key={v.name}>
                      <label className="mb-0.5 flex items-center gap-1 text-[10px] text-nexus-muted">
                        {v.label}
                        {v.required && <span className="text-red-400">*</span>}
                      </label>
                      {v.multiline ? (
                        <textarea
                          value={skillVars[v.name] ?? ""}
                          onChange={(e) =>
                            setSkillVars({ ...skillVars, [v.name]: e.target.value })
                          }
                          rows={2}
                          className="w-full resize-none rounded border border-nexus-border bg-nexus-bg/40 px-2 py-1 text-[11px] text-nexus-text outline-none focus:border-fuchsia-500/40"
                        />
                      ) : (
                        <input
                          value={skillVars[v.name] ?? ""}
                          onChange={(e) =>
                            setSkillVars({ ...skillVars, [v.name]: e.target.value })
                          }
                          className="w-full rounded border border-nexus-border bg-nexus-bg/40 px-2 py-1 text-[11px] text-nexus-text outline-none focus:border-fuchsia-500/40"
                        />
                      )}
                    </div>
                  ))}
                </div>
                <button
                  onClick={() => runSkill(selectedSkill)}
                  disabled={running}
                  className="mt-3 flex w-full items-center justify-center gap-2 rounded-md bg-gradient-to-r from-fuchsia-500 to-violet-500 px-3 py-1.5 text-[11px] font-semibold text-white shadow-md shadow-fuchsia-500/20 hover:shadow-fuchsia-500/40 disabled:opacity-50"
                >
                  <Play className="h-3 w-3" /> Run skill
                </button>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
