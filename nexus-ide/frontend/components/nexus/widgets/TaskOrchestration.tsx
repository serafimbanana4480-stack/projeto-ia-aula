"use client";

import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ListChecks, Clock, AlertTriangle, CheckCircle2,
  XCircle, Loader2, RotateCcw, Ban, ArrowUp,
  ArrowDown, Minus, Zap, Bot, Lock, Play,
} from "lucide-react";
import { useTaskStore, type Task, type TaskPriority, type TaskStatus } from "../../../stores/useTaskStore";

const PRIORITY_CONFIG: Record<TaskPriority, { color: string; icon: React.ElementType; label: string }> = {
  critical: { color: "#ef4444", icon: Zap, label: "Critical" },
  high: { color: "#f97316", icon: ArrowUp, label: "High" },
  medium: { color: "#f59e0b", icon: Minus, label: "Medium" },
  low: { color: "#64748b", icon: ArrowDown, label: "Low" },
};

const STATUS_CONFIG: Record<TaskStatus, { color: string; icon: React.ElementType; label: string }> = {
  pending: { color: "#475569", icon: Clock, label: "Pending" },
  queued: { color: "#64748b", icon: Loader2, label: "Queued" },
  running: { color: "#a78bfa", icon: Loader2, label: "Running" },
  completed: { color: "#10b981", icon: CheckCircle2, label: "Completed" },
  failed: { color: "#ef4444", icon: XCircle, label: "Failed" },
  blocked: { color: "#dc2626", icon: Ban, label: "Blocked" },
  retrying: { color: "#f97316", icon: RotateCcw, label: "Retrying" },
};

function TaskRow({ task }: { task: Task }) {
  const pConfig = PRIORITY_CONFIG[task.priority];
  const sConfig = STATUS_CONFIG[task.status];
  const PIcon = pConfig.icon;
  const SIcon = sConfig.icon;

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
        <PIcon size={11} style={{ color: pConfig.color }} />
        <span className="text-[8px] font-bold uppercase" style={{ color: pConfig.color }}>{task.priority}</span>
      </div>

      {/* Main content */}
      <div className="flex-1 min-w-0">
        <div className="flex items-start justify-between gap-2 mb-1">
          <p className="text-[12px] font-semibold text-slate-200 leading-tight">{task.title}</p>
          {task.retries > 0 && (
            <span className="shrink-0 text-[9px] px-1.5 py-0.5 rounded bg-amber-500/15 border border-amber-500/40 text-amber-300 font-semibold">
              retry #{task.retries}
            </span>
          )}
        </div>
        <p className="text-[10px] text-slate-500 mb-2 line-clamp-1">{task.description}</p>
        <div className="flex items-center gap-3 flex-wrap">
          <span className="flex items-center gap-1 text-[9px] text-slate-500">
            <Bot size={9} /> {task.agentId}
          </span>
          <span className="text-[9px] text-slate-600">${task.costActual.toFixed(4)}</span>
          <span className="text-[9px] text-slate-600">{task.tokensUsed.toLocaleString()} tok</span>
          {task.tags.map(tag => (
            <span key={tag} className="text-[8px] px-1 py-0.5 rounded bg-slate-800/80 border border-slate-700/60 text-slate-400">
              {tag}
            </span>
          ))}
        </div>

        {/* Progress bar */}
        {task.status === "running" && (
          <div className="mt-2">
            <div className="flex justify-between text-[9px] text-slate-500 mb-0.5">
              <span>Progress</span>
              <span>{task.progress.toFixed(0)}%</span>
            </div>
            <div className="h-1 rounded-full bg-slate-800 overflow-hidden">
              <motion.div
                className="h-full rounded-full bg-gradient-to-r from-violet-600 to-cyan-500"
                animate={{ width: `${task.progress}%` }}
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
  const { tasks, taskQueue } = useTaskStore();
  const allTasks = Object.values(tasks);

  const byStatus = {
    running: allTasks.filter(t => t.status === "running"),
    queued: allTasks.filter(t => t.status === "queued"),
    pending: allTasks.filter(t => t.status === "pending"),
    blocked: allTasks.filter(t => t.status === "blocked"),
    retrying: allTasks.filter(t => t.status === "retrying"),
    completed: allTasks.filter(t => t.status === "completed").slice(0, 5),
    failed: allTasks.filter(t => t.status === "failed"),
  };

  const statusOrder: TaskStatus[] = ["running", "queued", "pending", "retrying", "blocked", "failed", "completed"];

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-800/60">
        <div className="flex items-center justify-between mb-2">
          <div className="flex items-center gap-2">
            <ListChecks size={13} className="text-amber-400" />
            <span className="text-[11px] uppercase tracking-widest font-bold text-slate-400">Task Orchestration</span>
          </div>
          <div className="flex items-center gap-3 text-[10px]">
            <span className="flex items-center gap-1 text-amber-400"><ArrowUp size={10} /> {byStatus.running.length} running</span>
            <span className="flex items-center gap-1 text-slate-400"><Clock size={10} /> {byStatus.queued.length} queued</span>
            <span className="flex items-center gap-1 text-slate-400"><AlertTriangle size={10} /> {byStatus.blocked.length} blocked</span>
          </div>
        </div>

        {/* Queue preview */}
        {taskQueue.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-[9px] text-slate-500 uppercase tracking-wider">Queue:</span>
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
                <span className="text-[9px] text-slate-600">+{taskQueue.length - 5} more</span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Task groups */}
      <div className="flex-1 overflow-y-auto">
        {statusOrder.map(status => {
          const group = byStatus[status];
          if (group.length === 0) return null;
          const cfg = STATUS_CONFIG[status];

          return (
            <div key={status}>
              {/* Group header */}
              <div className="flex items-center gap-2 px-4 py-2 bg-slate-900/50 border-b border-slate-800/40 sticky top-0 z-10">
                <cfg.icon size={11} style={{ color: cfg.color }} className={status === "running" ? "animate-spin" : ""} />
                <span className="text-[10px] font-bold uppercase tracking-wider" style={{ color: cfg.color }}>{cfg.label}</span>
                <span className="text-[10px] text-slate-600">({group.length})</span>
              </div>

              {/* Tasks */}
              <AnimatePresence mode="popLayout">
                {group.map(task => (
                  <TaskRow key={task.id} task={task} />
                ))}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </div>
  );
}
