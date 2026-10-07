/**
 * Frontend mirror of the backend execution envelope contract.
 *
 * The backend authoritative source is
 * ``backend/orchestrator/execution_contracts.py`` — every JSON key in this
 * file matches the ``to_dict`` output of the dataclasses declared there.
 *
 * The frontend never infers completion from a missing error field. Completion
 * is only true when the envelope explicitly says so. This file is the single
 * place where that rule is encoded.
 */
import type { AgentName, StreamEvent } from "./types";

/* ────────────────────────────────────────────────────────────────────────
 * 1. Mode + state enums — backend JSON values, mirrored verbatim
 * ──────────────────────────────────────────────────────────────────────── */

export const EXECUTION_MODES = ["chat", "assisted", "mission"] as const;
export type ExecutionMode = (typeof EXECUTION_MODES)[number];

export const EXECUTION_STATES = [
  "queued",
  "routing",
  "planning",
  "executing",
  "verifying",
  "completed",
  "failed",
  "blocked",
  "cancelled",
  "interrupted",
] as const;
export type ExecutionState = (typeof EXECUTION_STATES)[number];

export const EXECUTION_ERROR_CATEGORIES = [
  "provider",
  "model",
  "tool",
  "validation",
  "verification",
  "project_context",
  "planning",
  "disk_pressure",
  "timeout",
  "cancellation",
  "internal",
  "unknown",
] as const;
export type ExecutionErrorCategory = (typeof EXECUTION_ERROR_CATEGORIES)[number];

/** States a run may occupy at the very end — never revisited once set. */
export const TERMINAL_EXECUTION_STATES: readonly ExecutionState[] = [
  "completed",
  "failed",
  "blocked",
  "cancelled",
  "interrupted",
] as const;

export function isTerminalExecutionState(state: ExecutionState | string | null | undefined): boolean {
  if (!state) return false;
  return (TERMINAL_EXECUTION_STATES as readonly string[]).includes(state);
}

/* ────────────────────────────────────────────────────────────────────────
 * 2. Provider health — surface area + telemetry for the active provider
 * ──────────────────────────────────────────────────────────────────────── */

export interface ProviderHealth {
  /** Provider key (openrouter, ollama, mock, dev, ...). */
  name: string;
  /** Whether the provider can answer real prompts. */
  healthy: boolean;
  /** True when the provider is the deterministic dev/mock backend. */
  simulation: boolean;
  /** Provider only serves free-tier models. */
  free_only: boolean;
  /** Quota left in the current window (null = unknown / not measured). */
  quota_available: number | null;
  /** Why this provider is or is not eligible. */
  eligibility_reason: string;
  /** Unix timestamp of the last health probe. */
  validated_at: number | null;
}

/* ────────────────────────────────────────────────────────────────────────
 * 3. Evidence — only verified items count toward completion
 * ──────────────────────────────────────────────────────────────────────── */

export interface ExecutionEvidence {
  /** Stable id within the run, useful for diffs. */
  id?: string;
  /** Human label, e.g. "pytest backend/tests". */
  label?: string;
  /** Free-form description of what the evidence proves. */
  description?: string;
  /** True ONLY when the verification actually passed. */
  verified: boolean;
  /** Anything the backend wants to attach (exit codes, screenshots). */
  details?: Record<string, unknown>;
}

/* ────────────────────────────────────────────────────────────────────────
 * 4. Error envelope — stable category + machine-readable retry hint
 * ──────────────────────────────────────────────────────────────────────── */

export interface ExecutionError {
  category: ExecutionErrorCategory;
  message: string;
  provider?: string | null;
  model?: string | null;
  /** Seconds the caller should wait before retrying. */
  retry_after?: number | null;
  details?: Record<string, unknown>;
}

/* ────────────────────────────────────────────────────────────────────────
 * 5. Mission payload — the brief + plan the orchestrator understood
 * ──────────────────────────────────────────────────────────────────────── */

export interface MissionFinding {
  id: string;
  title: string;
  severity: "critical" | "high" | "medium" | "low" | "info";
  category: string;
  detail: string;
  evidence: string;
}

export interface MissionBrief {
  objective_raw: string;
  objective_interpreted: string;
  initial_state: string[];
  priorities: string[];
  assumptions: string[];
  out_of_scope: string[];
  snapshot?: { findings?: MissionFinding[] };
}

