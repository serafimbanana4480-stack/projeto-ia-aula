"use client";

/**
 * Deterministic fold of the raw SSE event stream into an ordered list of
 * ``ChatMessage`` objects, each carrying a ``steps`` array for the
 * ``RunTimeline``.
 *
 * Why this is not just ``foldEvents`` anymore (§8 item 3):
 *  - the new primary runtime emits a total order via ``(run_id, seq)``; the
 *    legacy pipeline emits frames with no ``seq``. ``RunEventBuffer`` orders
 *    the former by ``seq`` and de-duplicates replays, while still rendering
 *    legacy frames in arrival order after the ordered ones;
 *  - every step preserves ``kind`` + ``label`` + ``target`` + ``seq`` so the
 *    timeline is a faithful, single-source rendering of one run rather than a
 *    re-derivation from wall-clock timestamps (which collide on Windows and
 *    produced the "agent started before its dependency" bug);
 *  - the live footer (phase, elapsed, tokens) is captured from the ``done``
 *    frame and the last ``metric``/``progress`` events.
 */
import { RunEventBuffer, type RuntimeEventLike } from "./eventOrdering";
import type {
  ActivityItem,
  AgentName,
  ChatMessage,
  RunStep,
  StepStatus,
  StreamEvent,
  ToolCallItem,
} from "./types";
import {
  activityFromProgress,
  activityFromMissionEvent,
  agentActivity,
  sanitizeAssistantContent,
} from "./chatPresentation";
import { stripAnsiCodes } from "./utils";

export interface FoldRunResult {
  messages: ChatMessage[];
  lastUserMessage: string;
}

/**
 * The single source for the caveat every agent-declared TODO surface must
 * carry. A checklist only reports what the agent SAID it did; nothing in the
 * UI independently verifies that execution. Two surfaces already rendered this
 * sentence (`ToolCallTimeline`'s todo result, `SessionTaskPanel`) while the
 * plan block inside the run timeline did not, so one bubble contradicted
 * itself. Kept here — the only module every one of those surfaces may import —
 * so the wording cannot drift.
 */
export const AGENT_DECLARED_TODO_CAVEAT =
  "Os estados são declarados pelo agente; esta checklist não verifica a execução de forma independente.";

/** Reason recorded on work the user stopped before it reported a result. */
const USER_CANCELLATION_REASON =
  "Execução cancelada a pedido do utilizador antes de chegar o resultado desta ação.";

const AGENT_COLORS: Record<string, string> = {
  ROUTER: "#7c3aed",
  ARCHITECT: "#4f46e5",
  RESEARCHER: "#2563eb",
  CODER: "#059669",
  ANALYZER: "#d97706",
  DEBUGGER: "#dc2626",
  DOCUMENTER: "#0284c7",
  OPTIMIZER: "#9333ea",
  DASHBOARD: "#0d9488",
  ORCHESTRATOR: "#7c3aed",
  SWARM: "#db2777",
  NEXUS: "#0ea5e9",
};

const AGENT_DEFAULT = "#7c3aee";

function agentSeed(name: string): string {
  return name && name.length ? name.charAt(0).toUpperCase() : "N";
}

function agentColor(name: string): string {
  return (AGENT_COLORS as Record<string, string>)[name] || AGENT_DEFAULT;
}

function iconFor(verb: RunStep["verb"]): string {
  switch (verb) {
    case "thinking":
      return "brain";
    case "tool":
      return "wrench";
    case "file":
      return "file-text";
    case "command":
      return "terminal";
    case "test":
      return "test-tube";
    case "agent":
      return "bot";
    case "status":
      return "activity";
    case "message":
      return "message-square";
    default:
      return "circle";
  }
}

/** Verb derived from the SSE frame type when the runtime envelope is absent. */
function verbFor(type: StreamEvent["type"]): RunStep["verb"] {
  switch (type) {
    case "thinking":
      return "thinking";
    case "tool_call":
    case "tool_result":
    case "tool_error":
    case "tool_confirmation":
      return "tool";
    case "agent_started":
    case "agent_finished":
      return "agent";
    case "progress":
    case "mission_brief":
    case "mission_plan":
    case "mission_wave":
    case "mission_agent":
    case "mission_decision":
    case "mission_verification":
    case "mission_completed":
      return "status";
    default:
      return "other";
  }
}

/**
 * The agent an `agent_*` step is actually about.
 *
 * For a delegation frame `event.agent` is the EMITTER — usually NEXUS handing
 * work over — while the subagent's own name arrives in `data.target`/`data.name`
 * (see `chat_primary._envelope`). Labelling the step with `event.agent` produced
 * a row reading "NEXUS começou · CODER", i.e. it looked like NEXUS was the
 * subject and CODER a parameter. Prefer the delegate, and fall back to the
 * emitter only when the frame names no delegate.
 */
function agentActor(event: StreamEvent): string {
  const data = event.data ?? {};
  const candidate = data.target ?? data.name ?? event.agent;
  return typeof candidate === "string" && candidate.trim() ? candidate : "Agente";
}

