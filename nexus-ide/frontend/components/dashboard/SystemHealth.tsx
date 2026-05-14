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

        if (response.ok) {
          healthChecks.push({
            name: "Ollama",
            status: "healthy",
            latency_ms: latency,
            last_check: new Date().toISOString(),
          });
        } else {
          healthChecks.push({
            name: "Ollama",
            status: "degraded",
            message: `HTTP ${response.status}`,
            last_check: new Date().toISOString(),
          });
        }
      } catch (error) {
        healthChecks.push({
          name: "Ollama",
          status: "unhealthy",
          message: error instanceof Error ? error.message : "Unknown error",
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

        if (response.ok) {
          healthChecks.push({
            name: "Backend",
            status: "healthy",
            latency_ms: latency,
            last_check: new Date().toISOString(),
          });
        } else {
          healthChecks.push({
            name: "Backend",
            status: "degraded",
            message: `HTTP ${response.status}`,
            last_check: new Date().toISOString(),
          });
        }
      } catch (error) {
        healthChecks.push({
          name: "Backend",
          status: "unhealthy",
          message: error instanceof Error ? error.message : "Unknown error",
          last_check: new Date().toISOString(),
        });
      }

      // Check Metrics Stream
      try {
        const start = Date.now();
        const response = await fetch(apiUrl("/api/metrics/current"), {
          signal: AbortSignal.timeout(5000),
        });
        const latency = Date.now() - start;

        if (response.ok) {
          healthChecks.push({
            name: "Metrics",
            status: "healthy",
            latency_ms: latency,
            last_check: new Date().toISOString(),
          });
        } else {
          healthChecks.push({
            name: "Metrics",
            status: "degraded",
            message: `HTTP ${response.status}`,
            last_check: new Date().toISOString(),
          });
        }
      } catch (error) {
        healthChecks.push({
          name: "Metrics",
          status: "unhealthy",
          message: error instanceof Error ? error.message : "Unknown error",
          last_check: new Date().toISOString(),
        });
      }

      setChecks(healthChecks);
      setLoading(false);
    };

    performHealthChecks();

    // Refresh every 30 seconds
    const interval = setInterval(performHealthChecks, 30000);

    return () => clearInterval(interval);
  }, []);

  const getStatusColor = (status: HealthCheck["status"]) => {
    switch (status) {
      case "healthy":
        return "bg-green-500/20 text-green-400 border-green-500/30";
      case "degraded":
        return "bg-yellow-500/20 text-yellow-400 border-yellow-500/30";
      case "unhealthy":
        return "bg-red-500/20 text-red-400 border-red-500/30";
      case "unknown":
        return "bg-gray-500/20 text-gray-400 border-gray-500/30";
    }
  };

  const getStatusIcon = (status: HealthCheck["status"]) => {
    switch (status) {
      case "healthy":
        return "✓";
      case "degraded":
        return "⚠";
      case "unhealthy":
        return "✗";
      case "unknown":
        return "?";
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
        <motion.div
          initial={{ scale: 0 }}
          animate={{ scale: 1 }}
          className={`flex items-center gap-2 rounded px-2 py-1 text-xs ${getStatusColor(overallStatus)}`}
        >
          <span>{getStatusIcon(overallStatus)}</span>
          <span className="capitalize">{overallStatus}</span>
        </motion.div>
      </div>

      {loading ? (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex h-32 items-center justify-center text-xs text-gray-500"
        >
          Verificando saúde...
        </motion.div>
      ) : checks.length > 0 ? (
        <div className="space-y-2">
          {checks.map((check, index) => (
            <motion.div
              key={check.name}
              initial={{ opacity: 0, x: -20 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ delay: index * 0.1 }}
              whileHover={{ scale: 1.02 }}
              className={`flex items-center justify-between rounded border p-2 ${getStatusColor(check.status)}`}
            >
              <div className="flex items-center gap-2">
                <motion.span
                  initial={{ scale: 0, rotate: -180 }}
                  animate={{ scale: 1, rotate: 0 }}
                  transition={{ delay: index * 0.1 + 0.2 }}
                  className="text-sm"
                >
                  {getStatusIcon(check.status)}
                </motion.span>
                <span className="text-sm font-medium">{check.name}</span>
              </div>
              <div className="flex items-center gap-3 text-xs">
                {check.latency_ms && (
                  <span className="text-gray-400">{check.latency_ms}ms</span>
                )}
                {check.message && (
                  <span className="text-gray-400">{check.message}</span>
                )}
                <span className="text-gray-500">
                  {new Date(check.last_check).toLocaleTimeString()}
                </span>
              </div>
            </motion.div>
          ))}
        </div>
      ) : (
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          className="flex h-32 items-center justify-center text-xs text-gray-500"
        >
          Sem dados de saúde
        </motion.div>
      )}
    </motion.div>
  );
}
