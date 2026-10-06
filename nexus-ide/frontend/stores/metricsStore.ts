/**
 * Metrics Store — Single source of truth for all dashboard metrics.
 *
 * One poller feeds all subscribers, so N widgets cost one request per tick
 * instead of N. A 3 s interval is the transport: see the note above
 * `pollingTimer` for why there is no SSE branch.
 */
import { create } from "zustand";
import { apiUrl, authHeaders, getMetricsHistory } from "../lib/api";
import {
  authenticatedFetch,
  autoLoginDev,
  isAuthenticated,
  isAutoLoginEnabled,
} from "../lib/auth";

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
  connectionStatus: "connecting" | "connected" | "degraded" | "offline" | "auth_required";
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

// ── Singleton poller ───────────────────────────────────────────────────────
//
// There is deliberately no SSE path here. `/api/dashboard/stream` needs a
// bearer token, and native `EventSource` cannot send an Authorization header;
// the only ways to reach it are to put the token in the query string — which
// leaks it into browser history, proxies and Uvicorn access logs — or to move
// to `fetch`-based streaming. Until one of those is worth it, polling is the
// real transport. An earlier revision kept a full `EventSource` block behind an
// unconditional `return`, which made it look wired while being unreachable.
let pollingTimer: ReturnType<typeof setInterval> | null = null;
let isInitialized = false;
let isStopped = false;
let authHeartbeat: ReturnType<typeof setInterval> | null = null;
let authRecovery: Promise<boolean> | null = null;

function startAuthHeartbeat() {  if (authHeartbeat) return;
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

async function recoverMetricsAuth(): Promise<boolean> {
  if (!isAutoLoginEnabled()) return false;
  if (!authRecovery) {
    authRecovery = autoLoginDev().finally(() => {
      authRecovery = null;
    });
  }
  return authRecovery;
}

function stopAll() {
  if (pollingTimer) {
    clearInterval(pollingTimer);
    pollingTimer = null;
  }
}

async function fetchMetrics() {
  // In development, start polling before login finishes so the auth bootstrap
  // can recover. The endpoint still requires a valid JWT; a 401 is handled
  // below as an authentication state, not a connectivity failure.
  if (!isAuthenticated() && process.env.NODE_ENV !== "development") {
    if (pollingTimer) {
      stopAll();
    }
    return false;
  }

  try {
    const response = await authenticatedFetch(apiUrl("/api/metrics/current"), {
      headers: authHeaders(),
      signal: AbortSignal.timeout(5000),
    });

    if (response.status === 401) {
      useMetricsStore.getState()._setBackendOnline(true);
      useMetricsStore.getState()._setConnectionStatus("auth_required");
      useMetricsStore.getState()._setConnectionMode("none");
      // The next authenticated request may refresh the access token. Do not
      // leave the singleton latched after this transient authentication miss.
      isInitialized = false;
      isStopped = false;
      stopAll();
      startAuthHeartbeat();
      void recoverMetricsAuth().then((recovered) => {
        if (recovered) initMetricsStream();
      });
      return false;
    }

    if (response.ok) {
      const data = (await response.json()) as SystemMetrics;
      useMetricsStore.getState()._setMetrics(data);
      // `startPolling` already set the mode; re-asserting it here is a no-op
      // and only existed to preserve an "sse" value that could never be set.
      return true;
    }

    // An HTTP response proves the backend answered, even when the metrics
    // endpoint failed. Keep the last successful snapshot visible, but mark it
    // degraded and do not advance its freshness timestamp.
    useMetricsStore.getState()._setBackendOnline(true);
    useMetricsStore.getState()._setConnectionStatus("degraded");
  } catch {
    // Keep the heartbeat alive so a temporary backend restart can recover
    // without requiring a route change or a full browser reload.
    isInitialized = false;
    isStopped = false;
    stopAll();
    useMetricsStore.getState()._setBackendOnline(false);
    useMetricsStore.getState()._setConnectionStatus("offline");
    useMetricsStore.getState()._setConnectionMode("none");
    startAuthHeartbeat();
  }
  return false;
}

function startPolling() {
  if (pollingTimer || isStopped) return;
  // Development may start before login so auth bootstrap can recover, but the
  // endpoint still requires a JWT and reports missing auth as a 401.
  if (!isAuthenticated() && process.env.NODE_ENV !== "development") return;

  useMetricsStore.getState()._setConnectionMode("polling");
  fetchMetrics(); // immediate
  pollingTimer = setInterval(fetchMetrics, 3000);
}

/** Initialize metrics polling. Idempotent. */
export function initMetricsStream() {
  // Allow restart after an auth failure stopped the stream.
  if (isInitialized && !isStopped) return;

  // In development, start polling before authentication completes so the
  // bootstrap/recovery flow can run. Metrics endpoints still require a valid
  // JWT; in production we wait for authentication before polling.
  if (!isAuthenticated() && process.env.NODE_ENV !== "development") {
    isInitialized = false;
    isStopped = false;
    startAuthHeartbeat();
    return;
  }

  isInitialized = true;
  isStopped = false;
  startAuthHeartbeat();
  useMetricsStore.getState()._setConnectionStatus("connecting");
  // Polling is the only transport, and it sets "connected" itself once a real
  // metrics payload lands. This used to call `startSSE()` afterwards, which
  // tore the interval down again and restarted it for no reason.
  startPolling();
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
