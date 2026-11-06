"use client";

import { useEffect, useId, useMemo, useState, memo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Brain,
  Activity,
  Loader2,
  CircleDashed,
  CheckCircle2,
  XCircle,
  ShieldAlert,
  Pause,
  Clock,
  BarChart3,
  TriangleAlert,
  ChevronDown,
} from "lucide-react";
import type { ChatMessage, RunStep, StepStatus } from "../../lib/types";
import { buildExecutionGraph } from "../../lib/executionGraph";
import { formatRunDuration, runStepKey } from "../../lib/chatPresentation";
import { collapseRepeatedStatus, narrateLive, narrateStep } from "../../lib/plainNarration";
import { compactActivityLine } from "../../lib/activityLine";
import { formatUsd } from "../../lib/format";
import { summarizeRunForHeader, isFailingActivityStatus } from "../../lib/foldRun";
import { foldSubagentCards, tallyActivity, toActivityBlocks } from "../../lib/activityGroups";
import { useModelStore } from "../../stores/modelStore";
import { usePresentationStore } from "../../stores/presentationStore";
import { useShallow } from "zustand/react/shallow";
import ExecutionActivity from "./ExecutionActivity";
import ToolCallTimeline from "./ToolCallTimeline";
import AgentExecutionGraph from "./AgentExecutionGraph";
import PlanBlock, { latestPlanActivity } from "./PlanBlock";
import { StepRow, StepStatusIcon, ActivityGroupRow, TaskGroupRow, timelineOrigin } from "./ActivityGroupRow";
import { AgentRoster, DetailLevelSwitch, MemoryNotice } from "./WorkNarration";

