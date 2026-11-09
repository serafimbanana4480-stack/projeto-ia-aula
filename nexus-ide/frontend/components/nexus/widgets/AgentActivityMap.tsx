"use client";

import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  Bot,
  CircleAlert,
  LoaderCircle,
  Pause,
  CircleSlash,
  CircleCheck,
  CircleX,
  CircleDot,
  Brain,
  Wrench,
  Timer,
} from "lucide-react";
import { useAgentStore, type Agent } from "../../../stores/useAgentStore";

/**
 * Agent state vocabulary.
 *
 * Colour alone must never carry state: `running`, `executing` and `completed`
 * used to share one hue, and `blocked` vs `failed` differed by 4% luminance —
 * invisible to a red/green colour-blind user and to anyone glancing quickly.
 * Each state therefore gets its own silhouette as well as its own tone, and
 * the tone comes from the shared `--nx-*` tokens so it follows the theme.
 */
const STATUS_META: Record<
  string,
  { color: string; label: string; Icon: React.ElementType }
> = {
  idle: { color: "var(--nx-text-faint)", label: "Inativo", Icon: CircleDot },
  thinking: { color: "var(--nx-accent-bright)", label: "A pensar", Icon: Brain },
  planning: { color: "var(--nx-amber)", label: "A planear", Icon: CircleDot },
  executing: { color: "var(--nx-emerald)", label: "A executar", Icon: CircleDot },
  running: { color: "var(--nx-emerald)", label: "A executar", Icon: CircleDot },
  tool_call: { color: "var(--nx-cyan)", label: "A usar ferramenta", Icon: Wrench },
  waiting: { color: "var(--nx-text-faint)", label: "À espera", Icon: Timer },
  blocked: { color: "var(--nx-rose)", label: "Bloqueado", Icon: CircleSlash },
  failed: { color: "var(--nx-rose)", label: "Falhou", Icon: CircleX },
  autonomous_loop: { color: "var(--nx-accent)", label: "Ciclo autónomo", Icon: CircleDot },
  learning: { color: "var(--nx-accent-bright)", label: "A aprender", Icon: Brain },
  syncing_memory: { color: "var(--nx-cyan)", label: "A sincronizar memória", Icon: Wrench },
  paused: { color: "var(--nx-amber)", label: "Pausado", Icon: Pause },
  completed: { color: "var(--nx-emerald)", label: "Concluído", Icon: CircleCheck },
  aborted: { color: "var(--nx-text-faint)", label: "Interrompido", Icon: CircleSlash },
  unknown: { color: "var(--nx-text-faint)", label: "Estado desconhecido", Icon: CircleDot },
};

/** States where the agent is genuinely doing work (not "paused"/"waiting"). */
const ACTIVE_STATUSES = new Set([
  "thinking", "planning", "executing", "running", "tool_call",
  "autonomous_loop", "learning", "syncing_memory",
]);

const SPECIALISATION_LABELS_PT: Record<string, string> = {
  ROUTER: "Encaminhador",
  ARCHITECT: "Arquiteto",
  CODER: "Programador",
  REVIEWER: "Revisor",
  RESEARCHER: "Investigador",
  TESTER: "Testador",
  UNKNOWN: "Agente",
};

