/**
 * Metrics Store — Single source of truth for all dashboard metrics.
 *
 * Eliminates redundant fetches across components. One SSE connection
 * feeds all subscribers. Polling fallback when SSE unavailable.
 */
import { create } from "zustand";
import { apiUrl, authHeaders } from "../lib/api";
import { getAccessToken, isAuthenticated } from "../lib/auth";

export interface SystemMetrics {
  tokens_per_second: number;
  active_model: string;
  active_sessions: number;
  queue_depth: number;
  ram_used_bytes: number;
  ram_total_bytes: number;
  ram_percent: number;
  cpu_percent: number;
  disk_used_bytes: number;
  disk_total_bytes: number;
  disk_percent: number;
  uptime_seconds: number;
  requests_total: number;
  requests_successful: number;
  requests_failed: number;
  avg_latency_ms: number;
  timestamp: number;
  message_stats?: {
    total_messages: number;
    sessions_with_messages: number;
    tokens_out_total?: number;
    tokens_in_total?: number;
    avg_latency_ms?: number;
  };
  change_stats?: {
    total_changes: number;
    files_modified: number;
  };
  agent_activity?: Array<{
    agent: string;
    status: "idle" | "active" | "error";
    tasks_completed: number;
    tasks_failed: number;
    avg_latency_ms: number;
    last_activity: string;
  }>;
}

interface MetricsState {
  metrics: SystemMetrics | null;
  history: SystemMetrics[];
  backendOnline: boolean;
  connectionStatus: "connecting" | "connected" | "degraded" | "offline";
  connectionMode: "none" | "sse" | "polling";
  lastUpdate: string;

  // Actions
  _setMetrics: (m: SystemMetrics) => void;
  _setBackendOnline: (online: boolean) => void;
  _setConnectionStatus: (status: MetricsState["connectionStatus"]) => void;
  _setConnectionMode: (mode: MetricsState["connectionMode"]) => void;
}

export const useMetricsStore = create<MetricsState>((set) => ({
  metrics: null,
  history: [],
  backendOnline: false,
  connectionStatus: "connecting",
  connectionMode: "none",
  lastUpdate: "—",

  _setMetrics: (m) =>
    set((state) => {
      const total = m.requests_total ?? 0;
      const failed = m.requests_failed ?? 0;
      const successRate = total > 0 ? (m.requests_successful ?? 0) / total : 1;
      let connectionStatus: MetricsState["connectionStatus"] = "connected";
      if (total > 0 && successRate === 0) {
        connectionStatus = "degraded";
      }
      return {
        metrics: m,
        history: [...state.history.slice(-99), m],
        lastUpdate: new Date().toLocaleTimeString(),
        backendOnline: true,
        connectionStatus,
      };
    }),
  _setBackendOnline: (online) => set({ backendOnline: online }),
  _setConnectionStatus: (status) => set({ connectionStatus: status }),
  _setConnectionMode: (mode) => set({ connectionMode: mode }),
}));

// ── Singleton SSE manager ────────────────────────────────────────────────
let sseInstance: EventSource | null = null;
let pollingTimer: ReturnType<typeof setInterval> | null = null;
let isInitialized = false;
let isStopped = false;
let backoffTimer: ReturnType<typeof setTimeout> | null = null;
let authHeartbeat: ReturnType<typeof setInterval> | null = null;

function clearBackoff() {
  if (backoffTimer) {
    clearTimeout(backoffTimer);
    backoffTimer = null;
  }
}

function startAuthHeartbeat() {
  if (authHeartbeat) return;
  authHeartbeat = setInterval(() => {
    if (isAuthenticated() && (!isInitialized || isStopped)) {
      initMetricsStream();
    }
  }, 5000);
}

function stopAuthHeartbeat() {
  if (authHeartbeat) {
    clearInterval(authHeartbeat);
    authHeartbeat = null;
  }
}

function stopAll() {
  clearBackoff();
  if (sseInstance) {
    sseInstance.close();
    sseInstance = null;
  }
  if (pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
}

async function fetchMetrics() {
  if (!isAuthenticated()) {
    if (sseInstance || pollingTimer) {
      stopAll();
    }
    return false;
  }

  try {
    const response = await fetch(apiUrl("/api/metrics/current"), {
      headers: authHeaders(),
      signal: AbortSignal.timeout(5000),
    });

    if (response.status === 401) {
      useMetricsStore.getState()._setBackendOnline(false);
      useMetricsStore.getState()._setConnectionStatus("offline");
      useMetricsStore.getState()._setConnectionMode("none");
      return false;
    }

    if (response.ok) {
      const data = (await response.json()) as SystemMetrics;
      useMetricsStore.getState()._setMetrics(data);
      useMetricsStore.getState()._setConnectionMode(
        useMetricsStore.getState().connectionMode === "sse" ? "sse" : "polling",
      );
      return true;
    }
  } catch {
    /* ignore */
  }
  useMetricsStore.getState()._setBackendOnline(false);
  useMetricsStore.getState()._setConnectionStatus("offline");
  useMetricsStore.getState()._setConnectionMode("none");
  return false;
}

function startSSE() {
  stopAll();

  if (isStopped) return;

  const token = getAccessToken();
  if (!token) {
    startPolling();
    return;
  }

  try {
    const streamUrl = `${apiUrl("/api/dashboard/stream")}?token=${encodeURIComponent(token)}`;
    const es = new EventSource(streamUrl);
    sseInstance = es;

    es.onopen = () => {
      useMetricsStore.getState()._setConnectionMode("sse");
    };

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as SystemMetrics;
        useMetricsStore.getState()._setMetrics(data);
      } catch {
        /* ignore parse errors */
      }
    };

    let errorHandled = false;
    es.onerror = () => {
      if (errorHandled) return;
      errorHandled = true;

      es.close();
      sseInstance = null;

      if (!isStopped) {
        clearBackoff();
        backoffTimer = setTimeout(() => {
          backoffTimer = null;
          if (!isStopped) {
            startPolling();
          }
        }, 2000);
      }
    };
  } catch {
    if (!isStopped) {
      startPolling();
    }
  }
}

function startPolling() {
  if (pollingTimer || isStopped) return;
  if (!isAuthenticated()) return;

  useMetricsStore.getState()._setConnectionMode("polling");
  fetchMetrics(); // immediate
  pollingTimer = setInterval(fetchMetrics, 3000);
}

/** Initialize the metrics stream (SSE → polling fallback). Idempotent. */
export function initMetricsStream() {
  clearBackoff();

  // Allow restart after an auth failure stopped the stream.
  if (isInitialized && !isStopped) return;

  // Do not start if user is not authenticated yet
  if (!isAuthenticated()) {
    isInitialized = false;
    isStopped = false;
    startAuthHeartbeat();
    return;
  }

  isInitialized = true;
  isStopped = false;
  startAuthHeartbeat();
  useMetricsStore.getState()._setConnectionStatus("connecting");
  // Establish polling first so "connected" reflects a real metrics payload.
  startPolling();
  startSSE();
}

/** Stop all metrics streaming. Call on app unmount if needed. */
export function stopMetricsStream() {
  stopAuthHeartbeat();
  isInitialized = false;
  isStopped = true;
  stopAll();
}

/** Force a manual refresh of metrics. */
export async function refreshMetrics(): Promise<boolean> {
  return fetchMetrics();
}
