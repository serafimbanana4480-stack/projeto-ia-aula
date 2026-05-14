"use client";

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Clock,
  FileText,
  X,
  Zap,
} from "lucide-react";
import { AreaChart, Area, ResponsiveContainer } from "recharts";
import { apiUrl } from "../../lib/api";

interface SystemMetrics {
  cpu_percent: number;
  ram_percent: number;
  ram_used_bytes: number;
  ram_total_bytes: number;
  disk_percent: number;
  disk_used_bytes: number;
  disk_total_bytes: number;
  uptime_seconds: number;
  tokens_per_second: number;
  avg_latency_ms: number;
}

function MiniSpark({ data, color }: { data: { v: number }[]; color: string }) {
  return (
    <div className="h-6 w-16">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data}>
          <defs>
            <linearGradient id={`bg-${color}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.3} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="v"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#bg-${color})`}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

function formatUptime(seconds: number): string {
  if (seconds < 60) return `${Math.floor(seconds)}s`;
  if (seconds < 3600) {
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}m ${s}s`;
  }
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  return `${hours}h ${mins}m`;
}

function formatBytes(bytes: number): string {
  if (bytes < 1e6) return `${(bytes / 1e3).toFixed(0)} KB`;
  if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`;
  return `${(bytes / 1e9).toFixed(1)} GB`;
}

export default function BottomHUD() {
  const [showLogs, setShowLogs] = useState(false);
  const [metrics, setMetrics] = useState<SystemMetrics | null>(null);
  const [ollamaOnline, setOllamaOnline] = useState(false);
  const [systemOnline, setSystemOnline] = useState(false);
  const [cpuHistory, setCpuHistory] = useState<{ v: number }[]>([]);
  const [ramHistory, setRamHistory] = useState<{ v: number }[]>([]);
  const [diskHistory, setDiskHistory] = useState<{ v: number }[]>([]);
  const [logs, setLogs] = useState<string[]>([]);

  // Poll metrics every 2 seconds
  useEffect(() => {
    const fetchMetrics = async () => {
      try {
        const response = await fetch(apiUrl("/api/metrics/current"));
        if (response.ok) {
          const data = await response.json();
          setMetrics(data);
          setSystemOnline(true);

          // Update sparkline histories
          setCpuHistory((prev) => [
            ...prev.slice(-19),
            { v: data.cpu_percent ?? 0 },
          ]);
          setRamHistory((prev) => [
            ...prev.slice(-19),
            { v: data.ram_percent ?? 0 },
          ]);
          setDiskHistory((prev) => [
            ...prev.slice(-19),
            { v: data.disk_percent ?? 0 },
          ]);
        } else {
          setSystemOnline(false);
        }
      } catch (error) {
        setSystemOnline(false);
      }
    };

    // Check Ollama status
    const checkOllama = async () => {
      try {
        const response = await fetch("http://localhost:11434/api/tags", {
          signal: AbortSignal.timeout(3000),
        });
        setOllamaOnline(response.ok);
      } catch {
        setOllamaOnline(false);
      }
    };

    fetchMetrics();
    checkOllama();

    const metricsInterval = setInterval(fetchMetrics, 2000);
    const ollamaInterval = setInterval(checkOllama, 10000);

    return () => {
      clearInterval(metricsInterval);
      clearInterval(ollamaInterval);
    };
  }, []);

  // Fetch logs when modal opens
  useEffect(() => {
    if (!showLogs) return;

    const fetchLogs = async () => {
      try {
        const response = await fetch(apiUrl("/api/metrics/current"));
        await response.json(); // ensure endpoint is reachable
        const logEntries: string[] = [];

        // Build log entries from real system state
        logEntries.push(
          ollamaOnline
            ? "✓ Ollama running on port 11434"
            : "✗ Ollama not reachable on port 11434",
        );
        logEntries.push(
          systemOnline
            ? "✓ Backend running on port 8000"
            : "✗ Backend not reachable on port 8000",
        );
        logEntries.push(
          `CPU: ${metrics?.cpu_percent?.toFixed(1) ?? "—"}% | RAM: ${metrics?.ram_percent?.toFixed(1) ?? "—"}% | Disk: ${metrics?.disk_percent?.toFixed(1) ?? "—"}%`,
        );
        if (metrics?.tokens_per_second) {
          logEntries.push(
            `Throughput: ${metrics.tokens_per_second.toFixed(1)} tokens/s | Latency: ${metrics.avg_latency_ms?.toFixed(0) ?? "—"}ms`,
          );
        }

        setLogs(logEntries);
      } catch {
        setLogs(["Failed to fetch system logs"]);
      }
    };

    fetchLogs();
  }, [showLogs, ollamaOnline, systemOnline, metrics]);

  return (
    <>
      <motion.div
        initial={{ y: 12, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        className="flex h-10 items-center justify-between border-t border-nexus-border bg-nexus-panel px-5 text-[11px]"
      >
        <div className="flex items-center gap-5">
          {/* System status */}
          <div className="flex items-center gap-1.5">
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${systemOnline ? "bg-green-500" : "bg-red-500"}`}
            />
            <span
              className={systemOnline ? "text-green-400" : "text-red-400"}
            >
              {systemOnline ? "Online" : "Offline"}
            </span>
            <span className="text-nexus-muted">Sistema</span>
          </div>

          {/* Ollama status */}
          <div className="flex items-center gap-1.5">
            <Zap
              className={`h-3 w-3 ${ollamaOnline ? "text-green-400" : "text-red-400"}`}
            />
            <span
              className={ollamaOnline ? "text-green-400" : "text-red-400"}
            >
              {ollamaOnline ? "Conectado" : "Desconectado"}
            </span>
            <span className="text-nexus-muted">Ollama</span>
          </div>

          <div className="h-4 w-px bg-nexus-border" />

          {/* CPU */}
          <div className="flex items-center gap-2 text-nexus-muted">
            <span>CPU</span>
            <span className="font-medium text-nexus-text">
              {metrics?.cpu_percent != null
                ? `${metrics.cpu_percent.toFixed(0)}%`
                : "—"}
            </span>
            {cpuHistory.length > 1 && (
              <MiniSpark data={cpuHistory} color="#60a5fa" />
            )}
          </div>

          {/* RAM */}
          <div className="flex items-center gap-2 text-nexus-muted">
            <span>RAM</span>
            <span className="font-medium text-nexus-text">
              {metrics?.ram_percent != null
                ? `${metrics.ram_percent.toFixed(0)}%`
                : "—"}
            </span>
            {ramHistory.length > 1 && (
              <MiniSpark data={ramHistory} color="#a78bfa" />
            )}
          </div>

          {/* Disk */}
          <div className="flex items-center gap-2 text-nexus-muted">
            <span>Disk</span>
            <span className="font-medium text-nexus-text">
              {metrics?.disk_percent != null
                ? `${metrics.disk_percent.toFixed(0)}%`
                : "—"}
            </span>
            {diskHistory.length > 1 && (
              <MiniSpark data={diskHistory} color="#5eead4" />
            )}
          </div>
        </div>

        <div className="flex items-center gap-4 text-nexus-muted">
          <div className="flex items-center gap-1.5">
            <Clock className="h-3 w-3" />
            <span>
              Uptime:{" "}
              {metrics?.uptime_seconds
                ? formatUptime(metrics.uptime_seconds)
                : "—"}
            </span>
          </div>
          <div className="h-4 w-px bg-nexus-border" />
          <button
            onClick={() => setShowLogs(true)}
            className="flex items-center gap-1.5 hover:text-nexus-text transition-colors"
          >
            <FileText className="h-3 w-3" />
            Ver Logs
          </button>
        </div>
      </motion.div>

      <AnimatePresence>
        {showLogs && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
            onClick={() => setShowLogs(false)}
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              exit={{ scale: 0.95 }}
              className="h-96 w-full max-w-4xl overflow-auto rounded-xl border border-nexus-border bg-nexus-panel p-4"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-sm font-semibold">System Logs</h2>
                <button
                  onClick={() => setShowLogs(false)}
                  className="rounded-lg p-1 hover:bg-nexus-card transition-colors"
                >
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="space-y-2 text-xs font-mono">
                <div className="rounded-lg bg-nexus-bg p-3">
                  {logs.length > 0 ? (
                    logs.map((log, i) => (
                      <div
                        key={i}
                        className={
                          log.startsWith("✓")
                            ? "text-green-400"
                            : log.startsWith("✗")
                              ? "text-red-400"
                              : "text-nexus-muted"
                        }
                      >
                        {log}
                      </div>
                    ))
                  ) : (
                    <div className="text-nexus-muted">
                      A carregar logs do sistema...
                    </div>
                  )}
                </div>
                <div className="rounded-lg bg-nexus-bg p-3 text-nexus-muted">
                  <div>Detalhes do sistema</div>
                  <div className="mt-1">
                    • RAM:{" "}
                    {metrics
                      ? `${formatBytes(metrics.ram_used_bytes)} / ${formatBytes(metrics.ram_total_bytes)}`
                      : "—"}
                  </div>
                  <div>
                    • Disk:{" "}
                    {metrics
                      ? `${formatBytes(metrics.disk_used_bytes)} / ${formatBytes(metrics.disk_total_bytes)}`
                      : "—"}
                  </div>
                  <div>
                    • Tokens/s:{" "}
                    {metrics?.tokens_per_second?.toFixed(1) ?? "—"}
                  </div>
                  <div>
                    • Latência:{" "}
                    {metrics?.avg_latency_ms?.toFixed(0) ?? "—"}ms
                  </div>
                </div>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </>
  );
}
