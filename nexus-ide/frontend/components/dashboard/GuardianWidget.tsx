"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { apiUrl } from "../../lib/api";
import { useMetricsStore } from "../../stores/metricsStore";
import {
  Shield,
  Wrench,
  Clock,
  CheckCircle2,
  Loader2,
  AlertTriangle,
} from "lucide-react";

export interface GuardianSuggestion {
  id: string;
  category: "performance" | "reliability" | "security" | "maintenance" | "health";
  priority: "low" | "medium" | "high" | "critical";
  title: string;
  description: string;
  created_at: string;
  auto_apply_safe: boolean;
  applied: boolean;
}

export interface GuardianStatus {
  agent: string;
  running: boolean;
  pending_suggestions: number;
  total_suggestions: number;
  system_health?: {
    cpu_percent: number;
    memory_percent: number;
    disk_percent: number;
    avg_latency_ms: number;
  };
}

const PRIORITY_CONFIG = {
  critical: { color: "bg-red-500/15 text-red-400 border-red-500/30", label: "Critical", dot: "bg-red-400" },
  high: { color: "bg-orange-500/15 text-orange-400 border-orange-500/30", label: "High", dot: "bg-orange-400" },
  medium: { color: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30", label: "Medium", dot: "bg-yellow-400" },
  low: { color: "bg-blue-500/15 text-blue-400 border-blue-500/30", label: "Low", dot: "bg-blue-400" },
};

const CATEGORY_LABELS: Record<string, string> = {
  performance: "Performance",
  reliability: "Reliability",
  security: "Security",
  maintenance: "Maintenance",
  health: "Health",
};

function getHealthIndicator(status: GuardianStatus | null) {
  if (!status || !status.system_health) return { color: "text-gray-500", label: "Unknown", dot: "bg-gray-500" };
  const { cpu_percent, memory_percent, disk_percent } = status.system_health;
  const hasCritical = cpu_percent > 90 || memory_percent > 90 || disk_percent > 90;
  const hasWarning = cpu_percent > 70 || memory_percent > 80 || disk_percent > 80;
  if (hasCritical) return { color: "text-red-400", label: "Critical", dot: "bg-red-400" };
  if (hasWarning) return { color: "text-yellow-400", label: "Warning", dot: "bg-yellow-400" };
  return { color: "text-green-400", label: "Healthy", dot: "bg-green-400" };
}

export default function GuardianWidget() {
  const [status, setStatus] = useState<GuardianStatus | null>(null);
  const [suggestions, setSuggestions] = useState<GuardianSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const backendOnline = useMetricsStore((s) => s.backendOnline);

  const fetchData = useCallback(async () => {
    if (!backendOnline) {
      setLoading(false);
      return;
    }
    try {
      const [statusRes, suggestionsRes] = await Promise.allSettled([
        fetch(apiUrl("/api/guardian/status"), { signal: AbortSignal.timeout(5000) }),
        fetch(apiUrl("/api/guardian/suggestions?limit=10"), { signal: AbortSignal.timeout(5000) }),
      ]);

      if (statusRes.status === "fulfilled" && statusRes.value.ok) {
        setStatus((await statusRes.value.json()) as GuardianStatus);
      }
      if (suggestionsRes.status === "fulfilled" && suggestionsRes.value.ok) {
        const data = (await suggestionsRes.value.json()) as { suggestions: GuardianSuggestion[] };
        setSuggestions(data.suggestions ?? []);
      }
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  }, [backendOnline]);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const applySuggestion = useCallback(
    async (id: string) => {
      setApplyingId(id);
      try {
        const response = await fetch(apiUrl(`/api/guardian/suggestions/${id}/apply`), {
          method: "POST",
          signal: AbortSignal.timeout(10000),
        });
        if (response.ok) {
          setSuggestions((prev) => prev.filter((s) => s.id !== id));
        }
      } catch {
        // ignore
      } finally {
        setApplyingId(null);
      }
    },
    []
  );

  const health = useMemo(() => getHealthIndicator(status), [status]);
  const pendingCount = status?.pending_suggestions ?? 0;

  return (
    <div className="rounded border border-nexus-border bg-nexus-panel p-3">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Shield className="h-4 w-4 text-nexus-accent" />
          <div className="text-sm font-semibold">Guardian</div>
          <div className={`flex items-center gap-1.5 rounded px-2 py-0.5 text-xs border ${health.color}`}>
            <span className={`h-2 w-2 rounded-full ${health.dot}`} />
            <span>{health.label}</span>
          </div>
        </div>
        {pendingCount > 0 && (
          <span className="rounded bg-nexus-accent/15 px-1.5 py-0.5 text-[10px] text-nexus-accent">
            {pendingCount} pending
          </span>
        )}
      </div>

      {!backendOnline && (
        <div className="mb-2 rounded border border-yellow-500/20 bg-yellow-500/5 px-3 py-1.5 text-xs text-yellow-400 flex items-center gap-2">
          <AlertTriangle className="h-3 w-3" />
          Backend offline — guardian unavailable
        </div>
      )}

      {loading ? (
        <div className="flex h-24 items-center justify-center text-xs text-gray-500">
          <Loader2 className="h-4 w-4 animate-spin mr-2" />
          Loading guardian status...
        </div>
      ) : (
        <div className="space-y-3">
          {/* System health mini summary */}
          {status?.system_health && (
            <div className="grid grid-cols-3 gap-2">
              <div className="rounded border border-nexus-border/50 bg-nexus-bg/50 p-2 text-center">
                <div className="text-[10px] text-gray-500 mb-0.5">CPU</div>
                <div
                  className={`text-xs font-mono font-semibold ${
                    status.system_health.cpu_percent > 80
                      ? "text-red-400"
                      : status.system_health.cpu_percent > 50
                      ? "text-yellow-400"
                      : "text-green-400"
                  }`}
                >
                  {status.system_health.cpu_percent.toFixed(0)}%
                </div>
              </div>
              <div className="rounded border border-nexus-border/50 bg-nexus-bg/50 p-2 text-center">
                <div className="text-[10px] text-gray-500 mb-0.5">RAM</div>
                <div
                  className={`text-xs font-mono font-semibold ${
                    status.system_health.memory_percent > 80
                      ? "text-red-400"
                      : status.system_health.memory_percent > 60
                      ? "text-yellow-400"
                      : "text-green-400"
                  }`}
                >
                  {status.system_health.memory_percent.toFixed(0)}%
                </div>
              </div>
              <div className="rounded border border-nexus-border/50 bg-nexus-bg/50 p-2 text-center">
                <div className="text-[10px] text-gray-500 mb-0.5">Latency</div>
                <div
                  className={`text-xs font-mono font-semibold ${
                    status.system_health.avg_latency_ms > 1000
                      ? "text-red-400"
                      : status.system_health.avg_latency_ms > 500
                      ? "text-yellow-400"
                      : "text-green-400"
                  }`}
                >
                  {status.system_health.avg_latency_ms.toFixed(0)}ms
                </div>
              </div>
            </div>
          )}

          {/* Suggestions list */}
          <div>
            <div className="mb-1.5 text-[10px] uppercase tracking-wider text-gray-500">
              Suggestions
            </div>
            {suggestions.length === 0 ? (
              <div className="flex h-16 flex-col items-center justify-center text-xs text-gray-500">
                <CheckCircle2 className="h-5 w-5 text-green-500/50 mb-1" />
                <span>No pending suggestions</span>
              </div>
            ) : (
              <div className="space-y-1.5 max-h-52 overflow-y-auto">
                {suggestions.map((s) => {
                  const config = PRIORITY_CONFIG[s.priority] ?? PRIORITY_CONFIG.low;
                  return (
                    <div
                      key={s.id}
                      className={`rounded border px-2.5 py-2 ${config.color}`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5 mb-0.5">
                            <span className={`h-1.5 w-1.5 rounded-full ${config.dot}`} />
                            <span className="text-xs font-medium truncate">{s.title}</span>
                          </div>
                          <div className="text-[10px] text-gray-400 line-clamp-2">
                            {s.description}
                          </div>
                          <div className="mt-1 flex items-center gap-2 text-[10px] text-gray-500">
                            <span>{CATEGORY_LABELS[s.category] ?? s.category}</span>
                            <span>·</span>
                            <Clock className="h-3 w-3 inline" />
                            <span>{formatTimeAgo(s.created_at)}</span>
                          </div>
                        </div>
                        {s.auto_apply_safe && (
                          <button
                            onClick={() => applySuggestion(s.id)}
                            disabled={applyingId === s.id}
                            className="shrink-0 inline-flex items-center gap-1 rounded bg-nexus-accent/20 px-2 py-1 text-[10px] text-nexus-accent hover:bg-nexus-accent/30 transition-colors disabled:opacity-50"
                          >
                            {applyingId === s.id ? (
                              <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                              <Wrench className="h-3 w-3" />
                            )}
                            Apply
                          </button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function formatTimeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  if (diff < 60000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3600000) return `${Math.floor(diff / 60000)}m ago`;
  if (diff < 86400000) return `${Math.floor(diff / 3600000)}h ago`;
  return `${Math.floor(diff / 86400000)}d ago`;
}
