"use client";

import { useRef, useCallback, useState, useEffect } from "react";
import { mapApiAgent, useAgentStore } from "./useAgentStore";
import { useTaskStore, type TaskStatus } from "./useTaskStore";
import { useSystemStore, type SystemMetrics } from "./useSystemStore";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

type SseHandler = (data: unknown) => void;
type ConnectFn = (url: string, storeKey: string, onData: SseHandler) => void;

const RECONNECT_DELAY_MS = 3000;

/** Wire shape of `GET /api/system/metrics/stream`. */
interface MetricsFrame {
  cpu_usage?: number;
  memory_usage?: number;
  gpu_usage?: number;
  disk_usage?: number;
  network_in?: number;
  network_out?: number;
  active_connections?: number;
  queue_size?: number;
  requests_per_second?: number;
  avg_response_time_ms?: number;
  tokens_per_second?: number;
  cache_hit_rate?: number;
  error_rate?: number;
  timestamp?: number;
}

/**
 * Wire shape of `GET /api/autonomous-tasks/stream`.
 *
 * Accepts both the canonical `StreamEvent` types and the legacy envelopes
 * (`type: "task"` with a `.task` object, `type: "agent_instance"` with an
 * `.agent_instance` object), so both shapes are modelled here rather than
 * reached for with `any`.
 */
interface TaskStreamFrame {
  type?: string;
  task?: { id?: string; status?: string };
  task_id?: string;
  agent_instance?: { agent_id?: string; state?: string };
  agent?: string;
}

interface TopologyAgentFrame {
  agentId?: string;
  id?: string;
  agentType?: string;
  status?: string;
  task?: string;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

const TASK_STATUSES: readonly string[] = [
  "pending",
  "queued",
  "running",
  "completed",
  "failed",
  "blocked",
  "retrying",
];

/**
 * Event type -> `TaskStatus`, for the events that really are a task lifecycle
 * transition.
 *
 * The handler used to write `status: ev.type` behind an `as any`, so the store
 * received values like `"task_scheduled"` or `"plan_created"` that are not
 * members of `TaskStatus` at all. Events that carry no lifecycle change
 * (`goal`, `plan_created`, `plan_updated`, `task_cancelled` — the enum has no
 * `cancelled`) are deliberately absent: they must not overwrite a real status
 * with a bogus one.
 */
const TASK_STATUS_BY_EVENT: Record<string, TaskStatus> = {
  task: "queued",
  task_scheduled: "queued",
  task_started: "running",
  task_completed: "completed",
  step_completed: "completed",
  task_failed: "failed",
};

function toTaskStatus(value: unknown): TaskStatus | undefined {
  if (typeof value !== "string" || !TASK_STATUSES.includes(value)) return undefined;
  return value as TaskStatus;
}

export function useEventBus() {
  const [isConnected, setIsConnected] = useState(false);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const abortControllers = useRef<Map<string, AbortController>>(new Map());
  const reconnectTimers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());
  // Keys the caller asked to be connected, independent of whether a socket is
  // currently open. Before this existed, `abortControllers` had to play both
  // roles: a mid-stream failure left the *dead* controller registered, so
  // `connectSSE` refused the retry ("already connected") and the scheduled
  // reconnect silently no-op'ed — a dropped stream never recovered.
  const desired = useRef<Set<string>>(new Set());

  const { updateAgent, setAgents } = useAgentStore();
  const { updateTask } = useTaskStore();
  const { updateSystemMetrics } = useSystemStore();

  const connectedRef = useRef(false);

  // `connectSSE` and `scheduleReconnect` are mutually recursive: a dropped
  // connection schedules a retry, and the retry connects. Listing either one as
  // a dependency of the other closes the cycle, and rebuilding either would
  // rebuild `startSSEConnections` — the identity every caller holds on to.
  //
  // The cycle is broken in ONE direction only. `scheduleReconnect` is declared
  // first and permanently stable (empty deps: it only touches refs and a
  // constant), so `connectSSE` can list it honestly. The other hop goes
  // through a ref that is published on mount, which is what stops
  // `exhaustive-deps` from seeing a cycle — and stops `useCallback` from
  // reading `scheduleReconnect` before its `const` is initialised.
  const connectRef = useRef<ConnectFn | null>(null);

  const scheduleReconnect = useCallback(
    (url: string, storeKey: string, onData: SseHandler) => {
      const existing = reconnectTimers.current.get(storeKey);
      if (existing) clearTimeout(existing);

      const timer = setTimeout(() => {
        reconnectTimers.current.delete(storeKey);
        // Only retry while the caller still wants this stream. A deliberate
        // `disconnectSSE`/`stopBus` removes the key, so a pending retry cannot
        // resurrect a bus the user closed.
        if (!desired.current.has(storeKey)) return;
        if (abortControllers.current.get(storeKey)) return;
        connectRef.current?.(url, storeKey, onData);
      }, RECONNECT_DELAY_MS);

      reconnectTimers.current.set(storeKey, timer);
    },
    [],
  );

