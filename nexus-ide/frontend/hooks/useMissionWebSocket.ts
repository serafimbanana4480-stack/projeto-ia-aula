/**
 * useMissionWebSocket — Real-time updates for Mission Control.
 *
 * Tries a native WebSocket at `/ws/missions/{mission_id}` first.
 * Falls back to SSE on `/api/bus/stream?topics=mission.update,agent.status`
 * if the WebSocket is unavailable.
 *
 * Browsers cannot set headers on a WebSocket handshake, so the access token
 * travels in the query string; the SSE transport uses a real
 * `Authorization: Bearer` header. A 401/403 on the SSE transport is
 * definitive — the credential is not going to become valid by retrying — so
 * the transport stops instead of hammering the backend, and the store is left
 * in an explicit error state.
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
import { getAccessToken } from "../lib/auth";
import { normalizeStreamEvent } from "../lib/executionTypes";
import { useMissionStore, type BusMessage, type Decision } from "../stores/missionStore";

/** Maximum reconnect delay — keeps exponential growth bounded. */
const MAX_RECONNECT_DELAY = 30_000;

const AUTH_FAILURE_MESSAGE =
  "Sem autorização para receber eventos da missão. Inicia sessão novamente.";

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

function wsUrl(missionId: string, token: string | null): string {
  const httpUrl = apiUrl("");
  const wsProtocol = httpUrl.startsWith("https") ? "wss" : "ws";
  const host = httpUrl.replace(/^https?:\/\//, "").replace(/\/$/, "");
  // A WebSocket handshake cannot carry an `Authorization` header from the
  // browser, so the token is passed as a query parameter.
  const query = token ? `?token=${encodeURIComponent(token)}` : "";
  return `${wsProtocol}://${host}/ws/missions/${missionId}${query}`;
}

/**
 * Split an SSE byte buffer into frames, returning the payload of every
 * default-message frame plus the trailing partial frame.
 */
function extractSseData(buffer: string): { payloads: string[]; rest: string } {
  const frames = buffer.split(/\r?\n\r?\n/);
  const rest = frames.pop() ?? "";
  const payloads: string[] = [];
  for (const frame of frames) {
    const lines = frame.split(/\r?\n/);
    const namedEvent = lines.find((line) => line.startsWith("event:"));
    if (namedEvent && namedEvent.slice(6).trim() !== "message") continue;
    const data = lines
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart())
      .join("\n");
    if (data) payloads.push(data);
  }
  return { payloads, rest };
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
  // The SSE transport is a `fetch` stream (an `EventSource` cannot send an
  // Authorization header), so the live handle is an AbortController.
  const sseAbortRef = useRef<AbortController | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempt = useRef(0);
  const bindingRef = useRef(false);
  // Set once the backend rejects our credentials. A 401/403 is definitive:
  // retrying the same token cannot succeed, so every transport stops here
  // instead of reconnecting forever.
  const authRejected = useRef(false);

  const rejectAuth = useCallback(() => {
    authRejected.current = true;
    if (reconnectTimer.current) {
      clearTimeout(reconnectTimer.current);
      reconnectTimer.current = null;
    }
    wsRef.current?.close();
    wsRef.current = null;
    sseAbortRef.current?.abort();
    sseAbortRef.current = null;
    useMissionStore.getState().setBackendOnline(false);
    useMissionStore.getState().setError(AUTH_FAILURE_MESSAGE);
  }, []);

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

  const handleBusFrame = useCallback(
    (payload: string) => {
      try {
        const data = JSON.parse(payload) as Record<string, unknown>;
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
    },
    [dispatch],
  );

  const startSSE = useCallback(() => {
    if (authRejected.current) return;
    if (sseAbortRef.current) {
      sseAbortRef.current.abort();
      sseAbortRef.current = null;
    }

    // The token is read per attempt: a reconnect after a token refresh sends
    // the new credential instead of the rejected one.
    const token = getAccessToken();
    if (!token) {
      rejectAuth();
      return;
    }

    const controller = new AbortController();
    sseAbortRef.current = controller;

    void (async () => {
      try {
        const response = await fetch(apiUrl(`/api/bus/stream?topics=${SSE_TOPICS}`), {
          headers: {
            Accept: "text/event-stream",
            Authorization: `Bearer ${token}`,
          },
          signal: controller.signal,
        });

        if (response.status === 401 || response.status === 403) {
          rejectAuth();
          return;
        }
        if (!response.ok || !response.body) {
          throw new Error(`HTTP ${response.status}`);
        }

        reconnectAttempt.current = 0;
        useMissionStore.getState().setBackendOnline(true);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const { payloads, rest } = extractSseData(buffer);
          buffer = rest;
          for (const payload of payloads) handleBusFrame(payload);
        }
      } catch {
        if (controller.signal.aborted) return;
        const delay = Math.min(1000 * 2 ** reconnectAttempt.current, MAX_RECONNECT_DELAY);
        reconnectAttempt.current += 1;
        if (reconnectAttempt.current > 2) {
          useMissionStore.getState().setBackendOnline(false);
        }
        reconnectTimer.current = setTimeout(startSSE, delay);
      }
    })();
  }, [handleBusFrame, rejectAuth]);

  const startWebSocket = useCallback(() => {
    if (!missionId) return;
    if (authRejected.current) return;
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const token = getAccessToken();
    if (!token) {
      rejectAuth();
      return;
    }

    try {
      const ws = new WebSocket(wsUrl(missionId, token));
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

      ws.onclose = (event) => {
        wsRef.current = null;
        // A handshake the backend refused on policy/auth grounds (1008 policy
        // violation, 4401/4403 private auth codes) is not worth retrying: the
        // SSE transport reports the definitive HTTP status instead.
        if (event.code === 1008 || event.code === 4401 || event.code === 4403) {
          if (!authRejected.current && !sseAbortRef.current) startSSE();
          return;
        }
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
  }, [missionId, dispatch, rejectAuth, startSSE]);

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
    authRejected.current = false;
    startWebSocket();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
      if (sseAbortRef.current) {
        sseAbortRef.current.abort();
        sseAbortRef.current = null;
      }
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
    };
  }, [missionId, startWebSocket]);
}
