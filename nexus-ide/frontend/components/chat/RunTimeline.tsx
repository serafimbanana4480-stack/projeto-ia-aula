"use client";

import { useEffect, useMemo, useState, memo, type ComponentType } from "react";
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
  CheckCircle2,
  XCircle,
  ShieldAlert,
  Clock,
  BarChart3,
  TestTube,
  ChevronDown,
} from "lucide-react";
import type { ChatMessage, RunStep, StepStatus } from "../../lib/types";
import ThinkingBlock from "./ThinkingBlock";
import ExecutionActivity from "./ExecutionActivity";
import ToolCallTimeline from "./ToolCallTimeline";

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
    default:
      return <Activity className="h-3 w-3 text-nexus-muted" />;
  }
}

function verbLabel(verb: RunStep["verb"]): string {
  switch (verb) {
    case "thinking":
      return "a raciocinar";
    case "tool":
      return "ferramenta";
    case "file":
      return "ficheiro";
    case "command":
      return "comando";
    case "test":
      return "verificação";
    case "agent":
      return "agente";
    case "status":
      return "estado";
    case "message":
      return "mensagem";
    default:
      return "passo";
  }
}

function formatDuration(ms?: number): string {
  if (typeof ms !== "number" || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = Math.floor(ms / 1000);
  const rest = Math.round(ms - s * 1000);
  return `${s}s ${rest}ms`;
}

/** One compact line per run step, ordered by ``seq``. */
function RunSteps({ steps, onStepClick }: { steps: RunStep[]; onStepClick: (step: RunStep) => void }) {
  const ordered = useMemo(
    () => [...steps].sort((a, b) => a.seq - b.seq),
    [steps],
  );

  if (!steps || steps.length === 0) return null;

  return (
    <div className="border-l border-nexus-border/30 pl-3.5">
      {ordered.map((step) => {
        const Icon = STEP_ICONS[step.verb] || Activity;
        return (
          <button
            key={`${step.seq}-${step.kind}`}
            type="button"
            data-testid="run-step"
            onClick={() => onStepClick(step)}
            className="flex w-full items-center gap-2.5 py-1.5 text-left hover:bg-nexus-card/40"
            title={step.target ? `${step.label} · ${step.target}` : step.label}
          >
            <span className="mt-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-nexus-card">
              <Icon className="h-3 w-3 text-nexus-muted" />
            </span>
            <span className="flex min-w-0 flex-1 items-center gap-1.5">
              <span className="text-[11px] font-medium text-nexus-text/90">
                {step.label}
              </span>
              {step.target && (
                <span className="truncate text-[10px] text-nexus-muted/70">
                  {step.target}
                </span>
              )}
            </span>
            <StatusDot status={step.status} />
            {step.durationMs !== undefined && step.status !== "running" && (
              <span className="text-[9px] text-nexus-muted">
                {formatDuration(step.durationMs)}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

function RunFooter({ message }: { message: ChatMessage }) {
  const footer = message.metadata?.footer as
    | { phase?: string; elapsedMs?: number; telemetry?: Record<string, unknown> }
    | undefined;
  const phase = footer?.phase;
  const elapsed = footer?.elapsedMs;
  const tokens = footer?.telemetry;

  if (!phase && elapsed === undefined && !tokens && !message.metrics) return null;

  const input = message.metrics?.Input ?? tokens?.input_tokens;
  const output = message.metrics?.Output ?? tokens?.output_tokens;
  const total = message.metrics?.Total ?? tokens?.total_tokens;
  const tokenCount =
    typeof total === "number"
      ? total
      : typeof total === "string"
        ? Number(total)
        : undefined;

  return (
    <div className="flex flex-wrap items-center gap-2.5 border-t border-nexus-border/30 px-1 py-2 text-[10px] text-nexus-muted">
      {phase && (
        <span className="inline-flex items-center gap-1 rounded bg-violet-400/10 px-2 py-0.5 text-nexus-text/80">
          <Activity className="h-3 w-3 text-violet-300" />
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
      {input !== undefined && output !== undefined && (
        <span className="hidden items-center gap-1 rounded bg-nexus-bg/70 px-2 py-0.5 sm:inline-flex">
          ↑{String(input)} ↓{String(output)}
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
}

function summarize(steps: RunStep[]): RunSummary {
  const counts: RunSummary = {
    steps: steps.length,
    tools: 0,
    files: 0,
    thinking: false,
    commands: 0,
    errors: 0,
  };
  for (const step of steps) {
    if (step.verb === "tool") counts.tools += 1;
    else if (step.verb === "file") counts.files += 1;
    else if (step.verb === "command") counts.commands += 1;
    else if (step.verb === "thinking") counts.thinking = true;
    if (step.status === "error") counts.errors += 1;
  }
  return counts;
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
  const hasSteps = Boolean(message.steps?.length);
  const hasThinking = Boolean(message.thinking);
  const hasActivities = Boolean(message.activities?.length);
  const hasTools = Boolean(message.toolCalls?.length);
  const hasMetrics = Boolean(message.metrics);

  // A pending confirmation or an error must be impossible to miss: those
  // states expand the detail automatically, everything else stays compact.
  const needsAttention = useMemo(() => {
    const confirmationPending = message.toolCalls?.some(
      (call) => call.status === "awaiting_confirmation",
    );
    const failedSteps = message.steps?.some((step) => step.status === "error");
    return Boolean(confirmationPending || failedSteps);
  }, [message.toolCalls, message.steps]);

  const [expanded, setExpanded] = useState<boolean>(needsAttention);

  useEffect(() => {
    if (needsAttention) setExpanded(true);
  }, [needsAttention]);

  const orderedSteps = useMemo(
    () => [...(message.steps ?? [])].sort((a, b) => a.seq - b.seq),
    [message.steps],
  );

  const summary = useMemo(() => summarize(message.steps ?? []), [message.steps]);

  const liveStep = useMemo(() => {
    for (let i = orderedSteps.length - 1; i >= 0; i -= 1) {
      const step = orderedSteps[i];
      if (step.status === "running" || step.status === "awaiting_confirmation") {
        return step;
      }
    }
    return undefined;
  }, [orderedSteps]);

  const liveThinking = isStreaming && !liveStep && hasThinking;

  if (!hasSteps && !hasThinking && !hasActivities && !hasTools && !hasMetrics) {
    return null;
  }

  const headerLabel = liveStep
    ? liveStep.target
      ? `${liveStep.label} · ${liveStep.target}`
      : liveStep.label
    : liveThinking
      ? "a raciocinar…"
      : "";

  const recapChips: string[] = [];
  if (summary.thinking) recapChips.push("raciocinou");
  if (summary.tools > 0) recapChips.push(`${summary.tools} ferramenta${summary.tools === 1 ? "" : "s"}`);
  if (summary.files > 0) recapChips.push(`${summary.files} ficheiro${summary.files === 1 ? "" : "s"}`);
  if (summary.commands > 0) recapChips.push(`${summary.commands} comando${summary.commands === 1 ? "" : "s"}`);

  return (
    <div className="my-2 overflow-hidden rounded-xl border border-nexus-border/40 bg-nexus-card/30">
      {/* Compact header: live status or done-recap + toggle. */}
      {(headerLabel || !isStreaming) && (
        <button
          type="button"
          data-testid="run-timeline-toggle"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          className="flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition-colors hover:bg-nexus-card/50"
        >
          {isStreaming ? (
            <>
              <Loader2 className="h-3 w-3 shrink-0 animate-spin text-nexus-accent" />
              <span className="min-w-0 flex-1 truncate bg-gradient-to-r from-nexus-text via-nexus-accent to-nexus-text bg-[length:200%_100%] bg-clip-text text-[11px] font-medium text-transparent motion-safe:animate-shimmer">
                {headerLabel}
              </span>
            </>
          ) : (
            <>
              {summary.errors > 0 ? (
                <XCircle className="h-3 w-3 shrink-0 text-rose-400" />
              ) : (
                <CheckCircle2 className="h-3 w-3 shrink-0 text-emerald-400" />
              )}
              <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-0.5 text-[11px] text-nexus-muted">
                <span className="font-medium text-nexus-text/80">
                  {summary.steps > 0
                    ? `${summary.steps} passo${summary.steps === 1 ? "" : "s"}`
                    : hasThinking
                      ? "raciocínio"
                      : "execução"}
                </span>
                {recapChips.slice(0, 3).map((chip) => (
                  <span key={chip} className="rounded-full bg-nexus-bg/70 px-1.5 py-px text-[9px]">
                    {chip}
                  </span>
                ))}
                {summary.errors > 0 && (
                  <span className="rounded-full bg-rose-500/10 px-1.5 py-px text-[9px] text-rose-300">
                    {summary.errors} erro{summary.errors === 1 ? "" : "s"}
                  </span>
                )}
              </span>
            </>
          )}
          <ChevronDown
            className={`h-3 w-3 shrink-0 text-nexus-muted transition-transform duration-200 ${
              expanded ? "rotate-180" : ""
            }`}
          />
        </button>
      )}

      {/* Detail body: mounted but visually collapsed so tests keep working. */}
      <div className={expanded ? "" : "hidden"}>
        {hasSteps && (
          <div className="px-2 pt-1.5 pb-1 text-[10px] font-semibold uppercase tracking-wide text-nexus-muted/60">
            Linha de execução
          </div>
        )}
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
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden border-t border-nexus-border/20"
            >
              <ThinkingBlock
                content={message.thinking!}
                isStreaming={isStreaming}
                defaultOpen={Boolean(isStreaming)}
              />
            </motion.div>
          )}
          {hasActivities && (
            <motion.div
              key="activities"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden border-t border-nexus-border/20"
            >
              <ExecutionActivity
                items={message.activities!}
                isStreaming={isStreaming}
              />
            </motion.div>
          )}
          {hasTools && (
            <motion.div
              key="tools"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              className="overflow-hidden border-t border-nexus-border/20"
            >
              <ToolCallTimeline calls={message.toolCalls!} sessionId={sessionId} />
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Live footer: phase + elapsed + tokens. */}
      <RunFooter message={message} />
    </div>
  );
}

export default memo(RunTimelineComponent);
