"use client";

import { useCallback, useMemo, useState, type ReactNode } from "react";
import { apiUrl, authHeaders } from "../../lib/api";
import { useMetricsStore } from "../../stores/metricsStore";
import { usePolling } from "../../hooks/usePolling";
import {
  Shield,
  Wrench,
  Clock,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { Badge, StatusDot, Meter, EmptyState, Button } from "../ui/Primitives";

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
  suggestions?: GuardianSuggestion[];
  system_health?: {
    cpu_percent: number;
    memory_percent: number;
    disk_percent: number;
    avg_latency_ms: number;
  };
}

type Tone = "neutral" | "info" | "accent" | "success" | "warning" | "danger";

const PRIORITY_CONFIG: Record<GuardianSuggestion["priority"], { tone: Tone; label: string }> = {
  critical: { tone: "danger", label: "Crítico" },
  high: { tone: "warning", label: "Alta" },
  medium: { tone: "warning", label: "Média" },
  low: { tone: "info", label: "Baixa" },
};

const CATEGORY_LABELS: Record<string, string> = {
  performance: "Performance",
  reliability: "Fiabilidade",
  security: "Segurança",
  maintenance: "Manutenção",
  health: "Saúde",
};

function getHealthIndicator(status: GuardianStatus | null): { tone: Tone; label: string } {
  if (!status || !status.system_health) return { tone: "neutral", label: "Desconhecido" };
  const { cpu_percent, memory_percent, disk_percent } = status.system_health;
  const hasCritical = cpu_percent > 90 || memory_percent > 90 || disk_percent > 90;
  const hasWarning = cpu_percent > 70 || memory_percent > 80 || disk_percent > 80;
  if (hasCritical) return { tone: "danger", label: "Crítico" };
  if (hasWarning) return { tone: "warning", label: "Aviso" };
  return { tone: "success", label: "Saudável" };
}

function formatTimeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  if (diff < 60000) return `há ${Math.floor(diff / 1000)}s`;
  if (diff < 3600000) return `há ${Math.floor(diff / 60000)}m`;
  if (diff < 86400000) return `há ${Math.floor(diff / 3600000)}h`;
  return `há ${Math.floor(diff / 86400000)}d`;
}

function percentTone(value: number, warn: number, danger: number): Tone {
  if (value > danger) return "danger";
  if (value > warn) return "warning";
  return "success";
}

function latencyTone(value: number): Tone {
  if (value > 1000) return "danger";
  if (value > 500) return "warning";
  return "success";
}

function HealthStat({
  label,
  value,
  percent,
  tone,
}: {
  label: string;
  value: string;
  percent?: number;
  tone: Tone;
}) {
  const TONE_TEXT: Record<Tone, string> = {
    neutral: "text-nexus-text",
    info: "text-cyan-400",
    accent: "text-[var(--nx-accent-bright)]",
    success: "text-emerald-400",
    warning: "text-amber-400",
    danger: "text-rose-400",
  };
  return (
    <div className="nx-inset rounded-lg p-2 text-center">
      <div className="mb-0.5 text-[10px] text-nexus-faint">{label}</div>
      <div className={`font-mono text-xs font-semibold tabular-nums ${TONE_TEXT[tone]}`}>{value}</div>
      {percent != null && <Meter value={percent} tone={tone === "neutral" ? undefined : tone} showThresholds={false} height={3} className="mt-1.5" />}
    </div>
  );
}

