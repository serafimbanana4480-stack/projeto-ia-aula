"use client";

import { create, type StoreApi } from "zustand";
import { subscribeWithSelector } from "zustand/middleware";
import { apiUrl } from "../lib/api";

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
  healthStatus: "healthy" | "degraded" | "critical";
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
  activeStream: Record<string, ReasoningStep[]>;
  messages: AgentMessage[];
  isLoading: boolean;
  error: string | null;

  setAgent: (agent: Agent) => void;
  updateAgent: (id: string, patch: Partial<Agent>) => void;
  removeAgent: (id: string) => void;
  addReasoningStep: (agentId: string, step: ReasoningStep) => void;
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

function mapApiAgent(apiAgent: any): Agent {
  const role = (apiAgent.name || apiAgent.role || "UNKNOWN").toUpperCase();
  return {
    id: apiAgent.id || apiAgent.name?.toLowerCase() || "unknown",
    name: apiAgent.name || "Unknown Agent",
    role: role,
    specialization: apiAgent.specialization || `${role} Agent`,
    model: apiAgent.model || "local",
    provider: apiAgent.provider || "Ollama",
    status: (apiAgent.status || "idle") as AgentStatus,
    currentTask: apiAgent.currentTask || undefined,
    task: apiAgent.task || undefined,
    memoryUsed: apiAgent.memoryUsed ?? 0,
    memory: apiAgent.memory ?? 0,
    tools: apiAgent.tools ?? [],
    costAccumulated: apiAgent.costAccumulated ?? 0,
    speed: apiAgent.speed ?? 0,
    tokensPerSecond: apiAgent.tokensPerSecond ?? 0,
    reasoningDepth: apiAgent.reasoningDepth ?? 0,
    accuracy: apiAgent.accuracy ?? 0,
    contextWindow: apiAgent.contextWindow ?? 0,
    contextUsed: apiAgent.contextUsed ?? 0,
    subTaskQueue: apiAgent.subTaskQueue ?? [],
    healthStatus: (apiAgent.healthStatus || "healthy") as Agent["healthStatus"],
    reasoningHistory: apiAgent.reasoningHistory ?? [],
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
        const res = await fetch(apiUrl("/api/agents/status"));
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const agentList: any[] = data.agents ?? [];
        const mapped = agentList.map(mapApiAgent);
        set({
          agents: Object.fromEntries(mapped.map((a) => [a.id, a])),
          isLoading: false,
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
