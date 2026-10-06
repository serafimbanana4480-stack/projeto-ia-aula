"use client";

import { CheckCircle2, Circle, ListChecks, Loader2, Play, ShieldCheck, XCircle } from "lucide-react";
import type { PlanCreateResult, PlanStatus } from "../../lib/api";

const STATUS_LABELS: Record<string, string> = {
  pending: "Por executar", planning: "A planear", planning_blocked: "Planeamento bloqueado",
  awaiting_approval: "Aguarda aprovação", approved: "Aprovado", executing: "Em execução",
  running: "Em curso", completed: "Concluído", failed: "Falhou", cancelled: "Cancelado",
  skipped: "Ignorado", blocked: "Bloqueado", ready: "Pronto para executar",
};

interface Props {
  plan: PlanCreateResult;
  status: PlanStatus | null;
  executing: boolean;
  error: string | null;
  onContinue: () => void;
  onApprove: () => void;
  onExecute: () => void;
  onCancel: () => void;
}

export default function PlanExecutionPanel({ plan, status, executing, error, onContinue, onApprove, onExecute, onCancel }: Props) {
  const steps = plan.steps ?? [];
  const states = new Map(status?.steps?.map((step) => [step.task_id, step]));
  const completed = steps.filter((step) => states.get(step.task_id)?.status === "completed").length;
  const progress = steps.length ? Math.round((completed / steps.length) * 100) : 0;
  const state = status?.status ?? "planning";
  const canExecute = status?.approved && ["approved", "ready", "awaiting_approval"].includes(state) && !executing;
  const tone = state === "completed" ? "text-emerald-400 bg-emerald-400/10"
    : ["failed", "planning_blocked", "blocked"].includes(state) ? "text-rose-400 bg-rose-400/10"
    : state === "awaiting_approval" ? "text-amber-300 bg-amber-300/10" : "text-nexus-accent-bright bg-nexus-accent/10";
  const names = new Map(steps.map((step, index) => [step.task_id, `Passo ${index + 1}: ${step.name}`]));

  return <section aria-label="Plano de execução" className="nx-plan-panel mb-4 overflow-hidden rounded-2xl border border-nexus-accent/25 bg-nexus-panel/80">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-nexus-border/60 px-4 py-3">
      <div className="flex min-w-0 items-center gap-2.5">
        <ListChecks className="h-4 w-4 shrink-0 text-nexus-accent-bright" />
        <h2 className="text-sm font-semibold text-nexus-text">Plano de execução</h2>
        <span title={state} className={`rounded-full px-2 py-1 text-[10px] font-medium ${tone}`}>{STATUS_LABELS[state] ?? state.replaceAll("_", " ")}</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {state === "planning_blocked" && !executing && <button type="button" onClick={onContinue} className="rounded-lg border border-amber-400/25 bg-amber-400/10 px-3 py-2 text-xs font-medium text-amber-300 focus-visible:ring-2 focus-visible:ring-nexus-accent">Continuar com plano seguro</button>}
        {state === "awaiting_approval" && !status?.approved && !executing && <button type="button" onClick={onApprove} className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent px-3 py-2 text-xs font-semibold text-white hover:bg-nexus-accent-deep focus-visible:ring-2 focus-visible:ring-nexus-accent"><ShieldCheck className="h-3.5 w-3.5" />Aprovar plano</button>}
        {canExecute && <button type="button" onClick={onExecute} className="inline-flex items-center gap-1.5 rounded-lg bg-nexus-accent/15 px-3 py-2 text-xs font-semibold text-nexus-accent-bright focus-visible:ring-2 focus-visible:ring-nexus-accent"><Play className="h-3.5 w-3.5" />Executar plano</button>}
        {executing && <button type="button" onClick={onCancel} className="inline-flex items-center gap-1.5 rounded-lg border border-rose-400/25 bg-rose-400/10 px-3 py-2 text-xs font-medium text-rose-300 focus-visible:ring-2 focus-visible:ring-nexus-accent"><XCircle className="h-3.5 w-3.5" />Cancelar</button>}
      </div>
    </div>
    <div className="px-4 py-3">
      <p className="break-words text-sm font-medium text-nexus-text">{plan.title}</p>
      {plan.description && <p className="mt-1 text-xs leading-relaxed text-nexus-muted">{plan.description}</p>}
      <div className="mt-3 flex items-center gap-3 text-[11px] text-nexus-muted"><span>{completed} de {steps.length} passos concluídos</span><span className="ml-auto font-mono">{progress}%</span></div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-nexus-bg" role="progressbar" aria-label="Progresso do plano" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}><div className="h-full rounded-full bg-nexus-accent transition-[width]" style={{width: `${progress}%`}} /></div>
      {error && <p role="alert" className="mt-3 rounded-lg border border-rose-400/20 bg-rose-400/5 p-3 text-xs leading-relaxed text-rose-300">{error}</p>}
      <ol className="mt-3 space-y-2">
        {steps.map((step, index) => {
          const live = states.get(step.task_id);
          const stepState = live?.status ?? step.status ?? "pending";
          return <li key={step.task_id} className="flex min-w-0 items-start gap-2.5 rounded-xl border border-nexus-border/60 bg-nexus-bg/25 p-3">
            {stepState === "completed" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
              : ["running", "executing"].includes(stepState) ? <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-nexus-accent-bright" />
              : ["failed", "cancelled", "blocked"].includes(stepState) ? <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-rose-400" />
              : <Circle className="mt-0.5 h-4 w-4 shrink-0 text-nexus-faint" />}
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1"><h3 className="break-words text-xs font-medium text-nexus-text">Passo {index + 1}: {step.name}</h3><span className="rounded-md bg-nexus-border/40 px-1.5 py-0.5 text-[10px] text-nexus-muted">{step.agent}</span><span className="ml-auto text-[10px] text-nexus-faint">{STATUS_LABELS[stepState] ?? stepState}</span></div>
              {step.description && <p className="mt-1 break-words text-[11px] leading-relaxed text-nexus-muted">{step.description}</p>}
              {!!step.depends_on?.length && <p className="mt-1.5 break-words text-[10px] leading-relaxed text-nexus-faint">Depende de: {step.depends_on.map((id) => names.get(id) ?? id).join(" · ")}</p>}
              {live?.error_message && <p className="mt-2 break-words text-[11px] text-rose-300">{live.error_message}</p>}
            </div>
          </li>;
        })}
      </ol>
      {state === "awaiting_approval" && <p className="mt-3 text-[11px] leading-relaxed text-nexus-faint">Revê os passos antes de aprovar. A execução começa depois da tua confirmação.</p>}
    </div>
  </section>;
}
