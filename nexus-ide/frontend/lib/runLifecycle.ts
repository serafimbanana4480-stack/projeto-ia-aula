/**
 * One view of a run, adapted from the SSE frames the backend already emits.
 *
 * The wire contract stays `StreamEvent` (`token`, `tool_call`, `done`, …).
 * This module only names those frames the way the UI talks about a run
 * (`message.delta`, `tool.started`, `run.completed`) so chat, tools and the
 * agent tree share one interpretation. It does not open a second stream.
 */
import type { ChatMessage, StreamEvent, ToolCallItem } from "./types";

export type RunLifecycleType =
  | "run.started"
  | "message.delta"
  | "agent.spawned"
  | "agent.updated"
  | "tool.started"
  | "tool.completed"
  | "tool.failed"
  | "tool.waiting"
  | "run.completed"
  | "run.failed"
  | "run.cancelled";

export interface RunLifecycleEvent {
  id: string;
  type: RunLifecycleType;
  runId: string;
  seq: number;
  agentId?: string;
  taskId?: string;
  ts: string;
  payload: Record<string, unknown>;
}

export type AgentRunState =
  | "QUEUED"
  | "RUNNING"
  | "WAITING"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED";

export interface AgentNode {
  id: string;
  name: string;
  parentId?: string;
  state: AgentRunState;
  task?: string;
  model?: string;
  tools: string[];
  files: string[];
  error?: string;
  startedAt?: string;
  endedAt?: string;
  durationMs?: number;
}

const TOOL_KIND: Record<string, string> = {
  read_file: "ficheiro",
  read_file_absolute: "ficheiro",
  write_file: "ficheiro",
  write_file_absolute: "ficheiro",
  list_dir: "ficheiro",
  search_codebase: "pesquisa",
  web_search: "pesquisa",
  fetch_url: "browser",
  execute_terminal: "terminal",
  execute_shell: "terminal",
  run_shell: "terminal",
  execute_code: "código",
  git_status: "git",
  git_diff: "git",
  git_commit: "git",
  git_clone: "git",
};

export function toolKind(name: string): string {
  if (TOOL_KIND[name]) return TOOL_KIND[name];
  if (/git/i.test(name)) return "git";
  if (/test|pytest|vitest/i.test(name)) return "testes";
  if (/search|grep|find/i.test(name)) return "pesquisa";
  if (/http|fetch|browser|url/i.test(name)) return "browser";
  if (/shell|terminal|bash|exec/i.test(name)) return "terminal";
  if (/read|write|file|diff/i.test(name)) return "ficheiro";
  return "tool";
}

export function toolAction(name: string, args: Record<string, unknown> | undefined): string {
  const record = args ?? {};
  const path = firstString(record, ["path", "file", "file_path", "target", "url"]);
  const command = firstString(record, ["command", "cmd", "code", "query"]);
  if (path) return path;
  if (command) return command.length > 96 ? `${command.slice(0, 96)}…` : command;
  return name.replace(/_/g, " ");
}

