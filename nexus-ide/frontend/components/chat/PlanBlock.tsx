"use client";

import { useId, useState } from "react";
import { CheckCircle2, CircleDashed, Loader2, ListTodo, XCircle, ChevronDown } from "lucide-react";

import { AGENT_DECLARED_TODO_CAVEAT } from "../../lib/foldRun";
import type { ActivityItem, StepStatus } from "../../lib/types";

/**
 * Living execution plan.
 *
 * The plan is not a static checklist: it is the run's own declaration of what
 * it intends to do, folded from the `plan` activities the runtime emits. The
 * current step is highlighted, counts are real ("3 de 8"), and the caveat is
 * the same sentence the rest of the UI uses — these states are what the agent
 * SAID, not an independent verification.
 */

interface PlanTodo {
  id: string;
  label: string;
  status: StepStatus | "unknown";
}

function planTodoStatus(value: unknown): PlanTodo["status"] {
  const status = String(value ?? "").toLowerCase();
  if (["pending", "queued", "todo"].includes(status)) return "pending";
  if (["done", "complete", "completed", "success"].includes(status)) return "success";
  if (["running", "in_progress", "in-progress"].includes(status)) return "running";
  if (["failed", "error"].includes(status)) return "error";
  if (["warning", "blocked"].includes(status)) return "warning";
  if (["cancelled", "canceled"].includes(status)) return "cancelled";
  if (["paused", "waiting_approval"].includes(status)) return "paused";
  return "unknown";
}

function planPill(status: PlanTodo["status"]): { text: string; className: string } | null {
  switch (status) {
    case "success":
      return { text: "concluída", className: "bg-emerald-400/12 text-nexus-accent2" };
    case "running":
      return { text: "em curso", className: "bg-nexus-accent/15 text-nexus-accent-bright" };
    case "error":
      return { text: "erro", className: "bg-rose-400/12 text-nexus-accent4" };
    case "pending":
      return { text: "por fazer", className: "bg-nexus-bg text-nexus-muted" };
    case "warning":
      return { text: "aviso", className: "bg-amber-400/12 text-nexus-accent3" };
    default:
      return null;
  }
}

