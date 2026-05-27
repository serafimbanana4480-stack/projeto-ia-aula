"use client";

import { useMemo } from "react";
import { Clock, Zap } from "lucide-react";
import { AreaChart, Area, ResponsiveContainer } from "recharts";
import { useMetricsStore } from "../../stores/metricsStore";

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

export default function BottomHUD() {
  const metrics = useMetricsStore((s) => s.metrics);
  const backendOnline = useMetricsStore((s) => s.backendOnline);

  // Derive sparkline data from history
  const history = useMetricsStore((s) => s.history);
  const cpuHistory = useMemo(
    () => history.slice(-20).map((m) => ({ v: m.cpu_percent })),
    [history]
  );
  const ramHistory = useMemo(
    () => history.slice(-20).map((m) => ({ v: m.ram_percent })),
    [history]
  );
  const diskHistory = useMemo(
    () => history.slice(-20).map((m) => ({ v: m.disk_percent })),
    [history]
  );

  return (
    <div className="flex h-10 items-center justify-between border-t border-nexus-border bg-nexus-panel px-5 text-[11px]">
      <div className="flex items-center gap-5">
        {/* System status */}
        <div className="flex items-center gap-1.5">
          <span
            className={`inline-block h-1.5 w-1.5 rounded-full ${backendOnline ? "bg-green-500" : "bg-red-500"}`}
          />
          <span className={backendOnline ? "text-green-400" : "text-red-400"}>
            {backendOnline ? "Online" : "Offline"}
          </span>
          <span className="text-nexus-muted">Sistema</span>
        </div>

        {/* Ollama status — derived from active_model */}
        <div className="flex items-center gap-1.5">
          <Zap
            className={`h-3 w-3 ${metrics && metrics.active_model !== "none" ? "text-green-400" : "text-yellow-400"}`}
          />
          <span
            className={metrics && metrics.active_model !== "none" ? "text-green-400" : "text-yellow-400"}
          >
            {metrics && metrics.active_model !== "none" ? "Conectado" : "Standby"}
          </span>
          <span className="text-nexus-muted">Ollama</span>
        </div>

        <div className="h-4 w-px bg-nexus-border" />

        {/* CPU */}
        <div className="flex items-center gap-2 text-nexus-muted">
          <span>CPU</span>
          <span className="font-medium text-nexus-text">
            {metrics?.cpu_percent != null ? `${metrics.cpu_percent.toFixed(0)}%` : "—"}
          </span>
          {cpuHistory.length > 1 && <MiniSpark data={cpuHistory} color="#60a5fa" />}
        </div>

        {/* RAM */}
        <div className="flex items-center gap-2 text-nexus-muted">
          <span>RAM</span>
          <span className="font-medium text-nexus-text">
            {metrics?.ram_percent != null ? `${metrics.ram_percent.toFixed(0)}%` : "—"}
          </span>
          {ramHistory.length > 1 && <MiniSpark data={ramHistory} color="#a78bfa" />}
        </div>

        {/* Disk */}
        <div className="flex items-center gap-2 text-nexus-muted">
          <span>Disk</span>
          <span className="font-medium text-nexus-text">
            {metrics?.disk_percent != null ? `${metrics.disk_percent.toFixed(0)}%` : "—"}
          </span>
          {diskHistory.length > 1 && <MiniSpark data={diskHistory} color="#5eead4" />}
        </div>
      </div>

      <div className="flex items-center gap-4 text-nexus-muted">
        <div className="flex items-center gap-1.5">
          <Clock className="h-3 w-3" />
          <span>Uptime: {metrics?.uptime_seconds ? formatUptime(metrics.uptime_seconds) : "—"}</span>
        </div>
      </div>
    </div>
  );
}