export interface RunTimelineProps {
  message: ChatMessage;
  isStreaming?: boolean;
  sessionId?: string;
}

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
      return <XCircle className="h-3 w-3 shrink-0 text-nexus-accent4" />;
    case "interrupted":
      return <TriangleAlert className="h-3 w-3 shrink-0 text-nexus-accent3" />;
    case "cancelled":
      return <CircleDashed className="h-3 w-3 shrink-0 text-nexus-muted" />;
    case "paused":
      return <Pause className="h-3 w-3 shrink-0 text-nexus-accent3" />;
    case "warning":
      return <TriangleAlert className="h-3 w-3 shrink-0 text-nexus-accent3" />;
    case "completed":
      return (
        <span aria-hidden="true" className="shrink-0 text-[12px] leading-none text-nexus-accent2">
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
      return <CheckCircle2 className="h-3 w-3 text-nexus-accent2" />;
    case "error":
      return <XCircle className="h-3 w-3 text-nexus-accent4" />;
    case "awaiting_confirmation":
      return <ShieldAlert className="h-3 w-3 text-nexus-accent3" />;
    case "warning":
      return <TriangleAlert className="h-3 w-3 text-nexus-accent3" />;
    case "paused":
      return <Pause className="h-3 w-3 text-nexus-accent3" />;
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

/** Empty status rows. They repeat "a avançar" without naming a tool or a thought. */
function isFillerStatus(step: RunStep): boolean {
  if (step.verb !== "status") return false;
  if ((step.target || "").trim()) return false;
  const label = (step.label || "").trim().toLowerCase();
  return label === "a avançar" || label === "a processar" || label === "atualização de execução";
}

/**
 * The activity fold's renderer: task groups (runtime's own), family groups
 * ("Explorou 24 ficheiros") and plain rows — all from the same `steps` array.
 * A group expands into the very same `StepRow`s an ungrouped run shows, so
 * grouping can hide work but never rewrite it.
 */
function RunSteps({ steps }: { steps: RunStep[] }) {
  const level = usePresentationStore((state) => state.level);
  const visible = useMemo(() => {
    const levelled = level === "technical" ? steps : collapseRepeatedStatus(steps);
    if (level === "technical") return levelled;
    return levelled.filter((step) => !isFillerStatus(step));
  }, [steps, level]);
  const blocks = useMemo(() => foldSubagentCards(toActivityBlocks(visible)), [visible]);
  const t0 = useMemo(() => timelineOrigin(visible), [visible]);

  if (steps.length === 0) return null;

  return (
    <div className="[content-visibility:auto]">
      {blocks.map((block, index) => {
        if (block.type === "task") {
          return <TaskGroupRow key={`task-${block.taskId}-${index}`} taskId={block.taskId} steps={block.steps} t0={t0} />;
        }
        if (block.type === "group") {
          return <ActivityGroupRow key={`group-${block.group.family}-${index}`} group={block.group} />;
        }
        return block.steps.map((step, stepIndex) => (
          <StepRow key={runStepKey(step, stepIndex)} step={step} t0={t0} />
        ));
      })}
    </div>
  );
}

function numOrUndefined(value: unknown): number | undefined {
  if (typeof value !== "number" && (typeof value !== "string" || !value.trim())) return undefined;
  const parsed = typeof value === "number" ? value : Number(value);
  return typeof parsed === "number" && Number.isFinite(parsed) && parsed >= 0 ? parsed : undefined;
}

function RunFooter({ message }: { message: ChatMessage }) {
  // One subscription, not two: each separate selector can trigger its own re-render
  // of a footer mounted once per message in view. useShallow is load-bearing:
  // returning a fresh object from the selector would make zustand see a new
  // reference on every store change and re-render forever.
  const { models } = useModelStore(
    useShallow((state) => ({
      models: state.models,
    })),
  );
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
  // A historical run must use the model reported for that run, not whatever
  // happens to be selected in the composer now. Both prices and both usage
  // counts are required; treating missing inputs as zero invents a cost.
  const reportedModel = typeof providerInfo?.model === "string" ? providerInfo.model : "";
  const reportedProvider = typeof providerInfo?.name === "string" ? providerInfo.name : "";
  const usedModel = reportedModel && reportedProvider
    ? models.find((model) => model.id === reportedModel && model.provider === reportedProvider)
    : undefined;
  const inputPrice = usedModel?.inputPricePer1M;
  const outputPrice = usedModel?.outputPricePer1M;
  const inputCount = numOrUndefined(input);
  const outputCount = numOrUndefined(output);
  const liveCost =
    inputPrice != null && outputPrice != null && inputCount !== undefined && outputCount !== undefined
      ? (inputPrice * inputCount + outputPrice * outputCount) / 1_000_000
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
    <div
      data-testid="run-observability"
      className="density-developer flex flex-wrap items-center gap-2.5 border-t border-nexus-border/30 px-1 py-2 text-[10px] text-nexus-muted"
    >
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
        <span className="rounded bg-nexus-accent3/10 px-2 py-0.5 text-nexus-accent3/90">
          simulação
        </span>
      )}
      {phase && (
        <span className="inline-flex items-center gap-1 rounded bg-nexus-accent/10 px-2 py-0.5 text-nexus-text/80">
          <Activity className="h-3 w-3 text-nexus-accent" />
          fase: {phase}
        </span>
      )}
      {typeof elapsed === "number" && (
        <span className="inline-flex items-center gap-1 rounded bg-nexus-bg/70 px-2 py-0.5">
          <Clock className="h-3 w-3 text-nexus-muted" />
          {formatDuration(elapsed)}
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
          className="inline-flex items-center gap-1 rounded bg-nexus-cyan/10 px-2 py-0.5 text-nexus-cyan/80"
          title={reasoningSource === "estimated"
            ? "Estimativa de tokens gastos pelo modelo a raciocinar"
            : "Tokens de raciocínio reportados pelo provider"}
        >
          <Brain className="h-3 w-3 text-nexus-cyan" />
          {Math.round(reasoningCount!)} em raciocínio
          {reasoningSource === "estimated" ? " · estimado" : ""}
        </span>
      )}
      {input !== undefined && output !== undefined && (
        <span
          className="hidden items-center gap-1 rounded bg-nexus-bg/70 px-2 py-0.5 sm:inline-flex"
          title="Tokens de entrada e de saída"
        >
          <span aria-hidden="true">↑{String(input)} ↓{String(output)}</span>
          <span className="sr-only">
            entrada {String(input)} tokens, saída {String(output)} tokens
          </span>
        </span>
      )}
      {liveCost != null && (
        <span
          data-testid="run-cost"
          title="Custo estimado com os preços atuais do modelo reportado para esta execução"
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

/**
 * Chat-style activity surface for one assistant turn.
 *
 * Collapsed by default it reads as a single living line — what the model is
 * doing right now while streaming, and a quiet "N passos · M ferramentas"
 * recap once done. The active plan stays beside the answer; expanding reveals
 * the ordered activity and tool details. The footer keeps the live telemetry
 * visible without any click.
 */
function RunTimelineComponent({ message, isStreaming, sessionId }: RunTimelineProps) {
  const level = usePresentationStore((state) => state.level);
  const timelineBodyId = `run-timeline-${useId().replace(/:/g, "")}`;
  const orderedSteps = useMemo(
    () => [...(message.steps ?? [])]
      .filter((step) => step.verb !== "thinking")
      .sort((a, b) => (a.seq > 0 ? a.seq : Number.MAX_SAFE_INTEGER) -
        (b.seq > 0 ? b.seq : Number.MAX_SAFE_INTEGER)),
    [message.steps],
  );
  const hasSteps = orderedSteps.length > 0;
  const hasActivities = Boolean(message.activities?.length);
  const hasPlan = Boolean(latestPlanActivity(message.activities ?? []));
  const hasTools = Boolean(message.toolCalls?.length);
  const hasMetrics = Boolean(message.metrics);
  const hasFooter = Boolean(message.runId || message.metadata?.footer);
  const recentSteps = useMemo(
    () => collapseRepeatedStatus(orderedSteps)
      .filter((step) => step.verb !== "agent" && !isFillerStatus(step))
      .slice(-3),
    [orderedSteps],
  );
  const publicThought = message.metadata?.reasoningVisibility === "label"
    ? message.thinking?.trim().slice(0, 240)
    : "";

  // A pending confirmation needs an immediate decision. Failures stay visible
  // in the compact outcome line and the chat error message; the technical log
  // opens only when the user asks for it.
  const needsImmediateAction = useMemo(() => {
    return Boolean(message.toolCalls?.some(
      (call) => call.status === "awaiting_confirmation",
    ));
  }, [message.toolCalls]);

  const [expanded, setExpanded] = useState<boolean>(needsImmediateAction);
  const [view, setView] = useState<"timeline" | "graph">("timeline");

  useEffect(() => {
    if (needsImmediateAction) setExpanded(true);
  }, [needsImmediateAction]);

  const summary = useMemo(() => summarize(orderedSteps), [orderedSteps]);
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
    isFailingActivityStatus(activity.status) && activity.data?.kind !== "cancel_requested",
  ).length;
  const errorCount = Math.max(
    summary.errors,
    message.toolCalls?.filter((call) => call.status === "error").length ?? 0,
    activityFailures,
  );
  const hasRunErrors = errorCount > 0;
  const hasRunCancelled = orderedSteps.some((step) => step.kind === "run_cancelled");
  const hasStopRequest = orderedSteps.some((step) => step.kind === "cancel_requested");
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
        : hasStopRequest
          ? "unknown"
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
                ? hasStopRequest ? "paragem pedida · estado final não confirmado" : "estado final não confirmado"
                : "";
  // Same three colours already in use for these states: rose for failures,
  // amber for warnings/interruptions/pause, muted for cancellation and for the
  // absence of a reported outcome.
  const runOutcomePillClass =
    runOutcome === "failed"
      ? "bg-rose-500/10 text-nexus-accent4"
      : runOutcome === "interrupted" || runOutcome === "paused" || runOutcome === "warning"
        ? "bg-amber-400/10 text-nexus-accent3"
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

  const liveActivity = [...(message.activities ?? [])].reverse().find(
    (activity) => activity.status === "running" || activity.status === "paused",
  );
  const liveNarration = useMemo(
    () => narrateLive({ ...message, steps: orderedSteps }, true),
    [message, orderedSteps],
  );

  // Editorial one-liner + day divider hooks must run before the early
  // return (rules-of-hooks).
  const editorial = useMemo(
    () => summarizeRunForHeader({ ...message, steps: orderedSteps, thinking: undefined }),
    [message, orderedSteps],
  );
  const dayDivider = useMemo(() => formatDayDivider(message.timestamp), [message.timestamp]);

  if (!hasSteps && !hasActivities && !hasTools && !hasMetrics && !hasFooter && !hasRunErrors && !isStreaming) {
    return null;
  }

  const currentTaskLabel = isStreaming
    ? level === "technical" && liveNarration.raw && liveNarration.raw !== liveNarration.sentence
      ? `${liveNarration.sentence} · ${liveNarration.raw}`
      : liveNarration.sentence
    : "";

  const recapChips: string[] = [];
  // Family chips answer "what kind of work was this?" in one glance — the
  // grouped activity below is the same data at the next disclosure level.
  const tally = tallyActivity(orderedSteps);
  if (tally.filesExplored > 0) recapChips.push(`${tally.filesExplored} ${tally.filesExplored === 1 ? "exploração" : "explorações"}`);
  if (tally.filesEdited > 0) recapChips.push(`${tally.filesEdited} ${tally.filesEdited === 1 ? "alteração" : "alterações"}`);
  if (tally.commands > 0) recapChips.push(`${tally.commands} comandos`);
  if (tally.searches > 0) recapChips.push(`${tally.searches} pesquisas`);
  if (tally.verifications > 0) recapChips.push(`${tally.verifications} ${tally.verifications === 1 ? "verificação" : "verificações"}`);
  if (tally.webRequests > 0) recapChips.push(`${tally.webRequests} web`);

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
    <div className="my-2 overflow-hidden border-l-2 border-nexus-border/50 pl-1">
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
          className="nx-motion-feedback flex w-full items-center gap-2.5 rounded-lg px-2 py-2 text-left transition-colors hover:bg-nexus-card/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/50"
        >
          {isStreaming ? (
            <>
              <span aria-hidden="true" className="shrink-0 animate-pulse text-[12px] leading-none text-nexus-accent">
                ◉
              </span>
              <StatusDot status={liveStep?.status ?? liveActivity?.status ?? "running"} />
              <span className="rounded bg-nexus-accent/10 px-1.5 py-0.5 text-[11px] text-nexus-accent">
                Tarefa atual
              </span>
              {/* No live region inside the toggle: it would join the button accessible name, so every stream event would re-announce the whole control. */}
              <span className="min-w-0 flex-1 truncate text-[11px] font-medium text-nexus-text">
                {currentTaskLabel}
              </span>
            </>
          ) : (
            <>
              <RunOutcomeDot outcome={runOutcome} />
              <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-nexus-muted">
                {editorialLabel ? (
                  <span
                    className="max-w-full truncate font-medium text-nexus-text/85"
                    title={editorialLabel}
                  >
                    {editorialLabel}
                  </span>
                ) : (
                  /* The main line states what the run DID; the pill below
                     states what the run REPORTED. Showing the outcome text in
                     both places repeated the same sentence twice on every
                     message ("estado final não confirmado" x2). */
                  <span className="font-medium text-nexus-text/80">
                    {summary.steps > 0
                      ? `${summary.steps} passo${summary.steps === 1 ? "" : "s"}`
                      : "execução"}
                  </span>
                )}
                {recapChips.slice(0, 4).map((chip) => (
                  <span
                    key={chip}
                    className="density-standard hidden shrink-0 rounded-full bg-nexus-bg/70 px-1.5 py-px text-[9px] sm:inline"
                  >
                    {chip}
                  </span>
                ))}
                {/* Legacy compact recap kept for screen readers/tests when the
                    editorial line already covers the story visually. */}
                <span className="sr-only">
                  {runOutcomeText ||
                    (summary.steps > 0
                      ? `${summary.steps} passos`
                      : "execução")}
                  {recapChips.length > 0 ? ` · ${recapChips.join(" · ")}` : ""}
                </span>
                {/* One status pill for every outcome that is not a completed run,
                    so the header always states what the run actually reported —
                    including when it reported nothing. */}
                {runOutcome !== "completed" && runOutcomeText && (
                  <span
                    data-testid="run-outcome-pill"
                    className={`rounded-full px-2 py-0.5 text-[10px] ${runOutcomePillClass}`}
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

      {isStreaming && (message.thinking || recentSteps.length > 0) && !expanded && (
        <div aria-label="Atividade recente" className="ml-3 space-y-1 border-l border-nexus-border/40 pb-1 pl-3">
          {message.thinking && (
            <div className="flex items-start gap-2 text-[12px] leading-relaxed text-nexus-faint">
              <Brain className="mt-0.5 h-3 w-3 shrink-0" aria-hidden="true" />
              <span>{publicThought || "A pensar…"}</span>
            </div>
          )}
          {recentSteps.map((step, index) => (
            <div key={runStepKey(step, index)} className="flex items-start gap-2 text-[12px] leading-relaxed text-nexus-muted">
              <StepStatusIcon status={step.status} className="mt-0.5 h-3 w-3" />
              <span className="min-w-0 break-words">{compactActivityLine(step) ?? narrateStep(step).sentence}</span>
            </div>
          ))}
        </div>
      )}

      <AgentRoster message={message} />
      {hasTools && <div className="px-2 pb-1"><ToolCallTimeline calls={message.toolCalls!} sessionId={sessionId} compact /></div>}

      {hasPlan && (
        <div className="px-2 pb-2">
          <PlanBlock activities={message.activities ?? []} />
        </div>
      )}

      {/*
        Detail body. It is genuinely UNMOUNTED while collapsed: keeping it in
        the DOM behind `className="hidden"` meant every tool result of every
        run in a long session was parsed, held in memory and reachable by
        assistive tech even when the user never opened the timeline. The header
        recap above is the collapsed affordance; `aria-controls` points at this
        region and `content-visibility` lets the browser skip layout/paint work
        for the collapsed frame.

        NOTE: the body itself carries NO density class. Gating the whole detail
        behind `density-developer` (as it once did) hid the plan, the grouped
        activity and the tool list from every user on the default density —
        information the header itself invites them to open. Density now only
        hides the telemetry footer (RunFooter), which is what its label
        promises: "resumo" vs "tokens + latência".
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
              <div className="flex items-center justify-between gap-2 px-3 pt-2">
                <DetailLevelSwitch />
              </div>
              {hasSteps && (
                <div className="px-3 pt-2">
                  <RunSteps steps={orderedSteps} />
                </div>
              )}
              <MemoryNotice message={message} />
              <AnimatePresence initial={false}>
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
              </AnimatePresence>
            </>
          )}
        </div>
      )}

      {/* Telemetry: hidden by the density classes (density-developer) unless
          the user asked for the developer level. */}
      <RunFooter message={message} />
    </div>
  );
}

export default memo(RunTimelineComponent);
