"use client";

import { useCallback, useMemo, useState } from "react";
import { apiUrl, authHeaders } from "../../lib/api";
import { useMetricsStore } from "../../stores/metricsStore";
import { usePolling } from "../../hooks/usePolling";
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

const PRIORITY_CONFIG: Record<
  GuardianSuggestion["priority"],
  { color: string; label: string; dot: string }
> = {
  critical: { color: "bg-red-500/15 text-red-400 border-red-500/30", label: "Crítico", dot: "bg-red-400" },
  high: { color: "bg-orange-500/15 text-orange-400 border-orange-500/30", label: "Alta", dot: "bg-orange-400" },
  medium: { color: "bg-yellow-500/15 text-yellow-400 border-yellow-500/30", label: "Média", dot: "bg-yellow-400" },
  low: { color: "bg-blue-500/15 text-blue-400 border-blue-500/30", label: "Baixa", dot: "bg-blue-400" },
};

const CATEGORY_LABELS: Record<string, string> = {
  performance: "Performance",
  reliability: "Fiabilidade",
  security: "Segurança",
  maintenance: "Manutenção",
  health: "Saúde",
};

function getHealthIndicator(status: GuardianStatus | null): {
  color: string;
  label: string;
  dot: string;
} {
  if (!status || !status.system_health)
    return { color: "text-gray-500", label: "Desconhecido", dot: "bg-gray-500" };
  const { cpu_percent, memory_percent, disk_percent } = status.system_health;
  const hasCritical = cpu_percent > 90 || memory_percent > 90 || disk_percent > 90;
  const hasWarning = cpu_percent > 70 || memory_percent > 80 || disk_percent > 80;
  if (hasCritical) return { color: "text-red-400", label: "Crítico", dot: "bg-red-400" };
  if (hasWarning) return { color: "text-yellow-400", label: "Aviso", dot: "bg-yellow-400" };
  return { color: "text-green-400", label: "Saudável", dot: "bg-green-400" };
}

function formatTimeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  if (diff < 60000) return `há ${Math.floor(diff / 1000)}s`;
  if (diff < 3600000) return `há ${Math.floor(diff / 60000)}m`;
  if (diff < 86400000) return `há ${Math.floor(diff / 3600000)}h`;
  return `há ${Math.floor(diff / 86400000)}d`;
}

