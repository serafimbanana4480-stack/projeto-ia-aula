"use client";

import React from "react";
import { motion } from "framer-motion";
import {
  GitBranch, CheckCircle2, XCircle, Clock, Loader2,
  RotateCcw, ArrowRight, Zap, Bot, Cpu,
} from "lucide-react";
import { useTaskStore, type Workflow, type WorkflowStep } from "../../../stores/useTaskStore";
import type { StoreApi } from "zustand";

const STATUS_CONFIG: Record<string, { icon: React.ElementType; color: string; label: string }> = {
  pending: { icon: Clock, color: "#475569", label: "Pending" },
  running: { icon: Loader2, color: "#a78bfa", label: "Running" },
  done: { icon: CheckCircle2, color: "#10b981", label: "Done" },
  failed: { icon: XCircle, color: "#ef4444", label: "Failed" },
  skipped: { icon: RotateCcw, color: "#64748b", label: "Skipped" },
};

function WorkflowCard({ workflow }: { workflow: Workflow }) {
  const stepConfig = (s: WorkflowStep) => STATUS_CONFIG[s.status] || STATUS_CONFIG.pending;

  return (
    <div className="p-4 border-b border-slate-800/60 last:border-0">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <GitBranch size={13} className="text-violet-400" />
          <span className="text-[12px] font-bold text-slate-200">{workflow.name}</span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold border ${
            workflow.status === "running" ? "bg-violet-500/15 border-violet-500/40 text-violet-300" :
            workflow.status === "completed" ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300" :
            workflow.status === "failed" ? "bg-red-500/15 border-red-500/40 text-red-300" :
            "bg-slate-700/50 border-slate-600/60 text-slate-400"
          }`}>
            {workflow.status}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-slate-500">
          <span>${workflow.totalCost.toFixed(4)}</span>
          <span>{(workflow.totalTokens / 1000).toFixed(1)}K tok</span>
          <span>{workflow.progress.toFixed(0)}%</span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-1.5 rounded-full bg-slate-800 mb-3 overflow-hidden">
        <motion.div
          className="h-full rounded-full bg-gradient-to-r from-violet-600 to-cyan-500"
          animate={{ width: `${workflow.progress}%` }}
          transition={{ duration: 0.8 }}
        />
      </div>

      {/* Timeline steps */}
      <div className="relative">
        <div className="flex items-center gap-1 overflow-x-auto pb-1">
          {workflow.steps.map((step, idx) => {
            const cfg = stepConfig(step);
            const Icon = cfg.icon;
            const isLast = idx === workflow.steps.length - 1;

            return (
              <React.Fragment key={step.id}>
                {/* Step */}
                <motion.div
                  whileHover={{ scale: 1.05 }}
                  className="flex flex-col items-center gap-1 shrink-0"
                >
                  <div
                    className="w-8 h-8 rounded-lg border-2 flex items-center justify-center transition-all"
                    style={{
                      background: `${cfg.color}20`,
                      borderColor: cfg.color,
                      boxShadow: step.status === "running" ? `0 0 12px ${cfg.color}60` : "none",
                    }}
                  >
                    {step.status === "running" ? (
                      <motion.div
                        animate={{ rotate: 360 }}
                        transition={{ duration: 1, repeat: Infinity, ease: "linear" }}
                      >
                        <Icon size={14} style={{ color: cfg.color }} />
                      </motion.div>
                    ) : (
                      <Icon size={14} style={{ color: cfg.color }} />
                    )}
                  </div>
                  <span className="text-[8px] text-slate-500 text-center max-w-[64px] truncate">
                    {step.agentId}
                  </span>
                </motion.div>

                {/* Connector */}
                {!isLast && (
                  <div className="flex-1 flex items-center min-w-[16px]">
                    <div className={`h-px flex-1 ${
                      step.status === "done" ? "bg-emerald-500" :
                      step.status === "failed" ? "bg-red-500" :
                      "bg-slate-700"
                    }`} />
                    <ArrowRight size={10} className="text-slate-600 mx-0.5 shrink-0" />
                    <div className={`h-px flex-1 ${
                      workflow.steps[idx + 1]?.status === "done" ? "bg-emerald-500" :
                      workflow.steps[idx + 1]?.status === "running" ? "bg-violet-500" :
                      "bg-slate-700"
                    }`} />
                  </div>
                )}
              </React.Fragment>
            );
          })}
        </div>
      </div>

      {/* Duration */}
      {workflow.steps.find(s => s.status === "running") && (
        <div className="mt-2 flex items-center gap-2 text-[10px] text-slate-500">
          <Clock size={10} />
          {(() => {
            const running = workflow.steps.find(s => s.status === "running");
            if (running?.startedAt) {
              const elapsed = Math.floor((Date.now() - running.startedAt) / 1000);
              const m = Math.floor(elapsed / 60); const s = elapsed % 60;
              return <span>Running for {m > 0 ? `${m}m ` : ""}${s}s</span>;
            }
            return null;
          })()}
        </div>
      )}
    </div>
  );
}

export default function WorkflowTimeline() {
  const workflows = useTaskStore((s) => s.workflows);
  const workflowList = Object.values(workflows);

  return (
    <div className="h-full flex flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-800/60 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitBranch size={13} className="text-emerald-400" />
          <span className="text-[11px] uppercase tracking-widest font-bold text-slate-400">Workflow Timeline</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-800/80 text-slate-400 border border-slate-700/60">
            {workflowList.filter(w => w.status === "running").length} active
          </span>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-slate-500">
          {Object.values(STATUS_CONFIG).map(cfg => (
            <span key={cfg.label} className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full" style={{ background: cfg.color }} />
              {cfg.label}
            </span>
          ))}
        </div>
      </div>

      {/* Workflows */}
      <div className="flex-1 overflow-y-auto">
        {workflowList.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-40 text-slate-500">
            <GitBranch size={24} className="mb-2 opacity-25" />
            <p className="text-xs">No active workflows</p>
          </div>
        ) : (
          workflowList.map(wf => <WorkflowCard key={wf.id} workflow={wf} />)
        )}
      </div>
    </div>
  );
}