function seqOf(event: StreamEvent): number {
  if (typeof event.seq === "number" && Number.isFinite(event.seq)) return event.seq;
  // Legacy frames expose seq only through the runtime envelope in `data`.
  const ds = event.data;
  if (ds && typeof ds.seq === "number" && Number.isFinite(ds.seq)) return ds.seq;
  // Fallback: preserve arrival order with a monotonically increasing value so
  // legacy steps still sort deterministically after the ordered ones.
  return -(event.data ? 1 : 0);
}

function stableSerialize(value: unknown): string {
  if (value === null || typeof value !== "object") {
    return JSON.stringify(value) ?? String(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(stableSerialize).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  return `{${Object.keys(record)
    .sort()
    .map((key) => `${JSON.stringify(key)}:${stableSerialize(record[key])}`)
    .join(",")}}`;
}

function isDuplicateAgentAnnouncement(previous: StreamEvent | undefined, event: StreamEvent): boolean {
  if (!previous || previous.type !== "agent_started" || event.type !== "agent_started") return false;
  if (previous.event_id || event.event_id) return previous.event_id === event.event_id;
  return previous.run_id === event.run_id &&
    previous.seq === event.seq &&
    previous.timestamp === event.timestamp &&
    previous.agent === event.agent &&
    previous.task_id === event.task_id &&
    previous.content === event.content &&
    stableSerialize(previous.data ?? {}) === stableSerialize(event.data ?? {});
}

function isSameToolCall(previous: StreamEvent | undefined, event: StreamEvent): boolean {
  return previous?.type === "tool_call" && event.type === "tool_call" &&
    previous.tool_name === event.tool_name &&
    stableSerialize(previous.tool_args ?? {}) === stableSerialize(event.tool_args ?? {});
}

function displayPhase(phase: string): string {
  const labels: Record<string, string> = {
    routing: "encaminhamento",
    context_build: "preparação do contexto",
    model_request: "chamada ao modelo",
    executing: "execução de ferramentas",
    verifying: "verificação",
    finished: "concluída",
    transport_complete: "concluída",
    provider_truncation: "resposta interrompida pelo provider",
  };
  return labels[phase] ?? phase.replaceAll("_", " ");
}

/** Build a single timeline step from an SSE frame. */
function stepOf(event: StreamEvent): RunStep {
  const data = event.data ?? {};
  const kind =
    (typeof data.kind === "string" && data.kind) ||
    (typeof data.runtime_type === "string" && data.runtime_type) ||
    event.type;
  const label =
    (typeof data.label === "string" && data.label) ||
    (typeof event.content === "string" && event.content) ||
    "";
  const target =
    (typeof data.target === "string" && data.target) ||
    event.tool_name ||
    (typeof event.agent === "string" ? event.agent : "") ||
    "";

  let verb: RunStep["verb"] = verbFor(event.type);
  if (kind.startsWith("file_")) verb = "file";
  else if (kind.startsWith("command_")) verb = "command";
  else if (kind.startsWith("test")) verb = "test";
  else if (kind.startsWith("subagent")) verb = "agent";

  const DEFAULT_LABEL: Partial<Record<RunStep["verb"], string>> = {
    thinking: "a raciocinar",
    tool: "a usar ferramenta",
    file: "a ler / escrever",
    command: "a executar comando",
    test: "a verificar",
    agent: "agente",
    status: "a avançar",
    message: "a pensar",
  };
  let stepLabel = label;
  if (!stepLabel && verb === "status") {
    stepLabel = typeof event.content === "string" ? event.content : "";
  }
  if (!stepLabel) stepLabel = DEFAULT_LABEL[verb] || "";
  if (!stepLabel) stepLabel = verb;

  return {
    seq: seqOf(event),
    kind,
    label: stepLabel,
    target,
    verb,
    status: "running",
    icon: iconFor(verb),
    taskId:
      (typeof event.task_id === "string" && event.task_id) ||
      (typeof data.task_id === "string" && data.task_id) ||
      undefined,
    agent: event.agent,
    // Wall clock of the first frame of this step. `Date.parse` on an
    // unparseable timestamp must not produce NaN, which would poison every
    // duration computed from it.
    startedAt: eventTimestamp(event),
    detail: data,
    event,
  };
}

function eventTimestamp(event: StreamEvent): number {
  const parsed = Date.parse(event.timestamp ?? "");
  return Number.isFinite(parsed) ? parsed : Date.now();
}

/** Freeze a step's elapsed time. Called when its block of work is over. */
function sealStep(step: RunStep, status: StepStatus, closedAt: number): void {
  step.status = status;
  if (step.startedAt !== undefined) {
    step.durationMs = Math.max(0, closedAt - step.startedAt);
  }
}

/** Update the matching in-flight tool step with a terminal status.

    One step per tool (call → result/error): the step keeps the call's ``seq``
    and ``kind``/``label``/``target``, and the result is folded into ``detail``
    together with the result event's own ``seq``, so no ordering information is
    lost when a call and its result collapse into a single timeline row.
    */
function closeStep(
  steps: RunStep[],
  target: string,
  status: StepStatus,
  detail?: unknown,
  resultSeq?: number,
  closedAt?: number,
): void {
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const step = steps[i];
    if (
      step.verb === "tool" &&
      (step.status === "running" || step.status === "awaiting_confirmation") &&
      step.target === target
    ) {
      sealStep(step, status, closedAt ?? Date.now());
      if (detail !== undefined) {
        const base = (step.detail as Record<string, unknown>) ?? {};
        step.detail = { ...base, result: detail, resultSeq };
      }
      return;
    }
  }
}

function closeStepByVerb(
  steps: RunStep[],
  verb: RunStep["verb"],
  status: StepStatus,
  detail?: unknown,
  resultSeq?: number,
  closedAt?: number,
): void {
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const step = steps[i];
    if (step.verb !== verb || step.status !== "running") continue;
    sealStep(step, status, closedAt ?? Date.now());
    if (detail !== undefined) {
      const base = (step.detail as Record<string, unknown>) ?? {};
      step.detail = { ...base, result: detail, resultSeq };
    }
    return;
  }
}

