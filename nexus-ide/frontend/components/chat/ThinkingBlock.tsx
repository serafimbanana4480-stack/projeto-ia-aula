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

interface ThinkingBlockProps {
  content: string;
  isStreaming?: boolean;
  defaultOpen?: boolean;
  durationMs?: number;
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
      setOpen(true);
    } else if (startRef.current && now === null) {
      setNow(Date.now() - startRef.current);
    }
  }, [isStreaming, now]);

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

  // Word count + approximate reading time
  const words = content.trim().split(/\s+/).length;
  const chars = content.length;
  const readingSec = Math.max(1, Math.round(words / 200));
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
            {isStreaming ? "A pensar" : "Pensamento"}
          </span>
        </span>

        {/* Word/chars counter */}
        <span className="hidden text-[10px] text-sky-300/50 sm:inline">
          {words} palavras · {chars} chars
        </span>

        {/* Duration */}
        <span className="ml-auto flex items-center gap-1 text-[10px] text-sky-300/60">
          {isStreaming ? (
            <Loader2 className="h-2.5 w-2.5 animate-spin" />
          ) : (
            <Clock className="h-2.5 w-2.5" />
          )}
          {isStreaming ? `${totalSec}s` : `${Math.max(readingSec, totalSec)}s`}
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

              <pre className="whitespace-pre-wrap break-words px-4 py-2.5 pl-5 font-mono text-[11.5px] leading-relaxed text-sky-100/80 thin-scrollbar">
                {content}
                {isStreaming && (
                  <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-sky-300/80" />
                )}
              </pre>

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
