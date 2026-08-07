"use client";
import { useEffect, useState, useMemo, type ReactNode } from "react";
import { useMetricsStore } from "../../stores/metricsStore";
import { useModelStore } from "../../stores/modelStore";
import { getHealth, getAvailableModels } from "../../lib/api";
import { Activity, Server, Cpu, Database, Wifi } from "lucide-react";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { Badge, StatusDot, Meter, AnimatedNumber, EmptyState } from "../ui/Primitives";

interface HealthCheck {
  name: string;
  status: "healthy" | "degraded" | "unhealthy" | "unknown";
  latency_ms?: number;
  message?: string;
  last_check: string;
  icon: ReactNode;
}

const STATUS_LABEL_PT: Record<HealthCheck["status"], string> = {
  healthy: "Saudável",
  degraded: "Degradado",
  unhealthy: "Instável",
  unknown: "Desconhecido",
};

const STATUS_TONE: Record<HealthCheck["status"], "success" | "warning" | "danger" | "neutral"> = {
  healthy: "success",
  degraded: "warning",
  unhealthy: "danger",
  unknown: "neutral",
};

function meterTone(pct: number): "success" | "warning" | "danger" {
  if (pct >= 90) return "danger";
  if (pct >= 75) return "warning";
  return "success";
}

function ResourceRow({
  label,
  percent,
  detail,
}: {
  label: string;
  percent: number;
  detail?: string;
}) {
  const tone = meterTone(percent);
  return (
    <div
      className="space-y-1"
      role="group"
      aria-label={`${label}: ${percent.toFixed(1)}%${tone === "danger" ? ", crítico" : tone === "warning" ? ", aviso" : ""}`}
    >
      <div className="flex items-center justify-between gap-2 text-[10px]">
        <span className="flex items-center gap-1.5 text-nexus-faint">
          {label}
          {tone !== "success" && (
            <Badge tone={tone}>{tone === "danger" ? "Crítico" : "Aviso"}</Badge>
          )}
        </span>
        <span className="tabular-nums text-nexus-muted">
          {detail ? `${detail} · ` : ""}
          <AnimatedNumber value={percent} decimals={1} />%
        </span>
      </div>
      <Meter value={percent} height={5} />
    </div>
  );
}

