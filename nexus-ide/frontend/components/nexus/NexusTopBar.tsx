"use client";

import { Activity, Clock3, Cpu, HardDrive, Users, Wifi, WifiOff, Zap } from "lucide-react";
import { useAgentStore } from "../../stores/useAgentStore";
import { useTaskStore } from "../../stores/useTaskStore";
import { useMetricsStore } from "../../stores/metricsStore";

function Metric({ icon: Icon, label, value }: { icon: typeof Activity; label: string; value: string }) {
  return (
    <div className="flex items-center gap-2 rounded-lg border border-slate-700/50 bg-slate-800/40 px-2.5 py-1.5">
      <Icon className="h-3.5 w-3.5 text-violet-300" />
      <div>
        <div className="text-[11px] font-semibold leading-none text-slate-100">{value}</div>
        <div className="mt-1 text-[8px] uppercase tracking-wider text-slate-400">{label}</div>
      </div>
    </div>
  );
}

export default function NexusTopBar() {
  const metrics = useMetricsStore((state) => state.metrics);
  const backendOnline = useMetricsStore((state) => state.backendOnline);
  const agents = Object.values(useAgentStore((state) => state.agents));
  const tasks = Object.values(useTaskStore((state) => state.tasks));

  const activeAgents = agents.filter((agent) => agent.status !== "idle").length;
  const runningTasks = tasks.filter((task) => task.status === "running").length;
  const pendingTasks = tasks.filter((task) => task.status === "pending" || task.status === "queued").length;

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-700/50 bg-[#0d0d2b]/90 px-4 backdrop-blur-xl">
      <div className="flex items-center gap-3">
        <div>
          <h1 className="text-sm font-bold uppercase tracking-tight text-slate-100">Nexus</h1>
          <p className="text-[9px] uppercase tracking-wider text-slate-400">Mission control</p>
        </div>
        <span className={`flex items-center gap-1.5 rounded-full border px-2 py-1 text-[9px] font-semibold uppercase ${
          backendOnline
            ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
            : "border-slate-600 bg-slate-800/50 text-slate-400"
        }`}>
          {backendOnline ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
          {backendOnline ? "Ligado" : "Offline"}
        </span>
      </div>

      <div className="hidden items-center gap-2 lg:flex">
        <Metric icon={Users} label="agentes ativos" value={String(activeAgents)} />
        <Metric icon={Activity} label="pedidos" value={metrics ? String(metrics.requests_total) : "—"} />
        <Metric icon={Clock3} label="latência" value={metrics?.avg_latency_ms != null ? `${metrics.avg_latency_ms.toFixed(0)} ms` : "—"} />
        <Metric icon={Zap} label="tokens/s" value={metrics?.tokens_per_second != null ? metrics.tokens_per_second.toFixed(1) : "—"} />
        <Metric icon={Cpu} label="cpu" value={metrics?.cpu_percent != null ? `${metrics.cpu_percent.toFixed(0)}%` : "—"} />
        <Metric icon={HardDrive} label="ram" value={metrics?.ram_percent != null ? `${metrics.ram_percent.toFixed(0)}%` : "—"} />
      </div>

      <div className="text-right text-[10px]">
        <div className="font-medium text-slate-200">{runningTasks} em execução</div>
        <div className="text-slate-400">{pendingTasks} em fila</div>
      </div>
    </header>
  );
}
