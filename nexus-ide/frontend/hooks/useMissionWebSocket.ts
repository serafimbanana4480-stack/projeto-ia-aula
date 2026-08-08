/**
 * useMissionWebSocket — Real-time updates for Mission Control.
 *
 * Tries a native WebSocket at `/ws/missions/{mission_id}` first.
 * Falls back to SSE on `/api/bus/stream?topics=mission.update,agent.status`
 * if the WebSocket is unavailable.
 *
 * Every event the backend emits — whether it arrives as a routing decision,
 * an execution_state/execution_error checkpoint, or one of the legacy
 * bus / mission_update envelopes — is normalized through
 * :func:`normalizeStreamEvent` and merged into the store via
 * :func:`mergeCheckpoint`. The panel therefore reads exactly one shape.
 *
 * The hook also wires the store's cancelMission / resumeMission / replanMission
 * actions to the matching REST verbs, keeping the dashboard free of fetch
 * boilerplate.
 */
import { useEffect, useRef, useCallback } from "react";

import {
  cancelMission as apiCancelMission,
  replanMission as apiReplanMission,
  resumeMission as apiResumeMission,
  apiUrl,
} from "../lib/api";
import { normalizeStreamEvent } from "../lib/executionTypes";
import { useMissionStore, type BusMessage, type Decision } from "../stores/missionStore";

/** Maximum reconnect delay — keeps exponential growth bounded. */
const MAX_RECONNECT_DELAY = 30_000;

/** Topics the SSE stream subscribes to. Mirrors the backend bus topics. */
const SSE_TOPICS =
  "mission.update,agent.status,code.changes,review.completed," +
  "architecture.proposals,routing,execution_state,execution_error," +
  "execution_completed,mission_brief,mission_plan,mission_wave," +
  "mission_agent,mission_decision,mission_verification,mission_completed";

type LegacyMessageType =
  | "agent_status"
  | "bus_message"
  | "phase_complete"
  | "decision"
  | "quality_gate"
  | "system_health"
  | "mission_update"
  | "routing"
  | "execution_state"
  | "execution_error"
  | "execution_completed"
  | "mission_brief"
  | "mission_plan"
  | "mission_wave"
  | "mission_agent"
  | "mission_decision"
  | "mission_verification"
  | "mission_completed";

interface LegacyEnvelope {
  type: LegacyMessageType;
  payload?: unknown;
  data?: unknown;
  timestamp?: string;
}