export function toLifecycle(event: StreamEvent, index: number): RunLifecycleEvent | null {
  const runId = event.run_id || "legacy";
  const seq = typeof event.seq === "number" && Number.isFinite(event.seq) ? event.seq : index + 1;
  const id = event.event_id || `${runId}:${seq}:${event.type}:${index}`;
  const base = {
    id,
    runId,
    seq,
    agentId: event.agent,
    taskId: event.task_id,
    ts: event.timestamp,
    payload: { ...(event.data ?? {}) },
  };

  switch (event.type) {
    case "routing":
      return { ...base, type: "run.started", payload: { ...base.payload, agent: event.agent } };
    case "agent_started":
      return {
        ...base,
        type: "agent.spawned",
        payload: {
          ...base.payload,
          agent: event.agent,
          ...(event.content ? { task: event.content } : {}),
        },
      };
    case "agent_finished":
      return { ...base, type: "agent.updated", payload: { ...base.payload, agent: event.agent, state: "COMPLETED" } };
    case "token":
      return { ...base, type: "message.delta", payload: { text: event.content ?? "" } };
    case "tool_call":
      return {
        ...base,
        type: "tool.started",
        payload: { name: event.tool_name, args: event.tool_args ?? {} },
      };
    case "tool_result":
      return {
        ...base,
        type: "tool.completed",
        payload: { name: event.tool_name, result: event.tool_result, duration_ms: event.data?.duration_ms },
      };
    case "tool_error":
      return { ...base, type: "tool.failed", payload: { name: event.tool_name, error: event.tool_error } };
    case "tool_confirmation":
      return { ...base, type: "tool.waiting", payload: { name: event.tool_name, ...(event.data ?? {}) } };
    case "error":
      return { ...base, type: "run.failed", payload: { message: event.content ?? "" } };
    case "done": {
      const cancelled = event.data?.cancelled === true || event.data?.status === "cancelled";
      return { ...base, type: cancelled ? "run.cancelled" : "run.completed", payload: { ...(event.data ?? {}) } };
    }
    default:
      return null;
  }
}

export function deriveAgents(events: StreamEvent[]): AgentNode[] {
  const nodes = new Map<string, AgentNode>();
  let lastId: string | undefined;

  const ensure = (id: string, name: string, ts: string, parentId?: string): AgentNode => {
    const existing = nodes.get(id);
    if (existing) return existing;
    const node: AgentNode = {
      id,
      name: name || "Agente",
      parentId,
      state: "RUNNING",
      tools: [],
      files: [],
      startedAt: ts,
    };
    nodes.set(id, node);
    return node;
  };

  events.forEach((event, index) => {
    const life = toLifecycle(event, index);
    if (!life) return;
    if (life.type === "agent.spawned") {
      const name = String(life.payload.agent || life.agentId || "Agente");
      const explicitParent = stringOrEmpty(life.payload.parent_id) || stringOrEmpty(life.payload.parent_task_id);
      const id = life.taskId || `${life.runId}:${name}:${life.seq}`;
      const parentId = explicitParent || (life.payload.delegated ? lastId : undefined);
      const node = ensure(id, name, life.ts, parentId);
      node.state = stateFromPayload(life.payload.state) ?? "RUNNING";
      const task = stringOrEmpty(life.payload.task) || stringOrEmpty(life.payload.objective);
      if (task) node.task = task;
      const model = stringOrEmpty(life.payload.model);
      if (model) node.model = model;
      lastId = id;
      return;
    }
    const target = findNode(nodes, life.taskId, life.agentId) ?? (lastId ? nodes.get(lastId) : undefined);
    if (!target) return;
    if (life.type === "agent.updated") {
      target.state = stateFromPayload(life.payload.state) ?? "COMPLETED";
      target.endedAt = life.ts;
      target.durationMs = durationBetween(target.startedAt, life.ts);
    } else if (life.type === "tool.started") {
      const name = String(life.payload.name || "tool");
      target.tools.push(name);
      const path = firstString((life.payload.args as Record<string, unknown>) ?? {}, ["path", "file", "file_path"]);
      if (path) target.files.push(path);
      if (target.state === "QUEUED") target.state = "RUNNING";
    } else if (life.type === "tool.waiting") {
      target.state = "WAITING";
    } else if (life.type === "tool.failed") {
      target.state = "FAILED";
      target.error = String(life.payload.error || "A ferramenta falhou");
      target.endedAt = life.ts;
    } else if (life.type === "run.failed") {
      finishOpenNodes(nodes, "FAILED", life.ts, String(life.payload.message || "A execução falhou"));
    } else if (life.type === "run.cancelled") {
      finishOpenNodes(nodes, "CANCELLED", life.ts);
    } else if (life.type === "run.completed") {
      finishOpenNodes(nodes, "COMPLETED", life.ts, undefined, ["RUNNING", "QUEUED"]);
    }
  });

  return [...nodes.values()];
}

