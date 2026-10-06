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

function isMeasuredNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export default function NexusTopBar() {
  const metrics = useMetricsStore((state) => state.metrics);
  const backendOnline = useMetricsStore((state) => state.backendOnline);
  const hasTelemetry = Boolean(metrics && [
    metrics.cpu_percent,
    metrics.ram_percent,
    metrics.disk_percent,
    metrics.tokens_per_second,
    metrics.queue_depth,
    metrics.active_sessions,
    metrics.requests_total,
    metrics.avg_latency_ms,
  ].some(isMeasuredNumber));
  const agents = Object.values(useAgentStore((state) => state.agents));
  const hasFetchedAgents = useAgentStore((state) => state.hasFetchedAgents);
  const agentsError = useAgentStore((state) => state.error);
  const tasks = Object.values(useTaskStore((state) => state.tasks));
  const hasFetchedTasks = useTaskStore((state) => state.hasFetchedTasks);
  const tasksError = useTaskStore((state) => state.tasksError);

  const activeAgents = agents.filter((agent) => [
    "thinking", "planning", "executing", "running", "tool_call", "waiting", "autonomous_loop", "learning", "syncing_memory",
  ].includes(agent.status)).length;
  const agentsKnown = agents.length > 0 || (hasFetchedAgents && !agentsError);
  const runningTasks = tasks.filter((task) => task.status === "running" || task.status === "retrying").length;
  const pendingTasks = tasks.filter((task) => ["pending", "queued", "approved", "awaiting_approval"].includes(task.status)).length;
  const tasksKnown = tasks.length > 0 || hasFetchedTasks;
  const taskStale = Boolean(tasksError && tasks.length > 0);
  const taskCountLabel = (count: number) => count >= 50 ? "50+" : String(count);

  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-slate-700/50 bg-[#0d0d2b]/90 pl-14 pr-4 backdrop-blur-xl md:px-4">
      <div className="flex items-center gap-3">
        <div>
          <h1 className="text-sm font-bold uppercase tracking-tight text-slate-100">Nexus</h1>
          <p className="text-[9px] uppercase tracking-wider text-slate-400">Centro de controlo</p>
        </div>
        <span className={`flex items-center gap-1.5 rounded-full border px-2 py-1 text-[9px] font-semibold uppercase ${
          backendOnline
            ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-400"
            : "border-slate-600 bg-slate-800/50 text-slate-400"
        }`}>
          {backendOnline ? <Wifi className="h-3 w-3" /> : <WifiOff className="h-3 w-3" />}
          {backendOnline
            ? hasTelemetry ? "API ligada" : "API ligada · sem dados"
            : hasTelemetry ? "Sem ligação · dados antigos" : "Sem ligação"}
        </span>
      </div>

      <div className="hidden items-center gap-2 lg:flex">
        <Metric icon={Users} label={agentsError && agents.length > 0 ? "agentes · desatualizados" : "agentes ativos"} value={agentsKnown ? String(activeAgents) : "—"} />
        <Metric icon={Activity} label="pedidos" value={isMeasuredNumber(metrics?.requests_total) ? String(metrics.requests_total) : "—"} />
        <Metric icon={Clock3} label="latência" value={isMeasuredNumber(metrics?.avg_latency_ms) ? `${metrics.avg_latency_ms.toFixed(0)} ms` : "—"} />
        <Metric icon={Zap} label="tokens/s" value={isMeasuredNumber(metrics?.tokens_per_second) ? metrics.tokens_per_second.toFixed(1) : "—"} />
        <Metric icon={Cpu} label="cpu" value={isMeasuredNumber(metrics?.cpu_percent) ? `${metrics.cpu_percent.toFixed(0)}%` : "—"} />
        <Metric icon={HardDrive} label="ram" value={isMeasuredNumber(metrics?.ram_percent) ? `${metrics.ram_percent.toFixed(0)}%` : "—"} />
      </div>

      <div className="text-right text-[10px]" title={taskStale ? "A mostrar o último estado de tarefas recebido." : undefined}>
        <div className="font-medium text-slate-200">{tasksKnown ? taskCountLabel(runningTasks) : "—"} em execução</div>
        <div className="text-slate-400">{tasksKnown ? taskCountLabel(pendingTasks) : "—"} em fila{taskStale ? " · desatualizado" : ""}</div>
      </div>
    </header>
  );
}