function AgentCard({ agent }: { agent: Agent }) {
  const status = agent.status.toLowerCase();
  const meta = STATUS_META[status] ?? STATUS_META.unknown;
  const isWorking = ACTIVE_STATUSES.has(status);
  const hasTokens = typeof agent.tokensUsed === "number" && Number.isFinite(agent.tokensUsed);
  const tokenText = hasTokens
    ? agent.tokenBudget !== undefined && Number.isFinite(agent.tokenBudget)
      ? `${agent.tokensUsed!.toLocaleString("pt-PT")} / ${agent.tokenBudget.toLocaleString("pt-PT")}`
      : agent.tokensUsed!.toLocaleString("pt-PT")
    : null;
  const role = SPECIALISATION_LABELS_PT[agent.role] ?? agent.role;

  return (
    <motion.article
      layout
      initial={{ opacity: 0, y: 5 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -5 }}
      className="nx-elev-1 rounded-nx p-3"
    >
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="flex min-w-0 items-center gap-2.5">
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border"
            style={{
              background: `color-mix(in srgb, ${agent.color} 12%, transparent)`,
              borderColor: `color-mix(in srgb, ${agent.color} 30%, transparent)`,
            }}
          >
            <Bot size={16} style={{ color: agent.color }} aria-hidden="true" />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-xs font-semibold text-nexus-text" title={agent.name || undefined}>
              {agent.name || "Nome indisponível"}
            </h3>
            <p className="mt-0.5 truncate text-[10px] text-nexus-faint">{role}</p>
          </div>
        </div>
        <span className="flex shrink-0 items-center gap-1.5 pt-1">
          <meta.Icon
            size={11}
            aria-hidden="true"
            style={{ color: meta.color }}
            className={isWorking ? "animate-pulse" : undefined}
          />
          <span
            className="max-w-[100px] truncate text-[10px] font-medium"
            style={{ color: meta.color }}
          >
            {meta.label}
          </span>
        </span>
      </div>

      {agent.currentTask && (
        <p className="mt-3 line-clamp-2 text-[10px] leading-relaxed text-nexus-muted" title={agent.currentTask}>
          {agent.currentTask}
        </p>
      )}

      {tokenText && (
        <div className="mt-3 flex items-center justify-between gap-3 border-t border-nexus-border pt-2">
          <span className="text-[9px] text-nexus-faint">Tokens usados</span>
          <span className="truncate font-mono text-[10px] tabular-nums text-nexus-muted" title={tokenText}>
            {tokenText}
          </span>
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

  return (
    <section className="flex h-full min-h-0 flex-col" aria-label="Agentes">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-nexus-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-2">
          <Bot size={15} className="shrink-0 text-nexus-accent" aria-hidden="true" />
          <h2 className="truncate text-xs font-semibold text-nexus-text">Agentes</h2>
        </div>
        {/* "0 em curso" while a fetch succeeded but returned nothing reads as
            "all idle" — say which of the two it actually is. */}
        <span
          className="rounded-full border border-nexus-border bg-nexus-bg/60 px-2 py-1 text-[10px] text-nexus-muted"
          role="status"
        >
          {!hasFetched || loading
            ? "A carregar…"
            : agents.length === 0
              ? "Sem agentes"
              : `${activeCount} em curso`}
        </span>
      </header>

      {error && agents.length > 0 && (
        <p role="status" className="border-b border-nexus-accent3/20 px-4 py-2 text-[10px] text-nexus-accent3">
          Não foi possível atualizar. A mostrar o último estado recebido.
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-4">
        {agents.length === 0 ? (
          <div className="flex h-full min-h-[170px] flex-col items-center justify-center gap-2 px-5 text-center text-nexus-faint">
            {loading ? (
              <LoaderCircle size={20} className="animate-spin" aria-hidden="true" />
            ) : error ? (
              <CircleAlert size={20} className="text-nexus-accent3" aria-hidden="true" />
            ) : (
              <Bot size={22} className="opacity-35" aria-hidden="true" />
            )}
            <p className="text-xs font-medium text-nexus-muted">
              {loading
                ? "A carregar agentes…"
                : error
                  ? "Não foi possível atualizar os agentes."
                  : hasFetched
                    ? "Ainda não há agentes ativos."
                    : "À espera de dados dos agentes."}
            </p>
            {!loading && !error && hasFetched && (
              <p className="max-w-xs text-[10px] leading-relaxed text-nexus-faint">
                Os agentes aparecem aqui assim que uma execução os iniciar.
              </p>
            )}
            {error && (
              <p className="max-w-xs text-[10px] leading-relaxed text-nexus-faint">
                O estado fica disponível quando a API voltar a responder.
              </p>
            )}
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
