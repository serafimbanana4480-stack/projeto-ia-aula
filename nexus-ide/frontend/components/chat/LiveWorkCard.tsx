"use client";

import { useMemo } from "react";
import { Clock, Loader2, Square, XCircle } from "lucide-react";

import type { ChatMessage } from "../../lib/types";
import { formatRunDuration } from "../../lib/chatPresentation";
import {
  buildAgentRoster,
  declaredPlanProgress,
  narrateLive,
} from "../../lib/plainNarration";
import { usePresentationStore } from "../../stores/presentationStore";
import { DetailLevelSwitch } from "./WorkNarration";

/**
 * Compact live region for work that is actually in progress.
 *
 * One sentence, the phase, and the agents this run started. A fraction is
 * shown only when the plan reported both a done count and a total.
 */

export interface LiveWorkCardProps {
  objective?: string;
  message: ChatMessage | null;
  elapsedMs?: number;
  onStop?: () => void;
  className?: string;
}

export default function LiveWorkCard({
  objective,
  message,
  elapsedMs,
  onStop,
  className = "",
}: LiveWorkCardProps) {
  const level = usePresentationStore((state) => state.level);
  const derived = useMemo(() => {
    const narration = narrateLive(message, true);
    const sentence = level === "technical" && narration.raw && narration.raw !== narration.sentence
      ? `${narration.sentence} · ${narration.raw}`
      : narration.sentence;
    const steps = message?.steps ?? [];
    const toolCalls = message?.toolCalls ?? [];
    // A tool failure can be present in both arrays, so adding the two counts
    // would report the same failure twice.
    const hasErrors = steps.some((step) => step.status === "error") ||
      toolCalls.some((call) => call.status === "error");
    return {
      sentence,
      phaseLabel: narration.phaseLabel,
      hasErrors,
      runningTools: toolCalls.filter((call) => call.status === "running").length,
      pendingApprovals: toolCalls.filter((call) => call.status === "awaiting_confirmation").length,
      roster: buildAgentRoster(message),
      progress: declaredPlanProgress(message?.activities),
    };
  }, [message, level]);

  return (
    <section
      data-testid="live-work-card"
      aria-label="Trabalho em curso"
      className={`nx-work-surface rounded-2xl border border-nexus-accent/20 px-4 py-4 ${className}`}
    >
      <div className="flex items-start gap-2.5">
        <span className="mt-1.5 inline-block h-2 w-2 shrink-0 rounded-full bg-nexus-accent" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <h2 className="text-[13px] font-medium text-nexus-text">NEXUS está a trabalhar</h2>
            <span className="text-[11px] text-nexus-faint" data-testid="live-work-state">
              {derived.phaseLabel}
            </span>
            {elapsedMs !== undefined && elapsedMs > 0 ? (
              <span className="inline-flex items-center gap-1 text-[11px] text-nexus-faint">
                <Clock className="h-3 w-3" aria-hidden="true" />
                {formatRunDuration(elapsedMs)}
              </span>
            ) : null}
          </div>
          {objective ? (
            <p className="mt-0.5 truncate text-[12px] text-nexus-muted" title={objective}>
              {objective}
            </p>
          ) : null}
        </div>
        {onStop ? (
          <button
            type="button"
            onClick={onStop}
            className="inline-flex min-h-9 shrink-0 items-center gap-1.5 rounded-lg border border-nexus-border px-3 text-[12px] text-nexus-muted hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
          >
            <Square className="h-3 w-3" />
            Parar
          </button>
        ) : null}
      </div>

      <p className="mt-3 rounded-xl border border-nexus-border/50 bg-nexus-bg/40 px-3 py-2.5 text-[13px] leading-5 text-nexus-text" data-testid="live-work-current" aria-live="polite">
        {derived.sentence}
      </p>

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-nexus-muted">
        {derived.progress ? (
          <span data-testid="live-work-progress">
            {derived.progress.done} de {derived.progress.total}
          </span>
        ) : null}
        {derived.roster.length > 0 ? (
          <span data-testid="live-work-agents">
            Equipa de agentes — {derived.roster.length}
            {derived.roster.some((entry) => entry.status === "running")
              ? ` · ${derived.roster.filter((entry) => entry.status === "running").map((entry) => entry.role).join(", ")}`
              : ""}
          </span>
        ) : null}
        {derived.runningTools > 0 ? (
          <span>{derived.runningTools} {derived.runningTools === 1 ? "ferramenta em execução" : "ferramentas em execução"}</span>
        ) : null}
        {derived.pendingApprovals > 0 ? (
          <span className="text-nexus-accent3">{derived.pendingApprovals} {derived.pendingApprovals === 1 ? "aprovação pendente" : "aprovações pendentes"}</span>
        ) : null}
        {derived.hasErrors ? (
          <span className="inline-flex items-center gap-1 text-nexus-accent4">
            <XCircle className="h-3 w-3" aria-hidden="true" />
            Problemas reportados
          </span>
        ) : null}
        <Loader2 className="h-3 w-3 animate-spin text-nexus-faint motion-reduce:animate-none" aria-hidden="true" />
      </div>

      <div className="mt-2">
        <DetailLevelSwitch />
      </div>
    </section>
  );
}
