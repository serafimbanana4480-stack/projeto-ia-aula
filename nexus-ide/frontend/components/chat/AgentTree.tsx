"use client";

import { useMemo, type ReactNode } from "react";
import { deriveAgents, type AgentNode, type AgentRunState } from "../../lib/runLifecycle";
import { useChatTelemetryStore } from "../../stores/chatTelemetryStore";

const STATE_CLASS: Record<AgentRunState, string> = {
  QUEUED: "text-nexus-muted",
  RUNNING: "text-sky-300",
  WAITING: "text-amber-300",
  COMPLETED: "text-emerald-300",
  FAILED: "text-rose-300",
  CANCELLED: "text-nexus-muted",
};

function Row({ node, depth }: { node: AgentNode; depth: number }) {
  return (
    <li
      className={`rounded-md border border-white/8 bg-black/20 px-2.5 py-2 ${depth > 0 ? "border-l-2 border-l-white/15" : ""}`}
      style={{ marginLeft: depth * 14 }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-xs font-medium text-nexus-text">{node.name}</span>
        <span className={`font-mono text-[10px] ${STATE_CLASS[node.state]}`}>{node.state}</span>
      </div>
      {node.task && <p className="mt-1 line-clamp-2 text-[11px] text-nexus-muted">{node.task}</p>}
      <dl className="mt-1.5 space-y-0.5 text-[10px] text-nexus-faint">
        {node.model && (
          <div className="flex gap-2">
            <dt>Modelo</dt>
            <dd className="truncate font-mono text-nexus-muted">{node.model}</dd>
          </div>
        )}
        {node.tools.length > 0 && (
          <div className="flex gap-2">
            <dt>Tools</dt>
            <dd className="truncate font-mono text-nexus-muted">{node.tools.join(", ")}</dd>
          </div>
        )}
        {node.files.length > 0 && (
          <div className="flex gap-2">
            <dt>Ficheiros</dt>
            <dd className="truncate font-mono text-nexus-muted">{node.files.join(", ")}</dd>
          </div>
        )}
        {node.durationMs != null && node.durationMs >= 1 && (
          <div className="flex gap-2">
            <dt>Duração</dt>
            <dd className="font-mono text-nexus-muted">{node.durationMs} ms</dd>
          </div>
        )}
      </dl>
      {node.error && <p className="mt-1 text-[11px] text-rose-300">{node.error}</p>}
    </li>
  );
}

/** Agents that actually appeared in the live run. Nothing is invented. */
export default function AgentTree() {
  const events = useChatTelemetryStore((state) => state.events);
  const nodes = useMemo(() => deriveAgents(events), [events]);
  const childrenOf = (parentId?: string) =>
    nodes.filter((node) => (parentId ? node.parentId === parentId : !node.parentId));

  const renderBranch = (parentId: string | undefined, depth: number): ReactNode =>
    childrenOf(parentId).map((node) => (
      <div key={node.id} className="space-y-1.5">
        <Row node={node} depth={depth} />
        {renderBranch(node.id, depth + 1)}
      </div>
    ));

  return (
    <section aria-label="Agentes da execução" data-testid="agent-tree" className="rounded-xl border border-white/10 bg-nexus-panel/80 p-3">
      <header className="mb-2 flex items-baseline justify-between">
        <h2 className="text-[11px] font-semibold uppercase tracking-wider text-nexus-muted">Agentes</h2>
        <span className="font-mono text-[10px] text-nexus-faint">{nodes.length}</span>
      </header>
      {nodes.length === 0 ? (
        <p className="text-[12px] leading-relaxed text-nexus-muted">
          Nenhum agente foi executado nesta conversa. Quando um run arrancar, o estado aparece aqui.
        </p>
      ) : (
        <ul className="space-y-1.5">{renderBranch(undefined, 0)}</ul>
      )}
    </section>
  );
}
