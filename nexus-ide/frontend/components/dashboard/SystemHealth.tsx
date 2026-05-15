"use client";
import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { apiUrl } from "../../lib/api";

interface HealthCheck {
  name: string;
  status: "healthy" | "degraded" | "unhealthy" | "unknown";
  latency_ms?: number;
  message?: string;
  last_check: string;
}

export default function SystemHealth() {
  const [checks, setChecks] = useState<HealthCheck[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const performHealthChecks = async () => {
      const healthChecks: HealthCheck[] = [];

      // Check Ollama
      try {
        const start = Date.now();
        const response = await fetch("http://localhost:11434/api/tags", {
          signal: AbortSignal.timeout(5000),
        });
        const latency = Date.now() - start;
        healthChecks.push({
          name: "Ollama",
          status: response.ok ? "healthy" : "degraded",
          latency_ms: latency,
          message: response.ok ? undefined : `HTTP ${response.status}`,
          last_check: new Date().toISOString(),
        });
      } catch (error) {
        healthChecks.push({
          name: "Ollama",
          status: "unhealthy",
          message: "Connection refused",
          last_check: new Date().toISOString(),
        });
      }

      // Check Backend
      try {
        const start = Date.now();
        const response = await fetch(apiUrl("/health"), {
          signal: AbortSignal.timeout(5000),
        });
        const latency = Date.now() - start;
        healthChecks.push({
          name: "Backend",
          status: response.ok ? "healthy" : "degraded",
          latency_ms: latency,
          message: response.ok ? undefined : `HTTP ${response.status}`,
          last_check: new Date().toISOString(),
        });
      } catch {
        healthChecks.push({
          name: "Backend",
          status: "unhealthy",
          message: "Connection refused",
          last_check: new Date().toISOString(),
        });
      }

      // Check Metrics
      try {
        const start = Date.now();
        const response = await fetch(apiUrl("/api/metrics/current"), {
          signal: AbortSignal.timeout(5000),
        });
        const latency = Date.now() - start;
        healthChecks.push({
          name: "Metrics",
          status: response.ok ? "healthy" : "degraded",
          latency_ms: latency,
          message: response.ok ? undefined : `HTTP ${response.status}`,
          last_check: new Date().toISOString(),
        });
      } catch {
        healthChecks.push({
          name: "Metrics",
          status: "unhealthy",
          message: "Connection refused",
          last_check: new Date().toISOString(),
        });
      }

      setChecks(healthChecks);
      setLoading(false);
    };

    performHealthChecks();
    const interval = setInterval(performHealthChecks, 30000);
    return () => clearInterval(interval);
  }, []);

  const getStatusColor = (status: HealthCheck["status"]) => {
    switch (status) {
      case "healthy": return "bg-green-500/20 text-green-400 border-green-500/30";
      case "degraded": return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
      case "unhealthy": return "bg-red-500/20 text-red-400 border-red-500/30";
      case "unknown": return "bg-gray-500/20 text-gray-400 border-gray-500/30";
    }
  };

  const getStatusIcon = (status: HealthCheck["status"]) => {
    switch (status) {
      case "healthy": return "ok";
      case "degraded": return "! ";
      case "unhealthy": return "X";
      case "unknown": return "?";
    }
  };

  const overallStatus =
    checks.length > 0
      ? checks.every((c) => c.status === "healthy")
        ? "healthy"
        : checks.some((c) => c.status === "unhealthy")
          ? "unhealthy"
          : "degraded"
      : "unknown";

  return (
    <motion.div
      initial={{ opacity: 0, scale: 0.95 }}
      animate={{ opacity: 1, scale: 1 }}
      transition={{ duration: 0.3 }}
      className="rounded border border-nexus-border bg-nexus-panel p-3"
    >
      <div className="mb-3 flex items-center justify-between">
        <div className="text-sm font-semibold">Saúde do Sistema</div>
        <div className={`flex items-center gap-1.5 rounded px-2 py-1 text-xs ${getStatusColor(overallStatus)}`}>
          <span className="font-bold">{getStatusIcon(overallStatus)}</span>
          <span className="capitalize">{overallStatus}</span>
        </div>
      </div>

      {loading ? (
        <div className="flex h-24 items-center justify-center text-xs text-gray-500">
          Verificando...
        </div>
      ) : checks.length > 0 ? (
        <div className="space-y-1.5">
          {checks.map((check) => (
            <div
              key={check.name}
              className={`flex items-center justify-between rounded border px-2.5 py-1.5 ${getStatusColor(check.status)}`}
            >
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold">{getStatusIcon(check.status)}</span>
                <span className="text-xs font-medium">{check.name}</span>
              </div>
              <div className="flex items-center gap-2 text-xs">
                {check.latency_ms && <span className="text-gray-400">{check.latency_ms}ms</span>}
                {check.message && <span className="text-gray-500">{check.message}</span>}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="flex h-24 items-center justify-center text-xs text-gray-500">
          Sem dados de saúde
        </div>
      )}
    </motion.div>
  );
}
