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
import { summarizeApproachContent } from "../../lib/chatPresentation";

interface ThinkingBlockProps {
  content: string;
  isStreaming?: boolean;
  defaultOpen?: boolean;
  durationMs?: number;
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
  durationMs: _durationMs,
}: ThinkingBlockProps) {
  const [open, setOpen] = useState(defaultOpen || isStreaming);
  const [copied, setCopied] = useState(false);
  const [now, setNow] = useState<number | null>(null);
  const startRef = useRef<number | null>(null);

  useEffect(() => {
    if (isStreaming) {
      startRef.current = Date.now();
      setNow(null);
      setOpen(true);
    } else if (startRef.current !== null) {
      setNow(Date.now() - startRef.current);
    }
  }, [isStreaming]);

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
  if (!plan && !visibleContent) return null;
  const totalSec = now !== null ? Math.round(now / 1000) : 0;

  return (
    <motion.div
      initial={{ opacity: 0, y: -4 }}
      animate={{ opacity: 1, y: 0 }}
      className="my-2 overflow-hidden rounded-xl border border-sky-500/25 bg-gradient-to-br from-sky-500/[0.04] via-cyan-500/[0.03] to-blue-600/[0.05] shadow-sm shadow-sky-900/10"
    >
      <button
        onClick={toggle}
        className="group flex w-full items-center gap-2.5 px-3.5 py-2 text-left text-[12px] font-medium text-sky-200/90 transition-colors hover:bg-sky-500/5"
      >
        {/* Pulsing dot or finished icon */}
        <span className="relative flex h-4 w-4 shrink-0 items-center justify-center">
          {isStreaming ? (
            <>
              <span className="absolute inset-0 animate-ping rounded-full bg-sky-400/50" />
              <span className="relative h-2 w-2 rounded-full bg-sky-400 shadow-[0_0_8px_rgba(56,189,248,0.6)]" />
            </>
          ) : (
            <Brain className="h-3.5 w-3.5 text-sky-300" />
          )}
        </span>

        <span className="flex items-center gap-1.5">
          <Sparkles className="h-3 w-3 text-sky-300/70" />
          <span className="uppercase tracking-wider text-sky-100/90">
            {plan ? "Plano de execução" : isStreaming ? "A definir a abordagem" : "Resumo da abordagem"}
          </span>
        </span>

        {/* Word/chars counter */}
        {plan && (
          <span className="hidden text-[10px] text-sky-300/50 sm:inline">
            {plan.length} tarefas
          </span>
        )}
        {/* Duration */}
        <span className="ml-auto flex items-center gap-1 text-[10px] text-sky-300/60">
          {isStreaming ? (
            <Loader2 className="h-2.5 w-2.5 animate-spin" />
          ) : (
            <Clock className="h-2.5 w-2.5" />
          )}
          {isStreaming ? `${totalSec}s` : totalSec > 0 ? `${totalSec}s` : "concluído"}
        </span>

        <ChevronDown
          className={`h-3 w-3 text-sky-300/60 transition-transform ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            className="overflow-hidden border-t border-sky-500/15"
          >
            <div className="relative">
              {/* Subtle left blue accent line */}
              <div className="absolute left-0 top-0 h-full w-0.5 bg-gradient-to-b from-sky-400/40 via-cyan-400/30 to-transparent" />

              {plan ? (
                <ol className="space-y-2 px-4 py-3 pl-5" aria-label="Tarefas do plano">
                  {plan.map((task, index) => (
                    <li
                      key={`${task.name}-${index}`}
                      className="rounded-lg border border-sky-500/15 bg-slate-950/20 px-3 py-2.5"
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-sky-400/15 text-[10px] font-semibold text-sky-200">
                          {index + 1}
                        </span>
                        <span className="text-xs font-medium text-sky-50">{task.name}</span>
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
                        <p className="mt-1.5 pl-7 text-[11px] leading-relaxed text-sky-100/65">
                          {task.description}
                        </p>
                      )}
                      {task.dependencies && task.dependencies.length > 0 && (
                        <p className="mt-1 pl-7 text-[10px] text-sky-300/45">
                          Depende das tarefas {task.dependencies.map((dependency) => dependency + 1).join(", ")}
                        </p>
                      )}
                    </li>
                  ))}
                </ol>
              ) : (
                <pre className="whitespace-pre-wrap break-words px-4 py-2.5 pl-5 font-mono text-[11.5px] leading-relaxed text-sky-100/80 thin-scrollbar">
                  {visibleContent}
                  {isStreaming && (
                    <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-sky-300/80" />
                  )}
                </pre>
              )}

              {/* Footer with copy button */}
              <div className="flex items-center justify-end gap-1 border-t border-sky-500/10 bg-sky-500/[0.02] px-3 py-1">
                <button
                  onClick={onCopy}
                  className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-sky-300/70 transition-colors hover:bg-sky-500/10 hover:text-sky-200"
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
                  className="flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-sky-300/70 transition-colors hover:bg-sky-500/10 hover:text-sky-200"
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
