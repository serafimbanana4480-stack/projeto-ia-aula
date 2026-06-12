/**
 * Metrics Store — Single source of truth for all dashboard metrics.
 *
 * Eliminates redundant fetches across components. One SSE connection
 * feeds all subscribers. Polling fallback when SSE unavailable.
 */
import { create } from "zustand";
import { apiUrl, authHeaders } from "../lib/api";
import { isAuthenticated } from "../lib/auth";

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
  connectionStatus: "connecting" | "connected" | "offline";
  lastUpdate: string;

  // Actions
  _setMetrics: (m: SystemMetrics) => void;
  _setBackendOnline: (online: boolean) => void;
  _setConnectionStatus: (status: MetricsState["connectionStatus"]) => void;
}

export const useMetricsStore = create<MetricsState>((set) => ({
  metrics: null,
  history: [],
  backendOnline: false,
  connectionStatus: "connecting",
  lastUpdate: "—",

  _setMetrics: (m) =>
    set((state) => ({
      metrics: m,
      history: [...state.history.slice(-99), m],
      lastUpdate: new Date().toLocaleTimeString(),
    })),
  _setBackendOnline: (online) => set({ backendOnline: online }),
  _setConnectionStatus: (status) => set({ connectionStatus: status }),
}));

// ── Singleton SSE manager ────────────────────────────────────────────────
let sseInstance: EventSource | null = null;
let pollingTimer: ReturnType<typeof setInterval> | null = null;
let isInitialized = false;
let isStopped = false;

function stopAll() {
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
  try {
    const response = await fetch(apiUrl("/api/metrics/current"), {
      headers: authHeaders(),
      signal: AbortSignal.timeout(5000),
    });

    if (response.status === 401) {
      // Stop everything on auth failure — don't retry
      stopAll();
      isStopped = true;
      useMetricsStore.getState()._setConnectionStatus("offline");
      return false;
    }

    if (response.ok) {
      const data = (await response.json()) as SystemMetrics;
      useMetricsStore.getState()._setMetrics(data);
      useMetricsStore.getState()._setBackendOnline(true);
      useMetricsStore.getState()._setConnectionStatus("connected");
      return true;
    }
  } catch {
    /* ignore */
  }
  useMetricsStore.getState()._setBackendOnline(false);
  useMetricsStore.getState()._setConnectionStatus("offline");
  return false;
}

function startSSE() {
  stopAll();

  if (isStopped) return;

  try {
    const es = new EventSource(apiUrl("/api/dashboard/stream"), {
      withCredentials: true,
    });
    sseInstance = es;

    es.onopen = () => {
      useMetricsStore.getState()._setConnectionStatus("connected");
    };

    es.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data) as SystemMetrics;
        useMetricsStore.getState()._setMetrics(data);
        useMetricsStore.getState()._setBackendOnline(true);
      } catch {
        /* ignore parse errors */
      }
    };

    es.onerror = () => {
      useMetricsStore.getState()._setConnectionStatus("offline");
      es.close();
      sseInstance = null;
      // Fallback to polling only if not explicitly stopped
      if (!isStopped) {
        startPolling();
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
  fetchMetrics(); // immediate
  pollingTimer = setInterval(fetchMetrics, 3000);
}

/** Initialize the metrics stream (SSE → polling fallback). Idempotent. */
export function initMetricsStream() {
  // Allow restart after an auth failure stopped the stream.
  if (isInitialized && !isStopped) return;

  // Do not start if user is not authenticated
  if (!isAuthenticated()) return;

  isInitialized = true;
  isStopped = false;
  startSSE();
}

/** Stop all metrics streaming. Call on app unmount if needed. */
export function stopMetricsStream() {
  isInitialized = false;
  isStopped = true;
  stopAll();
}

/** Force a manual refresh of metrics. */
export async function refreshMetrics(): Promise<boolean> {
  return fetchMetrics();
}
