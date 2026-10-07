"use client";

import { useMemo } from "react";
import { Clock, HardDrive, Zap } from "lucide-react";
import { AreaChart, Area, ResponsiveContainer } from "recharts";
import { useMetricsStore } from "../../stores/metricsStore";
import { StatusDot } from "../ui/Primitives";

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
  const connectionStatus = useMetricsStore((s) => s.connectionStatus);

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

  const hasActiveModel = Boolean(metrics && metrics.active_model && metrics.active_model !== "none");
  const diskPercent = metrics?.disk_percent;
  const diskTone = diskPercent != null && diskPercent >= 90
    ? "danger"
    : diskPercent != null && diskPercent >= 75
      ? "warning"
      : "success";
  const diskTextClass = diskTone === "danger"
    ? "text-rose-400"
    : diskTone === "warning"
      ? "text-amber-300"
      : "text-nexus-text";
  const connectionTone = connectionStatus === "degraded"
    ? "warning"
    : backendOnline
      ? "success"
      : connectionStatus === "connecting"
        ? "warning"
        : "danger";
  const connectionLabel = connectionStatus === "degraded"
    ? "Degradado"
    : backendOnline
      ? "A responder"
      : connectionStatus === "connecting"
        ? "A ligar"
        : "Offline";

  return (
    <div
      role="region"
      aria-label="Estado do sistema"
      tabIndex={0}
      className="thin-scrollbar relative z-20 flex h-9 w-full min-w-0 shrink-0 items-center overflow-x-auto overflow-y-hidden border-t border-nexus-border/60 bg-nexus-panel px-3 text-[10px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent sm:px-5"
    >
      <div className="flex min-w-0 flex-1 items-center justify-between gap-2 sm:min-w-max sm:gap-4">
        <div className="flex min-w-0 shrink-0 items-center gap-2.5 sm:gap-5">
          {/* Liveness only: readiness and resource pressure are shown separately. */}
          <div className="flex items-center gap-1.5">
            <StatusDot tone={connectionTone} pulse={connectionStatus === "connecting"} size={7} />
            <span className={connectionTone === "success" ? "text-emerald-400" : connectionTone === "warning" ? "text-amber-300" : "text-rose-400"}>
              {connectionLabel}
            </span>
            <span className="text-nexus-faint">Backend</span>
          </div>

          {/* Modelo ativo — dado real do backend (cloud-only, sem Ollama local) */}
          <div className="flex items-center gap-1.5">
            <Zap className={`h-3 w-3 ${hasActiveModel ? "text-emerald-400" : "text-nexus-faint"}`} />
            <span className={`max-w-[100px] truncate sm:max-w-[180px] ${hasActiveModel ? "text-nexus-text" : "text-nexus-faint"}`} title={hasActiveModel ? metrics!.active_model : undefined}>
              {hasActiveModel ? metrics!.active_model : "—"}
            </span>
            <span className="text-nexus-faint">Modelo</span>
          </div>

          <div className="hidden h-4 w-px bg-nexus-border sm:block" />

          {/* CPU */}
          <div className="hidden items-center gap-2 text-nexus-faint sm:flex">
            <span>CPU</span>
            <span className="tabular font-medium text-nexus-text">
              {metrics?.cpu_percent != null ? `${metrics.cpu_percent.toFixed(0)}%` : "—"}
            </span>
            {cpuHistory.length > 1 && <MiniSpark data={cpuHistory} color="#60a5fa" />}
          </div>

          {/* RAM */}
          <div className="hidden items-center gap-2 text-nexus-faint sm:flex">
            <span>RAM</span>
            <span className="tabular font-medium text-nexus-text">
              {metrics?.ram_percent != null ? `${metrics.ram_percent.toFixed(0)}%` : "—"}
            </span>
            {ramHistory.length > 1 && <MiniSpark data={ramHistory} color="#a78bfa" />}
          </div>

          {/* Disk */}
          <div className="hidden items-center gap-2 text-nexus-faint sm:flex">
            <span>Disco</span>
            <span className={`tabular font-medium ${diskTextClass}`}>
              {metrics?.disk_percent != null ? `${metrics.disk_percent.toFixed(0)}%` : "—"}
            </span>
            {diskHistory.length > 1 && <MiniSpark data={diskHistory} color={diskTone === "danger" ? "#fb7185" : diskTone === "warning" ? "#fbbf24" : "#5eead4"} />}
          </div>

          {diskPercent != null && diskPercent >= 75 && (
            <div
              className={`flex items-center gap-1.5 sm:hidden ${diskTextClass}`}
              role="status"
              aria-label={`Disco ${diskPercent.toFixed(0)}%, ${diskTone === "danger" ? "crítico" : "em aviso"}`}
            >
              <HardDrive className="h-3 w-3" aria-hidden="true" />
              <span>Disco {diskPercent.toFixed(0)}%</span>
              {diskTone === "danger" && <span className="font-semibold">Crítico</span>}
            </div>
          )}
        </div>

        <div className="hidden shrink-0 items-center gap-4 text-nexus-faint sm:flex">
          <div className="flex items-center gap-1.5">
            <Clock className="h-3 w-3" />
            <span>Uptime: {metrics?.uptime_seconds ? formatUptime(metrics.uptime_seconds) : "—"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}