function closeAgentStep(
  message: ChatMessage,
  event: StreamEvent,
  status: StepStatus = "success",
): boolean {
  const data = event.data ?? {};
  const target = String(data.target || data.name || event.agent || message.agent || "");
  const steps = message.steps ?? [];
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const step = steps[i];
    if (
      step.verb === "agent" &&
      step.status === "running" &&
      (!target || !step.target || step.target === target)
    ) {
      step.status = status;
      step.label =
        status === "success"
          ? `${target || "Agente"} concluiu`
          : status === "error"
            ? `${target || "Agente"} terminou com erro`
            : status === "cancelled"
              ? `${target || "Agente"} foi cancelado`
              : status === "paused"
                ? `${target || "Agente"} ficou em pausa`
                : `${target || "Agente"} terminou com aviso`;
      step.event = event;
      step.detail = { ...(step.detail as Record<string, unknown> | undefined), completed: data };
      return true;
    }
  }
  return false;
}

function findRunningTool(
  calls: ToolCallItem[],
  name?: string,
): number {
  if (!calls) return -1;
  for (let i = calls.length - 1; i >= 0; i -= 1) {
    if (calls[i].status !== "running") continue;
    if (!name || calls[i].name === name) return i;
  }
  return -1;
}

function resultRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** One result envelope says it failed. Mirrors `contextTelemetry` (`ok:false`). */
function envelopeReportsFailure(envelope: Record<string, unknown>): boolean {
  if (envelope.ok === false) return true;
  if (envelope.success === false) return true;
  if (envelope.timed_out === true) return true;
  const error = envelope.error;
  if (typeof error === "string" && error.trim().length > 0) return true;
  if (error && typeof error === "object" && Object.keys(error).length > 0) return true;
  return false;
}

/**
 * Whether a `tool_result` payload reports a failure.
 *
 * The frame TYPE alone cannot answer this: the backend answers a tool call on
 * the `tool_result` channel even when the tool itself failed, and the payload
 * carries the truth (`ok:false`, an `error` message, `success:false`,
 * `timed_out`). `ToolCallTimeline.isTodoResult` and
 * `contextTelemetry.loadedSkillsFromEvents` already refuse to trust such a
 * result; the fold must agree or the timeline paints a red X inside one row
 * and a green check in the other.
 *
 * Tools wrap their answer in `{ ok, result?, error? }`, and the two envelopes
 * can disagree, so both are inspected — `ok:false` nested under `result` is
 * still a failure. Payloads carrying none of these markers keep the previous
 * behaviour (success): the absence of an error is not a failure, but it is
 * also not the evidence for one.
 */
export function toolResultReportsFailure(result: unknown): boolean {
  const outer = resultRecord(result);
  if (!outer) return false;
  const inner = resultRecord(outer.result);
  return envelopeReportsFailure(outer) || (inner !== null && envelopeReportsFailure(inner));
}

/**
 * Short, truthful message for a failed `tool_result`; empty when the payload
 * reports no failure at all. Never describes a failure that was not reported —
 * an invented message is the same defect as an invented success.
 */
export function describeToolResultFailure(result: unknown): string {
  if (!toolResultReportsFailure(result)) return "";
  const outer = resultRecord(result) ?? {};
  const candidates = [outer, resultRecord(outer.result)].filter(
    (record): record is Record<string, unknown> => record !== null,
  );
  for (const record of candidates) {
    const error = record.error;
    if (typeof error === "string" && error.trim().length > 0) return error.trim();
    if (error && typeof error === "object" && Object.keys(error).length > 0) {
      const nested = (error as Record<string, unknown>).message ?? (error as Record<string, unknown>).detail;
      if (typeof nested === "string" && nested.trim().length > 0) return nested.trim();
      return "A ferramenta reportou um erro.";
    }
    if (record.timed_out === true) return "A ferramenta expirou (tempo limite).";
  }
  if (outer.ok === false || outer.success === false) {
    return "A ferramenta reportou `ok: false` sem detalhe do erro.";
  }
  return "A ferramenta reportou uma falha.";
}

