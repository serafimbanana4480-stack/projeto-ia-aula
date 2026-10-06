"use client";

import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ListChecks, Clock, AlertTriangle, CheckCircle2,
  XCircle, Loader2, RotateCcw, Ban, ArrowUp,
  ArrowDown, Minus, Zap, Bot,
} from "lucide-react";
import { useTaskStore, type Task, type TaskPriority, type TaskStatus } from "../../../stores/useTaskStore";

const PRIORITY_CONFIG: Record<TaskPriority, { color: string; icon: React.ElementType; label: string }> = {
  critical: { color: "#ef4444", icon: Zap, label: "Crítica" },
  high: { color: "#f97316", icon: ArrowUp, label: "Alta" },
  medium: { color: "#f59e0b", icon: Minus, label: "Média" },
  low: { color: "#64748b", icon: ArrowDown, label: "Baixa" },
};

const STATUS_CONFIG: Record<TaskStatus, { color: string; icon: React.ElementType; label: string }> = {
  pending: { color: "#475569", icon: Clock, label: "Pendente" },
  queued: { color: "#64748b", icon: Loader2, label: "Na fila" },
  running: { color: "#a78bfa", icon: Loader2, label: "Em curso" },
  completed: { color: "#10b981", icon: CheckCircle2, label: "Concluída" },
  failed: { color: "#ef4444", icon: XCircle, label: "Falhou" },
  blocked: { color: "#dc2626", icon: Ban, label: "Bloqueada" },
  retrying: { color: "#f97316", icon: RotateCcw, label: "A tentar novamente" },
  awaiting_approval: { color: "#f59e0b", icon: Clock, label: "A aguardar aprovação" },
  approved: { color: "#a78bfa", icon: Clock, label: "Aprovada · na fila" },
  paused: { color: "#f59e0b", icon: Clock, label: "Pausada" },
  cancelled: { color: "#64748b", icon: Ban, label: "Cancelada" },
  unknown: { color: "#64748b", icon: Clock, label: "Desconhecido" },
};

function TaskRow({ task }: { task: Task }) {
  const pConfig = task.priority ? PRIORITY_CONFIG[task.priority] : undefined;
  const sConfig = STATUS_CONFIG[task.status] ?? STATUS_CONFIG.pending;
  const PIcon = pConfig?.icon;
  const SIcon = sConfig.icon;
  const progress = typeof task.progress === "number" && Number.isFinite(task.progress)
    ? Math.min(100, Math.max(0, task.progress))
    : undefined;

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 12 }}
      className="flex items-start gap-3 px-4 py-3 hover:bg-slate-800/30 transition-colors border-b border-slate-800/40 last:border-0"
    >
      {/* Priority */}
      <div className="flex flex-col items-center gap-0.5 pt-0.5">
        {PIcon && pConfig ? (
          <PIcon size={11} style={{ color: pConfig.color }} />
        ) : (
          <span className="text-[8px] text-slate-600" aria-label="Priority not provided">—</span>
        )}
        <span className="text-[8px] font-bold uppercase" style={{ color: pConfig?.color ?? "#64748b" }}>
          {pConfig?.label ?? "Sem prioridade"}
        </span>
      </div>

      {/* Main content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2 mb-1">
          <p className="text-[12px] font-semibold text-slate-200 leading-tight">{task.title}</p>
          {(task.retries ?? 0) > 0 && (
            <span className="shrink-0 text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 border border-amber-500/40 text-amber-300 font-semibold">
              tentativa {task.retries}
            </span>
          )}
        </div>
        {task.description && (
          <p className="text-[10px] text-slate-500 mb-2 line-clamp-1">{task.description}</p>
        )}
        {task.kind === "plan" && task.completedSteps !== undefined && task.totalSteps !== undefined && (
          <p className="mb-2 text-[10px] tabular-nums text-slate-400">
            {task.completedSteps}/{task.totalSteps} etapas
            {task.approvalStatus === "awaiting_approval" && <span className="ml-2 text-amber-300">Rever no chat</span>}
          </p>
        )}
        <div className="flex items-center gap-3 flex-wrap">
          {task.agentId && (
            <span className="flex items-center gap-1 text-[9px] text-slate-500">
              <Bot size={9} /> {task.agentId}
            </span>
          )}
          {typeof task.costActual === "number" && Number.isFinite(task.costActual) && (
            <span className="text-[9px] text-slate-600">${task.costActual.toFixed(4)}</span>
          )}
          {typeof task.tokensUsed === "number" && Number.isFinite(task.tokensUsed) && (
            <span className="text-[9px] text-slate-600">{task.tokensUsed.toLocaleString()} tok</span>
          )}
          {(task.tags ?? []).map(tag => (
            <span key={tag} className="text-[8px] px-1 py-0.5 rounded bg-slate-800/80 border border-slate-700/60 text-slate-400">
              {tag}
            </span>
          ))}
        </div>

        {/* Progress bar */}
        {task.status === "running" && progress !== undefined && (
          <div className="mt-2">
            <div className="flex justify-between text-[9px] text-slate-500 mb-0.5">
              <span>Progresso</span>
              <span>{progress.toFixed(0)}%</span>
            </div>
            <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
              <motion.div
                className="h-full rounded-full bg-gradient-to-r from-violet-600 to-cyan-500"
                animate={{ width: `${progress}%` }}
                transition={{ duration: 0.5 }}
              />
            </div>
          </div>
        )}
      </div>

      {/* Status */}
      <div className="flex flex-col items-end gap-1 pt-0.5">
        <div className="flex items-center gap-1">
          <SIcon
            size={11}
            style={{ color: sConfig.color }}
            className={task.status === "running" ? "animate-spin" : ""}
          />
          <span className="text-[9px] font-semibold" style={{ color: sConfig.color }}>{sConfig.label}</span>
        </div>
        {task.status === "failed" && task.error && (
          <p className="text-[9px] text-red-400 max-w-[120px] truncate text-right" title={task.error}>
            {task.error}
          </p>
        )}
      </div>
    </motion.div>
  );
}

