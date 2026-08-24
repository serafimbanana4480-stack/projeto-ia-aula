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

function seqOf(event: StreamEvent): number {
  if (typeof event.seq === "number" && Number.isFinite(event.seq)) return event.seq;
  // Legacy frames expose seq only through the runtime envelope in `data`.
  const ds = event.data;
  if (ds && typeof ds.seq === "number" && Number.isFinite(ds.seq)) return ds.seq;
  // Fallback: preserve arrival order with a monotonically increasing value so
  // legacy steps still sort deterministically after the ordered ones.
  return -(event.data ? 1 : 0);
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
    detail: data,
    event,
  };
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
): void {
  for (let i = steps.length - 1; i >= 0; i -= 1) {
    const step = steps[i];
    if (
      step.verb === "tool" &&
      (step.status === "running" || step.status === "awaiting_confirmation") &&
      step.target === target
    ) {
      step.status = status;
      if (detail !== undefined) {
        const base = (step.detail as Record<string, unknown>) ?? {};
        step.detail = { ...base, result: detail, resultSeq };
      }
      return;
    }
  }
}

function extractThinking(text: string): { content: string; thinking?: string } {
  const thinkingParts: string[] = [];
  const cleaned = text.replace(/<thinking>([\s\S]*?)<\/thinking>/g, (_, inner) => {
    thinkingParts.push(inner.trim());
    return "";
  });
  return {
    content: cleaned.trim(),
    thinking: thinkingParts.length > 0 ? thinkingParts.join("\n\n---\n\n") : undefined,
  };
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

export function foldRun(
  pendingUser: ChatMessage[],
  events: StreamEvent[],
  lastUserMessage = "",
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

  const ensureCurrent = (event: StreamEvent) => {
    if (current) return current;
    current = {
      id: `a-${out.length}-${event.timestamp}`,
      role: "assistant",
      agent: currentAgent,
      content: "",
      timestamp: event.timestamp,
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
        message.steps?.push({ ...stepOf(e), label: `${e.agent ?? "IA"} começou` });
        break;
      }
      case "token": {
        if (e.content && e.content.startsWith("<event>thinking|iteration:")) {
          break;
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
        }
        const message = ensureCurrent(e);
        const separator = message.thinking && e.content ? "\n" : "";
        message.thinking = (message.thinking ?? "") + separator + (e.content ?? "");
        message.steps?.push(stepOf(e));
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
        current.steps?.push(stepOf(e));
        break;
      }
      case "tool_result": {
        const idx = findRunningTool(current?.toolCalls || [], e.tool_name);
        if (idx >= 0 && current) {
          current.toolCalls![idx].status = "success";
          current.toolCalls![idx].result = e.tool_result;
          const duration = e.data?.duration_ms;
          if (typeof duration === "number") current.toolCalls![idx].durationMs = duration;
        }
        closeStep(
          current?.steps || [],
          e.tool_name || "",
          "success",
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
        const activity = activityFromProgress(e, out.length);
        upsertActivity(activity);
        if (typeof e.data?.phase === "string") lastPhase = e.data.phase;
        current?.steps?.push(stepOf(e));
        break;
      }
      case "metric": {
        current = ensureCurrent(e);
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
        out.push({
          id: `err-${out.length}-${e.timestamp}`,
          role: "assistant",
          agent: "CODER",
          content: `⚠ ${e.content || "Erro desconhecido (sem mensagem do servidor)"}`,
          timestamp: e.timestamp,
          metadata: { kind: "error", canRetry: true, prompt: lastUserMessage },
        });
        current = null;
        break;
      }
      case "routing":
        // Bookend: triage decision. Ignored as a step; kept for diagnostics.
        if (typeof e.data?.phase === "string") lastPhase = e.data.phase;
        break;
      case "agent_finished": {
        upsertActivity(agentActivity(e, out.length, "success"));
        current?.steps?.push({ ...stepOf(e), status: "success", label: `${e.agent ?? "Agente"} concluiu` });
        break;
      }
      case "done": {
        if (typeof e.data?.elapsed === "number") elapsedMs = e.data.elapsed * 1000;
        if (e.data?.telemetry && typeof e.data.telemetry === "object") {
          telemetry = { ...(telemetry ?? {}), ...(e.data.telemetry as Record<string, unknown>) };
        }
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
  }

  // Post-process: split <thinking> out of rendered content (mirrors the
  // historical behaviour so history + streaming stay consistent).
  for (const m of out) {
    if (m.content) {
      m.content = sanitizeAssistantContent(stripAnsiCodes(m.content));
      const { content, thinking } = extractThinking(m.content);
      m.content = content;
      if (thinking) m.thinking = thinking;
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

export { agentColor, agentSeed, AGENT_DEFAULT, AGENT_COLORS };