/**
 * Whether an activity's status is evidence that the run did NOT complete
 * cleanly. Shared by `foldRun`, `RunTimeline` and `ExecutionActivity` so the
 * folder and the two surfaces cannot disagree about whether a run had a
 * problem — the bug this predicate exists to kill was an `error`/`warning`
 * activity that the header simply never counted.
 */
export function isFailingActivityStatus(status: ActivityItem["status"] | undefined): boolean {
  return status === "error" || status === "warning";
}

/**
 * A frame reporting that the run was cancelled — the backend's `RUN_CANCELLED`
 * (`progress`, `data.kind === "run_cancelled"`) or the client-local marker
 * `useAgentStream.cancel()` records for the same event.
 */
export function isCancellationFrame(event: StreamEvent): boolean {
  const data = event.data ?? {};
  return String(data.kind ?? "") === "run_cancelled" ||
    String(data.runtime_type ?? "") === "run_cancelled";
}

function foldSingleRun(
  pendingUser: ChatMessage[],
  events: StreamEvent[],
  lastUserMessage: string,
  runKey: string,
): FoldRunResult {
  const buffer = new RunEventBuffer();
  for (const e of events) buffer.push(e as unknown as RuntimeEventLike);
  const ordered = buffer.events() as unknown as StreamEvent[];

  const out: ChatMessage[] = [...pendingUser];
  let current: ChatMessage | null = null;
  let currentAgent: AgentName = "CODER";
  let lastThinkingIteration = 0;
  let lastPhase = "";
  let elapsedMs: number | undefined;
  let telemetry: Record<string, unknown> | undefined;
  // The reasoning step of the block currently streaming. A model emits one
  // `thinking` frame per delta, so pushing a step per frame turned a 2000-token
  // approach into hundreds of identical "Brain" rows. Exactly one open step is
  // kept per logical block and updated in place instead.
  let openThinkingStep: RunStep | null = null;

  const ensureCurrent = (event: StreamEvent) => {
    if (current) return current;
    const eventRunId = event.run_id ??
      (typeof event.data?.run_id === "string" ? event.data.run_id : undefined);
    current = {
      id: `a-${runKey}-${out.length}-${event.timestamp}`,
      role: "assistant",
      agent: currentAgent,
      content: "",
      timestamp: event.timestamp,
      ...(eventRunId ? { runId: eventRunId } : {}),
      toolCalls: [],
      activities: [],
      steps: [],
    };
    out.push(current);
    return current;
  };

  const upsertActivity = (
    activity: NonNullable<ChatMessage["activities"]>[number],
  ) => {
    const message = ensureCurrent({ type: "progress", timestamp: activity.timestamp });
    message.activities = message.activities || [];
    const existing = message.activities.findIndex((item) => item.id === activity.id);
    if (existing >= 0) {
      const previous = message.activities[existing];
      message.activities[existing] = {
        ...previous,
        ...activity,
        detail: activity.detail ?? previous.detail,
      };
    } else {
      message.activities.push(activity);
    }
  };

  for (const e of ordered) {
    switch (e.type) {
      case "agent_started": {
        currentAgent = (e.agent ?? "CODER") as AgentName;
        const message = ensureCurrent(e);
        if (!message.agent || message.agent === "CODER") message.agent = currentAgent;
        upsertActivity(agentActivity(e, out.length, "running"));
        const previousStep = message.steps?.[message.steps.length - 1];
        if (!isDuplicateAgentAnnouncement(previousStep?.event, e)) {
          message.steps?.push({ ...stepOf(e), label: `${agentActor(e)} começou` });
        }
        break;
      }
      case "token": {
        if (e.content && e.content.startsWith("<event>thinking|iteration:")) {
          break;
        }
        // The first answer token ends the reasoning block.
        if (openThinkingStep) {
          sealStep(openThinkingStep, "success", Date.now());
          openThinkingStep = null;
        }
        ensureCurrent(e).content += e.content ?? "";
        break;
      }
      case "thinking": {
        const iterMatch = (e.content ?? "").match(/thinking\|iteration:(\d+)/);
        if (iterMatch) {
          const iteration = parseInt(iterMatch[1], 10);
          if (iteration <= lastThinkingIteration) {
            break;
          }
          lastThinkingIteration = iteration;
          // A new iteration is a new logical block: seal the previous one.
          if (openThinkingStep) {
            sealStep(openThinkingStep, "success", eventTimestamp(e));
            openThinkingStep = null;
          }
        }
        const message = ensureCurrent(e);
        const content = e.content ?? "";
        if (!content) break;
        const separator = message.thinking ? "\n" : "";
        message.thinking = (message.thinking ?? "") + separator + content;
        if (openThinkingStep && openThinkingStep.status === "running") {
          // Same block: one row, updated in place.
          openThinkingStep.repeatCount = (openThinkingStep.repeatCount ?? 0) + 1;
          openThinkingStep.event = e;
          if (e.data?.label) openThinkingStep.label = String(e.data.label);
        } else {
          const step = stepOf(e);
          step.repeatCount = 1;
          message.steps?.push(step);
          openThinkingStep = step;
        }
        break;
      }
      case "tool_call": {
        current = ensureCurrent(e);
        current.toolCalls = current.toolCalls || [];
        current.toolCalls.push({
          id: `tc-${current.toolCalls.length}-${e.timestamp}`,
          name: e.tool_name || "tool",
          args: e.tool_args || {},
          status: "running",
          timestamp: e.timestamp,
        });
        const previousStep = current.steps?.[current.steps.length - 1];
        if (previousStep?.verb === "tool" && previousStep.status === "running" && isSameToolCall(previousStep.event, e)) {
          previousStep.repeatCount = (previousStep.repeatCount ?? 1) + 1;
          previousStep.event = e;
        } else {
          current.steps?.push(stepOf(e));
        }
        break;
      }
      case "tool_result": {
        // The frame type is not the outcome: the backend answers a failed tool
        // on the `tool_result` channel too. Derive the status from the payload
        // so the row, the step and the header cannot disagree.
        const failed = toolResultReportsFailure(e.tool_result);
        const status: StepStatus = failed ? "error" : "success";
        const idx = findRunningTool(current?.toolCalls || [], e.tool_name);
        if (idx >= 0 && current) {
          current.toolCalls![idx].status = status;
          if (failed) {
            current.toolCalls![idx].error = describeToolResultFailure(e.tool_result);
          }
          current.toolCalls![idx].result = e.tool_result;
          const duration = e.data?.duration_ms;
          if (typeof duration === "number") current.toolCalls![idx].durationMs = duration;
        }
        closeStep(
          current?.steps || [],
          e.tool_name || "",
          status,
          e.tool_result,
          seqOf(e),
        );
        break;
      }
      case "tool_error": {
        const idx = findRunningTool(current?.toolCalls || [], e.tool_name);
        if (idx >= 0 && current) {
          current.toolCalls![idx].status = "error";
          current.toolCalls![idx].error = e.tool_error;
        }
        closeStep(
          current?.steps || [],
          e.tool_name || "",
          "error",
          e.tool_error,
          seqOf(e),
        );
        break;
      }
      case "tool_confirmation": {
        const idx = findRunningTool(current?.toolCalls || [], e.tool_name);
        if (idx >= 0 && current) {
          const confirmation = e.data ?? {};
          current.toolCalls![idx].status = "awaiting_confirmation";
          current.toolCalls![idx].confirmationId = String(confirmation.confirmation_id ?? "");
          current.toolCalls![idx].suggestion = String(confirmation.suggestion ?? "");
          current.toolCalls![idx].riskLevel = String(confirmation.risk_level ?? "medium");
        }
        current?.steps?.push({ ...stepOf(e), status: "awaiting_confirmation" });
        break;
      }
      case "progress": {
        // Heartbeats carry replay/order information, but are transport noise
        // for the user. Keep them in the ordered stream without adding a row
        // to the visible run timeline.
        if (e.data?.kind === "heartbeat") break;
        if (isCancellationFrame(e)) {
          // A cancellation is ONE fact about the run. `useAgentStream` records
          // the user's request locally the instant the button is pressed — the
          // reader is aborted before the server's `run_cancelled` frame can
          // arrive — so a frame that does arrive must not add a second
          // cancellation line to the same timeline.
          if ((current?.steps ?? []).some((step) => step.kind === "run_cancelled")) break;
          // Also the abort path's `closeDanglingWork`: without it every tool
          // call still in flight stayed "running" forever, spinning, because
          // `done`/`error` never arrive on a cancelled stream. Cancelled work
          // is closed as CANCELLED, never as a failure.
          closeDanglingWork(current, USER_CANCELLATION_REASON, "cancelled");
        }
        const activity = activityFromProgress(e, out.length);
        const progressMessage = ensureCurrent(e);
        if (e.run_id && !progressMessage.runId) progressMessage.runId = e.run_id;
        upsertActivity(activity);
        if (typeof e.data?.phase === "string") lastPhase = displayPhase(e.data.phase);
        if (typeof e.data?.elapsed === "number" && Number.isFinite(e.data.elapsed)) {
          elapsedMs = Math.max(0, e.data.elapsed * 1000);
        }
        if (e.data?.telemetry && typeof e.data.telemetry === "object") {
          telemetry = {
            ...(telemetry ?? {}),
            ...(e.data.telemetry as Record<string, unknown>),
          };
        }
        const step = stepOf(e);
        step.status = activity.status;
        current?.steps?.push(step);
        break;
      }
      case "metric": {
        current = ensureCurrent(e);
        const data = e.data ?? {};
        const eventKind = String(data.kind ?? data.runtime_type ?? "");
        if (eventKind === "run_completed") {
          const agent = e.agent ?? currentAgent;
          const completedEvent = { ...e, agent };
          upsertActivity(agentActivity(completedEvent, out.length, "success"));
          closeAgentStep(current, completedEvent);
          if (typeof data.duration === "number" && Number.isFinite(data.duration)) {
            elapsedMs = Math.max(0, data.duration * 1000);
          }
          lastPhase = "concluída";
          if (data.telemetry && typeof data.telemetry === "object") {
            telemetry = {
              ...(telemetry ?? {}),
              ...(data.telemetry as Record<string, unknown>),
            };
          }
          const verification = data.verification;
          if (verification && typeof verification === "object") {
            const result = verification as Record<string, unknown>;
            const ran = result.ran !== false;
            const passed = result.ok === true;
            const status: StepStatus = !ran ? "pending" : passed ? "success" : "error";
            const activity = {
              id: `verification-${e.run_id ?? seqOf(e)}`,
              kind: "verification" as const,
              title: !ran
                ? "Verificação não executada"
                : passed
                  ? "Verificação aprovada"
                  : "Verificação falhou",
              detail: typeof result.summary === "string" ? result.summary : undefined,
              status,
              timestamp: e.timestamp,
              data: {
                ran,
                ok: typeof result.ok === "boolean" ? result.ok : undefined,
                command: typeof result.command === "string" ? result.command : undefined,
              },
            };
            const existingIndex = (current.activities ?? []).findLastIndex(
              (item) => item.kind === "verification",
            );
            if (existingIndex >= 0 && current.activities) {
              current.activities[existingIndex] = {
                ...current.activities[existingIndex],
                ...activity,
              };
            } else {
              current.activities?.push(activity);
            }
          }
          if (Array.isArray(data.changed_files)) {
            const changedFiles = data.changed_files.filter(
              (path): path is string => typeof path === "string" && path.trim().length > 0,
            );
            if (changedFiles.length > 0) {
              current.metadata = {
                ...(current.metadata ?? {}),
                changedFiles: Array.from(new Set(changedFiles.map((path) => path.trim()))),
              };
            }
          }
        } else if (eventKind === "test_result") {
          const ran = e.data?.ran !== false;
          const passed = e.data?.ok === true;
          const status: StepStatus = !ran ? "pending" : passed ? "success" : "error";
          closeStepByVerb(current.steps ?? [], "test", status, e.data, seqOf(e));
          const verification = [...(current.activities ?? [])]
            .reverse()
            .find((item) => item.kind === "verification" && item.status === "running");
          if (verification) {
            verification.status = status === "pending" ? "pending" : status;
            verification.detail = e.content || String(e.data?.summary || "");
          }
        }
        const usage = e.data?.usage;
        if (usage && typeof usage === "object") {
          const u = usage as Record<string, unknown>;
          current.metrics = {
            Input: String(u.input_tokens ?? 0),
            Output: String(u.output_tokens ?? 0),
            Raciocínio: String(u.reasoning_tokens ?? 0),
            Total: String(u.total_tokens ?? 0),
          };
          telemetry = { ...(telemetry ?? {}), ...u };
        }
        break;
      }
      case "error": {
        const runtimeType = String(e.data?.runtime_type ?? e.data?.kind ?? "").toLowerCase();
        const outcome = runtimeType === "run_interrupted" ? "interrupted" : "failed";
        closeDanglingWork(
          current,
          e.content || "A execução terminou antes de receber o resultado desta ação.",
        );
        // An interrupted run is neither a failure nor a cancellation, and the
        // error bubble below says so — but the bubble is a DIFFERENT message
        // from the one carrying the timeline, whose header had no way to tell
        // it apart from a clean run. Record the outcome on the run itself, as
        // a warning, so the header can report it. Pushed after
        // `closeDanglingWork` so it is not sealed along with the dangling work.
        if (outcome === "interrupted" && current) {
          current.steps?.push({
            ...stepOf(e),
            kind: "run_interrupted",
            status: "warning",
          });
        }
        out.push({
          id: `err-${runKey}-${out.length}-${e.timestamp}`,
          role: "assistant",
          agent: "CODER",
          content: `⚠ ${e.content || "Erro desconhecido (sem mensagem do servidor)"}`,
          timestamp: e.timestamp,
          ...(e.run_id ? { runId: e.run_id } : {}),
          metadata: {
            kind: "error",
            outcome,
            canRetry: true,
            prompt: lastUserMessage,
          },
        });
        current = null;
        break;
      }
      case "routing":
        // Bookend: triage decision. Ignored as a step; kept for diagnostics.
        if (typeof e.data?.phase === "string") lastPhase = displayPhase(e.data.phase);
        break;
      case "agent_finished": {
        const rawStatus = String(e.data?.status ?? "completed").toLowerCase();
        const completionStatus: StepStatus =
          ["failed", "error"].includes(rawStatus)
            ? "error"
            : ["cancelled", "canceled"].includes(rawStatus)
              ? "cancelled"
              : ["blocked", "paused", "waiting"].includes(rawStatus)
                ? "paused"
                : rawStatus === "warning"
                  ? "warning"
                  : "success";
        upsertActivity(agentActivity(e, out.length, completionStatus));
        if (current && !closeAgentStep(current, e, completionStatus)) {
          current.steps?.push({
            ...stepOf(e),
            status: completionStatus,
            label:
              completionStatus === "success"
                ? `${e.agent ?? "Agente"} concluiu`
                : completionStatus === "error"
                  ? `${e.agent ?? "Agente"} terminou com erro`
                  : completionStatus === "cancelled"
                    ? `${e.agent ?? "Agente"} foi cancelado`
                    : completionStatus === "paused"
                      ? `${e.agent ?? "Agente"} ficou em pausa`
                      : `${e.agent ?? "Agente"} terminou com aviso`,
          });
        }
        break;
      }
      case "done": {
        if (typeof e.data?.elapsed === "number") elapsedMs = e.data.elapsed * 1000;
        if (e.data?.telemetry && typeof e.data.telemetry === "object") {
          telemetry = { ...(telemetry ?? {}), ...(e.data.telemetry as Record<string, unknown>) };
        }
        closeDanglingWork(
          current,
          "A execução terminou antes de chegar o resultado desta ferramenta.",
        );
        current = null;
        break;
      }

      // Mission Control progress events — surface as status steps + activities.
      case "mission_brief":
      case "mission_plan":
      case "mission_wave":
      case "mission_agent":
      case "mission_decision":
      case "mission_verification":
      case "mission_completed": {
        upsertActivity(activityFromMissionEvent(e, out.length));
        current?.steps?.push(stepOf(e));
        break;
      }
      default:
        break;
    }
    // Anything other than a reasoning frame ends the current reasoning block.
    // The step itself is sealed by the case that consumed the transition
    // (token, a new iteration, done) or by closeDanglingWork below.
    if (e.type !== "thinking") openThinkingStep = null;
  }

  // Post-process: strip transport syntax from the rendered answer.
  //
  // ``extractThinking`` used to run here as well, but it was unreachable dead
  // code: `sanitizeAssistantContent` already removes ``<think>`` tags, so the
  // answer can no longer contain a block to extract. Reasoning reaches
  // `message.thinking` only through a real `thinking` SSE frame, above.
  for (const m of out) {
    if (m.content) {
      m.content = sanitizeAssistantContent(stripAnsiCodes(m.content));
    }
  }

  // Capture the live footer on the last assistant message.
  if (telemetry !== undefined || elapsedMs !== undefined || lastPhase) {
    const lastAssistant = [...out].reverse().find((m) => m.role === "assistant");
    if (lastAssistant) {
      lastAssistant.metadata = {
        ...(lastAssistant.metadata ?? {}),
        footer: {
          phase: lastPhase || undefined,
          elapsedMs,
          telemetry,
        },
      };
    }
  }

  return { messages: out, lastUserMessage };
}

