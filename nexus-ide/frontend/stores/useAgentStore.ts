"use client";

import { create } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import { apiUrl, authHeaders } from "../lib/api";

export type AgentStatus =
  | "idle"
  | "thinking"
  | "planning"
  | "executing"
  | "tool_call"
  | "waiting"
  | "blocked"
  | "failed"
  | "autonomous_loop"
  | "learning"
  | "syncing_memory";

export interface AgentTool {
  name: string;
  description: string;
  status: "available" | "running" | "error";
}

export interface ReasoningStep {
  id: string;
  type: "thought" | "plan" | "reflection" | "criticism" | "tool_use" | "memory_lookup" | "validation";
  content: string;
  timestamp: number;
  tokens?: number;
  confidence?: number;
  citations?: string[];
}

export interface AgentMessage {
  id: string;
  fromAgent: string;
  toAgent: string;
  content: string;
  timestamp: number;
  type: "message" | "delegation" | "result" | "error" | "help_request";
  attachments?: string[];
  confidence?: number;
  inReplyTo?: string;
}

export interface Agent {
  id: string;
  name: string;
  role: string;
  agentId?: string;
  specialization: string;
  model: string;
  provider: string;
  status: AgentStatus | string;
  currentTask?: string;
  task?: string;
  tokensUsed?: number;
  tokenBudget?: number;
  memoryUsed: number;
  memory?: number;
  tools: AgentTool[];
  costAccumulated: number;
  speed: number;
  tokensPerSecond?: number;
  reasoningDepth?: number;
  accuracy: number;
  contextWindow: number;
  contextUsed: number;
  subTaskQueue: string[];
  healthStatus: "healthy" | "degraded" | "critical" | "unknown";
  reasoningHistory: ReasoningStep[];
  lastSeen: number;
  uptime: number;
  totalTasks: number;
  successfulTasks: number;
  failedTasks: number;
  avgLatencyMs: number;
  chainOfThought: string;
  autonomyLevel: number;
  connections: string[];
  color: string;
  cpu?: number;
  confidence?: number;
}

interface AgentStore {
  agents: Record<string, Agent>;
  /**
   * Per-agent live reasoning steps, keyed by agent id.
   *
   * READ by two live components, WRITTEN by nothing in production:
   *   - `components/nexus/widgets/LiveReasoningStream.tsx` (dynamically
   *     imported by `app/nexus/page.tsx`)
   *   - `app/nexus/agents/[agentId]/page.tsx` ("Live Chain of Thought")
   * so both permanently render their empty state.
   *
   * NOT WIRED ON PURPOSE (audit 2026-09-26). The obvious candidate producer is
   * the chat lane's reasoning text (`StreamEvent` frames of type `thinking`,
   * folded by `lib/foldRun.ts` into `ChatMessage.thinking`). Wiring it here
   * would be dishonest rather than merely unfinished, for two reasons:
   *
   *  1. `ChatMessage.thinking` is one coalesced blob per assistant turn. It is
   *     not a per-agent step list, and splitting it would require a
   *     segmentation heuristic that invents the boundaries it claims to show.
   *  2. the id spaces do not match. `activeStream` is keyed by the agent ids
   *     from `GET /api/agents/instances` (the nexus agent registry), while the
   *     chat stream's `StreamEvent.agent` is a free-form label from the
   *     orchestrator. Mapping one to the other would misattribute reasoning to
   *     whichever agent happened to share a name.
   *
   * To wire it honestly, one of these has to be true first:
   *   (a) the backend emits an ordered, per-agent reasoning step stream that
   *       carries the nexus agent id — the same shape
   *       `backend/runtime/events.py` already uses for `(run_id, seq)`; or
   *   (b) `GET /api/agents/instances` starts returning the live run's steps,
   *       so `fetchAgents` can populate this map.
   *
   * Until then `addReasoningStep` / `clearReasoning` are covered by
   * `tests/stores/useAgentStore.test.ts` but have no production caller.
   */
  activeStream: Record<string, ReasoningStep[]>;
  messages: AgentMessage[];
  isLoading: boolean;
  hasFetchedAgents: boolean;
  error: string | null;

