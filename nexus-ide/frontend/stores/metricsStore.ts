/**
 * Metrics Store — Single source of truth for all dashboard metrics.
 *
 * Eliminates redundant fetches across components. One SSE connection
 * feeds all subscribers. Polling fallback when SSE unavailable.
 */
import { create } from "zustand";
import { apiUrl } from "../lib/api";

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
  };
  change_stats?: {
    total_changes: number;
    files_modified: number;
  };
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
      signal: AbortSignal.timeout(5000),
    });
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

  try {
    const es = new EventSource(apiUrl("/api/dashboard/stream"));
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
      // Fallback to polling
      startPolling();
    };
  } catch {
    startPolling();
  }
}

function startPolling() {
  if (pollingTimer) return;
  fetchMetrics(); // immediate
  pollingTimer = setInterval(fetchMetrics, 3000);
}

/** Initialize the metrics stream (SSE → polling fallback). Idempotent. */
export function initMetricsStream() {
  if (isInitialized) return;
  isInitialized = true;
  startSSE();
}

/** Stop all metrics streaming. Call on app unmount if needed. */
export function stopMetricsStream() {
  isInitialized = false;
  stopAll();
}

/** Force a manual refresh of metrics. */
export async function refreshMetrics(): Promise<boolean> {
  return fetchMetrics();
}