export default function GuardianWidget() {
  const [applyingId, setApplyingId] = useState<string | null>(null);
  const [applyError, setApplyError] = useState<string | null>(null);

  const guardian = useMetricsStore((s) => s.guardian) as GuardianStatus | null;
  const guardianError = useMetricsStore((s) => s.guardianError);
  const guardianLoading = useMetricsStore((s) => s.guardianLoading);
  const setGuardian = useMetricsStore((s) => s.setGuardian);
  const setGuardianError = useMetricsStore((s) => s.setGuardianError);
  const setGuardianLoading = useMetricsStore((s) => s.setGuardianLoading);
  const backendOnline = useMetricsStore((s) => s.backendOnline);

  usePolling(
    useCallback(async () => {
      if (!backendOnline) {
        setGuardian(null);
        setGuardianError(null);
        setGuardianLoading(false);
        return;
      }
      setGuardianLoading(true);
      setGuardianError(null);
      try {
        const [statusRes, suggestionsRes] = await Promise.allSettled([
          fetch(apiUrl("/api/guardian/status"), {
            headers: authHeaders(),
            signal: AbortSignal.timeout(5000),
          }),
          fetch(apiUrl("/api/guardian/suggestions?limit=10"), {
            headers: authHeaders(),
            signal: AbortSignal.timeout(5000),
          }),
        ]);

        let status: GuardianStatus | null = null;
        let suggestions: GuardianSuggestion[] = [];

        if (statusRes.status === "fulfilled" && statusRes.value.ok) {
          status = (await statusRes.value.json()) as GuardianStatus;
        }
        if (suggestionsRes.status === "fulfilled" && suggestionsRes.value.ok) {
          const data = (await suggestionsRes.value.json()) as {
            suggestions?: GuardianSuggestion[];
          };
          suggestions = data.suggestions ?? [];
        }

        setGuardian({
          running: status?.running,
          system_health: status?.system_health,
          pending: status?.pending_suggestions,
          total: status?.total_suggestions,
          suggestions,
        });
      } catch (err) {
        setGuardianError(err instanceof Error ? err.message : "Falha ao carregar");
      } finally {
        setGuardianLoading(false);
      }
    }, [
      backendOnline,
      setGuardian,
      setGuardianError,
      setGuardianLoading,
    ]),
    30000,
    { enabled: backendOnline },
  );

  const applySuggestion = useCallback(
    async (id: string) => {
      setApplyError(null);
      setApplyingId(id);
      try {
        const response = await fetch(apiUrl(`/api/guardian/suggestions/${id}/apply`), {
          headers: authHeaders(),
          method: "POST",
          signal: AbortSignal.timeout(10000),
        });
        if (response.ok) {
          const current = useMetricsStore.getState().guardian;
          const suggestions = (current?.suggestions ?? []) as GuardianSuggestion[];
          setGuardian({
            ...current,
            suggestions: suggestions.filter((s) => s.id !== id),
            pending: Math.max(0, (current?.pending ?? 0) - 1),
          });
        } else {
          setApplyError("Falha ao aplicar sugestão");
        }
      } catch {
        setApplyError("Falha ao aplicar sugestão");
      } finally {
        setApplyingId(null);
      }
    },
    [setGuardian],
  );

  const health = useMemo(() => getHealthIndicator(guardian), [guardian]);
  const suggestions = (guardian?.suggestions ?? []) as GuardianSuggestion[];
  const pendingCount = guardian?.pending ?? 0;

  return (
    <section
      className="rounded border border-nexus-border bg-nexus-panel p-3"
      aria-labelledby="guardian-widget-title"
    >
      <div className="mb-3 flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2 min-w-0">
          <Shield className="h-4 w-4 text-nexus-accent" aria-hidden="true" />
          <h3 id="guardian-widget-title" className="text-sm font-semibold">
            Guardião
          </h3>
          <span
            className={`flex items-center gap-1.5 rounded px-2 py-0.5 text-xs border ${health.color}`}
          >
            <span className={`h-2 w-2 rounded-full ${health.dot}`} aria-hidden="true" />
            <span>{health.label}</span>
          </span>
          <span className="sr-only">Estado do sistema: {health.label}</span>
        </div>
        {pendingCount > 0 && (
          <span
            className="rounded bg-nexus-accent/15 px-1.5 py-0.5 text-[10px] text-nexus-accent"
            aria-label={`${pendingCount} pendentes`}
          >
            {pendingCount} pendentes
          </span>
        )}
      </div>

      {!backendOnline && (
        <div
          role="alert"
          className="mb-2 rounded border border-yellow-500/20 bg-yellow-500/5 px-3 py-1.5 text-xs text-yellow-400 flex items-center gap-2"
        >
          <AlertTriangle className="h-3 w-3" aria-hidden="true" />
          Backend offline — guardião indisponível
        </div>
      )}

      {guardianError && guardian && guardian.running === undefined && (
        <div
          role="alert"
          className="mb-2 rounded border border-red-500/20 bg-red-500/5 px-3 py-1.5 text-xs text-red-400 flex items-center gap-2"
        >
          <AlertTriangle className="h-3 w-3" aria-hidden="true" />
          Falha ao carregar: {guardianError}
        </div>
      )}

      {applyError && (
        <div
          role="alert"
          className="mb-2 rounded border border-red-500/20 bg-red-500/5 px-3 py-1.5 text-xs text-red-400 flex items-center gap-2"
        >
          <AlertTriangle className="h-3 w-3" aria-hidden="true" />
          {applyError}
        </div>
      )}

      {guardianLoading ? (
        <div
          className="flex h-24 items-center justify-center text-xs text-gray-500"
          role="status"
          aria-live="polite"
        >
          <Loader2 className="h-4 w-4 animate-spin mr-2" aria-hidden="true" />
          A carregar…
        </div>
      ) : (
        <div className="space-y-3">
          {guardian?.system_health && (
            <div
              className="grid grid-cols-3 gap-2"
              role="group"
              aria-label="Estado do sistema"
            >
              <HealthCard
                label="CPU"
                value={`${guardian.system_health.cpu_percent.toFixed(0)}%`}
                tone={percentTone(guardian.system_health.cpu_percent, 50, 80)}
              />
              <HealthCard
                label="RAM"
                value={`${guardian.system_health.memory_percent.toFixed(0)}%`}
                tone={percentTone(guardian.system_health.memory_percent, 60, 80)}
              />
              <HealthCard
                label="Latência"
                value={`${guardian.system_health.avg_latency_ms.toFixed(0)}ms`}
                tone={latencyTone(guardian.system_health.avg_latency_ms)}
              />
            </div>
          )}

          <div>
            <div
              className="mb-1.5 text-[10px] uppercase tracking-wider text-gray-500"
              id="guardian-suggestions-heading"
            >
              Sugestões do Guardião
            </div>
            {suggestions.length === 0 ? (
              <div
                className="flex h-16 flex-col items-center justify-center text-xs text-gray-500"
                role="status"
              >
                <CheckCircle2 className="h-5 w-5 text-green-500/50 mb-1" aria-hidden="true" />
                <span>Sem sugestões pendentes</span>
              </div>
            ) : (
              <ul
                role="list"
                aria-labelledby="guardian-suggestions-heading"
                className="space-y-1.5 max-h-52 overflow-y-auto text-xs sm:text-sm"
              >
                {suggestions.map((s) => {
                  const config = PRIORITY_CONFIG[s.priority] ?? PRIORITY_CONFIG.low;
                  return (
                    <li
                      key={s.id}
                      className={`rounded border px-2.5 py-2 ${config.color}`}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5 mb-0.5">
                            <span className={`h-1.5 w-1.5 rounded-full ${config.dot}`} aria-hidden="true" />
                            <span className="text-xs font-medium truncate">{s.title}</span>
                          </div>
                          <span className="sr-only">Prioridade: {config.label}</span>
                          <div className="text-[10px] text-gray-400 line-clamp-2">
                            {s.description}
                          </div>
                          <div className="mt-1 flex items-center gap-2 text-[10px] text-gray-500">
                            <span>{CATEGORY_LABELS[s.category] ?? s.category}</span>
                            <span aria-hidden="true">·</span>
                            <Clock className="h-3 w-3 inline" aria-hidden="true" />
                            <span>{formatTimeAgo(s.created_at)}</span>
                          </div>
                        </div>
                        {s.auto_apply_safe && (
                          <button
                            type="button"
                            onClick={() => applySuggestion(s.id)}
                            disabled={applyingId === s.id}
                            aria-label={`Aplicar sugestão: ${s.title}`}
                            className="shrink-0 inline-flex items-center gap-1 rounded bg-nexus-accent/20 px-2 py-1 text-[10px] text-nexus-accent hover:bg-nexus-accent/30 transition-colors disabled:opacity-50"
                          >
                            {applyingId === s.id ? (
                              <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                            ) : (
                              <Wrench className="h-3 w-3" aria-hidden="true" />
                            )}
                            Aplicar
                          </button>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

function percentTone(value: number, warn: number, danger: number): "green" | "yellow" | "red" {
  if (value > danger) return "red";
  if (value > warn) return "yellow";
  return "green";
}

function latencyTone(value: number): "green" | "yellow" | "red" {
  if (value > 1000) return "red";
  if (value > 500) return "yellow";
  return "green";
}

const TONE_CLASS: Record<"green" | "yellow" | "red", string> = {
  green: "text-green-400",
  yellow: "text-yellow-400",
  red: "text-red-400",
};

function HealthCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "green" | "yellow" | "red";
}) {
  return (
    <div className="rounded border border-nexus-border/50 bg-nexus-bg/50 p-2 text-center min-w-0">
      <div className="text-[10px] text-gray-500 mb-0.5">{label}</div>
      <div className={`text-xs font-mono font-semibold ${TONE_CLASS[tone]}`}>{value}</div>
    </div>
  );
}
