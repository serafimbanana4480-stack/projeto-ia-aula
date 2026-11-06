"use client";

import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Pause,
  Play,
  XOctagon,
  Cpu,
  MemoryStick,
  Bot,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { useMissionStore, type AgentInstance } from "../../stores/missionStore";
import { interveneAgent } from "../../lib/api";

/**
 * Agent status vocabulary. Token-anchored so the tiles follow the theme, and
 * consistent with the tone used by `ActiveMissionsPanel` — the two panels sit
 * side by side on the same page and previously painted "em execução" green on
 * one and violet on the other.
 */
const statusConfig: Record<
  AgentInstance["status"],
  { label: string; border: string; bg: string; dot: string; text: string }
> = {
  pending: {
    label: "Pendente",
    border: "border-nexus-faint/30",
    bg: "bg-nexus-faint/5",
    dot: "bg-nexus-faint",
    text: "text-nexus-muted",
  },
  running: {
    label: "Em execução",
    border: "border-nexus-accent/30",
    bg: "bg-nexus-accent/5",
    dot: "bg-nexus-accent animate-pulse",
    text: "text-nexus-accent-bright",
  },
  paused: {
    label: "Pausado",
    border: "border-nexus-accent3/30",
    bg: "bg-nexus-accent3/5",
    dot: "bg-nexus-accent3",
    text: "text-nexus-accent3",
  },
  failed: {
    label: "Falhou",
    border: "border-nexus-accent4/30",
    bg: "bg-nexus-accent4/5",
    dot: "bg-nexus-accent4",
    text: "text-nexus-accent4",
  },
  idle: {
    label: "Inativo",
    border: "border-nexus-faint/30",
    bg: "bg-nexus-faint/5",
    dot: "bg-nexus-faint",
    text: "text-nexus-muted",
  },
  completed: {
    label: "Concluído",
    border: "border-nexus-accent2/30",
    bg: "bg-nexus-accent2/5",
    dot: "bg-nexus-accent2",
    text: "text-nexus-accent2",
  },
  aborted: {
    label: "Parado",
    border: "border-nexus-faint/30",
    bg: "bg-nexus-faint/5",
    dot: "bg-nexus-faint",
    text: "text-nexus-muted",
  },
};

/** Sort order. `aborted` must be listed: an absent key made `indexOf` return
 *  -1, so stopped agents sorted ABOVE the running ones. */
const STATUS_ORDER: AgentInstance["status"][] = [
  "running",
  "paused",
  "pending",
  "idle",
  "completed",
  "failed",
  "aborted",
];