function WidgetShell({ children }: { children: ReactNode }) {
  return (
    <Surface elevation={1} padding="sm">
      <SurfaceHeader
        icon={<Shield className="h-4 w-4" />}
        title="Guardião"
        subtitle="Sugestões automáticas de manutenção e saúde"
      />
      {children}
    </Surface>
  );
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
  const pendingCount = guardian?.pending_suggestions ?? 0;

  if (guardianLoading && !guardian) {
    return (
      <WidgetShell>
        <div className="mt-3 grid grid-cols-3 gap-2">
          <div className="nx-shimmer h-14 rounded-lg" />
          <div className="nx-shimmer h-14 rounded-lg" />
          <div className="nx-shimmer h-14 rounded-lg" />
        </div>
        <div className="mt-3 space-y-1.5">
          <div className="nx-shimmer h-12 rounded-lg" />
          <div className="nx-shimmer h-12 rounded-lg" />
        </div>
      </WidgetShell>
    );
  }

  return (
    <Surface elevation={1} padding="sm">
      <SurfaceHeader
        icon={<Shield className="h-4 w-4" />}
        title="Guardião"
        subtitle="Sugestões automáticas de manutenção e saúde"
        action={
          <div className="flex items-center gap-1.5">
            <StatusDot tone={health.tone} pulse={health.tone === "danger"} />
            <Badge tone={health.tone}>{health.label}</Badge>
            {pendingCount > 0 && <Badge tone="accent">{pendingCount} pendentes</Badge>}
          </div>
        }
      />

      {!backendOnline && (
        <div
          role="alert"
          className="mt-3 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300"
        >
          <AlertTriangle className="h-3 w-3" aria-hidden="true" />
          Backend offline — guardião indisponível
        </div>
      )}

      {guardianError && guardian && guardian.running === undefined && (
        <div
          role="alert"
          className="mt-3 flex items-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-300"
        >
          <AlertTriangle className="h-3 w-3" aria-hidden="true" />
          Falha ao carregar: {guardianError}
        </div>
      )}

      {applyError && (
        <div
          role="alert"
          className="mt-3 flex items-center gap-2 rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-1.5 text-xs text-rose-300"
        >
          <AlertTriangle className="h-3 w-3" aria-hidden="true" />
          {applyError}
        </div>
      )}

      <div className="mt-3 space-y-3">
        {guardian?.system_health && (
          <div className="grid grid-cols-3 gap-2" role="group" aria-label="Estado do sistema">
            <HealthStat
              label="CPU"
              value={`${guardian.system_health.cpu_percent.toFixed(0)}%`}
              percent={guardian.system_health.cpu_percent}
              tone={percentTone(guardian.system_health.cpu_percent, 50, 80)}
            />
            <HealthStat
              label="RAM"
              value={`${guardian.system_health.memory_percent.toFixed(0)}%`}
              percent={guardian.system_health.memory_percent}
              tone={percentTone(guardian.system_health.memory_percent, 60, 80)}
            />
            <HealthStat
              label="Latência"
              value={`${guardian.system_health.avg_latency_ms.toFixed(0)}ms`}
              tone={latencyTone(guardian.system_health.avg_latency_ms)}
            />
          </div>
        )}

        <div>
          <div className="mb-1.5 text-[10px] uppercase tracking-wider text-nexus-faint" id="guardian-suggestions-heading">
            Sugestões do Guardião
          </div>
          {suggestions.length === 0 ? (
            <EmptyState
              compact
              icon={<CheckCircle2 className="h-5 w-5" />}
              title="Sem sugestões pendentes"
              hint="O sistema está a funcionar dentro dos parâmetros esperados."
            />
          ) : (
            <ul
              role="list"
              aria-labelledby="guardian-suggestions-heading"
              className="max-h-52 space-y-1.5 overflow-y-auto text-xs sm:text-sm"
            >
              {suggestions.map((s) => {
                const config = PRIORITY_CONFIG[s.priority] ?? PRIORITY_CONFIG.low;
                return (
                  <li key={s.id}>
                    <Surface elevation={0} tone={config.tone} padding="sm">
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0 flex-1">
                          <div className="mb-0.5 flex items-center gap-1.5">
                            <Badge tone={config.tone}>{config.label}</Badge>
                            <span className="truncate text-xs font-medium text-nexus-text">{s.title}</span>
                          </div>
                          <div className="line-clamp-2 text-[10px] text-nexus-muted">{s.description}</div>
                          <div className="mt-1 flex items-center gap-2 text-[10px] text-nexus-faint">
                            <span>{CATEGORY_LABELS[s.category] ?? s.category}</span>
                            <span aria-hidden="true">·</span>
                            <Clock className="inline h-3 w-3" aria-hidden="true" />
                            <span>{formatTimeAgo(s.created_at)}</span>
                          </div>
                        </div>
                        {s.auto_apply_safe && (
                          <Button
                            variant="secondary"
                            size="xs"
                            icon={<Wrench className="h-3 w-3" />}
                            loading={applyingId === s.id}
                            onClick={() => applySuggestion(s.id)}
                            className="shrink-0"
                          >
                            Aplicar
                          </Button>
                        )}
                      </div>
                    </Surface>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </Surface>
  );
}
