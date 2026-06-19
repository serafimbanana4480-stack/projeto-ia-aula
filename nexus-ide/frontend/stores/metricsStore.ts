/**
 * Metrics Store — Single source of truth for all dashboard metrics.
 *
 * Eliminates redundant fetches across components. One SSE connection
 * feeds all subscribers. Polling fallback when SSE unavailable.
 */
import { create } from "zustand";
import { apiUrl, authHeaders, getMetricsHistory } from "../lib/api";
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

/** A single point in an aggregated historical metric series. */
export interface HistoryPoint {
  t: number;
  v: number;
}

interface MetricsState {
  metrics: SystemMetrics | null;
  history: SystemMetrics[];
  backendOnline: boolean;
  connectionStatus: "connecting" | "connected" | "degraded" | "offline";
  connectionMode: "none" | "sse" | "polling";
  lastUpdate: string;

  // Aggregated historical series (per metric key). Empty when offline/unavailable.
  historySeries: Record<string, HistoryPoint[]>;
  historyLoading: boolean;
  historyError: string | null;

  // ── Auxiliary cache for polled dashboard widgets ───────────────────────
  // Kept loose-typed intentionally: the AlertFeed / Guardian backend payloads
  // drift across versions and the widgets already coerce to their own local
  // interfaces (`AlertData`, `GuardianStatus`, ...). Defaults are empty/null
  // so a fresh store never breaks a consumer.
  alerts: unknown[];
  alertsError: string | null;
  alertsLoading: boolean;
  guardian: {
    running?: boolean;
    suggestions?: unknown[];
    system_health?: unknown;
    pending?: number;
    total?: number;
  } | null;
  guardianError: string | null;
  guardianLoading: boolean;

  // Actions
  _setMetrics: (m: SystemMetrics) => void;
  _setBackendOnline: (online: boolean) => void;
  _setConnectionStatus: (status: MetricsState["connectionStatus"]) => void;
  _setConnectionMode: (mode: MetricsState["connectionMode"]) => void;
  loadHistory: (metric: string, windowSeconds?: number) => Promise<void>;
  clearHistory: (metric?: string) => void;
  setAlerts: (list: unknown[]) => void;
  setAlertsError: (msg: string | null) => void;
  setAlertsLoading: (loading: boolean) => void;
  setGuardian: (
    data: {
      running?: boolean;
      suggestions?: unknown[];
      system_health?: unknown;
      pending?: number;
      total?: number;
    } | null,
  ) => void;
  setGuardianError: (msg: string | null) => void;
  setGuardianLoading: (loading: boolean) => void;
}

export const useMetricsStore = create<MetricsState>((set) => ({
  metrics: null,
  history: [],
  backendOnline: false,
  connectionStatus: "connecting",
  connectionMode: "none",
  lastUpdate: "—",
  historySeries: {},
  historyLoading: false,
  historyError: null,
  alerts: [],
  alertsError: null,
  alertsLoading: false,
  guardian: null,
  guardianError: null,
  guardianLoading: false,

    _setMetrics: (m) =>
    set((state) => {
      const total = m.requests_total ?? 0;
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

  loadHistory: async (metric, windowSeconds = 3600) => {
    set({ historyLoading: true, historyError: null });
    try {
      const raw = await getMetricsHistory(windowSeconds, metric);
      const series = normalizeHistorySeries(raw, metric);
      set((state) => ({
        historySeries: { ...state.historySeries, [metric]: series },
        historyLoading: false,
        historyError: null,
      }));
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to load metric history";
      set((state) => ({
        historySeries: { ...state.historySeries, [metric]: [] },
        historyLoading: false,
        historyError: message,
      }));
    }
  },

  clearHistory: (metric) =>
    set((state) => {
      if (!metric) {
        return { historySeries: {}, historyError: null };
      }
      const next = { ...state.historySeries };
      delete next[metric];
      return { historySeries: next };
    }),

  setAlerts: (list) => set({ alerts: Array.isArray(list) ? list : [], alertsError: null }),
  setAlertsError: (msg) => set({ alertsError: msg }),
  setAlertsLoading: (loading) => set({ alertsLoading: loading }),
  setGuardian: (data) => set({ guardian: data, guardianError: null }),
  setGuardianError: (msg) => set({ guardianError: msg }),
  setGuardianLoading: (loading) => set({ guardianLoading: loading }),
}));

/**
 * Normalize the assorted shapes returned by `/api/metrics/history` (and any
 * future backend variants) into a stable `{ t, v }[]` series.
 *
 * Accepts: arrays of `{timestamp|t|time, value|v}`; or wrapper objects with a
 * `data`/`history`/`points`/`series` array; or an object keyed by metric name
 * whose value is one of the above. Returns `[]` for anything unparseable so a
 * backend outage or schema drift never crashes the store or its consumers.
 */
function normalizeHistorySeries(
  raw: unknown,
  metric: string,
): HistoryPoint[] {
  if (!raw) return [];

  const isRecord = (v: unknown): v is Record<string, unknown> =>
    typeof v === "object" && v !== null && !Array.isArray(v);

  const toPoint = (item: unknown): HistoryPoint | null => {
    if (!isRecord(item)) return null;
    const tRaw = item.timestamp ?? item.t ?? item.time ?? item.ts;
    const vRaw = item.value ?? item.v ?? item[metric];
    const t = tRaw == null ? NaN : Number(tRaw);
    const v = vRaw == null ? NaN : Number(vRaw);
    if (Number.isNaN(t) || Number.isNaN(v)) return null;
    return { t, v };
  };

  const fromArray = (arr: unknown[]): HistoryPoint[] =>
    arr
      .map(toPoint)
      .filter((p): p is HistoryPoint => p !== null)
      .sort((a, b) => a.t - b.t);

  if (Array.isArray(raw)) return fromArray(raw);

  if (isRecord(raw)) {
    const bucketKeys = ["data", "history", "points", "series", "values"];
    for (const key of bucketKeys) {
      const bucket = raw[key];
      if (Array.isArray(bucket)) return fromArray(bucket);
    }
    const byMetric = raw[metric];
    if (Array.isArray(byMetric)) return fromArray(byMetric);
  }

  return [];
}

// ── Singleton SSE manager ────────────────────────────────────────────────
let sseInstance: EventSource | null = null;
let pollingTimer: ReturnType<typeof setInterval> | null = null;
let isInitialized = false;
let isStopped = false;
let backoffTimer: ReturnType<typeof setTimeout> | null = null;
let authHeartbeat: ReturnType<typeof setInterval> | null = null;

// SSE throttle: prevent re-render storms by limiting updates to one per 300ms
let lastSseUpdate = 0;
const SSE_THROTTLE_MS = 300;

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
      stopAuthHeartbeat();
      stopAll();
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
    stopAuthHeartbeat();
    stopAll();
    useMetricsStore.getState()._setBackendOnline(false);
    useMetricsStore.getState()._setConnectionStatus("offline");
    useMetricsStore.getState()._setConnectionMode("none");
  }
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
      const now = Date.now();
      if (now - lastSseUpdate < SSE_THROTTLE_MS) return;
      lastSseUpdate = now;
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
