"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronDown,
  Brain,
  Sparkles,
  Copy,
  Check,
  X,
  Loader2,
  Clock,
} from "lucide-react";
import { operationalSummaryForThinking, summarizeApproachContent } from "../../lib/chatPresentation";

interface ThinkingBlockProps {
  content: string;
  isStreaming?: boolean;
  defaultOpen?: boolean;
  /** Real elapsed milliseconds for the completed reasoning block. */
  durationMs?: number;
  /** Epoch ms the block started, used for the live timer after a remount. */
  startedAt?: number;
}

export interface PlanTask {
  name: string;
  description: string;
  agent?: string;
  priority?: string;
  dependencies?: number[];
}

/** Turns a planner JSON payload into a display-friendly task list. */
export function extractStructuredPlan(content: string): PlanTask[] | null {
  const start = content.indexOf("[");
  const end = content.lastIndexOf("]");
  if (start < 0 || end <= start) return null;

  try {
    const parsed: unknown = JSON.parse(content.slice(start, end + 1));
    if (!Array.isArray(parsed) || parsed.length === 0) return null;

    const tasks = parsed
      .filter((item): item is Record<string, unknown> =>
        Boolean(item) && typeof item === "object" && !Array.isArray(item),
      )
      .map((item) => ({
        name: typeof item.name === "string" ? item.name : "Tarefa sem nome",
        description: typeof item.description === "string" ? item.description : "",
        agent: typeof item.agent === "string" ? item.agent : undefined,
        priority: typeof item.priority === "string" ? item.priority : undefined,
        dependencies: Array.isArray(item.depends_on)
          ? item.depends_on.filter((dependency): dependency is number => typeof dependency === "number")
          : undefined,
      }));

    return tasks.some((task) => task.description || task.agent) ? tasks : null;
  } catch {
    return null;
  }
}

function priorityClass(priority?: string) {
  switch (priority?.toLowerCase()) {
    case "high":
    case "alta":
      return "border-rose-400/30 bg-rose-400/10 text-rose-200";
    case "medium":
    case "media":
    case "média":
      return "border-amber-400/30 bg-amber-400/10 text-amber-100";
    default:
      return "border-sky-400/25 bg-sky-400/10 text-sky-100";
  }
}

/**
 * Displays a `<thinking>...</thinking>` block extracted from an agent
 * response. Used by the chat, the swarm panel and the dashboard.
 *
 * Design inspired by Cursor and Claude Code:
 *  - Inline, compact by default
 *  - Blue/cyan accent gradient
 *  - Pulsing dot while streaming
 *  - Duration badge when done
 *  - Copy + close + auto-collapse controls
 */