const AgentTile = React.memo(function AgentTile({ agent }: { agent: AgentInstance }) {
  const [expanded, setExpanded] = useState(false);
  const [acting, setActing] = useState(false);
  const cfg = statusConfig[agent.status];

  const [actionError, setActionError] = useState<string | null>(null);

  async function handleAction(action: "pause" | "resume" | "abort") {
    setActing(true);
    setActionError(null);
    try {
      await interveneAgent(agent.id, action);
      useMissionStore.getState().updateAgentStatus(agent.id, action === "abort" ? "aborted" : action === "pause" ? "paused" : "running");
    } catch {
      // Swallowing the error made a failed intervention look identical to a
      // successful one: the row simply never changed.
      setActionError("A ação não foi aplicada. Verifica a ligação e tenta novamente.");
    } finally {
      setActing(false);
    }
  }

  return (
    <motion.div
      layout
      className={`rounded-lg border ${cfg.border} ${cfg.bg} p-3 transition-colors hover:border-nexus-accent/30`}
    >
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <Bot className="h-4 w-4 shrink-0 text-nexus-muted" />
          <div className="min-w-0">
            <div className="truncate text-xs font-semibold">{agent.name}</div>
            <div className="mt-0.5 flex items-center gap-1.5 text-[10px]">
              <span className={`h-1.5 w-1.5 rounded-full ${cfg.dot}`} />
              <span className={cfg.text}>{cfg.label}</span>
            </div>
          </div>
        </div>
        <button
          onClick={() => setExpanded(!expanded)}
          className="rounded p-1 text-nexus-muted hover:bg-nexus-card shrink-0 ml-2"
        >
          {expanded ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </button>
      </div>

      {agent.current_task && (
        <div className="mt-2 truncate text-[10px] text-nexus-muted">
          {agent.current_task}
        </div>
      )}

      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] text-nexus-muted">
        {agent.cpu_percent !== undefined && (
          <span className="flex items-center gap-1">
            <Cpu className="h-3 w-3" />
            {agent.cpu_percent.toFixed(1)}%
          </span>
        )}
        {agent.memory_mb !== undefined && (
          <span className="flex items-center gap-1">
            <MemoryStick className="h-3 w-3" />
            {agent.memory_mb.toFixed(0)} MB
          </span>
        )}
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            {actionError && (
              <p role="alert" className="mt-2 text-[10px] text-nexus-accent4">
                {actionError}
              </p>
            )}
            <div className="mt-2 flex flex-wrap gap-1.5 border-t border-nexus-border/50 pt-2">
              {agent.status === "running" && (
                <button
                  onClick={() => handleAction("pause")}
                  disabled={acting}
                  className="flex items-center gap-1 rounded bg-nexus-accent3/10 px-2 py-1 text-[10px] text-nexus-accent3 hover:bg-nexus-accent3/20 disabled:opacity-50"
                >
                  <Pause className="h-3 w-3" />
                  Pausar
                </button>
              )}
              {agent.status === "paused" && (
                <button
                  onClick={() => handleAction("resume")}
                  disabled={acting}
                  className="flex items-center gap-1 rounded bg-nexus-accent2/10 px-2 py-1 text-[10px] text-nexus-accent2 hover:bg-nexus-accent2/20 disabled:opacity-50"
                >
                  <Play className="h-3 w-3" />
                  Retomar
                </button>
              )}
              {(agent.status === "running" || agent.status === "paused") && (
                <button
                  onClick={() => handleAction("abort")}
                  disabled={acting}
                  className="flex items-center gap-1 rounded bg-nexus-accent4/10 px-2 py-1 text-[10px] text-nexus-accent4 hover:bg-nexus-accent4/20 disabled:opacity-50"
                >
                  <XOctagon className="h-3 w-3" />
                  Abortar
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
});

const AgentGrid = React.memo(function AgentGrid() {
  const agents = useMissionStore((s) => s.agents);
  const loading = useMissionStore((s) => s.loading);

  // Total comparator: equal statuses fall back to name so the grid does not
  // reshuffle on every 30s poll, and unknown statuses sort last rather than -1.
  const sorted = [...agents].sort((a, b) => {
    const rank = (status: AgentInstance["status"]) => {
      const i = STATUS_ORDER.indexOf(status);
      return i === -1 ? STATUS_ORDER.length : i;
    };
    return rank(a.status) - rank(b.status) || a.name.localeCompare(b.name);
  });

  return (
    <div className="rounded-lg border border-nexus-border bg-nexus-panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Bot className="h-4 w-4 text-nexus-accent2" />
          <span className="text-sm font-semibold">Agentes</span>
          <span className="rounded bg-nexus-accent2/10 px-1.5 py-0.5 text-[10px] text-nexus-accent2">
            {agents.length} total
          </span>
        </div>
        {/* Counts spelled out, not three bare numbers next to coloured dots. */}
        <div className="flex flex-wrap items-center gap-2 text-[10px] text-nexus-muted">
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-nexus-accent" aria-hidden="true" />
            {agents.filter((a) => a.status === "running").length} em execução
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-nexus-accent3" aria-hidden="true" />
            {agents.filter((a) => a.status === "paused").length} pausados
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-nexus-accent4" aria-hidden="true" />
            {agents.filter((a) => a.status === "failed").length} falhados
          </span>
        </div>
      </div>

      {loading && agents.length === 0 ? (
        <div className="space-y-2">
          <div className="nx-shimmer h-6 rounded" />
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="nx-shimmer h-24 rounded" />
            ))}
          </div>
        </div>
      ) : sorted.length === 0 ? (
        <div className="flex h-32 items-center justify-center text-xs text-nexus-muted">
          Nenhum agente registado
        </div>
      ) : (
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 md:grid-cols-4 max-h-[400px] overflow-y-auto thin-scrollbar pr-1">
          {sorted.map((agent) => (
            <AgentTile key={agent.id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  );
});

export default AgentGrid;