  setAgent: (agent: Agent) => void;
  updateAgent: (id: string, patch: Partial<Agent>) => void;
  removeAgent: (id: string) => void;
  /** See the `activeStream` doc comment: no production caller yet. */
  addReasoningStep: (agentId: string, step: ReasoningStep) => void;
  /** See the `activeStream` doc comment: no production caller yet. */
  clearReasoning: (agentId: string) => void;
  addMessage: (msg: AgentMessage) => void;
  setAgents: (agents: Agent[]) => void;
  fetchAgents: () => Promise<void>;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

const AGENT_COLORS: Record<string, string> = {
  ROUTER: "#7c3aed", ARCHITECT: "#06b6d4", RESEARCHER: "#f59e0b",
  CODER: "#10b981", ANALYZER: "#3b82f6", DEBUGGER: "#ef4444",
  DOCUMENTER: "#ec4899", OPTIMIZER: "#f97316",
};

/**
 * Loose shape of the agent objects the backend emits.
 *
 * The API has drifted over time (camelCase and snake_case in the same
 * payload, and `/api/agents/instances` is still `any[]` at the fetch site),
 * so every field is optional and read defensively. Typing it — rather than
 * taking `any` — is what makes a *misspelled* field a compile error instead
 * of a silent `undefined` that `?? 0` would swallow.
 */
interface ApiAgentLike {
  id?: string;
  instance_id?: string;
  agentId?: string;
  agent_id?: string;
  name?: string;
  agent_type?: string;
  role?: string;
  specialization?: string;
  model?: string;
  provider?: string;
  status?: string;
  currentTask?: string;
  current_task?: string;
  task?: string;
  objective?: string;
  tokensUsed?: number;
  tokens_used?: number;
  tokenBudget?: number;
  token_budget?: number;
  memoryUsed?: number;
  memory?: number;
  tools?: Array<{ name?: string; description?: string; status?: string }>;
  costAccumulated?: number;
  speed?: number;
  tokensPerSecond?: number;
  reasoningDepth?: number;
  accuracy?: number;
  contextWindow?: number;
  contextUsed?: number;
  subTaskQueue?: string[];
  healthStatus?: string;
  health_status?: string;
  reasoningHistory?: Array<Partial<ReasoningStep> & { id?: string }>;
  lastSeen?: number;
  start_time?: number;
  uptime?: number;
  totalTasks?: number;
  successfulTasks?: number;
  failedTasks?: number;
  avgLatencyMs?: number;
  chainOfThought?: string;
  autonomyLevel?: number;
  connections?: string[];
  cpu?: number;
  confidence?: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function firstString(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function firstFiniteNumber(...values: unknown[]): number | undefined {
  for (const value of values) {
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}

const TOOL_STATUSES: readonly string[] = ["available", "running", "error"];
const REASONING_STEP_TYPES: readonly string[] = [
  "thought",
  "plan",
  "reflection",
  "criticism",
  "tool_use",
  "memory_lookup",
  "validation",
];

/**
 * Tool status is a closed union on `AgentTool` but an open string on the wire.
 * The old `any` parameter passed it straight through, so a backend that grew a
 * fourth status wrote a value the type system had already ruled out, and every
 * consumer's `status === "running"` check silently went false. Unknown tools
 * are kept (so the operator can see them) but are reported as `"error"`, which
 * is the honest reading of a tool we cannot vouch for.
 */
function toAgentTools(tools: ApiAgentLike["tools"]): AgentTool[] {
  if (!Array.isArray(tools)) return [];
  const mapped: AgentTool[] = [];
  for (const tool of tools) {
    if (!tool || typeof tool.name !== "string" || !tool.name) continue;
    mapped.push({
      name: tool.name,
      description: typeof tool.description === "string" ? tool.description : "",
      status: TOOL_STATUSES.includes(tool.status ?? "")
        ? (tool.status as AgentTool["status"])
        : "error",
    });
  }
  return mapped;
}

/** Drops reasoning entries the UI cannot render (no id, or an unknown type). */
function toReasoningHistory(
  steps: ApiAgentLike["reasoningHistory"],
): ReasoningStep[] {
  if (!Array.isArray(steps)) return [];
  const mapped: ReasoningStep[] = [];
  for (const [index, step] of steps.entries()) {
    if (!step || typeof step.content !== "string") continue;
    mapped.push({
      id: typeof step.id === "string" && step.id ? step.id : `step-${index}`,
      type: REASONING_STEP_TYPES.includes(step.type ?? "")
        ? (step.type as ReasoningStep["type"])
        : "thought",
      content: step.content,
      timestamp: typeof step.timestamp === "number" ? step.timestamp : 0,
      tokens: step.tokens,
      confidence: step.confidence,
      citations: Array.isArray(step.citations) ? step.citations : undefined,
    });
  }
  return mapped;
}

export function mapApiAgent(apiAgent: ApiAgentLike): Agent {
  const sourceName = firstString(apiAgent.name, apiAgent.agent_type, apiAgent.role);
  const role = firstString(apiAgent.role, apiAgent.agent_type, apiAgent.name, "UNKNOWN").toUpperCase();
  const id = firstString(apiAgent.id, apiAgent.instance_id, apiAgent.agentId, apiAgent.agent_id, sourceName.toLowerCase());
  const status = firstString(apiAgent.status).toLowerCase() || "unknown";
  const healthStatus = firstString(apiAgent.healthStatus, apiAgent.health_status).toLowerCase();
  const tokensUsed = firstFiniteNumber(apiAgent.tokens_used, apiAgent.tokensUsed);
  const tokenBudget = firstFiniteNumber(apiAgent.token_budget, apiAgent.tokenBudget);
  return {
    // Leave absent identity fields empty so malformed records can be filtered;
    // a synthetic shared ID/name would collapse unrelated instances.
    id,
    name: sourceName,
    role,
    specialization: apiAgent.specialization || "—",
    model: apiAgent.model || "—",
    provider: apiAgent.provider || "—",
    status: status as AgentStatus,
    currentTask: firstString(apiAgent.currentTask, apiAgent.current_task, apiAgent.objective, apiAgent.task) || undefined,
    task: firstString(apiAgent.task, apiAgent.objective) || undefined,
    tokensUsed,
    tokenBudget,
    memoryUsed: apiAgent.memoryUsed ?? 0,
    memory: apiAgent.memory ?? 0,
    tools: toAgentTools(apiAgent.tools),
    costAccumulated: apiAgent.costAccumulated ?? 0,
    speed: apiAgent.speed ?? 0,
    tokensPerSecond: apiAgent.tokensPerSecond ?? 0,
    reasoningDepth: apiAgent.reasoningDepth ?? 0,
    accuracy: apiAgent.accuracy ?? 0,
    contextWindow: apiAgent.contextWindow ?? 0,
    contextUsed: apiAgent.contextUsed ?? 0,
    subTaskQueue: apiAgent.subTaskQueue ?? [],
    healthStatus: ["healthy", "degraded", "critical"].includes(healthStatus || "")
      ? healthStatus as Agent["healthStatus"]
      : "unknown",
    reasoningHistory: toReasoningHistory(apiAgent.reasoningHistory),
    lastSeen: apiAgent.lastSeen ?? Date.now(),
    uptime: apiAgent.uptime ?? 0,
    totalTasks: apiAgent.totalTasks ?? 0,
    successfulTasks: apiAgent.successfulTasks ?? 0,
    failedTasks: apiAgent.failedTasks ?? 0,
    avgLatencyMs: apiAgent.avgLatencyMs ?? 0,
    chainOfThought: apiAgent.chainOfThought ?? "",
    autonomyLevel: apiAgent.autonomyLevel ?? 0,
    connections: apiAgent.connections ?? [],
    color: AGENT_COLORS[role] || "#64748b",
    cpu: apiAgent.cpu ?? 0,
    confidence: apiAgent.confidence ?? 0,
  };
}

export const useAgentStore = create<AgentStore>()(
  subscribeWithSelector((set) => ({
    agents: {},
    activeStream: {},
    messages: [],
    isLoading: false,
    hasFetchedAgents: false,
    error: null,

    setAgent: (agent) =>
      set((s) => ({ agents: { ...s.agents, [agent.id]: agent } })),

    updateAgent: (id, patch) =>
      set((s) => ({
        agents: s.agents[id]
          ? { ...s.agents, [id]: { ...s.agents[id], ...patch } }
          : s.agents,
      })),

    removeAgent: (id) =>
      set((s) => {
        const agents = { ...s.agents };
        delete agents[id];
        return { agents };
      }),

    addReasoningStep: (agentId, step) =>
      set((s) => ({
        activeStream: {
          ...s.activeStream,
          [agentId]: [...(s.activeStream[agentId] ?? []), step],
        },
      })),

    clearReasoning: (agentId) =>
      set((s) => {
        const activeStream = { ...s.activeStream };
        delete activeStream[agentId];
        return { activeStream };
      }),

    addMessage: (msg) =>
      set((s) => ({
        messages: [...s.messages, msg],
      })),

    setAgents: (agents) =>
      set(() => ({ agents: Object.fromEntries(agents.map((a) => [a.id, a])) })),

    fetchAgents: async () => {
      set({ isLoading: true, error: null });
      try {
        const res = await fetch(apiUrl("/api/agents/instances"), {
          headers: authHeaders(),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data: unknown = await res.json();
        if (!isRecord(data) || !Array.isArray(data.agents)) {
          throw new Error("A API devolveu uma resposta de agentes inválida.");
        }
        const agentList = data.agents.filter(isRecord) as ApiAgentLike[];
      const mapped = agentList
        .map(mapApiAgent)
        .filter((agent) => Boolean(agent.id.trim()) && Boolean(agent.name.trim()));
        if (agentList.length > 0 && mapped.length === 0) {
          throw new Error("A API devolveu agentes sem identificação.");
        }
        set({
          agents: Object.fromEntries(mapped.map((a) => [a.id, a])),
          isLoading: false,
          hasFetchedAgents: true,
        });
      } catch (err) {
        set({
          isLoading: false,
          error: err instanceof Error ? err.message : "Failed to fetch agents",
        });
      }
    },

    setLoading: (loading) => set({ isLoading: loading }),
    setError: (error) => set({ error }),
  }))
);