/**
 * Seal the work that never reported back before the stream ended.
 *
 * `outcome` is what actually happened, because the caller knows it: a stream
 * that ended on its own leaves holes that ARE failures, while a run the user
 * stopped leaves holes that are not. Marking the second case as an error would
 * repaint a cancellation as a failure, which is the lie this argument removes.
 */
function closeDanglingWork(
  message: ChatMessage | null,
  reason: string,
  outcome: "error" | "cancelled" = "error",
): void {
  if (!message) return;
  const cancelled = outcome === "cancelled";
  for (const call of message.toolCalls ?? []) {
    if (call.status === "running") {
      // `ToolCallItem` has no `cancelled` state, and one must not be invented:
      // a tool call that never reported a result is NOT a success, so it can
      // only be `error` — with a `reason` that says it was the cancellation.
      call.status = "error";
      call.error = reason;
    }
  }
  for (const step of message.steps ?? []) {
    if (step.status !== "running") continue;
    // A reasoning block (or a status note) that never received its closing
    // frame is not a failure: the run completed, the model simply stopped
    // thinking. Marking it as an error painted a red X on every successful run
    // that reasoned first. Real work — tools, tests, files, commands — still
    // becomes an error so the user can see what never reported back.
    if (!cancelled && (step.verb === "thinking" || step.verb === "status" || step.verb === "message")) {
      sealStep(step, "success", Date.now());
      continue;
    }
    sealStep(step, outcome, Date.now());
    step.detail = step.detail ?? reason;
  }
  for (const activity of message.activities ?? []) {
    if (activity.status === "running") {
      activity.status = outcome;
      activity.detail = activity.detail ?? reason;
    }
  }
}

