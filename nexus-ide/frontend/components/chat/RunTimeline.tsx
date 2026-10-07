"use client";

import { useEffect, useId, useMemo, useState, memo, type ComponentType } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  Wrench,
  FileText,
  Terminal,
  Bot,
  Activity,
  MessageSquare,
  Loader2,
  CircleDashed,
  CheckCircle2,
  XCircle,
  ShieldAlert,
  Pause,
  Clock,
  BarChart3,
  TestTube,
  TriangleAlert,
  ChevronDown,
} from "lucide-react";
import type { ActivityItem, ChatMessage, RunStep, StepStatus } from "../../lib/types";
import { buildExecutionGraph } from "../../lib/executionGraph";
import { formatRunClock, formatRunDuration } from "../../lib/chatPresentation";
import { formatUsd } from "../../lib/format";
import { summarizeRunForHeader, isFailingActivityStatus, AGENT_DECLARED_TODO_CAVEAT } from "../../lib/foldRun";
import { useModelStore } from "../../stores/modelStore";
import ThinkingBlock from "./ThinkingBlock";
import ExecutionActivity from "./ExecutionActivity";
import ToolCallTimeline from "./ToolCallTimeline";
import AgentExecutionGraph from "./AgentExecutionGraph";

export interface RunTimelineProps {
  message: ChatMessage;
  isStreaming?: boolean;
  sessionId?: string;
}

const STEP_ICONS: Record<RunStep["verb"], ComponentType<{ className?: string }>> = {
  thinking: Brain,
  tool: Wrench,
  file: FileText,
  command: Terminal,
  test: TestTube,
  agent: Bot,
  status: Activity,
  message: MessageSquare,
  other: Activity,
};

/**
 * The outcome the run's own evidence supports.
 *
 * `completed` is a CLAIM and is only reachable with positive evidence — a
 * `run_completed` / `mission_completed` frame, or a terminal phase reported by
 * the runtime. `unknown` is the deliberate alternative to green: "nothing
 * reported a problem" is not "the run finished", and a silent backend restart,
 * an unread journal or a dropped stream all look identical from here.
 */
type RunOutcome = "failed" | "interrupted" | "cancelled" | "paused" | "warning" | "completed" | "unknown";

function RunOutcomeDot({ outcome }: { outcome: RunOutcome }) {
  switch (outcome) {
    case "failed":
      return <XCircle className="h-3 w-3 shrink-0 text-rose-400" />;
    case "interrupted":
      return <TriangleAlert className="h-3 w-3 shrink-0 text-amber-300" />;
    case "cancelled":
      return <CircleDashed className="h-3 w-3 shrink-0 text-nexus-muted" />;
    case "paused":
      return <Pause className="h-3 w-3 shrink-0 text-amber-300" />;
    case "warning":
      return <TriangleAlert className="h-3 w-3 shrink-0 text-amber-300" />;
    case "completed":
      return (
        <span aria-hidden="true" className="shrink-0 text-[12px] leading-none text-emerald-400">
          ◉
        </span>
      );
    default:
      // Neutral, not green: no terminal state was ever reported for this run.
      return <StatusDot status="pending" />;
  }
}

function StatusDot({ status }: { status: StepStatus }) {
  switch (status) {
    case "running":
      return <Loader2 className="h-3 w-3 animate-spin text-nexus-accent" />;
    case "success":
      return <CheckCircle2 className="h-3 w-3 text-emerald-400" />;
    case "error":
      return <XCircle className="h-3 w-3 text-rose-400" />;
    case "awaiting_confirmation":
      return <ShieldAlert className="h-3 w-3 text-amber-300" />;
    case "warning":
      return <TriangleAlert className="h-3 w-3 text-amber-300" />;
    case "paused":
      return <Pause className="h-3 w-3 text-amber-300" />;
    case "cancelled":
      return <CircleDashed className="h-3 w-3 text-nexus-muted" />;
    default:
      return <Activity className="h-3 w-3 text-nexus-muted" />;
  }
}

