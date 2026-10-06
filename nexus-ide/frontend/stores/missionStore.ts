/**
 * Mission Control Store — Central state for the autonomous system dashboard.
 *
 * Holds missions, agent instances, bus messages, decisions, quality gates,
 * and the execution envelope.  Updated by the REST API and the WebSocket
 * hook.  Task 10 adds envelope-derived state plus the
 * cancel / resume / replan / apply / mergeCheckpoint actions; the existing
 * public surface is preserved verbatim so dashboard consumers continue to
 * compile unchanged.
 */
import { create } from "zustand";

import {
  type ExecutionEnvelope,
  mergeEnvelopeMonotonic,
  normalizeExecutionEnvelope,
} from "../lib/executionTypes";
// Type-only, so it is erased at compile time and cannot form an import cycle
// with `lib/api`. The store previously declared its OWN `AgentInstance` with
// required `id`/`name` and a 5-value status union, while `lib/api` returned the
// normalized shape (`instance_id`→`id`, `agent_type`→`name`, plus `aborted`).
// Two same-named types meant the compiler could not catch a tile reading a
// field the backend never sends. One canonical type, imported, not redeclared.
import type { AgentInstance } from "../lib/api";

export type { AgentInstance };

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

  // Task 10 — execution envelope.
  envelope: ExecutionEnvelope | null;
  envelopeVersion: number;
  envelopePending: boolean;
  envelopeError: string | null;

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

  /**
   * Replace the current envelope unconditionally — used when the orchestrator
   * confirms a brand-new run (e.g. resumeMission just succeeded). The caller
   * is responsible for passing a fully-normalized envelope.
   */
  applyExecution: (envelope: ExecutionEnvelope | unknown) => void;
  /**
   * Monotonic checkpoint merge. Older envelopes are dropped without
   * touching the store. Use this for any SSE / WebSocket update where the
   * ordering cannot be guaranteed.
   */
  mergeCheckpoint: (envelope: ExecutionEnvelope | unknown) => void;
  clearEnvelope: () => void;
  setEnvelopePending: (pending: boolean) => void;
  setEnvelopeError: (message: string | null) => void;

  /** Action stubs — wired up by useMissionWebSocket so the store stays
   * transport-agnostic. They emit a friendly error when called without a
   * binding so callers can surface the issue. */
  cancelMission: (id: string) => Promise<{ status: string; mission_id: string }>;
  resumeMission: (id: string) => Promise<{ status: string; mission_id: string }>;
  replanMission: (id: string) => Promise<{ status: string; mission_id: string }>;
}

const initialEnvelopeState = {
  envelope: null as ExecutionEnvelope | null,
  envelopeVersion: 0,
  envelopePending: false,
  envelopeError: null as string | null,
};

/**
 * Default stub implementations for the action verbs. They throw so the
 * caller can decide whether the dashboard is missing a transport binding;
 * the WebSocket hook overrides them at runtime with real implementations.
 */
async function _notImplemented(action: string, id: string): Promise<{ status: string; mission_id: string }> {
  void action;
  void id;
  throw new Error(
    `missionStore.${action}() called without a transport binding`,
  );
}

export const useMissionStore = create<MissionState>((set, get) => ({
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
  ...initialEnvelopeState,

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

  applyExecution: (envelope) => {
    const normalized = normalizeExecutionEnvelope(envelope);
    set({
      envelope: normalized,
      envelopeVersion: normalized.version,
      envelopeError: null,
      selectedMission:
        normalized.context.mission_id ?? get().selectedMission,
    });
  },

  mergeCheckpoint: (envelope) => {
    const incoming = normalizeExecutionEnvelope(envelope);
    set((state) => {
      const merged = mergeEnvelopeMonotonic(state.envelope, incoming);
      return {
        envelope: merged,
        envelopeVersion: merged.version,
        envelopeError: null,
        selectedMission:
          merged.context.mission_id ?? state.selectedMission,
      };
    });
  },

  clearEnvelope: () => set({ ...initialEnvelopeState }),
  setEnvelopePending: (envelopePending) => set({ envelopePending }),
  setEnvelopeError: (envelopeError) => set({ envelopeError }),

  cancelMission: (id) => _notImplemented("cancelMission", id),
  resumeMission: (id) => _notImplemented("resumeMission", id),
  replanMission: (id) => _notImplemented("replanMission", id),
}));
