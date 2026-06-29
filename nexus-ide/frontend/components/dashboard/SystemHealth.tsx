"use client";
import { useEffect, useState, useMemo } from "react";
import { useMetricsStore } from "../../stores/metricsStore";
import { useModelStore } from "../../stores/modelStore";
import { getHealth, getAvailableModels } from "../../lib/api";
import { Activity, Server, Cpu, Database, Wifi } from "lucide-react";

interface HealthCheck {
  name: string;
  status: "healthy" | "degraded" | "unhealthy" | "unknown";
  latency_ms?: number;
  message?: string;
  last_check: string;
  icon: React.ReactNode;
}

const STATUS_LABEL_PT: Record<HealthCheck["status"], string> = {
  healthy: "Saudável",
  degraded: "Degradado",
  unhealthy: "Instável",
  unknown: "Desconhecido",
};

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

  const getStatusColor = (status: HealthCheck["status"]) => {
    switch (status) {
      case "healthy":
        return "bg-green-500/15 text-green-400 border-green-500/30";
      case "degraded":
        return "bg-yellow-500/15 text-yellow-400 border-yellow-500/30";
      case "unhealthy":
        return "bg-red-500/15 text-red-400 border-red-500/30";
      case "unknown":
        return "bg-gray-500/15 text-gray-400 border-gray-500/30";
    }
  };

  const getStatusDot = (status: HealthCheck["status"]) => {
    switch (status) {
      case "healthy":
        return <span className="h-2 w-2 rounded-full bg-green-400" aria-hidden="true" />;
      case "degraded":
        return <span className="h-2 w-2 rounded-full bg-yellow-400" aria-hidden="true" />;
      case "unhealthy":
        return <span className="h-2 w-2 rounded-full bg-red-400 animate-pulse" aria-hidden="true" />;
      case "unknown":
        return <span className="h-2 w-2 rounded-full bg-gray-500" aria-hidden="true" />;
    }
  };

  const checkAriaLabel = (check: HealthCheck) => {
    const parts = [`${check.name}: ${STATUS_LABEL_PT[check.status]}`];
    if (check.latency_ms !== undefined) parts.push(`${check.latency_ms}ms`);
    if (check.message) parts.push(check.message);
    return parts.join(", ");
  };

  const resourceBar = (label: string, value: number, used: number, total: number, color: string) => {
    const pctClamped = Math.min(Math.max(value, 0), 100);
    const valueText =
      label === "RAM"
        ? `${(used / 1e9).toFixed(1)}/${(total / 1e9).toFixed(0)} GB (${value.toFixed(1)}%)`
        : `${value.toFixed(1)}%`;
    const barAriaLabel = `${label}: ${valueText}${value > 80 ? ", Crítico" : value > 60 ? ", Aviso" : ""}`;
    return (
      <div className="space-y-1">
        <div className="flex justify-between text-[10px] sm:text-xs">
          <span className="text-gray-500">{label}</span>
          <span
            className={value > 80 ? "text-red-400" : value > 60 ? "text-yellow-400" : "text-gray-300"}
          >
            {valueText}
            {value > 80 ? <span className="ml-1" aria-hidden="true">Crítico</span> : value > 60 ? <span className="ml-1" aria-hidden="true">Aviso</span> : null}
          </span>
        </div>
        <div
          role="progressbar"
          aria-valuenow={Math.round(pctClamped)}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={barAriaLabel}
          className="h-1.5 w-full rounded-full bg-nexus-border/50 overflow-hidden"
        >
          <div
            className={`h-full rounded-full transition-all duration-500 ${color}`}
            style={{ width: `${pctClamped}%` }}
          />
        </div>
      </div>
    );
  };

  const overallAriaLabel = `Estado geral: ${STATUS_LABEL_PT[overallStatus]}, ${healthyCount} de ${checks.length} saudáveis`;

  return (
    <div
      className="rounded border border-nexus-border bg-nexus-panel p-3"
      aria-labelledby="system-health-title"
    >
      <h3 id="system-health-title" className="sr-only">
        Saúde do Sistema
      </h3>
      <div className="mb-3 flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <div className="truncate text-sm font-semibold">Saúde do Sistema</div>
          <span className="shrink-0 text-[10px] text-gray-500 sm:text-xs">
            ({healthyCount} de {checks.length} saudáveis)
          </span>
        </div>
        <div
          role="status"
          aria-live="polite"
          aria-label={overallAriaLabel}
          className={`flex shrink-0 items-center gap-1.5 rounded px-2 py-1 text-xs ${getStatusColor(overallStatus)}`}
        >
          {getStatusDot(overallStatus)}
          <span>{STATUS_LABEL_PT[overallStatus]}</span>
        </div>
      </div>

      {/* Resource bars from shared store */}
      {metrics && (
        <div
          className="mb-3 space-y-2 rounded border border-nexus-border/50 bg-nexus-bg/50 p-2.5"
          aria-label="Barras de recursos"
        >
          {resourceBar(
            "CPU",
            metrics.cpu_percent,
            0,
            100,
            metrics.cpu_percent > 80 ? "bg-red-500" : metrics.cpu_percent > 50 ? "bg-yellow-500" : "bg-green-500"
          )}
          {resourceBar(
            "RAM",
            metrics.ram_percent,
            metrics.ram_used_bytes,
            metrics.ram_total_bytes,
            metrics.ram_percent > 80 ? "bg-red-500" : metrics.ram_percent > 60 ? "bg-yellow-500" : "bg-green-500"
          )}
          {resourceBar(
            "Disco",
            metrics.disk_percent,
            metrics.disk_used_bytes,
            metrics.disk_total_bytes,
            metrics.disk_percent > 90 ? "bg-red-500" : metrics.disk_percent > 75 ? "bg-yellow-500" : "bg-green-500"
          )}
        </div>
      )}

      {loading ? (
        <div
          className="flex h-24 items-center justify-center text-xs text-gray-500"
          role="status"
          aria-live="polite"
        >
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" aria-hidden="true" />
            A carregar…
          </div>
        </div>
      ) : checks.length > 0 ? (
        <ul role="list" className="space-y-1.5">
          {checks.map((check) => (
            <li
              key={check.name}
              role="listitem"
              aria-label={checkAriaLabel(check)}
              className={`flex items-center justify-between rounded border px-2.5 py-2 ${getStatusColor(check.status)}`}
            >
              <div className="flex min-w-0 items-center gap-2">
                <span className="shrink-0 text-gray-400" aria-hidden="true">{check.icon}</span>
                <span className="truncate text-xs font-medium sm:text-sm">{check.name}</span>
              </div>
              <div className="flex shrink-0 items-center gap-2 text-xs">
                {check.latency_ms !== undefined && <span className="text-gray-400">{check.latency_ms}ms</span>}
                {check.message && <span className="text-gray-500">{check.message}</span>}
                <span className="sr-only">{STATUS_LABEL_PT[check.status]}</span>
                {getStatusDot(check.status)}
              </div>
            </li>
          ))}
        </ul>
      ) : (
        <div className="flex h-24 items-center justify-center text-xs text-gray-500" role="status">
          Sem dados de saúde
        </div>
      )}

      <div className="mt-2 text-right text-[10px] text-gray-600 sm:text-xs">
        {secondsAgo === null ? "Atualizado há —" : `Atualizado há ${secondsAgo}s`}
      </div>
    </div>
  );
}
