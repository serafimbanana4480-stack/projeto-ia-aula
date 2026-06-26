"use client";

import { create, type StoreApi } from "zustand";
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

interface SystemStore {
  metrics: SystemMetrics;
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

function deriveStatus(metrics: SystemMetrics): SystemStore["globalStatus"] {
  if (metrics.hallucinationAlerts > 2 || metrics.agentFailures > 1) return "degraded";
  if (metrics.apiErrorsPerMin > 5) return "incident";
  return "operational";
}

export const useSystemStore = create<SystemStore>((set) => ({
  metrics: { ...DEFAULT_METRICS },
  isLive: false,
  isLoading: false,
  error: null,
  globalStatus: "operational",

  updateSystemMetrics: (patch) => {
    set((s) => {
      const newMetrics = { ...s.metrics, ...patch };
      return { metrics: newMetrics, globalStatus: deriveStatus(newMetrics) };
    });
  },

  fetchMetrics: async () => {
    set({ isLoading: true, error: null });
    try {
      const res = await fetch(apiUrl("/api/metrics/current"));
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const mapped: Partial<SystemMetrics> = {
        cpuUsage: data.cpu_percent ?? data.cpuUsage ?? 0,
        memoryUsage: data.ram_percent ?? data.memoryUsage ?? 0,
        gpuUsage: data.gpu_usage ?? data.gpuUsage ?? 0,
        diskUsage: data.disk_percent ?? data.diskUsage ?? 0,
        networkIn: data.network_in ?? data.networkIn ?? 0,
        networkOut: data.network_out ?? data.networkOut ?? 0,
        activeConnections: data.active_connections ?? data.activeConnections ?? 0,
        queueSize: data.queue_size ?? data.queueSize ?? 0,
        vectorDbQueriesPerSec: data.vector_db_qps ?? data.vectorDbQueriesPerSec ?? 0,
        embeddingThroughput: data.embedding_throughput ?? data.embeddingThroughput ?? 0,
        cacheHitRate: data.cache_hit_rate ?? data.cacheHitRate ?? 0,
        apiErrorsPerMin: data.api_errors_per_min ?? data.apiErrorsPerMin ?? 0,
        hallucinationAlerts: data.hallucination_alerts ?? data.hallucinationAlerts ?? 0,
        agentFailures: data.agent_failures ?? data.agentFailures ?? 0,
        avgResponseTime: data.avg_latency_ms ?? data.avgResponseTime ?? 0,
        requestsPerSec: data.requests_per_sec ?? data.requestsPerSec ?? 0,
        totalTokensToday: data.total_tokens_today ?? data.totalTokensToday ?? 0,
        costToday: data.cost_today ?? data.costToday ?? 0,
        activeWorkflows: data.active_workflows ?? data.activeWorkflows ?? 0,
        pendingTasks: data.pending_tasks ?? data.pendingTasks ?? 0,
        runningAgents: data.running_agents ?? data.runningAgents ?? 0,
        timestamp: data.timestamp ?? Date.now(),
      };
      set({
        metrics: { ...DEFAULT_METRICS, ...mapped },
        isLive: true,
        isLoading: false,
        globalStatus: deriveStatus({ ...DEFAULT_METRICS, ...mapped } as SystemMetrics),
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