export default function TaskOrchestration() {
  const tasks = useTaskStore((state) => state.tasks);
  const taskQueue = useTaskStore((state) => state.taskQueue);
  const loading = useTaskStore((state) => state.tasksLoading);
  const error = useTaskStore((state) => state.tasksError);
  const warnings = useTaskStore((state) => state.tasksWarnings);
  const allTasks = Object.values(tasks);
  const displayCount = (count: number) => allTasks.length > 0 ? String(count) : "—";

  const byStatus = {
    running: allTasks.filter(t => t.status === "running"),
    queued: allTasks.filter(t => t.status === "queued"),
    pending: allTasks.filter(t => t.status === "pending"),
    blocked: allTasks.filter(t => t.status === "blocked"),
    awaiting_approval: allTasks.filter(t => t.status === "awaiting_approval"),
    approved: allTasks.filter(t => t.status === "approved"),
    paused: allTasks.filter(t => t.status === "paused"),
    retrying: allTasks.filter(t => t.status === "retrying"),
    completed: allTasks.filter(t => t.status === "completed").slice(0, 5),
    failed: allTasks.filter(t => t.status === "failed"),
    cancelled: allTasks.filter(t => t.status === "cancelled"),
    unknown: allTasks.filter(t => t.status === "unknown"),
  };

  const statusOrder: TaskStatus[] = [
    "running", "awaiting_approval", "approved", "queued", "pending", "paused",
    "retrying", "blocked", "failed", "completed", "cancelled", "unknown",
  ];

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-slate-800/60 px-3 py-3 sm:px-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <ListChecks size={13} className="text-amber-400" />
            <span className="text-[11px] uppercase tracking-widest font-bold text-slate-400">Tarefas</span>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px]">
            <span className="flex items-center gap-1 text-amber-400"><ArrowUp size={10} /> {displayCount(byStatus.running.length)} em curso</span>
            <span className="flex items-center gap-1 text-slate-400"><Clock size={10} /> {displayCount(byStatus.queued.length + byStatus.approved.length + byStatus.awaiting_approval.length)} na fila</span>
            <span className="flex items-center gap-1 text-slate-400"><AlertTriangle size={10} /> {displayCount(byStatus.blocked.length)} bloqueadas</span>
          </div>
        </div>

        {/* Queue preview */}
        {taskQueue.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-[9px] text-slate-500 uppercase tracking-wider">Fila:</span>
            <div className="flex gap-1 overflow-x-auto">
              {taskQueue.slice(0, 5).map((taskId, i) => (
                <motion.span
                  key={taskId}
                  initial={{ opacity: 0, scale: 0.8 }}
                  animate={{ opacity: 1, scale: 1 }}
                  className="text-[9px] px-1.5 py-0.5 rounded bg-slate-800/80 border border-slate-700/60 text-slate-400 font-mono whitespace-nowrap"
                >
                  {i + 1}. {tasks[taskId]?.title.slice(0, 30) || taskId}
                </motion.span>
              ))}
              {taskQueue.length > 5 && (
                <span className="text-[9px] text-slate-600">+{taskQueue.length - 5} mais</span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Task groups */}
      <div className="flex-1 overflow-y-auto">
        {error && (
          <p role="status" className="border-b border-rose-500/20 px-4 py-2 text-[10px] text-rose-300">
            {allTasks.length > 0
              ? "Não foi possível atualizar as tarefas. A mostrar o último estado recebido."
              : "Não foi possível obter as tarefas agora."}
          </p>
        )}
        {warnings.length > 0 && (
          <p role="status" className="border-b border-amber-500/20 px-4 py-2 text-[10px] text-amber-200">
            Parte dos dados está desatualizada: {warnings.join(" ")}
          </p>
        )}
        {allTasks.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center gap-2 text-slate-500">
            {loading ? <Loader2 size={18} className="animate-spin" aria-label="A carregar tarefas" /> : <ListChecks size={20} className="opacity-30" />}
            <p className="text-xs">{loading ? "A carregar tarefas…" : error ? "Lista de tarefas indisponível" : "Ainda não há tarefas registadas"}</p>
          </div>
        ) : (
          statusOrder.map(status => {
            const group = byStatus[status];
            if (group.length === 0) return null;
            const cfg = STATUS_CONFIG[status];

            return (
              <div key={status}>
                <div className="flex items-center gap-2 px-4 py-2 bg-slate-900/50 border-b border-slate-800/40 sticky top-0 z-10">
                  <cfg.icon size={11} style={{ color: cfg.color }} className={status === "running" ? "animate-spin" : ""} />
                  <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: cfg.color }}>{cfg.label}</span>
                  <span className="text-[10px] text-slate-600">({group.length})</span>
                </div>
                <AnimatePresence mode="popLayout">
                  {group.map(task => <TaskRow key={task.id} task={task} />)}
                </AnimatePresence>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
