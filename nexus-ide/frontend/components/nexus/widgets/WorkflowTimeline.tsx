"use client";

import React from "react";
import { motion } from "framer-motion";
import {
  GitBranch, CheckCircle2, XCircle, Clock, Loader2,
  RotateCcw, ArrowRight,
} from "lucide-react";
import { useTaskStore, type Workflow, type WorkflowStep } from "../../../stores/useTaskStore";

const STATUS_CONFIG: Record<string, { icon: React.ElementType; color: string; label: string }> = {
  pending: { icon: Clock, color: "#475569", label: "Pendente" },
  running: { icon: Loader2, color: "#a78bfa", label: "Em curso" },
  done: { icon: CheckCircle2, color: "#10b981", label: "Concluída" },
  failed: { icon: XCircle, color: "#ef4444", label: "Falhou" },
  skipped: { icon: RotateCcw, color: "#64748b", label: "Ignorada" },
  unknown: { icon: Clock, color: "#64748b", label: "Desconhecido" },
};

const WORKFLOW_STATUS_LABELS: Record<string, string> = {
  pending: "Pendente",
  running: "Em curso",
  completed: "Concluído",
  failed: "Falhou",
  paused: "Pausado",
  cancelled: "Cancelado",
  unknown: "Desconhecido",
};

function WorkflowCard({ workflow }: { workflow: Workflow }) {
  const stepConfig = (s: WorkflowStep) => STATUS_CONFIG[s.status] ?? STATUS_CONFIG.unknown;
  const steps = Array.isArray(workflow.steps)
    ? workflow.steps.filter((step): step is WorkflowStep => (
      typeof step === "object" && step !== null && typeof step.id === "string"
    ))
    : [];
  const progress = typeof workflow.progress === "number" && Number.isFinite(workflow.progress)
    ? Math.min(100, Math.max(0, workflow.progress))
    : undefined;
  const runningStep = steps.find((step) => step.status === "running");
  const workflowName = typeof workflow.name === "string" && workflow.name.trim()
    ? workflow.name.trim()
    : "Fluxo sem nome";

  return (
    <div className="border-b border-slate-800/60 p-3 last:border-0 sm:p-4">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex min-w-0 items-center gap-2">
          <GitBranch size={13} className="text-violet-400" />
          <span className="truncate text-[12px] font-bold text-slate-200">{workflowName}</span>
          <span className={`text-[9px] px-1.5 py-0.5 rounded font-semibold border ${
            workflow.status === "running" ? "bg-violet-500/15 border-violet-500/40 text-violet-300" :
            workflow.status === "completed" ? "bg-emerald-500/15 border-emerald-500/40 text-emerald-300" :
            workflow.status === "failed" ? "bg-red-500/15 border-red-500/40 text-red-300" :
            "bg-slate-700/50 border-slate-600/60 text-slate-400"
          }`}>
            {WORKFLOW_STATUS_LABELS[workflow.status] ?? WORKFLOW_STATUS_LABELS.unknown}
          </span>
        </div>
        <div className="flex items-center gap-3 text-[10px] text-slate-500">
          {typeof workflow.totalCost === "number" && Number.isFinite(workflow.totalCost) && (
            <span>${workflow.totalCost.toFixed(4)}</span>
          )}
          {typeof workflow.totalTokens === "number" && Number.isFinite(workflow.totalTokens) && (
            <span>{(workflow.totalTokens / 1000).toFixed(1)}K tok</span>
          )}
          {progress !== undefined && (
            <span>{progress.toFixed(0)}%</span>
          )}
        </div>
      </div>

      {/* Progress bar */}
      {progress !== undefined && (
        <div
          className="mb-3 h-1.5 overflow-hidden rounded-full bg-slate-800"
          role="progressbar"
          aria-label="Progresso do fluxo"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={progress}
        >
          <motion.div
            className="h-full rounded-full bg-gradient-to-r from-violet-600 to-cyan-500"
            animate={{ width: `${progress}%` }}
            transition={{ duration: 0.8 }}
          />
        </div>
      )}

      {/* Timeline steps */}
      <div className="relative">
        <div className="flex items-center gap-1 overflow-x-auto pb-1">
          {steps.length > 0 ? steps.map((step, idx) => {
            const cfg = stepConfig(step);
            const Icon = cfg.icon;
            const isLast = idx === steps.length - 1;

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
                    {step.agentId || step.name || `Etapa ${idx + 1}`}
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
                      steps[idx + 1]?.status === "done" ? "bg-emerald-500" :
                      steps[idx + 1]?.status === "running" ? "bg-violet-500" :
                      "bg-slate-700"
                    }`} />
                  </div>
                )}
              </React.Fragment>
            );
          }) : (
            <p className="w-full py-3 text-center text-[10px] text-slate-500">Este fluxo ainda não tem etapas.</p>
          )}
        </div>
      </div>

      {/* Duration */}
      {runningStep && (
        <div className="mt-2 flex items-center gap-2 text-[10px] text-slate-500">
          <Clock size={10} />
          {(() => {
            const running = steps.find(s => s.status === "running");
            if (running?.startedAt) {
              const elapsed = Math.floor((Date.now() - running.startedAt) / 1000);
              const m = Math.floor(elapsed / 60); const s = elapsed % 60;
              return <span>Em curso há {m > 0 ? `${m}m ` : ""}${s}s</span>;
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
  const loading = useTaskStore((s) => s.workflowsLoading);
  const error = useTaskStore((s) => s.workflowsError);
  const workflowList = Object.values(workflows ?? {}).filter((workflow): workflow is Workflow => (
    typeof workflow === "object" && workflow !== null &&
    typeof workflow.id === "string" && typeof workflow.status === "string"
  ));

  return (
    <div className="flex h-full min-h-0 flex-col">
      {/* Header */}
      <div className="px-4 py-3 border-b border-slate-800/60 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <GitBranch size={13} className="text-emerald-400" />
          <span className="text-[11px] uppercase tracking-widest font-bold text-slate-400">Fluxos</span>
        </div>
        <span className="text-[10px] text-slate-500">{workflowList.length > 0 ? `${workflowList.length} ${workflowList.length === 1 ? "fluxo" : "fluxos"}` : ""}</span>
      </div>

      {/* Workflows */}
      <div className="flex-1 overflow-y-auto">
        {error && (
          <p role="status" className="border-b border-rose-500/20 px-4 py-2 text-[10px] text-rose-300">
            {workflowList.length > 0
              ? "Não foi possível atualizar os fluxos. A mostrar a última versão recebida."
              : "Não foi possível obter os fluxos agora."}
          </p>
        )}
        {workflowList.length === 0 ? (
          <div className="flex h-40 flex-col items-center justify-center gap-2 text-slate-500">
            {loading ? <Loader2 size={18} className="animate-spin" aria-label="A carregar fluxos" /> : <GitBranch size={24} className="opacity-25" />}
            <p className="text-xs">{loading ? "A carregar fluxos…" : error ? "Lista de fluxos indisponível" : "Ainda não há fluxos registados"}</p>
          </div>
        ) : (
          workflowList.map(wf => <WorkflowCard key={wf.id} workflow={wf} />)
        )}
      </div>
    </div>
  );
}
