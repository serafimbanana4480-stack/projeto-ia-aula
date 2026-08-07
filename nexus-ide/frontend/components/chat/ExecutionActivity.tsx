"use client";

import { memo, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  Bot,
  Check,
  ChevronDown,
  CircleDashed,
  ListChecks,
  Loader2,
  ShieldCheck,
  XCircle,
} from "lucide-react";
import type { ActivityItem } from "../../lib/types";

function statusIcon(status: ActivityItem["status"]) {
  if (status === "running") return <Loader2 className="h-3.5 w-3.5 animate-spin text-violet-300" />;
  if (status === "error") return <XCircle className="h-3.5 w-3.5 text-rose-400" />;
  if (status === "success") return <Check className="h-3.5 w-3.5 text-emerald-400" />;
  return <CircleDashed className="h-3.5 w-3.5 text-nexus-muted" />;
}

function kindIcon(kind: ActivityItem["kind"]) {
  if (kind === "agent") return Bot;
  if (kind === "plan") return ListChecks;
  if (kind === "verification") return ShieldCheck;
  return CircleDashed;
}

function ExecutionActivity({
  items,
  isStreaming = false,
}: {
  items: ActivityItem[];
  isStreaming?: boolean;
}) {
  const [open, setOpen] = useState(isStreaming);

  useEffect(() => {
    if (isStreaming) setOpen(true);
  }, [isStreaming]);

  const summary = useMemo(() => {
    const agents = new Set(items.map((item) => item.agent).filter(Boolean));
    const errors = items.filter((item) => item.status === "error").length;
    if (isStreaming) return "A executar";
    if (errors) return `${errors} problema${errors === 1 ? "" : "s"} durante a execução`;
    if (agents.size > 1) return `${agents.size} agentes colaboraram`;
    return "Trabalho concluído";
  }, [isStreaming, items]);

  if (items.length === 0) return null;

  return (
    <div className="my-2 overflow-hidden rounded-xl border border-violet-400/15 bg-violet-400/[0.025]">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-center gap-2.5 px-3 py-2 text-left hover:bg-violet-400/[0.04]"
        aria-expanded={open}
      >
        <span className="flex h-5 w-5 items-center justify-center rounded-md bg-violet-400/10">
          {isStreaming ? (
            <Loader2 className="h-3 w-3 animate-spin text-violet-300" />
          ) : (
            <Check className="h-3 w-3 text-emerald-400" />
          )}
        </span>
        <span className="text-[11px] font-semibold text-nexus-text">{summary}</span>
        <span className="text-[10px] text-nexus-muted">
          {items.length} atualização{items.length === 1 ? "" : "ões"}
        </span>
        <ChevronDown
          className={`ml-auto h-3.5 w-3.5 text-nexus-muted transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>

      <AnimatePresence initial={false}>
        {open && (
          <motion.ol
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden border-t border-violet-400/10 px-3 py-2"
          >
            {items.map((item, index) => {
              const Icon = kindIcon(item.kind);
              return (
                <li key={`${item.id}-${index}`} className="relative flex gap-2.5 py-1.5">
                  {index < items.length - 1 && (
                    <span className="absolute left-[7px] top-5 h-[calc(100%-8px)] w-px bg-nexus-border" />
                  )}
                  <span className="relative z-10 mt-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-nexus-card">
                    {item.status === "pending" ? <Icon className="h-3 w-3 text-nexus-muted" /> : statusIcon(item.status)}
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5">
                      <span className="text-[11px] font-medium text-nexus-text/90">{item.title}</span>
                      {item.agent && (
                        <span className="rounded bg-violet-400/8 px-1.5 py-0.5 text-[9px] font-medium text-violet-200/75">
                          {item.agent}
                        </span>
                      )}
                    </div>
                    {item.detail && item.detail !== item.title && (
                      <p className="mt-0.5 truncate text-[10px] text-nexus-muted" title={item.detail}>
                        {item.detail}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </motion.ol>
        )}
      </AnimatePresence>
    </div>
  );
}

export default memo(ExecutionActivity);
