"use client";

import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Bot, CircleAlert, LoaderCircle } from "lucide-react";
import { useAgentStore, type Agent } from "../../../stores/useAgentStore";

const STATUS_COLORS: Record<string, string> = {
  idle: "#64748b", thinking: "#a78bfa", planning: "#f59e0b",
  executing: "#10b981", running: "#10b981", tool_call: "#06b6d4",
  waiting: "#64748b", blocked: "#ef4444", failed: "#dc2626",
  autonomous_loop: "#7c3aed", learning: "#ec4899", syncing_memory: "#22d3ee",
  paused: "#f59e0b", completed: "#10b981", aborted: "#64748b", unknown: "#64748b",
};

const STATUS_LABELS: Record<string, string> = {
  idle: "Inativo", thinking: "A pensar", planning: "A planear",
  executing: "A executar", running: "A executar", tool_call: "A usar ferramenta",
  waiting: "À espera", blocked: "Bloqueado", failed: "Falhou",
  autonomous_loop: "Ciclo autónomo", learning: "A aprender", syncing_memory: "A sincronizar memória",
  paused: "Pausado", completed: "Concluído", aborted: "Interrompido", unknown: "Estado desconhecido",
};

const ACTIVE_STATUSES = new Set([
  "thinking", "planning", "executing", "running", "tool_call", "waiting",
  "autonomous_loop", "learning", "syncing_memory",
]);

function AgentCard({ agent }: { agent: Agent }) {
  const status = agent.status.toLowerCase();
  const statusColor = STATUS_COLORS[status] ?? STATUS_COLORS.unknown;
  const statusLabel = STATUS_LABELS[status] ?? "Estado desconhecido";
  const isActive = ACTIVE_STATUSES.has(status);
  const hasTokens = typeof agent.tokensUsed === "number" && Number.isFinite(agent.tokensUsed);
  const tokenText = hasTokens
    ? agent.tokenBudget !== undefined && Number.isFinite(agent.tokenBudget)
      ? `${agent.tokensUsed!.toLocaleString()} / ${agent.tokenBudget.toLocaleString()}`
      : agent.tokensUsed!.toLocaleString()
    : null;

  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -5 }}
      className="rounded-xl border border-slate-800/80 bg-slate-900/55 p-3 transition-colors hover:border-slate-700"
    >
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border"
            style={{ background: `${agent.color}20`, borderColor: `${agent.color}45` }}
          >
            <Bot size={16} style={{ color: agent.color }} />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-xs font-semibold text-slate-100" title={agent.name || undefined}>
              {agent.name || "Nome indisponível"}
            </h3>
            <p className="mt-0.5 truncate text-[10px] text-slate-500">{agent.role === "UNKNOWN" ? "Agente" : agent.role}</p>
          </div>
        </div>
        <span className="flex shrink-0 items-center gap-1.5 pt-1" title={statusLabel}>
          <span
            className={`h-1.5 w-1.5 rounded-full ${isActive ? "animate-pulse" : ""}`}
            style={{ background: statusColor }}
          />
          <span className="max-w-[100px] truncate text-[9px] font-medium" style={{ color: statusColor }}>
            {statusLabel}
          </span>
        </span>
      </div>

      {agent.currentTask && (
        <p className="mt-3 line-clamp-2 text-[10px] leading-relaxed text-slate-400" title={agent.currentTask}>
          {agent.currentTask}
        </p>
      )}

      {tokenText && (
        <div className="mt-3 flex items-center justify-between gap-3 border-t border-slate-800/70 pt-2">
          <span className="text-[9px] text-slate-500">Tokens usados</span>
          <span className="truncate font-mono text-[10px] tabular-nums text-slate-300" title={tokenText}>{tokenText}</span>
        </div>
      )}
    </motion.article>
  );
}

export default function AgentActivityMap() {
  const storedAgents = useAgentStore((state) => state.agents);
  const loading = useAgentStore((state) => state.isLoading);
  const hasFetched = useAgentStore((state) => state.hasFetchedAgents);
  const error = useAgentStore((state) => state.error);
  const agents = Object.values(storedAgents).filter((agent) => agent.id.trim() && agent.name.trim());
  const activeCount = agents.filter((agent) => ACTIVE_STATUSES.has(agent.status.toLowerCase())).length;
  const countLabel = agents.length > 0 || (hasFetched && !error) ? String(activeCount) : "—";

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Agentes">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800/70 px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <Bot size={15} className="shrink-0 text-violet-300" />
          <h2 className="truncate text-xs font-semibold text-slate-100">Agentes</h2>
        </div>
        <span className="rounded-full border border-slate-700/80 bg-slate-900/60 px-2 py-1 text-[10px] text-slate-400">
          {countLabel} em curso
        </span>
      </header>

      {error && agents.length > 0 && (
        <p role="status" className="border-b border-amber-500/20 px-4 py-2 text-[10px] text-amber-200">
          Não foi possível atualizar. A mostrar o último estado recebido.
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
        {agents.length === 0 ? (
          <div className="flex h-full min-h-[170px] flex-col items-center justify-center gap-2 px-5 text-center text-slate-500">
            {loading ? <LoaderCircle size={20} className="animate-spin" aria-label="A carregar agentes" /> : error ? <CircleAlert size={20} className="text-amber-400/70" /> : <Bot size={22} className="opacity-35" />}
            <p className="text-xs font-medium">
              {loading
                ? "A carregar agentes…"
                : error
                  ? "Não foi possível atualizar os agentes."
                  : hasFetched
                    ? "Ainda não há agentes ativos."
                    : "À espera de dados dos agentes."}
            </p>
            {error && <p className="max-w-xs text-[10px] leading-relaxed text-slate-600">O estado fica disponível quando a API voltar a responder.</p>}
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 2xl:grid-cols-3">
            <AnimatePresence mode="popLayout">
              {agents.map((agent) => <AgentCard key={agent.id} agent={agent} />)}
            </AnimatePresence>
          </div>
        )}
      </div>
    </section>
  );
}