export interface MissionPhasePlan {
  phase: string;
  label: string;
  steps: string[];
  rationale: string;
  skipped: boolean;
  skip_reason: string;
}

export interface MissionPlan {
  phases: MissionPhasePlan[];
  concurrency_limit: number;
}

export interface MissionContract {
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

export interface MissionWave {
  index: number;
  name: string;
  phase: string;
  state: string;
  contracts: MissionContract[];
}

export interface MissionDecision {
  number: number;
  choice: string;
  reason: string;
  alternatives: string[];
  outcome: string;
  at: string;
}

export interface MissionVerification {
  command: string;
  exit_code: number | null;
  summary: string;
  duration_s: number;
  passed: boolean;
  skipped_reason: string | null;
}

export interface MissionTimelineEntry {
  at: string;
  label: string;
  detail: string;
}

/**
 * The mission shape rendered in the panel — mirrors
 * ``MissionTracker.mission.to_dict()`` and the existing
 * ``/api/mission/current`` payload.
 */
export interface MissionPayload {
  id: string;
  title: string;
  /** Old string state field — kept for backward compatibility. */
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
  brief: MissionBrief | null;
  plan: MissionPlan | null;
  waves: MissionWave[];
  decisions: MissionDecision[];
  timeline: MissionTimelineEntry[];
  verifications: MissionVerification[];
}

/* ────────────────────────────────────────────────────────────────────────
 * 6. The envelope — one object that carries everything the panel needs
 * ──────────────────────────────────────────────────────────────────────── */

export interface ExecutionContext {
  session_id: string;
  run_id: string;
  correlation_id: string;
  mission_id: string | null;
  project_path: string | null;
  mode: ExecutionMode;
}

export interface ExecutionEnvelope {
  /** Monotonic checkpoint version — older payloads are dropped. */
  version: number;
  /** Wall-clock capture moment (ISO). */
  captured_at: string;
  state: ExecutionState;
  context: ExecutionContext;
  provider: string | null;
  model: string | null;
  /** Final-mile cost in USD when the run finishes. */
  cost_usd: number | null;
  /** True when the producer of this envelope is a simulation client. */
  simulation: boolean;
  provider_health: ProviderHealth | null;
  error: ExecutionError | null;
  evidence: ExecutionEvidence[];
  files_changed: string[];
  commands_run: string[];
  failed_tasks: string[];
  /** True only when the backend *proved* completion — verified evidence + no errors. */
  completion_proven: boolean;
  /** Free-form agent currently driving the run. */
  active_agent: AgentName | string | null;
  /** Optional rich mission payload (present in mission mode). */
  mission: MissionPayload | null;
}

/* ────────────────────────────────────────────────────────────────────────
 * 7. Normalization — accepts loose shapes from REST/SSE/WebSocket
 * ──────────────────────────────────────────────────────────────────────── */

function asString(v: unknown, fallback = ""): string {
  return typeof v === "string" ? v : fallback;
}

function asNumber(v: unknown, fallback: number | null = null): number | null {
  if (v === null || v === undefined) return fallback;
  const n = typeof v === "string" ? Number(v) : (v as number);
  return Number.isFinite(n) ? n : fallback;
}

function asBool(v: unknown, fallback = false): boolean {
  return typeof v === "boolean" ? v : fallback;
}

function asMode(v: unknown): ExecutionMode {
  return (EXECUTION_MODES as readonly string[]).includes(String(v))
    ? (v as ExecutionMode)
    : "chat";
}

function asState(v: unknown): ExecutionState {
  return (EXECUTION_STATES as readonly string[]).includes(String(v))
    ? (v as ExecutionState)
    : "queued";
}

function asErrorCategory(v: unknown): ExecutionErrorCategory {
  return (EXECUTION_ERROR_CATEGORIES as readonly string[]).includes(String(v))
    ? (v as ExecutionErrorCategory)
    : "unknown";
}

function asRecord(v: unknown): Record<string, unknown> {
  return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
}

function normalizeContext(raw: unknown): ExecutionContext {
  const r = asRecord(raw);
  return {
    session_id: asString(r.session_id),
    run_id: asString(r.run_id),
    correlation_id: asString(r.correlation_id),
    mission_id: r.mission_id == null ? null : asString(r.mission_id, ""),
    project_path: r.project_path == null ? null : asString(r.project_path, ""),
    mode: asMode(r.mode),
  };
}

function normalizeProviderHealth(raw: unknown): ProviderHealth | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  return {
    name: asString(r.name ?? r.provider),
    healthy: asBool(r.healthy),
    simulation: asBool(r.simulation),
    free_only: asBool(r.free_only),
    quota_available: asNumber(r.quota_available),
    eligibility_reason: asString(r.eligibility_reason ?? r.reason),
    validated_at: asNumber(r.validated_at ?? r.last_check),
  };
}