export default function SystemHealth() {
  const [checks, setChecks] = useState<HealthCheck[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdateTs, setLastUpdateTs] = useState<number>(0);
  const [secondsAgo, setSecondsAgo] = useState<number | null>(null);

  const metrics = useMetricsStore((s) => s.metrics);

  // Use dedicated lightweight endpoints; avoid calling /api/projects here
  // because the projectStore already loads it once via DataInitProvider.
  useEffect(() => {
    let mounted = true;

    const run = async () => {
      if (!mounted) return;
      setLoading(true);

      const startAll = Date.now();

      const [localLlmRes, backendRes] = await Promise.allSettled([
        getAvailableModels().then(() => ({
          ok: true,
          latency: Date.now() - startAll,
        })).catch(() => ({
          ok: false,
          latency: Date.now() - startAll,
        })),
        getHealth().then(() => ({
          ok: true,
          latency: Date.now() - startAll,
        })).catch(() => ({
          ok: false,
          latency: Date.now() - startAll,
        })),
      ]);

      if (!mounted) return;

      const now = new Date().toISOString();
      const hasMetrics = useMetricsStore.getState().metrics !== null;
      const modelsLoaded = useModelStore.getState().modelsLoaded;
      const modelCount = useModelStore.getState().models.length;

      const healthChecks: HealthCheck[] = [
        {
          name: "LLM Local",
          status: localLlmRes.status === "fulfilled" && localLlmRes.value.ok ? "healthy" : "unhealthy",
          latency_ms: localLlmRes.status === "fulfilled" ? localLlmRes.value.latency : undefined,
          message: localLlmRes.status === "rejected" ? "Ligação recusada" : undefined,
          last_check: now,
          icon: <Cpu className="h-3.5 w-3.5" />,
        },
        {
          name: "Backend",
          status: backendRes.status === "fulfilled" && backendRes.value.ok ? "healthy" : "unhealthy",
          latency_ms: backendRes.status === "fulfilled" ? backendRes.value.latency : undefined,
          message: backendRes.status === "rejected" ? "Ligação recusada" : undefined,
          last_check: now,
          icon: <Server className="h-3.5 w-3.5" />,
        },
        {
          name: "Métricas",
          status: hasMetrics ? "healthy" : "unhealthy",
          message: hasMetrics ? undefined : "Sem métricas recebidas",
          last_check: now,
          icon: <Activity className="h-3.5 w-3.5" />,
        },
        {
          name: "Base de dados",
          status: backendRes.status === "fulfilled" && backendRes.value.ok ? "healthy" : "unhealthy",
          latency_ms: backendRes.status === "fulfilled" ? backendRes.value.latency : undefined,
          message: backendRes.status === "rejected" ? "Ligação recusada" : undefined,
          last_check: now,
          icon: <Database className="h-3.5 w-3.5" />,
        },
        {
          name: "Fluxo de eventos",
          status: "healthy",
          message: undefined,
          last_check: now,
          icon: <Wifi className="h-3.5 w-3.5" />,
        },
        {
          name: "Registo de modelos",
          status: modelsLoaded && modelCount > 0 ? "healthy" : modelsLoaded ? "degraded" : "unknown",
          message: modelsLoaded ? undefined : "Modelos ainda não carregados",
          last_check: now,
          icon: <Cpu className="h-3.5 w-3.5" />,
        },
      ];

      setChecks(healthChecks);
      setLastUpdateTs(Date.now());
      setLoading(false);
    };

    run();
    const interval = setInterval(run, 30000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  // Ticker para mostrar "Atualizado há Xs" de forma relativa.
  useEffect(() => {
    if (lastUpdateTs === 0) {
      setSecondsAgo(null);
      return;
    }
    const tick = () => setSecondsAgo(Math.floor((Date.now() - lastUpdateTs) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [lastUpdateTs]);

  const overallStatus = useMemo(() => {
    if (checks.length === 0) return "unknown";
    if (checks.every((c) => c.status === "healthy")) return "healthy";
    if (checks.some((c) => c.status === "unhealthy")) return "unhealthy";
    return "degraded";
  }, [checks]);

  const healthyCount = useMemo(() => checks.filter((c) => c.status === "healthy").length, [checks]);

  const checkAriaLabel = (check: HealthCheck) => {
    const parts = [`${check.name}: ${STATUS_LABEL_PT[check.status]}`];
    if (check.latency_ms !== undefined) parts.push(`${check.latency_ms}ms`);
    if (check.message) parts.push(check.message);
    return parts.join(", ");
  };

  const overallAriaLabel = `Estado geral: ${STATUS_LABEL_PT[overallStatus]}, ${healthyCount} de ${checks.length} saudáveis`;

  return (
    <section aria-label="Saúde do Sistema">
      <Surface elevation={2} padding="md">
        <SurfaceHeader
          icon={<Activity className="h-4 w-4" />}
          title="Saúde do Sistema"
          subtitle={
            checks.length > 0
              ? `${healthyCount} de ${checks.length} verificações saudáveis`
              : "Verificações contínuas às ligações e recursos"
          }
          action={
            <div role="status" aria-live="polite" aria-label={overallAriaLabel} className="flex items-center gap-1.5">
              <StatusDot tone={STATUS_TONE[overallStatus]} pulse={overallStatus === "unhealthy"} />
              <Badge tone={STATUS_TONE[overallStatus]}>{STATUS_LABEL_PT[overallStatus]}</Badge>
            </div>
          }
        />

        {/* Resource bars from shared store */}
        {metrics && (
          <div className="nx-inset mt-4 space-y-2.5 rounded-lg p-2.5" aria-label="Barras de recursos">
            <ResourceRow label="CPU" percent={metrics.cpu_percent} />
            <ResourceRow
              label="RAM"
              percent={metrics.ram_percent}
              detail={`${(metrics.ram_used_bytes / 1e9).toFixed(1)}/${(metrics.ram_total_bytes / 1e9).toFixed(0)} GB`}
            />
            <ResourceRow label="Disco" percent={metrics.disk_percent} />
          </div>
        )}

        <div className="mt-4">
          {loading ? (
            <div className="space-y-1.5" role="status" aria-live="polite" aria-label="A carregar verificações de saúde">
              {Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="nx-shimmer h-8 rounded-lg" />
              ))}
            </div>
          ) : checks.length > 0 ? (
            <ul role="list" className="nx-inset divide-y divide-[var(--nx-line)] overflow-hidden rounded-lg">
              {checks.map((check) => (
                <li
                  key={check.name}
                  role="listitem"
                  aria-label={checkAriaLabel(check)}
                  className="flex items-center justify-between gap-2 px-2.5 py-2"
                >
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="shrink-0 text-nexus-faint" aria-hidden="true">
                      {check.icon}
                    </span>
                    <span className="truncate text-xs font-medium text-nexus-text">{check.name}</span>
                  </div>
                  <div className="flex shrink-0 items-center gap-2 text-[11px]">
                    {check.latency_ms !== undefined && (
                      <span className="tabular-nums text-nexus-muted">{check.latency_ms}ms</span>
                    )}
                    {check.message && (
                      <span className="max-w-[120px] truncate text-nexus-faint" title={check.message}>
                        {check.message}
                      </span>
                    )}
                    <span className="sr-only">{STATUS_LABEL_PT[check.status]}</span>
                    <StatusDot tone={STATUS_TONE[check.status]} pulse={check.status === "unhealthy"} />
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState
              compact
              icon={<Activity className="h-5 w-5" />}
              title="Sem dados de saúde"
              hint="As verificações aparecem assim que o sistema completar a primeira ronda."
            />
          )}
        </div>

        <div className="mt-2 text-right text-[10px] tabular-nums text-nexus-faint">
          {secondsAgo === null ? "Atualizado há —" : `Atualizado há ${secondsAgo}s`}
        </div>
      </Surface>
    </section>
  );
}