export interface ExecutionSnapshot {
  goal: string;
  plan: string[];
  steps: Array<{ label: string; status: string }>;
  blockers: string[];
  artifacts: string[];
}

export function deriveExecution(goal: string, messages: ChatMessage[]): ExecutionSnapshot {
  const lastAssistant = [...messages].reverse().find((message) => message.role === "assistant");
  const plan = (lastAssistant?.activities ?? [])
    .filter((item) => item.kind === "plan" || item.kind === "task")
    .map((item) => item.title)
    .filter(Boolean);
  const steps = (lastAssistant?.steps ?? []).map((step) => ({
    label: step.label || step.target || step.kind,
    status: step.status,
  }));
  const blockers = [
    ...(lastAssistant?.toolCalls ?? [])
      .filter((call) => call.status === "error" || call.status === "cancelled")
      .map((call) => call.error || call.name),
    ...messages
      .filter((message) => message.metadata?.kind === "error")
      .map((message) => message.content),
  ].filter(Boolean);
  const artifacts = unique(
    (lastAssistant?.toolCalls ?? []).flatMap((call) => filesFromCall(call)),
  );
  return { goal, plan, steps, blockers, artifacts };
}

export function filesFromCall(call: ToolCallItem): string[] {
  const args = call.args ?? {};
  const path = firstString(args, ["path", "file", "file_path", "target"]);
  return path ? [path] : [];
}

export function terminalFields(result: unknown): {
  stdout: string;
  stderr: string;
  exitCode: number | null;
  cwd: string;
} | null {
  if (!result || typeof result !== "object") return null;
  const record = result as Record<string, unknown>;
  const stdout = typeof record.stdout === "string" ? record.stdout : "";
  const stderr = typeof record.stderr === "string" ? record.stderr : "";
  const hasStreams = "stdout" in record || "stderr" in record || "exit_code" in record;
  if (!hasStreams) return null;
  const exitRaw = record.exit_code ?? record.exitCode;
  const exitCode = typeof exitRaw === "number" ? exitRaw : null;
  const cwd = typeof record.cwd === "string" ? record.cwd : "";
  return { stdout, stderr, exitCode, cwd };
}

export function looksLikeDiff(value: string): boolean {
  return value.startsWith("diff ") || value.includes("\n@@") || value.startsWith("--- ") || value.startsWith("+++ ");
}

function finishOpenNodes(
  nodes: Map<string, AgentNode>,
  state: AgentRunState,
  ts: string,
  error?: string,
  open: AgentRunState[] = ["RUNNING", "WAITING", "QUEUED"],
): void {
  for (const node of nodes.values()) {
    if (!open.includes(node.state)) continue;
    node.state = state;
    node.endedAt = ts;
    node.durationMs = durationBetween(node.startedAt, ts);
    if (error) node.error = error;
  }
}

function findNode(
  nodes: Map<string, AgentNode>,
  taskId: string | undefined,
  agentId: string | undefined,
): AgentNode | undefined {
  if (taskId && nodes.has(taskId)) return nodes.get(taskId);
  if (!agentId) return undefined;
  for (const node of nodes.values()) {
    if (node.name === agentId && (node.state === "RUNNING" || node.state === "WAITING")) return node;
  }
  return undefined;
}

function stateFromPayload(value: unknown): AgentRunState | undefined {
  const text = String(value ?? "").toUpperCase();
  if (text === "QUEUED" || text === "PENDING") return "QUEUED";
  if (text === "RUNNING") return "RUNNING";
  if (text === "WAITING") return "WAITING";
  if (text === "COMPLETED" || text === "SUCCESS") return "COMPLETED";
  if (text === "FAILED" || text === "ERROR") return "FAILED";
  if (text === "CANCELLED" || text === "CANCELED") return "CANCELLED";
  return undefined;
}

function durationBetween(start?: string, end?: string): number | undefined {
  if (!start || !end) return undefined;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  return Number.isFinite(ms) && ms >= 0 ? ms : undefined;
}

function firstString(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function stringOrEmpty(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}