  const connectSSE = useCallback<ConnectFn>(
    (url, storeKey, onData) => {
      desired.current.add(storeKey);
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
              if (controller.signal.aborted) return;
              // Release the key first: `connectSSE` refuses to open a second
              // socket for a storeKey that still has a controller, and this one
              // is finished. The key stays in `desired`, so the retry below is
              // still wanted — it just has to be allowed to happen.
              if (abortControllers.current.get(storeKey) === controller) {
                abortControllers.current.delete(storeKey);
              }
              console.warn(`SSE stream ${storeKey} error:`, err);
              scheduleReconnect(url, storeKey, onData);
            });
          }
          read();
        })
        .catch((err) => {
          if (controller.signal.aborted) return;
          if (abortControllers.current.get(storeKey) === controller) {
            abortControllers.current.delete(storeKey);
          }
          setConnectionError(`Falha ao ligar a ${storeKey}`);
          setIsConnected(false);
          connectedRef.current = false;
          console.warn(`SSE connection ${storeKey} failed:`, err);
          scheduleReconnect(url, storeKey, onData);
        });
    },
    [scheduleReconnect],
  );

  useEffect(() => {
    connectRef.current = connectSSE;
  }, [connectSSE]);

  const disconnectSSE = useCallback((storeKey: string) => {
    desired.current.delete(storeKey);
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
      if (!isRecord(data)) return;
      const metrics = data as MetricsFrame;
      const patch: Partial<SystemMetrics> = {};
      const fields = [
        ["cpuUsage", metrics.cpu_usage],
        ["memoryUsage", metrics.memory_usage],
        ["gpuUsage", metrics.gpu_usage],
        ["diskUsage", metrics.disk_usage],
        ["networkIn", metrics.network_in],
        ["networkOut", metrics.network_out],
        ["activeConnections", metrics.active_connections],
        ["queueSize", metrics.queue_size],
        ["avgResponseTime", metrics.avg_response_time_ms],
        ["tokensPerSecond", metrics.tokens_per_second],
        ["cacheHitRate", metrics.cache_hit_rate],
        ["apiErrorsPerMin", metrics.error_rate],
      ] as const;
      for (const [field, value] of fields) {
        const measured = finiteNumber(value);
        if (measured !== undefined) patch[field] = measured;
      }

      const requestsPerSecond = finiteNumber(metrics.requests_per_second);
      if (requestsPerSecond !== undefined) {
        // Both spellings exist in `SystemMetrics`; retain the legacy alias
        // while keeping the field read by System Health current as well.
        patch.requestsPerSec = requestsPerSecond;
        patch.requestsPerSecond = requestsPerSecond;
      }
      const timestamp = finiteNumber(metrics.timestamp);
      if (timestamp !== undefined) patch.timestamp = timestamp;

      // A timestamp alone is not telemetry. Empty or malformed frames leave
      // the previous measurements and their availability signal untouched.
      if (Object.keys(patch).some((field) => field !== "timestamp")) {
        updateSystemMetrics(patch);
      } else if (timestamp !== undefined) {
        updateSystemMetrics({ timestamp });
      }
    });

    // Connect to the autonomous-tasks/stream for task & agent events
    connectSSE("/api/autonomous-tasks/stream", "tasks", (data) => {
      if (!isRecord(data)) return;
      const ev = data as TaskStreamFrame;
      // Accept both canonical StreamEvent types and legacy formats
      // Canonical: type="task_scheduled", type="agent_started", type="goal", etc.
      // Legacy:    type="task" (with .task sub-object), type="agent_instance"
      if (ev.type && ev.type in TASK_STATUS_BY_EVENT) {
        // Update task store from event
        const taskId = ev.task?.id ?? ev.task_id;
        if (taskId) {
          updateTask(taskId, {
            status: toTaskStatus(ev.task?.status) ?? TASK_STATUS_BY_EVENT[ev.type],
          });
        }
      }
      if (ev.type === "agent_instance" || ev.type === "agent_started" ||
          ev.type === "agent_finished" || ev.type === "agent_failed" ||
          ev.type === "agent_retry") {
        // Update agent store from event
        const agentId = ev.agent_instance?.agent_id ?? ev.agent;
        if (agentId) {
          updateAgent(agentId, { status: ev.agent_instance?.state || "idle" });
        }
      }
    });

    // Connect to topology stream for graph data
    connectSSE("/api/agents/topology/stream", "topology", (data) => {
      if (!Array.isArray(data)) return;
      const agents = data as TopologyAgentFrame[];
      setAgents(agents.map((a) => mapApiAgent({
        id: a.agentId || a.id,
        name: a.agentType || a.agentId,
        status: a.status,
        task: a.task || "",
      })));
    });

    setIsConnected(true);
    connectedRef.current = true;
  }, [connectSSE, updateAgent, updateTask, setAgents, updateSystemMetrics]);

  const stopBus = useCallback(() => {
    // `disconnectSSE` is the single per-stream teardown: it aborts the socket
    // AND drops the key from `desired`, which is what makes any reconnect
    // timer that is already pending a no-op.
    for (const key of [...abortControllers.current.keys()]) {
      disconnectSSE(key);
    }
    // Streams that were mid-reconnect (no live controller) are not in the map
    // above, so drain their timers and unregister them explicitly.
    for (const key of [...reconnectTimers.current.keys()]) {
      disconnectSSE(key);
    }

    setIsConnected(false);
    connectedRef.current = false;
  }, [disconnectSSE]);

  const startBus = useCallback(() => {
    if (connectedRef.current) return;
    startSSEConnections();
  }, [startSSEConnections]);

  return { startBus, stopBus, isConnected, connectionError };
}
