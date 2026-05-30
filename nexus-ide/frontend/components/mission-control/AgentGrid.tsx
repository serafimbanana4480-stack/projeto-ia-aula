"use client";

import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Pause,
  Play,
  XOctagon,
  Cpu,
  MemoryStick,
  Activity,
  Bot,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { useMissionStore, type AgentInstance } from "../../stores/missionStore";
import { interveneAgent } from "../../lib/api";

const statusConfig: Record<
  AgentInstance["status"],
  { label: string; border: string; bg: string; dot: string; text: string }
> = {
  running: {
    label: "Em execução",
    border: "border-green-500/30",
    bg: "bg-green-500/5",
    dot: "bg-green-400 animate-pulse",
    text: "text-green-400",
  },
  paused: {
    label: "Pausado",
    border: "border-yellow-500/30",
    bg: "bg-yellow-500/5",
    dot: "bg-yellow-400",
    text: "text-yellow-400",
  },
  failed: {
    label: "Falhou",
    border: "border-red-500/30",
    bg: "bg-red-500/5",
    dot: "bg-red-400",
    text: "text-red-400",
  },
  idle: {
    label: "Inativo",
    border: "border-gray-500/30",
    bg: "bg-gray-500/5",
    dot: "bg-gray-400",
    text: "text-gray-400",
  },
  completed: {
    label: "Concluído",
    border: "border-blue-500/30",
    bg: "bg-blue-500/5",
    dot: "bg-blue-400",
    text: "text-blue-400",
  },
};

function AgentTile({ agent }: { agent: AgentInstance }) {
  const [expanded, setExpanded] = useState(false);
  const [acting, setActing] = useState(false);
  const cfg = statusConfig[agent.status];

  async function handleAction(action: "pause" | "resume" | "abort") {
    setActing(true);
    try {
      await interveneAgent(agent.id, action);
      useMissionStore.getState().updateAgentStatus(agent.id, action === "abort" ? "failed" : action === "pause" ? "paused" : "running");
    } catch {
      /* ignore */
    } finally {
      setActing(false);
    }
  }

  return (
    <motion.div
      layout
      className={`rounded-lg border ${cfg.border} ${cfg.bg} p-3 transition-colors hover:brightness-110`}
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

      <div className="mt-2 flex items-center gap-3 text-[10px] text-nexus-muted">
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
        <span className="flex items-center gap-1">
          <Activity className="h-3 w-3" />
          {agent.tokens_used.toLocaleString()}
        </span>
      </div>

      <AnimatePresence>
        {expanded && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden"
          >
            <div className="mt-2 flex flex-wrap gap-1.5 border-t border-nexus-border/50 pt-2">
              {agent.status === "running" && (
                <button
                  onClick={() => handleAction("pause")}
                  disabled={acting}
                  className="flex items-center gap-1 rounded bg-yellow-500/10 px-2 py-1 text-[10px] text-yellow-400 hover:bg-yellow-500/20 disabled:opacity-50"
                >
                  <Pause className="h-3 w-3" />
                  Pausar
                </button>
              )}
              {agent.status === "paused" && (
                <button
                  onClick={() => handleAction("resume")}
                  disabled={acting}
                  className="flex items-center gap-1 rounded bg-green-500/10 px-2 py-1 text-[10px] text-green-400 hover:bg-green-500/20 disabled:opacity-50"
                >
                  <Play className="h-3 w-3" />
                  Retomar
                </button>
              )}
              {(agent.status === "running" || agent.status === "paused") && (
                <button
                  onClick={() => handleAction("abort")}
                  disabled={acting}
                  className="flex items-center gap-1 rounded bg-red-500/10 px-2 py-1 text-[10px] text-red-400 hover:bg-red-500/20 disabled:opacity-50"
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
}

export default function AgentGrid() {
  const agents = useMissionStore((s) => s.agents);
  const loading = useMissionStore((s) => s.loading);

  const statusOrder: AgentInstance["status"][] = ["running", "paused", "failed", "idle", "completed"];
  const sorted = [...agents].sort(
    (a, b) => statusOrder.indexOf(a.status) - statusOrder.indexOf(b.status)
  );

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
        <div className="flex items-center gap-2 text-[10px] text-nexus-muted">
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-green-400" />
            {agents.filter((a) => a.status === "running").length}
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-yellow-400" />
            {agents.filter((a) => a.status === "paused").length}
          </span>
          <span className="flex items-center gap-1">
            <span className="h-1.5 w-1.5 rounded-full bg-red-400" />
            {agents.filter((a) => a.status === "failed").length}
          </span>
        </div>
      </div>

      {loading && agents.length === 0 ? (
        <div className="flex h-32 items-center justify-center text-xs text-nexus-muted">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-nexus-accent2 border-t-transparent mr-2" />
          A carregar agentes...
        </div>
      ) : sorted.length === 0 ? (
        <div className="flex h-32 items-center justify-center text-xs text-nexus-muted">
          Nenhum agente registado
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3 max-h-[400px] overflow-y-auto thin-scrollbar pr-1">
          {sorted.map((agent) => (
            <AgentTile key={agent.id} agent={agent} />
          ))}
        </div>
      )}
    </div>
  );
}
