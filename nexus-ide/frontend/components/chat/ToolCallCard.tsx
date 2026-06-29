"use client";
import { useState, memo } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { stripAnsiCodes } from "../../lib/utils";
import {
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  XCircle,
  Play,
  Terminal,
  Clock,
  Code
} from "lucide-react";

interface ToolCallCardProps {
  toolName: string;
  args: Record<string, unknown>;
  status: "running" | "success" | "error";
  result?: unknown;
  error?: string;
  durationMs?: number;
}

function ToolCallCard({
  toolName,
  args,
  status,
  result,
  error,
  durationMs,
}: ToolCallCardProps) {
  const [expanded, setExpanded] = useState(false);

  const getStatusIcon = () => {
    switch (status) {
      case "running":
        return (
          <div className="relative flex h-5 w-5 items-center justify-center">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-nexus-accent/40 opacity-75"></span>
            <span className="relative flex h-3 w-3 items-center justify-center rounded-full bg-nexus-accent">
              <Play className="h-2 w-2 fill-white text-white translate-x-[0.5px]" />
            </span>
          </div>
        );
      case "success":
        return <CheckCircle2 className="h-5 w-5 text-emerald-500 drop-shadow-[0_0_8px_rgba(16,185,129,0.3)]" />;
      case "error":
        return <XCircle className="h-5 w-5 text-rose-500 drop-shadow-[0_0_8px_rgba(244,63,94,0.3)]" />;
    }
  };

  const getStatusStyle = () => {
    switch (status) {
      case "running":
        return "border-nexus-accent/30 bg-gradient-to-r from-nexus-accent/10 via-nexus-accent/5 to-transparent shadow-[inset_0_1px_1px_rgba(255,255,255,0.05)]";
      case "success":
        return "border-emerald-500/20 bg-gradient-to-r from-emerald-500/5 via-emerald-500/2 to-transparent";
      case "error":
        return "border-rose-500/20 bg-gradient-to-r from-rose-500/5 via-rose-500/2 to-transparent";
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className={`mb-3 overflow-hidden rounded-xl border p-3.5 backdrop-blur-md transition-all duration-300 hover:shadow-lg ${getStatusStyle()}`}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center justify-between gap-3 text-left focus:outline-none"
      >
        <div className="flex items-center gap-3">
          {getStatusIcon()}
          <div className="flex flex-col gap-0.5">
            <span className="text-xs font-semibold tracking-wide text-nexus-text uppercase flex items-center gap-1.5">
              <Terminal className="h-3 w-3 text-nexus-muted" />
              {toolName}
            </span>
            <div className="flex items-center gap-2">
              <span className="text-[10px] uppercase font-bold text-nexus-muted px-1.5 py-0.5 rounded bg-nexus-bg/50">
                Executando ferramenta
              </span>
              {durationMs !== undefined && (
                <span className="text-[10px] text-nexus-muted flex items-center gap-1">
                  <Clock className="h-2.5 w-2.5" />
                  {durationMs}ms
                </span>
              )}
            </div>
          </div>
        </div>
        <motion.div 
          className="flex h-6 w-6 items-center justify-center rounded-full bg-nexus-bg/40 text-nexus-muted"
          whileHover={{ scale: 1.05, backgroundColor: "rgba(255,255,255,0.05)" }}
        >
          {expanded ? (
            <ChevronUp className="h-3.5 w-3.5" />
          ) : (
            <ChevronDown className="h-3.5 w-3.5" />
          )}
        </motion.div>
      </button>

      <AnimatePresence initial={false}>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: "easeInOut" }}
            className="mt-3 overflow-hidden border-t border-nexus-border/30 pt-3"
          >
            <div className="mb-3">
              <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-nexus-muted">
                <Code className="h-3 w-3" />
                Parâmetros (Arguments)
              </div>
              <pre className="mt-1.5 max-h-48 overflow-y-auto rounded-lg bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-nexus-muted scrollbar-thin scrollbar-thumb-nexus-border border border-nexus-border/30 shadow-inner">
                {JSON.stringify(args, null, 2)}
              </pre>
            </div>

            {status === "success" && result != null && (
              <div>
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wider text-nexus-muted">
                  <CheckCircle2 className="h-3 w-3 text-emerald-500" />
                  Resultado (Output)
                </div>
                <pre className="mt-1.5 max-h-60 overflow-y-auto rounded-lg bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-nexus-muted scrollbar-thin scrollbar-thumb-nexus-border border border-nexus-border/30 shadow-inner">
                  {typeof result === "string"
                    ? stripAnsiCodes(result)
                    : JSON.stringify(result, null, 2)}
                </pre>
              </div>
            )}

            {status === "error" && error && (
              <div className="rounded-lg border border-rose-500/20 bg-rose-500/5 p-3 text-xs leading-relaxed text-rose-400">
                <div className="font-semibold uppercase tracking-wider text-[10px] mb-1">Erro de Execução:</div>
                <pre className="font-mono text-[11px] whitespace-pre-wrap">{stripAnsiCodes(error)}</pre>
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
}

export default memo(ToolCallCard);
