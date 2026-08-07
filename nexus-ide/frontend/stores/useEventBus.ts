"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import { mapApiAgent, useAgentStore } from "./useAgentStore";
import { useTaskStore } from "./useTaskStore";
import { useSystemStore } from "./useSystemStore";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function useEventBus() {
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);
  
  const abortControllers = useRef<Map<string, AbortController>>(new Map());
  const reconnectTimers = useRef<Map<string, NodeJS.Timeout>>(new Map());
  
  const { updateAgent, setAgents } = useAgentStore();
  const { updateTask } = useTaskStore();
  const { updateSystemMetrics } = useSystemStore();
  
  const connectedRef = useRef(false);

  const connectSSE = useCallback((url: string, storeKey: string, onData: (data: unknown) => void) => {
    if (abortControllers.current.get(storeKey)) {
      return;
    }

    const controller = new AbortController();
    abortControllers.current.set(storeKey, controller);

    fetch(`${API_BASE}${url}`, {
      signal: controller.signal,
      headers: { Accept: "text/event-stream" },
    })
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const reader = response.body?.getReader();
        if (!reader) throw new Error("No reader available");

        const decoder = new TextDecoder();
        let buffer = "";

        function read() {
          if (!reader) return;
          reader.read().then(({ done, value }) => {
            if (done || controller.signal.aborted) return;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() || "";

            for (const line of lines) {
              if (line.startsWith("data: ")) {
                try {
                  const data = JSON.parse(line.slice(6));
                  onData(data);
                } catch {
                }
              }
            }
            read();
          }).catch((err) => {
            if (!controller.signal.aborted) {
              console.warn(`SSE stream ${storeKey} error:`, err);
              scheduleReconnect(url, storeKey, onData);
            }
          });
        }
        read();
      })
      .catch((err) => {
        if (!controller.signal.aborted) {
          abortControllers.current.delete(storeKey);
          setConnectionError(`Falha ao ligar a ${storeKey}`);
          setIsConnected(false);
          console.warn(`SSE connection ${storeKey} failed:`, err);
          scheduleReconnect(url, storeKey, onData);
        }
      });
  }, []);

  const scheduleReconnect = useCallback((url: string, storeKey: string, onData: (data: unknown) => void) => {
    const existing = reconnectTimers.current.get(storeKey);
    if (existing) clearTimeout(existing);

    const timer = setTimeout(() => {
      reconnectTimers.current.delete(storeKey);
      if (!abortControllers.current.get(storeKey)) return;
      connectSSE(url, storeKey, onData);
    }, 3000);

    reconnectTimers.current.set(storeKey, timer);
  }, [connectSSE]);

  const disconnectSSE = useCallback((storeKey: string) => {
    const controller = abortControllers.current.get(storeKey);
    if (controller) {
      controller.abort();
      abortControllers.current.delete(storeKey);
    }
    const timer = reconnectTimers.current.get(storeKey);
    if (timer) {
      clearTimeout(timer);
      reconnectTimers.current.delete(storeKey);
    }
  }, []);

  const startSSEConnections = useCallback(() => {
    setConnectionError(null);

    // Connect to the system metrics stream
    connectSSE("/api/system/metrics/stream", "metrics", (data) => {
      if (data && typeof data === "object") {
        const metrics = data as any;
        updateSystemMetrics({
          cpuUsage: metrics.cpu_usage || 0,
          memoryUsage: metrics.memory_usage || 0,
          gpuUsage: metrics.gpu_usage || 0,
          diskUsage: metrics.disk_usage || 0,
          networkIn: metrics.network_in || 0,
          networkOut: metrics.network_out || 0,
          activeConnections: metrics.active_connections || 0,
          queueSize: metrics.queue_size || 0,
          requestsPerSecond: metrics.requests_per_second || 0,
          avgResponseTime: metrics.avg_response_time_ms || 0,
          tokensPerSecond: metrics.tokens_per_second || 0,
          cacheHitRate: metrics.cache_hit_rate || 0,
          apiErrorsPerMin: metrics.error_rate || 0,
          timestamp: metrics.timestamp || Date.now(),
        });
      }
    });

    // Connect to the autonomous-tasks/stream for task & agent events
    connectSSE("/api/autonomous-tasks/stream", "tasks", (data) => {
      if (data && typeof data === "object") {
        const ev = data as any;
        // Accept both canonical StreamEvent types and legacy formats
        // Canonical: type="task_scheduled", type="agent_started", type="goal", etc.
        // Legacy:    type="task" (with .task sub-object), type="agent_instance"
        if (ev.type === "task" || ev.type === "task_scheduled" || ev.type === "task_started" ||
            ev.type === "task_completed" || ev.type === "task_failed" || ev.type === "task_cancelled" ||
            ev.type === "goal" || ev.type === "plan_created" || ev.type === "plan_updated" ||
            ev.type === "step_completed") {
          // Update task store from event
          const taskData = ev.task || { id: ev.task_id, status: ev.type };
          if (taskData.id) {
            updateTask(taskData.id, { status: taskData.status });
          }
        }
        if (ev.type === "agent_instance" || ev.type === "agent_started" ||
            ev.type === "agent_finished" || ev.type === "agent_failed" ||
            ev.type === "agent_retry") {
          // Update agent store from event
          const agentData = ev.agent_instance || { agent_id: ev.agent };
          if (agentData.agent_id) {
            updateAgent(agentData.agent_id, { status: agentData.state || "idle" });
          }
        }
      }
    });

    // Connect to topology stream for graph data
    connectSSE("/api/agents/topology/stream", "topology", (data) => {
      if (data && Array.isArray(data)) {
        const agents = data as any[];
        setAgents(agents.map((a: any) => mapApiAgent({
          id: a.agentId || a.id,
          name: a.agentType || a.agentId,
          status: a.status,
          task: a.task || "",
        })));
      }
    });

    setIsConnected(true);
    connectedRef.current = true;
  }, [connectSSE, updateAgent, updateTask, setAgents, updateSystemMetrics]);

  const stopBus = useCallback(() => {
    for (const [key, controller] of abortControllers.current) {
      controller.abort();
      abortControllers.current.delete(key);
    }
    for (const timer of reconnectTimers.current.values()) {
      clearTimeout(timer);
    }
    reconnectTimers.current.clear();

    setIsConnected(false);
    connectedRef.current = false;
  }, []);

  const startBus = useCallback(() => {
    if (connectedRef.current) return;
    startSSEConnections();
  }, [startSSEConnections]);

  return { startBus, stopBus, isConnected, connectionError };
}
