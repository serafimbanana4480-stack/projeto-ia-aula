"use client";
import { useEffect, useState, useMemo, useCallback } from "react";
import { useMetricsStore } from "../../stores/metricsStore";
import { useModelStore } from "../../stores/modelStore";
import { getHealth, getModelStatus } from "../../lib/api";
import { Activity, Server, Cpu, Database, Wifi } from "lucide-react";

interface HealthCheck {
  name: string;
  status: "healthy" | "degraded" | "unhealthy" | "unknown";
  latency_ms?: number;
  message?: string;
  last_check: string;
  icon: React.ReactNode;
}

export default function SystemHealth() {
  const [checks, setChecks] = useState<HealthCheck[]>([]);
  const [loading, setLoading] = useState(true);
  const [lastUpdate, setLastUpdate] = useState<string>("—");

  const metrics = useMetricsStore((s) => s.metrics);
  const backendOnline = useMetricsStore((s) => s.backendOnline);
  const modelsLoaded = useModelStore((s) => s.modelsLoaded);
  const rawModelStatus = useModelStore((s) => s.rawModelStatus);

  // Use dedicated lightweight endpoints; avoid calling /api/projects here
  // because the projectStore already loads it once via DataInitProvider.
  const performHealthChecks = useCallback(async () => {
    setLoading(true);
    const startAll = Date.now();

    const [localLlmRes, backendRes] = await Promise.allSettled([
      getModelStatus().then(() => ({
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

    const now = new Date().toISOString();
    const healthChecks: HealthCheck[] = [
      {
        name: "Local LLM",
        status: localLlmRes.status === "fulfilled" && localLlmRes.value.ok ? "healthy" : "unhealthy",
        latency_ms: localLlmRes.status === "fulfilled" ? localLlmRes.value.latency : undefined,
        message: localLlmRes.status === "rejected" ? "Connection refused" : undefined,
        last_check: now,
        icon: <Cpu className="h-3.5 w-3.5" />,
      },
      {
        name: "Backend",
        status: backendRes.status === "fulfilled" && backendRes.value.ok ? "healthy" : "unhealthy",
        latency_ms: backendRes.status === "fulfilled" ? backendRes.value.latency : undefined,
        message: backendRes.status === "rejected" ? "Connection refused" : undefined,
        last_check: now,
        icon: <Server className="h-3.5 w-3.5" />,
      },
      {
        name: "Metrics",
        status: backendOnline ? "healthy" : "unhealthy",
        message: backendOnline ? undefined : "No metrics received",
        last_check: now,
        icon: <Activity className="h-3.5 w-3.5" />,
      },
      {
        name: "Database",
        status: backendRes.status === "fulfilled" && backendRes.value.ok ? "healthy" : "unhealthy",
        latency_ms: backendRes.status === "fulfilled" ? backendRes.value.latency : undefined,
        message: backendRes.status === "rejected" ? "Connection refused" : undefined,
        last_check: now,
        icon: <Database className="h-3.5 w-3.5" />,
      },
      {
        name: "Event Stream",
        status: backendOnline ? "healthy" : "unhealthy",
        message: backendOnline ? undefined : "SSE disconnected",
        last_check: now,
        icon: <Wifi className="h-3.5 w-3.5" />,
      },
      {
        name: "Model Registry",
        status: modelsLoaded && rawModelStatus.length > 0 ? "healthy" : modelsLoaded ? "degraded" : "unknown",
        message: modelsLoaded ? undefined : "Models not loaded yet",
        last_check: now,
        icon: <Cpu className="h-3.5 w-3.5" />,
      },
    ];

    setChecks(healthChecks);
    setLastUpdate(new Date().toLocaleTimeString());
    setLoading(false);
  }, [backendOnline, modelsLoaded, rawModelStatus.length]);

  useEffect(() => {
    performHealthChecks();
    const interval = setInterval(performHealthChecks, 30000);
    return () => clearInterval(interval);
  }, [performHealthChecks]);

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
        return <span className="h-2 w-2 rounded-full bg-green-400" />;
      case "degraded":
        return <span className="h-2 w-2 rounded-full bg-yellow-400" />;
      case "unhealthy":
        return <span className="h-2 w-2 rounded-full bg-red-400 animate-pulse" />;
      case "unknown":
        return <span className="h-2 w-2 rounded-full bg-gray-500" />;
    }
  };

  const resourceBar = (label: string, value: number, used: number, total: number, color: string) => (
    <div className="space-y-1">
      <div className="flex justify-between text-[10px]">
        <span className="text-gray-500">{label}</span>
        <span className={value > 80 ? "text-red-400" : value > 60 ? "text-yellow-400" : "text-gray-300"}>
          {label === "RAM"
            ? `${(used / 1e9).toFixed(1)}/${(total / 1e9).toFixed(0)} GB (${value.toFixed(1)}%)`
            : `${value.toFixed(1)}%`}
        </span>
      </div>
      <div className="h-1.5 w-full rounded-full bg-nexus-border/50 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${Math.min(value, 100)}%` }}
        />
      </div>
    </div>
  );

  return (
    <div className="rounded border border-nexus-border bg-nexus-panel p-3">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="text-sm font-semibold">Saúde do Sistema</div>
          <span className="text-[10px] text-gray-500">
            ({healthyCount}/{checks.length} healthy)
          </span>
        </div>
        <div
          className={`flex items-center gap-1.5 rounded px-2 py-1 text-xs ${getStatusColor(overallStatus)}`}
        >
          {getStatusDot(overallStatus)}
          <span className="capitalize">{overallStatus}</span>
        </div>
      </div>

      {/* Resource bars from shared store */}
      {metrics && (
        <div className="mb-3 space-y-2 rounded border border-nexus-border/50 bg-nexus-bg/50 p-2.5">
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
            "Disk",
            metrics.disk_percent,
            metrics.disk_used_bytes,
            metrics.disk_total_bytes,
            metrics.disk_percent > 90 ? "bg-red-500" : metrics.disk_percent > 75 ? "bg-yellow-500" : "bg-green-500"
          )}
        </div>
      )}

      {loading ? (
        <div className="flex h-24 items-center justify-center text-xs text-gray-500">
          <div className="flex items-center gap-2">
            <div className="h-3 w-3 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
            Verificando...
          </div>
        </div>
      ) : checks.length > 0 ? (
        <div className="space-y-1.5">
          {checks.map((check) => (
            <div
              key={check.name}
              className={`flex items-center justify-between rounded border px-2.5 py-2 ${getStatusColor(check.status)}`}
            >
              <div className="flex items-center gap-2">
                <span className="text-gray-400">{check.icon}</span>
                <span className="text-xs font-medium">{check.name}</span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                {check.latency_ms !== undefined && <span className="text-gray-400">{check.latency_ms}ms</span>}
                {check.message && <span className="text-gray-500">{check.message}</span>}
                {getStatusDot(check.status)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex h-24 items-center justify-center text-xs text-gray-500">Sem dados de saúde</div>
      )}

      <div className="mt-2 text-right text-[10px] text-gray-600">Last check: {lastUpdate}</div>
    </div>
  );
}