interface RunEventGroup {
  key: string;
  events: StreamEvent[];
  closed: boolean;
}

function normalizeRunEnvelope(event: StreamEvent): StreamEvent {
  const data = event.data ?? {};
  const runId = event.run_id ?? (typeof data.run_id === "string" ? data.run_id : undefined);
  const seq = event.seq ?? (typeof data.seq === "number" ? data.seq : undefined);
  const eventId = event.event_id ?? (typeof data.event_id === "string" ? data.event_id : undefined);
  return {
    ...event,
    ...(runId ? { run_id: runId } : {}),
    ...(seq !== undefined ? { seq } : {}),
    ...(eventId ? { event_id: eventId } : {}),
  };
}

function groupRunEvents(events: StreamEvent[]): RunEventGroup[] {
  const groups: RunEventGroup[] = [];
  const byRunId = new Map<string, RunEventGroup>();
  let active: RunEventGroup | null = null;
  let legacyIndex = 0;

  for (const rawEvent of events) {
    const event = normalizeRunEnvelope(rawEvent);
    const runId = event.run_id;
    if (runId) {
      let group = byRunId.get(runId);
      if (!group) {
        group = { key: runId, events: [], closed: false };
        byRunId.set(runId, group);
        groups.push(group);
      }
      group.events.push(event);
      group.closed = event.type === "done";
      active = group.closed ? null : group;
      continue;
    }

    if (!active || active.closed) {
      active = { key: `legacy-${legacyIndex++}`, events: [], closed: false };
      groups.push(active);
    }
    active.events.push(event);
    if (event.type === "done") {
      active.closed = true;
      active = null;
    }
  }

  return groups;
}

