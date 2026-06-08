/**
 * Mission Control Store — Central state for the autonomous system dashboard.
 *
 * Holds missions, agent instances, bus messages, decisions, quality gates,
 * and system health.  Updated by the REST API and the WebSocket hook.
 */
import { create } from "zustand";

// Debounce helpers for high-frequency store updates
let _busMsgTimeout: ReturnType<typeof setTimeout> | null = null;
let _pendingBusMessages: BusMessage[] = [];

export type MissionStatus = "PENDING" | "RUNNING" | "PAUSED" | "COMPLETED" | "FAILED" | "ABORTED";

export interface MissionPhase {
  name: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "FAILED" | "SKIPPED";
  progress: number;
  agent?: string;
  started_at?: string;
  completed_at?: string;
}

export interface Mission {
  id: string;
  objective: string;
  status: MissionStatus;
  progress: number;
  active_agents: string[];
  elapsed_seconds: number;
  tokens_used: number;
  phases: MissionPhase[];
  created_at: string;
  updated_at: string;
}

export interface AgentInstance {
  id: string;
  name: string;
  status: "idle" | "running" | "paused" | "failed" | "completed";
  current_task?: string;
  cpu_percent?: number;
  memory_mb?: number;
  tokens_used: number;
  mission_id?: string;
  started_at?: string;
  last_heartbeat?: string;
}

export interface BusMessage {
  message_id: string;
  topic: string;
  source_agent: string;
  payload: Record<string, unknown>;
  timestamp: string;
}

export interface Decision {
  id: string;
  timestamp: string;
  agent: string;
  type: "proposal" | "flag" | "decision" | "review";
  summary: string;
  details?: string;
  mission_id?: string;
}

export interface QualityGate {
  name: string;
  label: string;
  status: "pass" | "fail" | "warn" | "unknown";
  value: string;
  threshold?: string;
}

export interface SystemHealthSnapshot {
  workers: Array<{
    name: string;
    status: "healthy" | "degraded" | "unhealthy" | "unknown";
    last_run?: string;
    queue_size?: number;
  }>;
  token_usage_hourly: Array<{ hour: string; tokens: number }>;
  token_usage_daily: Array<{ day: string; tokens: number }>;
  mission_success_rate: number;
  mission_failure_rate: number;
  agent_failure_rate: number;
  total_missions: number;
  total_agents: number;
}

interface MissionState {
  missions: Mission[];
  agents: AgentInstance[];
  busMessages: BusMessage[];
  decisions: Decision[];
  qualityGates: QualityGate[];
  systemHealth: SystemHealthSnapshot | null;
  selectedMission: string | null;
  loading: boolean;
  error: string | null;
  backendOnline: boolean;

  // Actions
  setMissions: (missions: Mission[]) => void;
  updateMission: (mission: Mission) => void;
  setAgents: (agents: AgentInstance[]) => void;
  updateAgentStatus: (agentId: string, status: AgentInstance["status"], updates?: Partial<AgentInstance>) => void;
  addBusMessage: (msg: BusMessage) => void;
  setBusMessages: (messages: BusMessage[]) => void;
  addDecision: (decision: Decision) => void;
  setDecisions: (decisions: Decision[]) => void;
  setQualityGates: (gates: QualityGate[]) => void;
  setSystemHealth: (health: SystemHealthSnapshot | null) => void;
  selectMission: (id: string | null) => void;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
  setBackendOnline: (online: boolean) => void;
}

export const useMissionStore = create<MissionState>((set) => ({
  missions: [],
  agents: [],
  busMessages: [],
  decisions: [],
  qualityGates: [],
  systemHealth: null,
  selectedMission: null,
  loading: false,
  error: null,
  backendOnline: true,

  setMissions: (missions) => set({ missions }),
  updateMission: (mission) =>
    set((state) => ({
      missions: state.missions.map((m) => (m.id === mission.id ? mission : m)),
    })),
  setAgents: (agents) => set({ agents }),
  updateAgentStatus: (agentId, status, updates) =>
    set((state) => ({
      agents: state.agents.map((a) =>
        a.id === agentId ? { ...a, status, ...updates } : a
      ),
    })),
  addBusMessage: (msg) => {
    _pendingBusMessages.push(msg);
    if (_busMsgTimeout) return;
    _busMsgTimeout = setTimeout(() => {
      const batch = _pendingBusMessages;
      _pendingBusMessages = [];
      _busMsgTimeout = null;
      set((state) => ({
        busMessages: [...batch.reverse(), ...state.busMessages].slice(0, 500),
      }));
    }, 150);
  },
  setBusMessages: (messages) => set({ busMessages: messages }),
  addDecision: (decision) =>
    set((state) => ({
      decisions: [decision, ...state.decisions].slice(0, 200),
    })),
  setDecisions: (decisions) => set({ decisions }),
  setQualityGates: (gates) => set({ qualityGates: gates }),
  setSystemHealth: (health) => set({ systemHealth: health }),
  selectMission: (id) => set({ selectedMission: id }),
  setLoading: (loading) => set({ loading }),
  setError: (error) => set({ error }),
  setBackendOnline: (online) => set({ backendOnline: online }),
}));