function formatDuration(ms?: number): string {
  if (typeof ms !== "number" || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = Math.floor(ms / 1000);
  const rest = Math.round(ms - s * 1000);
  return `${s}s ${rest}ms`;
}

const PT_MONTHS = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

/**
 * One faint date divider above the header when the run is not from today:
 * “Ontem · 14:02” / “12 mai · 14:02”. Same-day runs show nothing.
 * Plain `Date`, no libs.
 */
function formatDayDivider(timestamp: string | undefined): string | null {
  if (!timestamp) return null;
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return null;
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  if (sameDay) return null;
  const time = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  const isYesterday =
    date.getFullYear() === yesterday.getFullYear() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getDate() === yesterday.getDate();
  if (isYesterday) return `Ontem · ${time}`;
  return `${date.getDate()} ${PT_MONTHS[date.getMonth()]} · ${time}`;
}

function RunStepRow({ step, t0, onStepClick }: { step: RunStep; t0?: number; onStepClick: (step: RunStep) => void }) {
  const Icon = STEP_ICONS[step.verb] || Activity;
  // An agent step's label already names the agent ("CODER começou" /
  // "CODER concluiu"), and `step.target` holds that same name — it is what
  // `closeAgentStep` matches on. Printing it again rendered "CODER · CODER",
  // so the trailing column is only meaningful for the verbs whose label is a
  // generic action ("a usar ferramenta" · "read_file").
  const showTarget = Boolean(step.target) && step.verb !== "agent";
  const clock = t0 !== undefined && typeof step.startedAt === "number"
    ? formatRunClock(step.startedAt - t0)
    : null;
  return (
    <button
      key={`${step.seq}-${step.kind}`}
      type="button"
      data-testid="run-step"
      onClick={() => onStepClick(step)}
      className="flex w-full items-center gap-2 py-1.5 text-left transition-colors duration-150 hover:bg-nexus-card/40"
      title={showTarget ? `${step.label} · ${step.target}` : step.label}
    >
      {clock && (
        <time className="w-8 shrink-0 font-mono text-[9px] tabular-nums text-nexus-muted">
          {clock}
        </time>
      )}
      <span className="relative mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-nexus-card">
        <Icon className="h-3 w-3 text-nexus-muted" />
      </span>
      <span className="flex min-w-0 flex-1 items-center gap-1.5">
        <span className="truncate text-[11px] font-medium text-nexus-text/90">{step.label}</span>
        {showTarget ? (
          <span className="truncate text-[10px] text-nexus-muted">{step.target}</span>
        ) : null}
      </span>
      <StatusDot status={step.status} />
      {step.durationMs !== undefined && step.status !== "running" && (
        <span className="shrink-0 tabular-nums text-[9px] text-nexus-muted">{formatDuration(step.durationMs)}</span>
      )}
    </button>
  );
}

interface RunStepGroup {
  taskId: string | null;
  steps: RunStep[];
}

function groupContiguousTaskSteps(steps: RunStep[]): RunStepGroup[] {
  const groups: RunStepGroup[] = [];
  for (const step of steps) {
    const taskId = step.taskId?.trim() || null;
    const last = groups[groups.length - 1];
    if (taskId && last?.taskId === taskId) last.steps.push(step);
    else groups.push({ taskId, steps: [step] });
  }
  return groups;
}

function taskGroupStatus(steps: RunStep[]): StepStatus {
  if (steps.some((step) => step.status === "error")) return "error";
  if (steps.some((step) => step.status === "awaiting_confirmation")) return "awaiting_confirmation";
  if (steps.some((step) => step.status === "paused")) return "paused";
  if (steps.some((step) => step.status === "running")) return "running";
  if (steps.some((step) => step.status === "warning")) return "warning";
  if (steps.every((step) => step.status === "cancelled")) return "cancelled";
  if (steps.every((step) => step.status === "success")) return "success";
  return "pending";
}

/** Group only adjacent rows that carry the same explicit runtime task id. */
function RunSteps({ steps, onStepClick }: { steps: RunStep[]; onStepClick: (step: RunStep) => void }) {
  const groups = useMemo(
    () => groupContiguousTaskSteps([...steps].sort((a, b) => a.seq - b.seq)),
    [steps],
  );
  // Vertical timeline clock origin: first step with a wall-clock timestamp.
  const t0 = useMemo(() => {
    const stamps = steps
      .map((step) => step.startedAt)
      .filter((value): value is number => typeof value === "number" && Number.isFinite(value));
    return stamps.length > 0 ? Math.min(...stamps) : undefined;
  }, [steps]);

  if (steps.length === 0) return null;

  return (
    <div className="relative ml-1 border-l border-nexus-border/30 pl-3.5 [content-visibility:auto]">
      {groups.map((group, index) => {
        if (!group.taskId || group.steps.length < 2) {
          return group.steps.map((step) => (
            <RunStepRow key={`${step.seq}-${step.kind}`} step={step} t0={t0} onStepClick={onStepClick} />
          ));
        }
        const agent = group.steps.find((step) => step.agent)?.agent;
        return (
          <details
            key={`task-${group.taskId}-${index}`}
            data-testid="run-step-group"
            className="my-1 rounded-md bg-nexus-bg/35 px-2"
            title={`Grupo por task_id ${group.taskId}`}
          >
            <summary className="flex cursor-pointer list-none items-center gap-2 py-1.5 text-[10px] text-nexus-muted transition-colors duration-150 hover:text-nexus-text">
              <Bot className="h-3 w-3 text-nexus-accent" />
              <span className="font-medium text-nexus-text/80">{agent || "Tarefa"}</span>
              <span>{group.steps.length} atualizações da mesma tarefa</span>
              <StatusDot status={taskGroupStatus(group.steps)} />
              <ChevronDown className="ml-auto h-3 w-3 transition-transform duration-150" />
            </summary>
            <div className="border-t border-nexus-border/30 pl-2">
              {group.steps.map((step) => (
                <RunStepRow key={`${step.seq}-${step.kind}`} step={step} t0={t0} onStepClick={onStepClick} />
              ))}
            </div>
          </details>
        );
      })}
    </div>
  );
}

function numOrUndefined(value: unknown): number | undefined {
  const parsed = typeof value === "number" ? value : Number(value);
  return typeof parsed === "number" && Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function formatRunElapsed(milliseconds: number): string {
  if (milliseconds < 60_000) {
    return `${(milliseconds / 1_000).toLocaleString("pt-PT", { maximumFractionDigits: 1 })}s`;
  }
  return formatDuration(milliseconds);
}

function RunFooter({ message }: { message: ChatMessage }) {
  const activeModelId = useModelStore((state) => state.activeModel);
  const models = useModelStore((state) => state.models);
  const footer = message.metadata?.footer as
    | { phase?: string; elapsedMs?: number; telemetry?: Record<string, unknown> }
    | undefined;
  const phase = footer?.phase;
  const elapsed = footer?.elapsedMs;
  const tokens = footer?.telemetry;
  const providerInfo = tokens?.provider && typeof tokens.provider === "object"
    ? tokens.provider as Record<string, unknown>
    : undefined;
  const providerLabel = [providerInfo?.name, providerInfo?.model]
    .filter((value): value is string => typeof value === "string" && value.trim().length > 0)
    .join(" · ");
  const tokenSource = typeof tokens?.source === "string" ? tokens.source : undefined;

  if (!phase && elapsed === undefined && !tokens && !message.metrics && !message.runId) return null;

  const input = message.metrics?.Input ?? tokens?.input_tokens;
  const output = message.metrics?.Output ?? tokens?.output_tokens;
  const total = message.metrics?.Total ?? tokens?.total_tokens;
  // Live cost (Claude Code Chat style): only when the active model reports
  // pricing — never invent a $0. `formatUsd` keeps sub-cent amounts honest.
  const activeModel = models.find((model) => model.id === activeModelId);
  const inputPrice = activeModel?.inputPricePer1M;
  const outputPrice = activeModel?.outputPricePer1M;
  const inputCount = numOrUndefined(input);
  const outputCount = numOrUndefined(output);
  const liveCost =
    inputPrice != null || outputPrice != null
      ? ((inputPrice ?? 0) * (inputCount ?? 0) + (outputPrice ?? 0) * (outputCount ?? 0)) / 1_000_000
      : null;
  // `foldRun` already computes the reasoning tokens; nothing read them, so the
  // panel reported "SAÍDA 0" for a run that spent thousands of tokens thinking.
  const reasoning = message.metrics?.["Raciocínio"] ?? tokens?.reasoning_tokens;
  const tokenCount =
    typeof total === "number"
      ? total
      : typeof total === "string"
        ? Number(total)
        : undefined;
  const reasoningCount =
    typeof reasoning === "number"
      ? reasoning
      : typeof reasoning === "string"
        ? Number(reasoning)
        : undefined;
  const reasoningSource = typeof tokens?.reasoning_source === "string"
    ? tokens.reasoning_source
    : undefined;
  const showReasoning =
    reasoningCount !== undefined &&
    !Number.isNaN(reasoningCount) &&
    reasoningSource !== "not_measured" &&
    (reasoningSource === "provider" || reasoningSource === "estimated" || reasoningCount > 0);

  return (
    <div data-testid="run-observability" className="flex flex-wrap items-center gap-2.5 border-t border-nexus-border/30 px-1 py-2 text-[10px] text-nexus-muted">
      {message.runId && (
        <code
          data-testid="run-id"
          title={`ID da execução: ${message.runId}`}
          className="max-w-48 truncate rounded bg-nexus-bg/70 px-2 py-0.5 font-mono"
        >
          run {message.runId}
        </code>
      )}
      {providerLabel && (
        <span data-testid="run-provider" className="rounded bg-nexus-bg/70 px-2 py-0.5">
          {providerLabel}
        </span>
      )}
      {providerInfo?.simulation === true && (
        <span className="rounded bg-amber-400/10 px-2 py-0.5 text-amber-200/90">
          simulação
        </span>
      )}
      {phase && (
        <span className="inline-flex items-center gap-1 rounded bg-violet-400/10 px-2 py-0.5 text-nexus-text/80">
          <Activity className="h-3 w-3 text-violet-300" />
          <span>fase:</span>
          <span>{phase}</span>
        </span>
      )}
      {typeof elapsed === "number" && (
        <span className="inline-flex items-center gap-1 rounded bg-nexus-bg/70 px-2 py-0.5">
          <Clock className="h-3 w-3 text-nexus-muted" />
          {formatRunElapsed(elapsed)}
        </span>
      )}
      {tokenCount !== undefined && !Number.isNaN(tokenCount) && (
        <span className="inline-flex items-center gap-1 rounded bg-nexus-bg/70 px-2 py-0.5">
          <BarChart3 className="h-3 w-3 text-nexus-muted" />
          {Math.round(tokenCount)} tokens
        </span>
      )}
      {(input !== undefined || output !== undefined || tokenCount !== undefined) && (
        <span data-testid="token-source" className="rounded bg-nexus-bg/70 px-2 py-0.5">
          {tokenSource === "provider"
            ? "Medido pelo provider"
            : tokenSource === "estimated"
              ? "Estimativa NEXUS"
              : "Origem não informada"}
        </span>
      )}
      {showReasoning && (
        <span
          className="inline-flex items-center gap-1 rounded bg-sky-400/10 px-2 py-0.5 text-sky-200/80"
          title={reasoningSource === "estimated"
            ? "Estimativa de tokens gastos pelo modelo a raciocinar"
            : "Tokens de raciocínio reportados pelo provider"}
        >
          <Brain className="h-3 w-3 text-sky-300" />
          {Math.round(reasoningCount!)} em raciocínio
          {reasoningSource === "estimated" ? " · estimado" : ""}
        </span>
      )}
      {input !== undefined && output !== undefined && (
        <span className="hidden items-center gap-1 rounded bg-nexus-bg/70 px-2 py-0.5 sm:inline-flex">
          ↑{String(input)} ↓{String(output)}
        </span>
      )}
      {liveCost != null && (
        <span
          data-testid="run-cost"
          title="Custo estimado a partir do preço do modelo ativo"
          className="rounded bg-nexus-bg/70 px-2 py-0.5 tabular-nums"
        >
          ~{formatUsd(liveCost)}
        </span>
      )}
    </div>
  );
}

interface RunSummary {
  steps: number;
  tools: number;
  files: number;
  thinking: boolean;
  commands: number;
  errors: number;
  warnings: number;
  cancelled: number;
  paused: number;
}

function summarize(steps: RunStep[]): RunSummary {
  const counts: RunSummary = {
    steps: steps.length,
    tools: 0,
    files: 0,
    thinking: false,
    commands: 0,
    errors: 0,
    warnings: 0,
    cancelled: 0,
    paused: 0,
  };
  for (const step of steps) {
    if (step.verb === "tool") counts.tools += 1;
    else if (step.verb === "file") counts.files += 1;
    else if (step.verb === "command") counts.commands += 1;
    else if (step.verb === "thinking") counts.thinking = true;
    if (step.status === "error") counts.errors += 1;
    if (step.status === "warning") counts.warnings += 1;
    if (step.status === "cancelled") counts.cancelled += 1;
    if (step.status === "paused" || step.status === "awaiting_confirmation") counts.paused += 1;
  }
  return counts;
}

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

function ExecutionPlan({ activities }: { activities: ActivityItem[] }) {
  const latestPlan = [...activities].reverse().find(
    (activity) => activity.kind === "plan" && Array.isArray(activity.data?.todos),
  );
  if (!latestPlan) return null;

  const todos = (latestPlan.data?.todos as unknown[])
    .filter((todo): todo is Record<string, unknown> => Boolean(todo && typeof todo === "object"))
    .map((todo, index): PlanTodo => ({
      id: String(todo.id ?? `plan-step-${index}`),
      label: String(todo.content ?? todo.title ?? todo.name ?? todo.task ?? "").trim(),
      status: planTodoStatus(todo.status),
    }))
    .filter((todo) => todo.label);
  if (todos.length === 0) return null;

  const completed = todos.filter((todo) => todo.status === "success").length;
  const knownStates = todos.filter((todo) => todo.status !== "unknown").length;
  const summary = knownStates === todos.length
    ? `${completed} de ${todos.length} concluídas`
    : `${todos.length} etapas no plano`;
  const renderTodo = (todo: PlanTodo) => (
    <li key={todo.id} className="flex items-start gap-2 py-1 text-[11px]">
      <span className="mt-0.5 shrink-0">
        {todo.status === "unknown" ? (
          <CircleDashed className="h-3 w-3 text-nexus-muted" aria-hidden="true" />
        ) : (
          <StatusDot status={todo.status} />
        )}
      </span>
      <span className={todo.status === "success" ? "text-nexus-muted line-through" : "text-nexus-text/85"}>
        {todo.label}
        {todo.status === "unknown" && <span className="sr-only"> — estado não informado</span>}
      </span>
    </li>
  );

  return (
    <section className="border-b border-nexus-border/30 px-2.5 py-2" aria-label="Plano de execução">
      <div className="mb-1 flex items-center gap-2 text-[10px]">
        <CheckCircle2 className="h-3 w-3 text-nexus-accent" />
        <span className="font-semibold uppercase tracking-wide text-nexus-muted">Plano</span>
        <span className="ml-auto text-nexus-muted">{summary}</span>
      </div>
      {/* The ticks below are statuses the agent CLAIMED, drawn green — the same
          claim the checklist and session panels already disclaim. One sentence,
          one constant (`AGENT_DECLARED_TODO_CAVEAT`), so the plan cannot quietly
          grow a stronger claim than the rest of the UI is willing to make. */}
      <p role="note" className="mb-1 text-[10px] leading-relaxed text-nexus-muted">
        {AGENT_DECLARED_TODO_CAVEAT}
      </p>
      <ol>{todos.slice(0, 5).map(renderTodo)}</ol>
      {todos.length > 5 && (
        <details className="mt-1 pl-5">
          <summary className="cursor-pointer text-[10px] text-nexus-muted hover:text-nexus-text">
            Ver mais {todos.length - 5} etapas
          </summary>
          <ol className="mt-1">{todos.slice(5).map(renderTodo)}</ol>
        </details>
      )}
    </section>
  );
}

/**
 * Chat-style activity surface for one assistant turn.
 *
 * Collapsed by default it reads as a single living line — what the model is
 * doing right now while streaming, and a quiet "N passos · M ferramentas"
 * recap once done. Expanding reveals the faithful ordered timeline plus the
 * rich detail blocks (thinking, activities, tool calls). The footer keeps the
 * live telemetry visible without any click.
 */
function RunTimelineComponent({ message, isStreaming, sessionId }: RunTimelineProps) {
  const timelineBodyId = `run-timeline-${useId().replace(/:/g, "")}`;
  const hasSteps = Boolean(message.steps?.length);
  const hasThinking = Boolean(message.thinking);
  const hasActivities = Boolean(message.activities?.length);
  const hasTools = Boolean(message.toolCalls?.length);
  const hasMetrics = Boolean(message.metrics);
  const hasFooter = Boolean(message.runId || message.metadata?.footer);

  // A pending confirmation or an error must be impossible to miss: those
  // states expand the detail automatically, everything else stays compact.
  const needsAttention = useMemo(() => {
    const confirmationPending = message.toolCalls?.some(
      (call) => call.status === "awaiting_confirmation",
    );
    const failedSteps = message.steps?.some((step) => step.status === "error");
    const pausedOrCancelled = message.steps?.some(
      (step) => step.status === "paused" || step.status === "cancelled",
    );
    const failedTools = message.toolCalls?.some((call) => call.status === "error");
    return Boolean(confirmationPending || failedSteps || failedTools || pausedOrCancelled);
  }, [message.toolCalls, message.steps]);

  const [expanded, setExpanded] = useState<boolean>(needsAttention);
  const [view, setView] = useState<"timeline" | "graph">("timeline");

  useEffect(() => {
    if (needsAttention) setExpanded(true);
  }, [needsAttention]);

  const orderedSteps = useMemo(
    () => [...(message.steps ?? [])].sort((a, b) => a.seq - b.seq),
    [message.steps],
  );

  const summary = useMemo(() => summarize(message.steps ?? []), [message.steps]);
  const executionGraph = useMemo(
    () => buildExecutionGraph(message.activities ?? []),
    [message.activities],
  );
  // ACTIVITIES are evidence too. `sessionRecovery` injects a `warning`
  // activity — "Execução interrompida" — for a run the backend recorded as
  // interrupted, and counting steps and tool calls only left the header green
  // directly above a panel stating the run was interrupted. Step `warning`s
  // keep their own amber state below; activities have no separate one, so a
  // failing activity is counted as a problem here.
  const activityFailures = (message.activities ?? []).filter((activity) =>
    isFailingActivityStatus(activity.status),
  ).length;
  const errorCount = Math.max(
    summary.errors,
    message.toolCalls?.filter((call) => call.status === "error").length ?? 0,
    activityFailures,
  );
  const hasRunErrors = errorCount > 0;
  const hasRunCancelled = orderedSteps.some((step) => step.kind === "run_cancelled");
  // The backend's `RUN_INTERRUPTED` error frame: neither a failure nor a
  // cancellation (the run died from outside — backend restart, killed process),
  // and `MessageBubble` already labels it "Interrompido". It needs its own
  // header state, otherwise it is indistinguishable from a clean run.
  const hasRunInterrupted = orderedSteps.some((step) => step.kind === "run_interrupted");
  const hasPausedWork = summary.paused > 0 || message.activities?.some((item) => item.status === "paused");

  // Positive evidence that the run reported completion. Anything else is
  // `unknown`, never green.
  const footerPhase = (message.metadata?.footer as { phase?: string } | undefined)?.phase;
  const hasCompletionEvidence =
    footerPhase === "concluída" ||
    orderedSteps.some((step) => step.kind === "run_completed" || step.kind === "mission_completed") ||
    (message.activities ?? []).some(
      (activity) =>
        activity.data?.kind === "run_completed" || activity.data?.runtime_type === "run_completed",
    );

  // Precedence matters for the truth of the label: a run the user stopped did
  // not "fail" even though the tool calls it abandoned are sealed as errors
  // (`closeDanglingWork` has no `cancelled` tool-call state to use).
  const runOutcome: RunOutcome = hasRunInterrupted
    ? "interrupted"
    : hasRunCancelled
      ? "cancelled"
      : hasRunErrors
        ? "failed"
        : hasPausedWork
          ? "paused"
          : summary.warnings > 0
            ? "warning"
            : hasCompletionEvidence
              ? "completed"
              : "unknown";
  // One label per outcome, reused by the fallback line AND the status pill so
  // the two can never describe different runs. Vocabulary is the one already in
  // use here ("execução cancelada" / "execução em pausa") plus the "Interrompido"
  // `MessageBubble` uses for the same backend outcome.
  const runOutcomeText =
    runOutcome === "interrupted"
      ? "execução interrompida"
      : runOutcome === "cancelled"
        ? "execução cancelada"
        : runOutcome === "paused"
          ? "execução em pausa"
          : runOutcome === "failed"
            ? `${errorCount} erro${errorCount === 1 ? "" : "s"}`
            : runOutcome === "warning"
              ? `${summary.warnings} aviso${summary.warnings === 1 ? "" : "s"}`
              : runOutcome === "unknown"
                ? "estado final não confirmado"
                : "";
  // Same three colours already in use for these states: rose for failures,
  // amber for warnings/interruptions/pause, muted for cancellation and for the
  // absence of a reported outcome.
  const runOutcomePillClass =
    runOutcome === "failed"
      ? "bg-rose-500/10 text-rose-300"
      : runOutcome === "interrupted" || runOutcome === "paused" || runOutcome === "warning"
        ? "bg-amber-400/10 text-amber-200"
        : "bg-nexus-bg/70 text-nexus-muted";

  const liveStep = useMemo(() => {
    for (let i = orderedSteps.length - 1; i >= 0; i -= 1) {
      const step = orderedSteps[i];
      if (step.status === "running" || step.status === "awaiting_confirmation" || step.status === "paused") {
        return step;
      }
    }
    return undefined;
  }, [orderedSteps]);

  const liveThinking = isStreaming && !liveStep && hasThinking;
  const liveActivity = [...(message.activities ?? [])].reverse().find(
    (activity) => activity.status === "running" || activity.status === "paused",
  );

  // The reasoning block's real wall time. `foldRun` fills `durationMs` when the
  // block closes, so a finished run shows the true elapsed instead of the
  // "concluído" placeholder the component used to always show.
  const thinkingTiming = useMemo(() => {
    const step = message.steps?.find(
      (item) => item.verb === "thinking" && item.durationMs !== undefined,
    );
    return {
      durationMs: step?.durationMs,
      startedAt: step?.startedAt,
    };
  }, [message.steps]);

  // Editorial one-liner + day divider hooks must run before the early
  // return (rules-of-hooks).
  const editorial = useMemo(() => summarizeRunForHeader(message), [message]);
  const dayDivider = useMemo(() => formatDayDivider(message.timestamp), [message.timestamp]);

  if (!hasSteps && !hasThinking && !hasActivities && !hasTools && !hasMetrics && !hasFooter && !hasRunErrors && !isStreaming) {
    return null;
  }

  // Streaming one-liner: “◉ A usar read_file · CODER · 00:42…”.
  // Falls back to “A iniciar execução…” before the first detail arrives.
  const streamingAgent = liveStep?.agent ?? liveActivity?.agent;
  const streamingClock =
    liveStep?.startedAt !== undefined && Number.isFinite(liveStep.startedAt)
      ? formatRunClock(Math.max(0, Date.now() - liveStep.startedAt))
      : null;
  const currentTaskLabel = liveStep
    ? (() => {
        const base =
          liveStep.verb === "tool"
            ? `A usar ${liveStep.target || liveStep.label || "ferramenta"}`
            : liveStep.target
              ? `${liveStep.label} · ${liveStep.target}`
              : liveStep.label;
        const parts = [base];
        if (streamingAgent) parts.push(streamingAgent);
        if (streamingClock) parts.push(streamingClock);
        return `${parts.join(" · ")}…`;
      })()
    : liveActivity
      ? `${[liveActivity.detail || liveActivity.title, liveActivity.agent].filter(Boolean).join(" · ")}…`
    : liveThinking
      ? "A analisar a tarefa"
      : isStreaming
        ? "A iniciar execução…"
        : "";

  const recapChips: string[] = [];
  // The recap must not depend on a `verb:"thinking"` step existing: a run whose
  // reasoning arrived only as a `thinking` frame with no coalesced step (older
  // journals, a lane that emits no timeline) still reasoned, and `message.
  // thinking` is the authoritative evidence.
  if (summary.thinking || hasThinking) recapChips.push("raciocinou");
  if (summary.tools > 0) recapChips.push(`${summary.tools} ferramenta${summary.tools === 1 ? "" : "s"}`);
  if (summary.files > 0) recapChips.push(`${summary.files} ficheiro${summary.files === 1 ? "" : "s"}`);
  if (summary.commands > 0) recapChips.push(`${summary.commands} comando${summary.commands === 1 ? "" : "s"}`);

  // Editorial one-liner: “◉ Trabalhou 2m14s · 17 ações · 3 agentes · 2 erros”.
  // Activity lives here; Result is the markdown answer — never mixed.
  // Errors show only when > 0; agents only when known.
  const editorialDuration = formatRunDuration(editorial.elapsedMs);
  const editorialParts = [
    `${editorial.actions} ${editorial.actions === 1 ? "ação" : "ações"}`,
  ];
  if (editorial.agents > 0) {
    editorialParts.push(`${editorial.agents} ${editorial.agents === 1 ? "agente" : "agentes"}`);
  }
  if (errorCount > 0) {
    editorialParts.push(`${errorCount} ${errorCount === 1 ? "erro" : "erros"}`);
  }
  const editorialLabel = editorial.actions > 0 || editorialDuration
    ? editorialDuration
      ? `Trabalhou ${editorialDuration} · ${editorialParts.join(" · ")}`
      : `Trabalhou ${editorialParts.join(" · ")}`
    : "";

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-nexus-border/60 bg-nexus-panel/45">
      {dayDivider && (
        <div className="px-2.5 pt-1.5 text-[10px] leading-none text-nexus-faint" aria-hidden="true">
          {dayDivider}
        </div>
      )}
      {/* Compact header: live status or done-recap + toggle. */}
      {(currentTaskLabel || !isStreaming) && (
        <button
          type="button"
          data-testid="run-timeline-toggle"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          aria-controls={expanded ? timelineBodyId : undefined}
          className="nx-motion-feedback flex w-full items-center gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-nexus-card/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nexus-accent/50"
        >
          {isStreaming ? (
            <>
              <span aria-hidden="true" className="shrink-0 animate-pulse text-[12px] leading-none text-nexus-accent">
                ◉
              </span>
              <StatusDot status={liveStep?.status ?? liveActivity?.status ?? "running"} />
              <span className="rounded bg-nexus-accent/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-nexus-accent">
                Tarefa atual
              </span>
              <span role="status" aria-live="polite" className="min-w-0 flex-1 truncate text-[11px] font-medium text-nexus-text">
                {currentTaskLabel}
              </span>
            </>
          ) : (
            <>
              <RunOutcomeDot outcome={runOutcome} />
              <span className="flex min-w-0 flex-1 items-center gap-x-2 gap-y-0.5 overflow-hidden whitespace-nowrap text-[11px] text-nexus-muted">
                {editorialLabel ? (
                  <span className="truncate font-medium text-nexus-text/85" title={editorialLabel}>
                    {editorialLabel}
                  </span>
                ) : (
                  <span className="font-medium text-nexus-text/80">
                    {runOutcomeText ||
                      (summary.steps > 0
                        ? `${summary.steps} passo${summary.steps === 1 ? "" : "s"}`
                        : hasThinking
                          ? "raciocínio"
                          : "execução")}
                  </span>
                )}
                {recapChips.slice(0, 3).map((chip) => (
                  <span key={chip} className="hidden shrink-0 rounded-full bg-nexus-bg/70 px-1.5 py-px text-[9px] sm:inline">
                    {chip}
                  </span>
                ))}
                {/* Legacy compact recap kept for screen readers/tests when the
                    editorial line already covers the story visually. */}
                <span className="sr-only">
                  {runOutcomeText ||
                    (summary.steps > 0
                      ? `${summary.steps} passos`
                      : hasThinking
                        ? "raciocínio"
                        : "execução")}
                  {recapChips.length > 0 ? ` · ${recapChips.join(" · ")}` : ""}
                </span>
                {/* One status pill for every outcome that is not a completed run,
                    so the header always states what the run actually reported —
                    including when it reported nothing. */}
                {runOutcome !== "completed" && runOutcomeText && (
                  <span
                    data-testid="run-outcome-pill"
                    className={`shrink-0 rounded-full px-1.5 py-px text-[9px] ${runOutcomePillClass}`}
                  >
                    {runOutcomeText}
                  </span>
                )}
              </span>
            </>
          )}
          <ChevronDown
            className={`h-3 w-3 shrink-0 text-nexus-muted transition-transform duration-150 ${
              expanded ? "rotate-180" : ""
            }`}
          />
        </button>
      )}

      {/*
        Detail body. It is genuinely UNMOUNTED while collapsed: keeping it in
        the DOM behind `className="hidden"` meant every tool result of every
        run in a long session was parsed, held in memory and reachable by
        assistive tech even when the user never opened the timeline. The header
        recap above is the collapsed affordance; `aria-controls` points at this
        region and `content-visibility` lets the browser skip layout/paint work
        for the collapsed frame.
      */}
      {expanded && (
        <div
          id={timelineBodyId}
          data-testid="run-timeline-body"
          role="region"
          aria-label="Atividade da execução"
          className="[content-visibility:auto]"
        >
          {executionGraph.nodes.length > 0 && (
            <div role="group" aria-label="Vista da execução" className="flex gap-1 border-b border-nexus-border/20 px-2 py-1.5">
              <button
                type="button"
                data-testid="execution-view-timeline"
                aria-pressed={view === "timeline"}
                onClick={() => setView("timeline")}
                className="rounded px-2 py-1 text-[10px] text-nexus-muted aria-pressed:bg-nexus-accent/10 aria-pressed:text-nexus-accent"
              >
                Timeline
              </button>
              <button
                type="button"
                data-testid="execution-view-graph"
                aria-pressed={view === "graph"}
                onClick={() => setView("graph")}
                className="rounded px-2 py-1 text-[10px] text-nexus-muted aria-pressed:bg-nexus-accent/10 aria-pressed:text-nexus-accent"
              >
                Grafo
              </button>
            </div>
          )}

          {view === "graph" ? (
            <AgentExecutionGraph graph={executionGraph} />
          ) : (
            <>
              {hasSteps && (
                <div className="px-2 pt-1.5 pb-1 text-[10px] font-semibold uppercase tracking-wide text-nexus-muted/60">
                  Linha de execução
                </div>
              )}
              {hasActivities && <ExecutionPlan activities={message.activities ?? []} />}
              {hasSteps && (
                <RunSteps
                  steps={message.steps!}
                  onStepClick={() => setExpanded(true)}
                />
              )}

              <AnimatePresence initial={false}>
                {hasThinking && (
                  <motion.div
                    key="thinking"
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    transition={{ duration: 0.16, ease: "easeOut" }}
                    className="overflow-hidden border-t border-nexus-border/20 [content-visibility:auto]"
                  >
                    <ThinkingBlock
                      content={message.thinking!}
                      isStreaming={isStreaming}
                      defaultOpen={Boolean(isStreaming)}
                      durationMs={thinkingTiming.durationMs}
                      startedAt={thinkingTiming.startedAt}
                    />
                  </motion.div>
                )}
                {(hasActivities || hasRunErrors) && (
                  <motion.div
                    key="activities"
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    transition={{ duration: 0.16, ease: "easeOut" }}
                    className="overflow-hidden border-t border-nexus-border/20 [content-visibility:auto]"
                  >
                    <ExecutionActivity
                      items={message.activities ?? []}
                      isStreaming={isStreaming}
                      hasErrors={hasRunErrors}
                    />
                  </motion.div>
                )}
                {hasTools && (
                  <motion.div
                    key="tools"
                    initial={{ opacity: 0, y: -4 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    transition={{ duration: 0.16, ease: "easeOut" }}
                    className="overflow-hidden border-t border-nexus-border/20 [content-visibility:auto]"
                  >
                    <ToolCallTimeline calls={message.toolCalls!} sessionId={sessionId} />
                  </motion.div>
                )}
              </AnimatePresence>
            </>
          )}
        </div>
      )}

      {/* Live footer: phase + elapsed + tokens. */}
      <RunFooter message={message} />
    </div>
  );
}

export default memo(RunTimelineComponent);