/**
 * Fold an accumulated session stream one run at a time. `useAgentStream`
 * retains earlier turns, while `RunEventBuffer` deliberately accepts only
 * one run id; grouping here preserves both complete turns and their order.
 */
export function foldRun(
  pendingUser: ChatMessage[],
  events: StreamEvent[],
  lastUserMessage = "",
): FoldRunResult {
  const groups = groupRunEvents(events);
  if (groups.length === 0) return { messages: [...pendingUser], lastUserMessage };

  const messages: ChatMessage[] = [];
  let userIndex = 0;
  for (const group of groups) {
    const user = pendingUser[userIndex];
    if (user) userIndex += 1;
    const result = foldSingleRun(
      user ? [user] : [],
      group.events,
      user?.content ?? lastUserMessage,
      group.key,
    );
    messages.push(...result.messages);
  }
  messages.push(...pendingUser.slice(userIndex));
  return { messages, lastUserMessage };
}

/**
 * Editorial summary for the collapsed RunTimeline header:
 * “◉ Trabalhou 2m14s · 17 ações · 3 agentes · 2 erros”.
 * Pure derivation — Activity (timeline) stays separate from Result (markdown).
 */
export interface RunEditorialSummary {
  actions: number;
  agents: number;
  agentNames: string[];
  elapsedMs?: number;
  /** Steps / tool calls / activities reporting a failure (max, to avoid double count). */
  errors: number;
}