function normalizeEvidence(raw: unknown): ExecutionEvidence[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((item) => {
    const r = asRecord(item);
    return {
      id: r.id ? asString(r.id) : undefined,
      label: r.label ? asString(r.label) : r.command ? asString(r.command) : undefined,
      description: r.description ? asString(r.description) : r.summary ? asString(r.summary) : undefined,
      verified: asBool(r.verified ?? r.passed),
      details: r.details && typeof r.details === "object" ? (r.details as Record<string, unknown>) : undefined,
    };
  });
}

function normalizeError(raw: unknown): ExecutionError | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  return {
    category: asErrorCategory(r.category),
    message: asString(r.message ?? r.detail ?? "Erro não especificado."),
    provider: r.provider == null ? null : asString(r.provider, ""),
    model: r.model == null ? null : asString(r.model, ""),
    retry_after: asNumber(r.retry_after),
    details: r.details && typeof r.details === "object" ? (r.details as Record<string, unknown>) : undefined,
  };
}

function normalizeStrings(raw: unknown): string[] {
  return Array.isArray(raw) ? raw.filter((s): s is string => typeof s === "string") : [];
}

function normalizeMission(raw: unknown): MissionPayload | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (!asString(r.id)) return null;
  return {
    id: asString(r.id),
    title: asString(r.title),
    state: asString(r.state),
    phase_label: asString(r.phase_label),
    progress: asNumber(r.progress, 0) ?? 0,
    active_agents: asNumber(r.active_agents, 0) ?? 0,
    tasks_total: asNumber(r.tasks_total, 0) ?? 0,
    tasks_done: asNumber(r.tasks_done, 0) ?? 0,
    files_changed: normalizeStrings(r.files_changed),
    tests_passed: asNumber(r.tests_passed, 0) ?? 0,
    tests_failed: asNumber(r.tests_failed, 0) ?? 0,
    risks: normalizeStrings(r.risks),
    unresolved: normalizeStrings(r.unresolved),
    brief: (r.brief as MissionBrief | null) ?? null,
    plan: (r.plan as MissionPlan | null) ?? null,
    waves: Array.isArray(r.waves) ? (r.waves as MissionWave[]) : [],
    decisions: Array.isArray(r.decisions) ? (r.decisions as MissionDecision[]) : [],
    timeline: Array.isArray(r.timeline) ? (r.timeline as MissionTimelineEntry[]) : [],
    verifications: Array.isArray(r.verifications) ? (r.verifications as MissionVerification[]) : [],
  };
}

/**
 * Build a :class:`ExecutionEnvelope` from any loosely-shaped payload. Accepts
 * the canonical envelope, REST responses, or chat SSE events.
 *
 * ``version`` defaults to ``Date.now()`` for ad-hoc payloads and is taken from
 * the source when present — callers that stream many updates rely on it for
 * monotonic merging.
 */