function wsUrl(missionId: string): string {
  const httpUrl = apiUrl("");
  const wsProtocol = httpUrl.startsWith("https") ? "wss" : "ws";
  const host = httpUrl.replace(/^https?:\/\//, "").replace(/\/$/, "");
  return `${wsProtocol}://${host}/ws/missions/${missionId}`;
}

function parseBusMessage(data: Record<string, unknown>): BusMessage | null {
  if (!data.topic || !data.source_agent) return null;
  return {
    message_id: (data.message_id as string) || "unknown",
    topic: (data.topic as string) || "unknown",
    source_agent: (data.source_agent as string) || "unknown",
    payload: (data.payload as Record<string, unknown>) || {},
    timestamp: (data.timestamp as string) || new Date().toISOString(),
  };
}

function parseDecision(data: Record<string, unknown>): Decision | null {
  if (!data.agent || !data.summary) return null;
  return {
    id: (data.id as string) || `${Date.now()}`,
    timestamp: (data.timestamp as string) || new Date().toISOString(),
    agent: data.agent as string,
    type: (data.type as Decision["type"]) || "decision",
    summary: data.summary as string,
    details: (data.details as string) || undefined,
    mission_id: (data.mission_id as string) || undefined,
  };
}

export function useMissionWebSocket(missionId: string | null) {
  const wsRef = useRef<WebSocket | null>(null);
  const esRef = useRef<EventSource | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempt = useRef(0);
  const bindingRef = useRef(false);
  const dispatch = useCallback((raw: unknown) => {
    // The stream normalizer accepts anything that looks like an SSE/WS
    // envelope. When the event is not a known execution shape we fall back to
    // legacy field-by-field dispatch so the rest of the dashboard keeps
    // working until the backend emits the new envelope shape.
    const normalized = normalizeStreamEvent(raw as never);
    if (normalized) {
      useMissionStore.getState().mergeCheckpoint(normalized);
      return;
    }
    if (raw && typeof raw === "object" && "data" in raw) {
      const inner = normalizeStreamEvent((raw as { data: unknown }).data as never);
      if (inner) {
        useMissionStore.getState().mergeCheckpoint(inner);
        return;
      }
    }

    const legacy = raw as LegacyEnvelope;
    const store = useMissionStore.getState();
    switch (legacy.type) {
      case "mission_update":
      case "phase_complete": {
        const payload = (legacy.payload ?? legacy.data ?? {}) as Record<string, unknown>;
        if (payload.mission) {
          store.updateMission(payload.mission as Parameters<typeof store.updateMission>[0]);
        }
        if (payload.envelope) {
          store.mergeCheckpoint(payload.envelope);
        }
        break;
      }
      case "agent_status": {
        const payload = (legacy.payload ?? legacy.data ?? {}) as Record<string, unknown>;
        if (payload.agent_id && payload.status) {
          store.updateAgentStatus(
            payload.agent_id as string,
            payload.status as Parameters<typeof store.updateAgentStatus>[1],
            (payload.updates as Record<string, unknown>) || undefined,
          );
        }
        break;
      }
      case "bus_message": {
        const parsed = parseBusMessage((legacy.payload ?? legacy.data ?? {}) as Record<string, unknown>);
        if (parsed) store.addBusMessage(parsed);
        break;
      }
      case "decision": {
        const parsed = parseDecision((legacy.payload ?? legacy.data ?? {}) as Record<string, unknown>);
        if (parsed) store.addDecision(parsed);
        break;
      }
      case "quality_gate": {
        const payload = (legacy.payload ?? legacy.data ?? {}) as Record<string, unknown>;
        if (payload.gates && Array.isArray(payload.gates)) {
          store.setQualityGates(payload.gates as Parameters<typeof store.setQualityGates>[0]);
        }
        break;
      }
      case "system_health": {
        const payload = (legacy.payload ?? legacy.data ?? {}) as Record<string, unknown>;
        if (payload.health) {
          store.setSystemHealth(payload.health as Parameters<typeof store.setSystemHealth>[0]);
        }
        break;
      }
      default:
        // Unknown type — nothing to do.
        break;
    }
  }, []);

  const startSSE = useCallback(() => {
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }

    try {
      const es = new EventSource(apiUrl(`/api/bus/stream?topics=${SSE_TOPICS}`));
      esRef.current = es;

      es.onopen = () => {
        reconnectAttempt.current = 0;
        useMissionStore.getState().setBackendOnline(true);
      };

      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as Record<string, unknown>;
          // Route SSE bus messages through the same dispatcher. The bus
          // sometimes wraps execution envelopes under ``data``.
          if (data && typeof data === "object") {
            dispatch({ type: "bus_message", data });
          }

          // Keep legacy behaviour: certain bus topics imply a decision.
          const topic = (data.topic as string) || "";
          if (topic === "architecture.proposals" || topic === "review.completed") {
            const decision = parseDecision({
              agent: data.source_agent,
              summary: `${data.source_agent} ${topic === "architecture.proposals" ? "proposed" : "reviewed"} ${(data.payload as Record<string, unknown>)?.proposal || (data.payload as Record<string, unknown>)?.verdict || "update"}`,
              type: topic === "architecture.proposals" ? "proposal" : "review",
              timestamp: data.timestamp,
            });
            if (decision) {
              dispatch({ type: "decision", payload: decision as unknown as Record<string, unknown> });
            }
          }
        } catch {
          /* ignore parse errors */
        }
      };

      es.onerror = () => {
        es.close();
        esRef.current = null;
        const delay = Math.min(1000 * 2 ** reconnectAttempt.current, MAX_RECONNECT_DELAY);
        reconnectAttempt.current += 1;
        if (reconnectAttempt.current > 2) {
          useMissionStore.getState().setBackendOnline(false);
        }
        reconnectTimer.current = setTimeout(startSSE, delay);
      };
    } catch {
      /* SSE not available */
    }
  }, [dispatch]);

  const startWebSocket = useCallback(() => {
    if (!missionId) return;
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    try {
      const ws = new WebSocket(wsUrl(missionId));
      wsRef.current = ws;

      ws.onopen = () => {
        reconnectAttempt.current = 0;
        useMissionStore.getState().setBackendOnline(true);
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as LegacyEnvelope;
          dispatch(msg);
        } catch {
          /* ignore parse errors */
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        const delay = Math.min(1000 * 2 ** reconnectAttempt.current, MAX_RECONNECT_DELAY);
        reconnectAttempt.current += 1;
        if (reconnectAttempt.current > 2) {
          useMissionStore.getState().setBackendOnline(false);
        }
        reconnectTimer.current = setTimeout(startWebSocket, delay);
      };

      ws.onerror = () => {
        ws.close();
        wsRef.current = null;
        // Fallback to SSE on first error
        if (reconnectAttempt.current === 0) {
          startSSE();
        }
      };
    } catch {
      startSSE();
    }
  }, [missionId, dispatch, startSSE]);

  // Wire the store's action verbs to REST calls. We bind once per mount; the
  // store keeps the binding for the lifetime of the hook, and any later
  // mount overwrites the previous binding.
  useEffect(() => {
    if (bindingRef.current) return;
    bindingRef.current = true;
    useMissionStore.setState({
      cancelMission: async (id: string) => {
        useMissionStore.getState().setEnvelopePending(true);
        try {
          return await apiCancelMission(id);
        } finally {
          useMissionStore.getState().setEnvelopePending(false);
        }
      },
      resumeMission: async (id: string) => {
        useMissionStore.getState().setEnvelopePending(true);
        try {
          return await apiResumeMission(id);
        } finally {
          useMissionStore.getState().setEnvelopePending(false);
        }
      },
      replanMission: async (id: string) => {
        useMissionStore.getState().setEnvelopePending(true);
        try {
          return await apiReplanMission(id);
        } finally {
          useMissionStore.getState().setEnvelopePending(false);
        }
      },
    });
  }, []);

  useEffect(() => {
    if (!missionId) return;
    reconnectAttempt.current = 0;
    startWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (esRef.current) {
        esRef.current.close();
        esRef.current = null;
      }
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
    };
  }, [missionId, startWebSocket]);
}