function PlanStatusPill({ status }: { status: PlanTodo["status"] }) {
  const pill = planPill(status);
  if (!pill) return null;
  return (
    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium ${pill.className}`}>
      {pill.text}
    </span>
  );
}

function TodoStatusIcon({ status }: { status: PlanTodo["status"] }) {
  switch (status) {
    case "success":
      return <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-nexus-accent2" aria-hidden="true" />;
    case "running":
      return <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-nexus-accent-bright" aria-hidden="true" />;
    case "error":
      return <XCircle className="h-3.5 w-3.5 shrink-0 text-nexus-accent4" aria-hidden="true" />;
    case "cancelled":
      return <CircleDashed className="h-3.5 w-3.5 shrink-0 text-nexus-faint" aria-hidden="true" />;
    case "unknown":
      return <CircleDashed className="h-3.5 w-3.5 shrink-0 text-nexus-muted" aria-hidden="true" />;
    default:
      return <span className="mt-[5px] h-[7px] w-[7px] shrink-0 rounded-full border border-nexus-muted" aria-hidden="true" />;
  }
}

/** The latest plan activity, which is the one whose states are current. */
export function latestPlanActivity(activities: ActivityItem[]): ActivityItem | undefined {
  return [...activities]
    .reverse()
    .find((activity) => activity.kind === "plan" && Array.isArray(activity.data?.todos));
}

export default function PlanBlock({
  activities,
}: {
  activities: ActivityItem[];
}) {
  const bodyId = `plan-block-${useId().replace(/:/g, "")}`;
  const latestPlan = latestPlanActivity(activities);
  const [open, setOpen] = useState(false);

  const todos: PlanTodo[] = !latestPlan
    ? []
    : ((latestPlan.data?.todos as unknown[]) ?? [])
        .filter((todo): todo is Record<string, unknown> => Boolean(todo && typeof todo === "object"))
        .map((todo, index): PlanTodo => ({
          id: String(todo.id ?? `plan-step-${index}`),
          label: String(todo.content ?? todo.title ?? todo.name ?? todo.task ?? "").trim(),
          status: planTodoStatus(todo.status),
        }))
        .filter((todo) => todo.label);
  if (todos.length === 0) return null;

  const completed = todos.filter((todo) => todo.status === "success").length;
  const failed = todos.filter((todo) => todo.status === "error").length;
  const current = todos.find((todo) => todo.status === "running");
  const next = todos.find((todo) => todo.status === "pending");
  const knownStates = todos.filter((todo) => todo.status !== "unknown").length;
  const summary = knownStates === todos.length
    ? `${completed} de ${todos.length} concluídas`
    : `${todos.length} etapas no plano`;
  const focused = current ?? next;
  const announcedState = current
    ? `A IA está a trabalhar em: ${current.label}.`
    : next
      ? `Próxima etapa: ${next.label}.`
      : completed === todos.length
        ? "Todas as etapas do plano estão concluídas."
        : "O plano foi atualizado.";

  return (
    <section
      aria-label="Plano da IA"
      data-testid="plan-block"
      className="nx-work-surface rounded-xl border border-nexus-border/45 px-2.5 py-2"
    >
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
        aria-controls={open ? bodyId : undefined}
        aria-label={`Plano da IA, ${summary}${focused ? `, ${focused.label}` : ""}`}
        className="flex w-full min-w-0 items-center gap-2 rounded-md text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
        data-testid="plan-toggle"
      >
        <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-lg bg-nexus-accent/12 text-nexus-accent-bright">
          <ListTodo className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
        <span className="shrink-0 text-[11px] font-semibold tracking-tight text-nexus-text">Plano da IA</span>
        <span className="nx-nums shrink-0 text-[10px] text-nexus-muted" data-testid="plan-summary">
          {knownStates === todos.length ? `${completed}/${todos.length}` : `${todos.length} etapas`}
        </span>
        {focused && (
          <span className="min-w-0 flex-1 truncate text-[11px] text-nexus-muted" data-testid="plan-current-step">
            <span className="mr-1.5 text-nexus-faint">·</span>{focused.label}
          </span>
        )}
        {!focused && <span className="min-w-0 flex-1" />}
        <span className="rounded-md p-0.5 text-nexus-faint" aria-hidden="true">
          <ChevronDown className={`h-3.5 w-3.5 transition-transform duration-[180ms] ${open ? "" : "-rotate-90"}`} />
        </span>
      </button>
      <span role="status" aria-live="polite" className="sr-only">{announcedState}</span>

      {open && (
        <div id={bodyId} className="mt-2 border-t border-nexus-border/30 pt-1.5">
          {knownStates === todos.length && todos.length > 0 && (
            <div className="mb-1.5 h-1 overflow-hidden rounded-full bg-nexus-bg" aria-hidden="true">
              <div
                className="h-full rounded-full bg-nexus-accent2 transition-[width] duration-200"
                style={{ width: `${Math.round((completed / todos.length) * 100)}%` }}
              />
            </div>
          )}
          <ol className="space-y-0.5">
            {todos.map((todo) => (
              <li
                key={todo.id}
                data-testid="plan-step"
                data-status={todo.status}
                className={`flex items-start gap-2 rounded-lg px-1.5 py-1 text-[11.5px] leading-relaxed ${
                  todo.status === "running" ? "bg-nexus-accent/10 text-nexus-text" : "text-nexus-text/85"
                }`}
              >
                <span className="mt-[3px]">
                  <TodoStatusIcon status={todo.status} />
                </span>
                <span className={todo.status === "success" ? "min-w-0 flex-1 text-nexus-muted" : "min-w-0 flex-1"}>
                  {todo.label}
                  {todo.status === "unknown" ? <span className="sr-only"> — estado não informado</span> : null}
                </span>
                <PlanStatusPill status={todo.status} />
              </li>
            ))}
          </ol>
          <div className="mt-1 flex items-center justify-between gap-2 px-1.5 text-[10px]">
            {focused ? <span className="min-w-0 truncate text-nexus-faint">{current ? "A fazer agora:" : "A seguir:"} {focused.label}</span> : <span />}
            {failed > 0 && <span className="shrink-0 text-nexus-accent4">{failed} com erro</span>}
          </div>
          <p role="note" className="mt-1 px-1.5 text-[10px] leading-relaxed text-nexus-muted">
            {AGENT_DECLARED_TODO_CAVEAT}
          </p>
        </div>
      )}
    </section>
  );
}