export function normalizeExecutionEnvelope(raw: unknown, fallbackVersion?: number): ExecutionEnvelope {
  const r = asRecord(raw);
  const context = normalizeContext(r.context ?? r.run_context ?? r);
  const evidence = normalizeEvidence(r.evidence);
  const error = normalizeError(r.error ?? r.execution_error);
  const mission = normalizeMission(r.mission ?? r);
  const providerHealth = normalizeProviderHealth(r.provider_health);

  // The truthful completion flag. We never infer it from the absence of
  // errors — it must arrive explicitly, and only when the state is the
  // ``completed`` terminal state.
  const explicitFlag = asBool(r.completion_proven);
  const state = asState(r.state ?? r.execution_state);
  const completion_proven =
    explicitFlag && state === "completed" && error == null && evidence.some((e) => e.verified);

  const versionRaw = asNumber(r.version ?? r.checkpoint_version);
  const version =
    versionRaw != null ? versionRaw : fallbackVersion ?? Date.now();

  return {
    version,
    captured_at: asString(r.captured_at ?? r.timestamp ?? new Date().toISOString()),
    state,
    context,
    provider: r.provider == null ? null : asString(r.provider, ""),
    model: r.model == null ? null : asString(r.model, ""),
    cost_usd: asNumber(r.cost_usd ?? r.cost),
    simulation: asBool(r.simulation) || providerHealth?.simulation === true,
    provider_health: providerHealth,
    error,
    evidence,
    files_changed: normalizeStrings(r.files_changed),
    commands_run: normalizeStrings(r.commands_run),
    failed_tasks: normalizeStrings(r.failed_tasks ?? r.tasks_failed),
    completion_proven,
    active_agent: r.active_agent == null ? null : asString(r.active_agent, ""),
    mission,
  };
}

/**
 * Normalize a chat SSE ``StreamEvent`` into an envelope-shaped object. We
 * pull execution_state / execution_error / routing / mission_* events into
 * one shape so the store and the panel don't have to know the SSE dialect.
 */
export function normalizeStreamEvent(event: StreamEvent | Record<string, unknown>): ExecutionEnvelope | null {
  const e = event as StreamEvent & Record<string, unknown>;
  const type = asString(e.type);

  // Skip non-execution events early — token / thinking / tool_result / etc.
  if (
    type !== "routing" &&
    type !== "done" &&
    type !== "execution_state" &&
    type !== "execution_error" &&
    type !== "execution_completed" &&
    type !== "mission_brief" &&
    type !== "mission_plan" &&
    type !== "mission_wave" &&
    type !== "mission_agent" &&
    type !== "mission_decision" &&
    type !== "mission_verification" &&
    type !== "mission_completed" &&
    type !== "execution_envelope"
  ) {
    return null;
  }

  const data = asRecord(e.data);
  // ``done`` events also carry the envelope in their data field when the
  // session finishes — the backend embeds the final state there.
  if (type === "done" && data && Object.keys(data).length > 0) {
    return normalizeExecutionEnvelope(data);
  }

  switch (type) {
    case "routing":
      return normalizeExecutionEnvelope({
        ...data,
        state: "routing",
        mode: data.mode ?? (data.decision && "auto") ?? "chat",
        context: data.context ?? data,
      });
    case "execution_state":
      return normalizeExecutionEnvelope({ ...data, state: data.state ?? "executing" });
    case "execution_error":
      return normalizeExecutionEnvelope({
        ...data,
        state: data.state ?? "failed",
        error: {
          category: data.category ?? data.error_category ?? "unknown",
          message: data.message ?? data.detail ?? "",
          provider: data.provider ?? null,
          model: data.model ?? null,
          retry_after: data.retry_after ?? null,
        },
      });
    case "execution_completed":
      return normalizeExecutionEnvelope({
        ...data,
        state: "completed",
        completion_proven: true,
      });
    case "mission_brief":
    case "mission_plan":
    case "mission_wave":
    case "mission_agent":
    case "mission_decision":
    case "mission_verification":
      return normalizeExecutionEnvelope({
        ...data,
        // The mission_* events may carry a nested ``mission`` object; if not,
        // the top-level ``data`` itself is a MissionPayload.
        mission: (data.mission as MissionPayload) ?? ((type === "mission_brief" ? data : null) as MissionPayload | null),
        state: data.state ?? "planning",
        mode: "mission",
      });
    case "mission_completed":
      return normalizeExecutionEnvelope({
        ...data,
        mission: (data.mission as MissionPayload) ?? (data as unknown as MissionPayload),
        state: "completed",
        mode: "mission",
        completion_proven: true,
      });
    case "execution_envelope":
      return normalizeExecutionEnvelope(data);
    default:
      return null;
  }
}

/* ────────────────────────────────────────────────────────────────────────
 * 8. Monotonic merge — older envelopes never overwrite newer ones
 * ──────────────────────────────────────────────────────────────────────── */

/** True when a context carries no information at all. */
function isEmptyContext(context: ExecutionContext): boolean {
  return (
    context.session_id === "" &&
    context.run_id === "" &&
    context.correlation_id === "" &&
    context.mission_id === null &&
    context.project_path === null
  );
}

