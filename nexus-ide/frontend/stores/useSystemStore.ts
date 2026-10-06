"use client";

import { create } from "zustand";
import { apiUrl } from "../lib/api";

export interface SystemMetrics {
  cpuUsage: number;
  memoryUsage: number;
  gpuUsage: number;
  diskUsage: number;
  networkIn: number;
  networkOut: number;
  activeConnections: number;
  queueSize: number;
  vectorDbQueriesPerSec: number;
  embeddingThroughput: number;
  cacheHitRate: number;
  apiErrorsPerMin: number;
  hallucinationAlerts: number;
  agentFailures: number;
  avgResponseTime: number;
  avgResponseTimeMs?: number;
  requestsPerSec: number;
  requestsPerSecond?: number;
  totalTokensToday: number;
  costToday: number;
  activeWorkflows: number;
  pendingTasks: number;
  runningAgents: number;
  tokensPerSecond?: number;
  timestamp?: number;
}

export type SystemMetricField = Exclude<keyof SystemMetrics, "timestamp">;
export type MeasuredSystemMetrics = Partial<Record<SystemMetricField, true>>;

interface SystemStore {
  metrics: SystemMetrics;
  /** True when the latest successful response included at least one measured metric. */
  hasTelemetry: boolean;
  /** Fields present in the latest successful response; absent fields are not zero. */
  measuredMetrics: MeasuredSystemMetrics;
  isLive: boolean;
  isLoading: boolean;
  error: string | null;
  globalStatus: "operational" | "degraded" | "incident" | "maintenance";
  updateSystemMetrics: (patch: Partial<SystemMetrics>) => void;
  fetchMetrics: () => Promise<void>;
  setLoading: (loading: boolean) => void;
  setError: (error: string | null) => void;
}

const DEFAULT_METRICS: SystemMetrics = {
  cpuUsage: 0,
  memoryUsage: 0,
  gpuUsage: 0,
  diskUsage: 0,
  networkIn: 0,
  networkOut: 0,
  activeConnections: 0,
  queueSize: 0,
  vectorDbQueriesPerSec: 0,
  embeddingThroughput: 0,
  cacheHitRate: 0,
  apiErrorsPerMin: 0,
  hallucinationAlerts: 0,
  agentFailures: 0,
  avgResponseTime: 0,
  requestsPerSec: 0,
  totalTokensToday: 0,
  costToday: 0,
  activeWorkflows: 0,
  pendingTasks: 0,
  runningAgents: 0,
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteNumber(record: Record<string, unknown>, ...keys: string[]): number | undefined {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === "number" && Number.isFinite(value)) return value;
  }
  return undefined;
}

function deriveStatus(metrics: SystemMetrics): SystemStore["globalStatus"] {
  if (metrics.hallucinationAlerts > 2 || metrics.agentFailures > 1) return "degraded";
  if (metrics.apiErrorsPerMin > 5) return "incident";
  return "operational";
}

export const useSystemStore = create<SystemStore>((set) => ({
  metrics: { ...DEFAULT_METRICS },
  hasTelemetry: false,
  measuredMetrics: {},
  isLive: false,
  isLoading: false,
  error: null,
  globalStatus: "operational",

  updateSystemMetrics: (patch) => {
    set((s) => {
      const newMetrics = { ...s.metrics, ...patch };
      const measuredMetrics = { ...s.measuredMetrics };
      for (const [field, value] of Object.entries(patch)) {
        if (
          field !== "timestamp" &&
          typeof value === "number" &&
          Number.isFinite(value)
        ) {
          measuredMetrics[field as SystemMetricField] = true;
        }
      }
      return {
        metrics: newMetrics,
        measuredMetrics,
        hasTelemetry: Object.keys(measuredMetrics).length > 0,
        globalStatus: deriveStatus(newMetrics),
      };
    });
  },

  fetchMetrics: async () => {
    set({ isLoading: true, error: null });
    try {
      const res = await fetch(apiUrl("/api/metrics/current"));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const payload: unknown = await res.json();
      if (!isRecord(payload)) {
        set({
          isLive: true,
          isLoading: false,
          hasTelemetry: false,
          measuredMetrics: {},
          error: "A API devolveu um formato de métricas inválido.",
        });
        return;
      }

      const mapped: Partial<SystemMetrics> = {};
      const measuredMetrics: MeasuredSystemMetrics = {};
      const mapNumber = (
        field: SystemMetricField,
        ...aliases: string[]
      ) => {
        const value = finiteNumber(payload, ...aliases);
        if (value === undefined) return;
        mapped[field] = value;
        measuredMetrics[field] = true;
      };

      // These aliases include the current /api/metrics/current contract as
      // well as older camelCase/SSE fields. Missing fields remain unmeasured.
      mapNumber("cpuUsage", "cpu_percent", "cpuUsage");
      mapNumber("memoryUsage", "ram_percent", "memoryUsage");
      mapNumber("gpuUsage", "gpu_usage", "gpuUsage");
      mapNumber("diskUsage", "disk_percent", "diskUsage");
      mapNumber("networkIn", "network_in", "networkIn");
      mapNumber("networkOut", "network_out", "networkOut");
      mapNumber("activeConnections", "active_connections", "activeConnections");
      mapNumber("queueSize", "queue_depth", "queue_size", "queueSize");
      mapNumber("vectorDbQueriesPerSec", "vector_db_qps", "vectorDbQueriesPerSec");
      mapNumber("embeddingThroughput", "embedding_throughput", "embeddingThroughput");
      mapNumber("cacheHitRate", "cache_hit_rate", "cacheHitRate");
      mapNumber("apiErrorsPerMin", "api_errors_per_min", "apiErrorsPerMin");
      mapNumber("hallucinationAlerts", "hallucination_alerts", "hallucinationAlerts");
      mapNumber("agentFailures", "agent_failures", "agentFailures");
      mapNumber("avgResponseTime", "avg_latency_ms", "avgResponseTime");
      mapNumber("tokensPerSecond", "tokens_per_second", "tokensPerSecond");
      mapNumber("requestsPerSec", "requests_per_sec", "requestsPerSec");
      mapNumber("totalTokensToday", "total_tokens_today", "totalTokensToday");
      mapNumber("costToday", "cost_today", "costToday");
      mapNumber("activeWorkflows", "active_workflows", "activeWorkflows");
      mapNumber("pendingTasks", "pending_tasks", "pendingTasks");
      mapNumber("runningAgents", "running_agents", "runningAgents");
      const timestamp = finiteNumber(payload, "timestamp");
      mapped.timestamp = timestamp ?? Date.now();

      if (Object.keys(measuredMetrics).length === 0) {
        // A 2xx response proves the endpoint answered, not that it supplied
        // telemetry. Keep the last values internally, but mark every field as
        // unavailable so the UI cannot present stale/default zeros as current.
        set({
          isLive: true,
          isLoading: false,
          hasTelemetry: false,
          measuredMetrics: {},
          error: "A API respondeu sem dados de telemetria.",
        });
        return;
      }

      set((state) => {
        const metrics = { ...state.metrics, ...mapped };
        return {
          metrics,
          measuredMetrics,
          hasTelemetry: true,
          isLive: true,
          isLoading: false,
          error: null,
          globalStatus: deriveStatus(metrics),
        };
      });
    } catch (err) {
      set({
        isLoading: false,
        isLive: false,
        error: err instanceof Error ? err.message : "Failed to fetch metrics",
      });
    }
  },

  setLoading: (loading) => set({ isLoading: loading }),
  setError: (error) => set({ error }),
}));
