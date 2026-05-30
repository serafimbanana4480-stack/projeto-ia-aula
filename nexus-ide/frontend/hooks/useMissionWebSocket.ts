/**
 * useMissionWebSocket — Real-time updates for Mission Control.
 *
 * Tries a native WebSocket at `/ws/missions/{mission_id}` first.
 * Falls back to SSE on `/api/bus/stream?topics=mission.update,agent.status`
 * if the WebSocket is unavailable.
 *
 * Integrates directly with the missionStore so any component can subscribe
 * to store changes without knowing the transport layer.
 */
import { useEffect, useRef, useCallback } from "react";
import { API_BASE_URL, apiUrl } from "../lib/api";
import { useMissionStore, type BusMessage, type Decision } from "../stores/missionStore";

interface WebSocketMessage {
  type: "agent_status" | "bus_message" | "phase_complete" | "decision" | "quality_gate" | "system_health" | "mission_update";
  payload: unknown;
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
  const maxReconnectDelay = 30000;

  const handleMessage = useCallback((msg: WebSocketMessage) => {
    const store = useMissionStore.getState();
    switch (msg.type) {
      case "mission_update": {
        const payload = msg.payload as Record<string, unknown>;
        if (payload.mission) {
          store.updateMission(payload.mission as Parameters<typeof store.updateMission>[0]);
        }
        break;
      }
      case "agent_status": {
        const payload = msg.payload as Record<string, unknown>;
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
        const parsed = parseBusMessage(msg.payload as Record<string, unknown>);
        if (parsed) store.addBusMessage(parsed);
        break;
      }
      case "phase_complete": {
        const payload = msg.payload as Record<string, unknown>;
        if (payload.mission) {
          store.updateMission(payload.mission as Parameters<typeof store.updateMission>[0]);
        }
        break;
      }
      case "decision": {
        const parsed = parseDecision(msg.payload as Record<string, unknown>);
        if (parsed) store.addDecision(parsed);
        break;
      }
      case "quality_gate": {
        const payload = msg.payload as Record<string, unknown>;
        if (payload.gates && Array.isArray(payload.gates)) {
          store.setQualityGates(payload.gates as Parameters<typeof store.setQualityGates>[0]);
        }
        break;
      }
      case "system_health": {
        const payload = msg.payload as Record<string, unknown>;
        if (payload.health) {
          store.setSystemHealth(payload.health as Parameters<typeof store.setSystemHealth>[0]);
        }
        break;
      }
    }
  }, []);

  const startSSE = useCallback(() => {
    if (!missionId) return;
    if (esRef.current) {
      esRef.current.close();
      esRef.current = null;
    }

    try {
      const es = new EventSource(
        apiUrl("/api/bus/stream?topics=mission.update,agent.status,code.changes,review.completed,architecture.proposals"),
      );
      esRef.current = es;

      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as Record<string, unknown>;
          const msg: WebSocketMessage = {
            type: "bus_message",
            payload: data,
          };
          handleMessage(msg);

          // Derive decisions from certain bus topics
          const topic = (data.topic as string) || "";
          if (topic === "architecture.proposals" || topic === "review.completed") {
            const decision = parseDecision({
              agent: data.source_agent,
              summary: `${data.source_agent} ${topic === "architecture.proposals" ? "proposed" : "reviewed"} ${(data.payload as Record<string, unknown>)?.proposal || (data.payload as Record<string, unknown>)?.verdict || "update"}`,
              type: topic === "architecture.proposals" ? "proposal" : "review",
              timestamp: data.timestamp,
            });
            if (decision) {
              handleMessage({ type: "decision", payload: decision as unknown as Record<string, unknown> });
            }
          }
        } catch {
          /* ignore parse errors */
        }
      };

      es.onerror = () => {
        es.close();
        esRef.current = null;
        const delay = Math.min(1000 * 2 ** reconnectAttempt.current, maxReconnectDelay);
        reconnectAttempt.current += 1;
        reconnectTimer.current = setTimeout(startSSE, delay);
      };
    } catch {
      /* SSE not available */
    }
  }, [missionId, handleMessage]);

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
      };

      ws.onmessage = (event) => {
        try {
          const msg = JSON.parse(event.data) as WebSocketMessage;
          handleMessage(msg);
        } catch {
          /* ignore parse errors */
        }
      };

      ws.onclose = () => {
        wsRef.current = null;
        const delay = Math.min(1000 * 2 ** reconnectAttempt.current, maxReconnectDelay);
        reconnectAttempt.current += 1;
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
  }, [missionId, handleMessage, startSSE]);

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