export function summarizeRunForHeader(message: ChatMessage): RunEditorialSummary {
  const steps = message.steps ?? [];
  const tools = message.toolCalls ?? [];
  const activities = message.activities ?? [];
  const thinking = message.thinking?.trim() ? 1 : 0;
  const actions = steps.length > 0
    ? steps.length
    : tools.length + activities.length + thinking;
  const names = new Set<string>();
  for (const step of steps) {
    if (typeof step.agent === "string" && step.agent.trim()) names.add(step.agent.trim());
  }
  for (const activity of activities) {
    if (activity.agent?.trim()) names.add(activity.agent.trim());
  }
  if (message.agent?.trim()) names.add(message.agent.trim());
  const stepErrors = steps.filter((step) => step.status === "error").length;
  const toolErrors = tools.filter((call) => call.status === "error").length;
  // A `warning` activity is a failure too. `sessionRecovery` injects one —
  // "Execução interrompida", `status:"warning"` — for a run the backend
  // recorded as interrupted, and counting only `error` left the header green
  // directly above a panel saying the run was interrupted.
  const activityErrors = activities.filter((item) => isFailingActivityStatus(item.status)).length;
  const errors = Math.max(stepErrors, toolErrors, activityErrors);
  const footer = message.metadata?.footer as { elapsedMs?: number } | undefined;
  const elapsedMs = typeof footer?.elapsedMs === "number"
    ? footer.elapsedMs
    : (() => {
        const durations = steps
          .map((step) => step.durationMs)
          .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
        if (durations.length === 0) return undefined;
        const starts = steps
          .map((step) => step.startedAt)
          .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
        if (starts.length >= 2) {
          const span = Math.max(...starts) - Math.min(...starts);
          if (Number.isFinite(span) && span > 0) return span;
        }
        return durations.reduce((acc, value) => acc + value, 0) || undefined;
      })();
  return { actions, agents: names.size, agentNames: Array.from(names).slice(0, 6), elapsedMs, errors };
}

export { agentColor, agentSeed, AGENT_DEFAULT, AGENT_COLORS };