export default function ThinkingBlock({
  content,
  isStreaming = false,
  defaultOpen = false,
  durationMs,
  startedAt,
}: ThinkingBlockProps) {
  const [open, setOpen] = useState(defaultOpen || isStreaming);
  const [copied, setCopied] = useState(false);
  const [now, setNow] = useState<number | null>(null);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (isStreaming) {
      // A remount mid-run must not restart the clock at zero: the block
      // already started, and `startedAt` says when.
      startRef.current = startedAt ?? Date.now();
      setNow(null);
      setOpen(true);
    } else if (startRef.current !== null) {
      setNow(Date.now() - startRef.current);
    }
  }, [isStreaming, startedAt]);

  useEffect(() => {
    if (!isStreaming || now !== null) return;
    const t = setInterval(() => {
      if (startRef.current) {
        setNow(Date.now() - startRef.current);
      }
    }, 100);
    return () => clearInterval(t);
  }, [isStreaming, now]);

  const toggle = useCallback(() => setOpen((o) => !o), []);

  const onCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  }, [content]);

  if (!content || !content.trim()) return null;

  const plan = extractStructuredPlan(content);
  const visibleContent = plan ? content : summarizeApproachContent(content);
  // Operational one-liner for the collapsed header (Activity level).
  // The full reasoning wall stays behind the toggle (Detail level).
  const operational = plan
    ? `Planeando ${plan.length} tarefa${plan.length === 1 ? "" : "s"}…`
    : operationalSummaryForThinking(content);
  if (!plan && !visibleContent) return null;
  // ``durationMs`` used to be destructured into ``_durationMs`` and thrown away,
  // so a completed block always read "concluído" no matter how long the model
  // actually thought. It is now the primary source; the local clock is the
  // fallback for a block that is still streaming.
  const elapsedMs = isStreaming
    ? (now ?? 0)
    : (durationMs ?? (now !== null ? now : undefined));
  const totalSec = typeof elapsedMs === "number" ? Math.round(elapsedMs / 1000) : 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      className="my-2 overflow-hidden rounded-xl border border-nexus-accent/15 bg-nexus-accent/[0.035]"
    >
      <button
        onClick={toggle}
        aria-expanded={open}
        aria-controls="thinking-block-body"
        className="group flex w-full items-center gap-2.5 px-3.5 py-2.5 text-left text-[12px] font-medium text-nexus-text transition-colors hover:bg-nexus-accent/5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-nexus-accent/50"
      >
        {/* Discreet operational dot: ◉ pulses while streaming, Brain when done */}
        <span className="relative flex h-4 w-4 shrink-0 items-center justify-center">
          {isStreaming ? (
            <span aria-hidden="true" className="animate-pulse text-[13px] leading-none text-nexus-accent">
              ◉
            </span>
          ) : (
            <Brain className="h-3.5 w-3.5 text-nexus-accent" />
          )}
        </span>

        <span className="flex min-w-0 items-center gap-1.5">
          <Sparkles className="hidden h-3 w-3 shrink-0 text-nexus-accent/70 sm:block" />
          <span className="truncate text-[11px] font-medium text-nexus-text">
            {plan ? "Plano de execução" : isStreaming ? "A definir a abordagem" : "Resumo da abordagem"}
          </span>
          <span
            data-testid="thinking-operational"
            className="hidden truncate text-[11px] font-normal normal-case tracking-normal text-nexus-muted sm:block"
            title={operational}
          >
            · {operational}
          </span>
        </span>

        {/* Word/chars counter */}
        {plan && (
          <span className="hidden text-[10px] text-sky-300/50 sm:inline">
            {plan.length} tarefas
          </span>
        )}
        {/* Duration */}
        <span className="ml-auto flex shrink-0 items-center gap-1 text-[10px] tabular-nums text-nexus-muted">
          {isStreaming ? (
            <Loader2 className="h-2.5 w-2.5 animate-spin" />
          ) : (
            <Clock className="h-2.5 w-2.5" />
          )}
          {isStreaming || totalSec > 0 ? `${totalSec}s` : "concluído"}
        </span>

        <ChevronDown
          className={`h-3 w-3 shrink-0 text-nexus-muted transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            id="thinking-block-body"
            data-testid="thinking-block-body"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.16, ease: "easeOut" }}
            className="overflow-hidden border-t border-nexus-accent/10 [content-visibility:auto]"
          >
            <div className="relative">
              {/* Subtle left blue accent line */}
              <div className="absolute left-0 top-0 h-full w-0.5 bg-gradient-to-b from-nexus-accent/40 to-transparent" />

              {plan ? (
                <ol className="space-y-2 px-4 py-3 pl-5" aria-label="Tarefas do plano">
                  {plan.map((task, index) => (
                    <li
                      key={`${task.name}-${index}`}
                      className="rounded-lg border border-nexus-border/60 bg-nexus-bg/30 px-3 py-2.5"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-nexus-accent/10 text-[10px] font-semibold text-nexus-accent">
                          {index + 1}
                        </span>
                        <span className="text-xs font-medium text-nexus-text">{task.name}</span>
                        {task.agent && (
                          <span className="rounded border border-violet-400/25 bg-violet-400/10 px-1.5 py-0.5 text-[9px] font-medium tracking-wide text-violet-200">
                            {task.agent}
                          </span>
                        )}
                        {task.priority && (
                          <span className={`rounded border px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide ${priorityClass(task.priority)}`}>
                            {task.priority}
                          </span>
                        )}
                      </div>
                      {task.description && (
                        <p className="mt-1.5 pl-7 text-[12px] leading-relaxed text-nexus-muted">
                          {task.description}
                        </p>
                      )}
                      {task.dependencies && task.dependencies.length > 0 && (
                        <p className="mt-1 pl-7 text-[10px] text-nexus-faint">
                          Depende das tarefas {task.dependencies.map((dependency) => dependency + 1).join(", ")}
                        </p>
                      )}
                    </li>
                  ))}
                </ol>
              ) : (
                <pre className="whitespace-pre-wrap break-words px-4 py-3 pl-5 font-mono text-[12px] leading-relaxed text-nexus-muted thin-scrollbar">
                  {visibleContent}
                  {isStreaming && (
                    <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-nexus-accent/80" />
                  )}
                </pre>
              )}

              {/* Footer with copy button */}
              <div className="flex items-center justify-end gap-1 border-t border-nexus-border/40 px-3 py-1.5">
                <button
                  onClick={onCopy}
                  className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-nexus-muted transition-colors hover:bg-nexus-accent/10 hover:text-nexus-text"
                  title="Copiar pensamento"
                >
                  {copied ? (
                    <>
                      <Check className="h-2.5 w-2.5" />
                      Copiado
                    </>
                  ) : (
                    <>
                      <Copy className="h-2.5 w-2.5" />
                      Copiar
                    </>
                  )}
                </button>
                <button
                  onClick={toggle}
                  className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-nexus-muted transition-colors hover:bg-nexus-accent/10 hover:text-nexus-text"
                  title="Fechar"
                >
                  <X className="h-2.5 w-2.5" />
                  Fechar
                </button>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}
