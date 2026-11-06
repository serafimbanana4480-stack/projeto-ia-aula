"use client";

import { memo } from "react";
import { Bot, ChevronDown } from "lucide-react";
import { runStepKey } from "../../lib/chatPresentation";

import type { RunStep, StepStatus } from "../../lib/types";
import { workerOf, type ActivityGroup } from "../../lib/activityGroups";
import { formatRunClock } from "../../lib/chatPresentation";
import { narrateStep } from "../../lib/plainNarration";
import { compactActivityLine, verificationWasSkipped } from "../../lib/activityLine";
import { usePresentationStore } from "../../stores/presentationStore";

/**
 * Timeline rows — the three shapes the activity fold can produce.
 *
 * - `StepRow`: one faithful runtime step (ferramenta · alvo · estado · tempo).
 * - `ActivityGroupRow`: the synthesis row — "Explorou 24 ficheiros · 18s" —
 *   collapsed by default so a 40-step exploration reads as one line.
 * - `TaskGroupRow`: the runtime's own grouping by `task_id` (delegated work).
 *
 * All three render the SAME `StepRow` inside, so an expanded group is
 * indistinguishable from the ungrouped faithful timeline: grouping hides, it
 * never rewrites.
 */

export function StepStatusIcon({ status, className = "h-3 w-3" }: { status: StepStatus; className?: string }) {
  switch (status) {
    case "success":
      return (
        <svg viewBox="0 0 16 16" className={`${className} shrink-0 text-nexus-accent2`} aria-hidden="true">
          <path
            d="M3.5 8.5l3 3 6-7"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.8"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      );
    case "error":
      return (
        <svg viewBox="0 0 16 16" className={`${className} shrink-0 text-nexus-accent4`} aria-hidden="true">
          <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      );
    case "running":
      return (
        <svg viewBox="0 0 16 16" className={`${className} shrink-0 animate-spin text-nexus-accent`} aria-hidden="true">
          <path d="M8 1.5a6.5 6.5 0 1 0 6.5 6.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      );
    case "awaiting_confirmation":
      return (
        <svg viewBox="0 0 16 16" className={`${className} shrink-0 text-nexus-accent3`} aria-hidden="true">
          <path d="M8 1.8l6 11.4H2L8 1.8z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
          <path d="M8 6v3.2M8 11.2v.1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "warning":
      return (
        <svg viewBox="0 0 16 16" className={`${className} shrink-0 text-nexus-accent3`} aria-hidden="true">
          <path d="M8 1.8l6 11.4H2L8 1.8z" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
          <path d="M8 6v3.2M8 11.2v.1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "paused":
      return (
        <svg viewBox="0 0 16 16" className={`${className} shrink-0 text-nexus-accent3`} aria-hidden="true">
          <path d="M5.5 3.5v9M10.5 3.5v9" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        </svg>
      );
    case "cancelled":
      return <span className={`${className} shrink-0 rounded-full border border-nexus-muted`} aria-hidden="true" />;
    default:
      return <span className={`${className} shrink-0 rounded-full border border-nexus-faint/60`} aria-hidden="true" />;
  }
}

function formatStepDuration(ms?: number): string {
  if (typeof ms !== "number" || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = Math.floor(ms / 1000);
  const rest = Math.round(ms - s * 1000);
  return `${s}s ${rest}ms`;
}

/** One faithful step. Never grouped away: this is the evidence row. */
export const StepRow = memo(function StepRow({ step, t0 }: { step: RunStep; t0?: number }) {
  const level = usePresentationStore((state) => state.level);
  const primaryTarget = step.target === "NEXUS" || step.target === "ORCHESTRATOR";
  const showTarget = Boolean(step.target) && step.verb !== "agent" && (level === "technical" || !primaryTarget);
  const detail = step.detail;
  const detailVisibility =
    detail && typeof detail === "object"
      ? (detail as { visibility?: unknown }).visibility
      : undefined;
  const publishedReasoning =
    step.verb === "thinking" &&
    (detailVisibility === "full" ||
      detailVisibility === "label" ||
      step.event?.data?.visibility === "full" ||
      step.event?.data?.visibility === "label");
  const narration = narrateStep(step);
  const sentence = verificationWasSkipped(step)
    ? "Verificação não executada"
    : step.verb === "thinking" && !publishedReasoning ? "A analisar a tarefa…" : narration.sentence;
  const cue = step.verb === "thinking" ? null : compactActivityLine(step);
  const label = cue ?? sentence;
  const clock = level === "technical" && t0 !== undefined && typeof step.startedAt === "number"
    ? formatRunClock(step.startedAt - t0)
    : null;
  const quiet = step.status === "success" || step.status === "pending";
  return (
    <div
      data-testid="run-step"
      className="flex w-full items-center gap-2 py-0.5 pl-4"
      title={showTarget ? `${label} · ${step.target}` : label}
    >
      {clock && (
        <time dateTime={new Date(step.startedAt!).toISOString()} className="w-8 shrink-0 font-mono text-[9px] tabular-nums text-nexus-faint">
          {clock}
        </time>
      )}
      <span className="min-w-0 flex-1 truncate text-[13px] text-nexus-muted">{label}</span>
      {cue && cue !== sentence ? <span className="sr-only">{sentence}</span> : null}
      {narration.technical && narration.raw && narration.raw !== label && !(step.verb === "thinking" && !publishedReasoning) && level === "technical" ? (
        <span className="truncate font-mono text-[9px] text-nexus-faint">{narration.raw}</span>
      ) : null}
      {showTarget && level === "technical" ? <span className="truncate font-mono text-[10px] text-nexus-faint">{step.target}</span> : null}
      {quiet ? null : <StepStatusIcon status={step.status} />}
      {level === "technical" && step.durationMs !== undefined && step.status !== "running" && (
        <span className="shrink-0 font-mono text-[9px] tabular-nums text-nexus-faint">
          {formatStepDuration(step.durationMs)}
        </span>
      )}
    </div>
  );
});

/** Clock origin for the vertical timeline: first step with a wall clock. */
export function timelineOrigin(steps: RunStep[]): number | undefined {
  const stamps = steps
    .map((step) => step.startedAt)
    .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  return stamps.length > 0 ? Math.min(...stamps) : undefined;
}

export function ActivityGroupRow({ group }: { group: ActivityGroup }) {
  const shownTargets = group.targets.slice(0, 3);
  return (
    <details data-testid="run-activity-group" data-family={group.family} className="group/g py-0.5">
      <summary
        className="flex cursor-pointer list-none items-center gap-1.5 rounded-md py-0.5 text-[13px] text-nexus-muted transition-colors duration-100 hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
        title={`${group.label}${shownTargets.length > 0 ? ` · ${group.targets.join(", ")}` : ""}`}
      >
        <ChevronDown className="h-3 w-3 shrink-0 -rotate-90 text-nexus-faint transition-transform duration-150 group-open/g:rotate-0" />
        <span className="min-w-0 flex-1 truncate">{group.label}</span>
        {group.errors > 0 ? (
          <span className="shrink-0 text-[11px] text-nexus-accent4">
            {group.errors} erro{group.errors === 1 ? "" : "s"}
          </span>
        ) : null}
      </summary>
      <div className="ml-[22px] border-l border-nexus-border/30 pl-2.5">
        {group.steps.map((step, stepIndex) => (
          <StepRow key={runStepKey(step, stepIndex)} step={step} t0={undefined} />
        ))}
      </div>
    </details>
  );
}

const FILLER_PREVIEW = /^(a avançar|a processar|a raciocinar|a analisar a tarefa…|atualização de execução)$/i;

/** The latest thing this subagent actually did: a tool, a file, or its approach. */
export function subagentPreview(steps: RunStep[]): string {
  for (let index = steps.length - 1; index >= 0; index -= 1) {
    const step = steps[index];
    if (step.verb === "agent" && /começou|concluiu/i.test(step.label)) continue;
    const line = (step.verb === "thinking" ? null : compactActivityLine(step)) ?? narrateStep(step).sentence;
    const clean = line.trim();
    if (!clean || FILLER_PREVIEW.test(clean)) continue;
    return clean;
  }
  return "";
}

/** One delegated task, opened on its own: the worker, what it is doing, then its steps. */
export function TaskGroupRow({
  taskId,
  steps,
  t0,
}: {
  taskId: string;
  steps: RunStep[];
  t0?: number;
}) {
  const worker = steps.map(workerOf).find(Boolean) || steps.find((step) => step.agent)?.agent || "Tarefa";
  const preview = subagentPreview(steps);
  return (
    <details
      data-testid="run-step-group"
      data-agent={worker}
      className="group/task my-0.5 rounded-lg px-1.5"
      title={`Subagente ${worker}`}
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-md py-1 text-[13px] text-nexus-muted transition-colors duration-100 hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent">
        <ChevronDown className="h-3 w-3 shrink-0 -rotate-90 text-nexus-faint transition-transform duration-150 group-open/task:rotate-0" />
        <Bot className="h-3 w-3 shrink-0 text-nexus-accent" />
        <span className="shrink-0 font-medium text-nexus-text">{worker}</span>
        {preview ? <span className="min-w-0 flex-1 truncate text-nexus-muted">{preview}</span> : <span className="sr-only">{taskId}</span>}
        <StepStatusIcon status={summaryStatus(steps)} />
      </summary>
      <div className="ml-[22px] border-l border-nexus-border/30 pl-2.5">
        {steps.map((step, stepIndex) => (
          <StepRow key={runStepKey(step, stepIndex)} step={step} t0={t0} />
        ))}
      </div>
    </details>
  );
}

function summaryStatus(steps: RunStep[]): StepStatus {
  if (steps.some((step) => step.status === "error")) return "error";
  if (steps.some((step) => step.status === "awaiting_confirmation")) return "awaiting_confirmation";
  if (steps.some((step) => step.status === "running")) return "running";
  if (steps.every((step) => step.status === "success")) return "success";
  return "pending";
}