/**
 * Return ``next`` only when it carries a strictly higher version than
 * ``prev`` — otherwise return ``prev`` untouched. The store calls this for
 * every envelope update; it guarantees the UI never regresses when packets
 * arrive out of order.
 */
export function mergeEnvelopeMonotonic(
  prev: ExecutionEnvelope | null,
  next: ExecutionEnvelope,
): ExecutionEnvelope {
  if (!prev) return next;
  if (typeof prev.version === "number" && typeof next.version === "number" && next.version <= prev.version) {
    return prev;
  }

  return {
    ...prev,
    ...next,
    // `normalizeExecutionEnvelope` always materialises a `context` object, so
    // `next.context ?? prev.context` could never fall back: a thin REST poll
    // produced `context: { session_id: "", run_id: "", … }` and the carry-forward
    // silently did nothing, blanking the run/session the UI was showing. An
    // all-blank context is what "omitted" actually looks like on the wire.
    context: isEmptyContext(next.context) ? prev.context : next.context,
    provider_health: next.provider_health ?? prev.provider_health,
    evidence: next.evidence.length > 0 ? next.evidence : prev.evidence,
    // Union, not "longer list wins". The old comparison kept `prev` whenever
    // `next` was shorter, which threw away entries the UI had never seen: a
    // poll reporting only the newest change lost every older one. These lists
    // are the run's history, so they only ever grow.
    files_changed: Array.from(new Set([...prev.files_changed, ...next.files_changed])),
    commands_run: Array.from(new Set([...prev.commands_run, ...next.commands_run])),
    failed_tasks: Array.from(new Set([...prev.failed_tasks, ...next.failed_tasks])),
    mission: next.mission ?? prev.mission,
  };
}

/* ────────────────────────────────────────────────────────────────────────
 * 9. Display helpers — short labels and tones for the UI
 * ──────────────────────────────────────────────────────────────────────── */

export const EXECUTION_STATE_LABEL_PT: Record<ExecutionState, string> = {
  queued: "Em fila",
  routing: "A decidir rota",
  planning: "A planear",
  executing: "A executar",
  verifying: "A verificar",
  completed: "Concluída",
  failed: "Falhou",
  blocked: "Bloqueada",
  cancelled: "Cancelada",
  interrupted: "Interrompida",
};

export const EXECUTION_MODE_LABEL_PT: Record<ExecutionMode, string> = {
  chat: "Chat",
  assisted: "Assistido",
  mission: "Missão",
};

export const EXECUTION_ERROR_LABEL_PT: Record<ExecutionErrorCategory, string> = {
  provider: "Provider",
  model: "Modelo",
  tool: "Ferramenta",
  validation: "Validação",
  verification: "Verificação",
  project_context: "Contexto",
  planning: "Planeamento",
  disk_pressure: "Disco cheio",
  timeout: "Timeout",
  cancellation: "Cancelamento",
  internal: "Interno",
  unknown: "Desconhecido",
};

export interface ExecutionDisplayState {
  state: ExecutionState;
  /** True only when state is terminal AND the backend proves completion. */
  isTerminal: boolean;
  /** True only for the truthful "completed" state. */
  isComplete: boolean;
  /** True for failed / blocked / interrupted / cancelled. */
  isStalled: boolean;
  /** Convenience flag for cancel/resume/replan button enablement. */
  canCancel: boolean;
  canResume: boolean;
  canReplan: boolean;
}

/**
 * Derive the UI display state from a single envelope — never infers
 * completion from the absence of error fields.
 */
export function deriveDisplayState(envelope: ExecutionEnvelope | null): ExecutionDisplayState {
  const state: ExecutionState = envelope?.state ?? "queued";
  const isTerminal = isTerminalExecutionState(state);
  const isComplete = state === "completed" && (envelope?.completion_proven ?? false);
  const isStalled = state === "failed" || state === "blocked" || state === "interrupted" || state === "cancelled";
  return {
    state,
    isTerminal,
    isComplete,
    isStalled,
    canCancel: state === "queued" || state === "routing" || state === "planning" || state === "executing" || state === "verifying",
    canResume: state === "interrupted" || state === "blocked" || state === "cancelled",
    canReplan: state === "failed" || state === "blocked" || state === "interrupted",
  };
}
