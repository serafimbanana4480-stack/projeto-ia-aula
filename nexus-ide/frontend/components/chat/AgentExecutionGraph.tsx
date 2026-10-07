"use client";

import { useState } from "react";
import { ArrowRight } from "lucide-react";
import type { ExecutionGraph, ExecutionGraphNode } from "../../lib/executionGraph";

const STATUS_LABELS: Record<ExecutionGraphNode["status"], string> = {
  pending: "Pendente",
  running: "A executar",
  success: "Concluído",
  error: "Falhou",
  warning: "Aviso",
  cancelled: "Cancelado",
  paused: "Em pausa",
};

function formatDuration(durationMs?: number): string | undefined {
  if (durationMs === undefined) return undefined;
  if (durationMs < 1000) return `${Math.round(durationMs)} ms`;
  return `${(durationMs / 1000).toFixed(1)} s`;
}

export default function AgentExecutionGraph({ graph }: { graph: ExecutionGraph }) {
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const selected = graph.nodes.find((node) => node.taskId === selectedTaskId);
  const nodesById = new Map(graph.nodes.map((node) => [node.taskId, node]));
  const selectedDependencies = selected?.dependsOn.map(
    (taskId) => nodesById.get(taskId)?.agent ?? taskId,
  ) ?? [];

  return (
    <section
      aria-label="Grafo de execução"
      data-testid="execution-graph"
      className="border-t border-nexus-border/20 px-3 py-3"
    >
      <p className="mb-3 text-[10px] leading-5 text-nexus-muted">
        As ligações representam dependências de tarefas reportadas pelo scheduler. Não representam relações pai-filho entre agentes.
      </p>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_240px]">
        <div className="space-y-3">
          <div className="grid gap-2 sm:grid-cols-2">
            {graph.nodes.map((node) => (
              <button
                key={node.taskId}
                type="button"
                data-testid="execution-graph-node"
                aria-pressed={selectedTaskId === node.taskId}
                onClick={() => setSelectedTaskId(node.taskId)}
                className={`min-w-0 rounded-lg border px-3 py-2 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/60 ${
                  selectedTaskId === node.taskId
                    ? "border-nexus-accent/50 bg-nexus-accent/10"
                    : "border-nexus-border/30 bg-nexus-bg/30 hover:bg-nexus-card/50"
                }`}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="truncate text-xs font-semibold text-nexus-text">{node.agent}</span>
                  <span className="shrink-0 text-[10px] text-nexus-muted">{STATUS_LABELS[node.status]}</span>
                </span>
                <span className="mt-1 block break-words text-[11px] leading-5 text-nexus-muted">
                  {node.objective || "Objetivo não informado pelo runtime"}
                </span>
                <span className="mt-1 block truncate font-mono text-[9px] text-nexus-muted/70">
                  {node.taskId}
                </span>
              </button>
            ))}
          </div>

          {graph.edges.length > 0 ? (
            <div aria-label="Dependências reportadas" className="space-y-1.5">
              <h4 className="text-[10px] font-semibold uppercase tracking-wide text-nexus-muted/70">
                Dependências reportadas
              </h4>
              {graph.edges.map((edge) => {
                const source = nodesById.get(edge.fromTaskId)!;
                const target = nodesById.get(edge.toTaskId)!;
                return (
                  <div
                    key={`${edge.fromTaskId}-${edge.toTaskId}`}
                    data-testid="execution-graph-edge"
                    aria-label={`${target.agent} depende de ${source.agent}`}
                    className="flex min-w-0 items-center gap-2 rounded-md bg-nexus-bg/25 px-2 py-1.5 text-[10px]"
                  >
                    <span className="truncate text-nexus-text/80">{source.agent}</span>
                    <ArrowRight className="h-3 w-3 shrink-0 text-nexus-accent" aria-hidden="true" />
                    <span className="min-w-0 truncate text-nexus-text/80">{target.agent}</span>
                    <span className="ml-auto shrink-0 text-nexus-muted">depende de</span>
                  </div>
                );
              })}
            </div>
          ) : graph.unresolvedDependencies.length === 0 ? (
            <p className="rounded-md bg-nexus-bg/25 px-2 py-2 text-[10px] text-nexus-muted">
              O runtime não reportou dependências entre estas tarefas.
            </p>
          ) : null}

          {graph.unresolvedDependencies.length > 0 && (
            <p role="status" className="text-[10px] text-amber-300/90">
              {graph.unresolvedDependencies.length} dependência(s) recebida(s) sem a tarefa correspondente neste stream; não foi desenhada ligação.
            </p>
          )}
        </div>

        <aside
          aria-label="Inspector da tarefa"
          data-testid="execution-graph-inspector"
          className="min-h-28 rounded-lg border border-nexus-border/25 bg-nexus-bg/25 p-3"
        >
          {selected ? (
            <>
              <h4 className="mb-2 text-xs font-semibold text-nexus-text">{selected.agent}</h4>
              <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-[10px]">
                <dt className="text-nexus-muted">Estado</dt>
                <dd className="text-nexus-text/80">{STATUS_LABELS[selected.status]}</dd>
                <dt className="text-nexus-muted">Tarefa</dt>
                <dd className="break-words text-nexus-text/80">{selected.objective || "Não informada"}</dd>
                <dt className="text-nexus-muted">ID</dt>
                <dd className="break-all font-mono text-nexus-text/80">{selected.taskId}</dd>
                {selected.model && <><dt className="text-nexus-muted">Modelo</dt><dd className="text-nexus-text/80">{selected.model}</dd></>}
                {formatDuration(selected.durationMs) && <><dt className="text-nexus-muted">Duração</dt><dd className="text-nexus-text/80">{formatDuration(selected.durationMs)}</dd></>}
                {selectedDependencies.length > 0 && <><dt className="text-nexus-muted">Depende de</dt><dd className="break-words text-nexus-text/80">{selectedDependencies.join(", ")}</dd></>}
                {selected.error && <><dt className="text-nexus-muted">Erro</dt><dd className="break-words text-rose-300">{selected.error}</dd></>}
              </dl>
              <p className="mt-2 text-[9px] text-nexus-muted/70">Atualização recebida: {selected.timestamp}</p>
            </>
          ) : (
            <p className="text-[10px] leading-5 text-nexus-muted">Seleciona uma tarefa para inspecionar os campos reportados.</p>
          )}
        </aside>
      </div>
    </section>
  );
}
