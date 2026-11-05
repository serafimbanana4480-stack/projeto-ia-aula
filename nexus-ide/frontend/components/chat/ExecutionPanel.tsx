"use client";

import { useMemo } from "react";
import { foldRun } from "../../lib/foldRun";
import { deriveExecution } from "../../lib/runLifecycle";
import { useChatTelemetryStore } from "../../stores/chatTelemetryStore";
import { useRunUiStore } from "../../stores/runUiStore";

const STATUS_PT: Record<string, string> = {
  running: "a correr",
  success: "feito",
  error: "falhou",
  awaiting_confirmation: "à espera",
  pending: "na fila",
  cancelled: "cancelado",
};

/** Goal, steps and blockers taken only from the current run's events. */
export default function ExecutionPanel() {
  const goal = useRunUiStore((state) => state.goal);
  const events = useChatTelemetryStore((state) => state.events);
  const snapshot = useMemo(() => {
    const folded = foldRun([], events, goal);
    return deriveExecution(goal, folded.messages);
  }, [events, goal]);

  const empty = !snapshot.goal && snapshot.steps.length === 0 && snapshot.blockers.length === 0;

  return (
    <section aria-label="Execução" data-testid="execution-panel" className="rounded-xl border border-white/10 bg-nexus-panel/80 p-3">
      <h2 className="text-[11px] font-semibold uppercase tracking-wider text-nexus-muted">Execução</h2>
      {empty ? (
        <p className="mt-2 text-[12px] leading-relaxed text-nexus-muted">
          Sem objetivo activo. Envia uma mensagem para ver o plano, os passos e os bloqueios reais.
        </p>
      ) : (
        <div className="mt-2 space-y-3 text-[12px]">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-nexus-faint">Objetivo</div>
            <p className="mt-0.5 text-nexus-text">{snapshot.goal || "Ainda não definido"}</p>
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-nexus-faint">Plano</div>
            {snapshot.plan.length === 0 ? (
              <p className="mt-0.5 text-nexus-muted">O run não emitiu um plano.</p>
            ) : (
              <ol className="mt-1 list-decimal space-y-0.5 pl-4 text-nexus-text">
                {snapshot.plan.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ol>
            )}
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-nexus-faint">Passos</div>
            {snapshot.steps.length === 0 ? (
              <p className="mt-0.5 text-nexus-muted">Sem passos registados.</p>
            ) : (
              <ul className="mt-1 space-y-1">
                {snapshot.steps.slice(-8).map((step, index) => (
                  <li key={`${step.label}-${index}`} className="flex items-center justify-between gap-2">
                    <span className="truncate text-nexus-text">{step.label}</span>
                    <span className="shrink-0 font-mono text-[10px] text-nexus-muted">
                      {STATUS_PT[step.status] || step.status}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-nexus-faint">Bloqueios</div>
            {snapshot.blockers.length === 0 ? (
              <p className="mt-0.5 text-nexus-muted">Nenhum.</p>
            ) : (
              <ul className="mt-1 space-y-1 text-rose-300">
                {snapshot.blockers.map((blocker) => (
                  <li key={blocker}>{blocker}</li>
                ))}
              </ul>
            )}
          </div>
          {snapshot.artifacts.length > 0 && (
            <div>
              <div className="text-[10px] uppercase tracking-wide text-nexus-faint">Artefactos</div>
              <ul className="mt-1 space-y-0.5 font-mono text-[11px] text-nexus-text">
                {snapshot.artifacts.map((path) => (
                  <li key={path}>{path}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
