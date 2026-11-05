"use client";

import { useEffect, useState } from "react";
import AppShell from "../../components/layout/AppShell";
import { getAgentInstances, type AgentInstance } from "../../lib/api";

const KNOWN: Record<string, string> = {
  running: "RUNNING",
  paused: "WAITING",
  completed: "COMPLETED",
  failed: "FAILED",
  aborted: "CANCELLED",
  cancelled: "CANCELLED",
  queued: "QUEUED",
};

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentInstance[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let stop = false;
    const load = async () => {
      try {
        const next = await getAgentInstances({ includeTerminal: true });
        if (!stop) {
          setAgents(next);
          setError(null);
        }
      } catch (err) {
        if (!stop) setError(err instanceof Error ? err.message : "Não foi possível ler os agentes");
      }
    };
    void load();
    const timer = window.setInterval(() => void load(), 4000);
    return () => {
      stop = true;
      window.clearInterval(timer);
    };
  }, []);

  return (
    <AppShell title="Agentes">
      <div className="mx-auto max-w-4xl">
        <h1 className="text-xl font-semibold">Agentes</h1>
        <p className="mt-1 text-sm text-nexus-muted">
          Instâncias devolvidas por <span className="font-mono">/api/agents/instances</span>. Estados desconhecidos ficam com o valor original.
        </p>
        {error && <p className="mt-4 text-sm text-rose-300">{error}</p>}
        {agents && agents.length === 0 && !error && (
          <p className="mt-6 rounded-xl border border-white/10 p-4 text-sm text-nexus-muted">
            Nenhum agente foi executado. Esta lista só mostra trabalho real do backend.
          </p>
        )}
        <ul className="mt-4 space-y-2">
          {(agents ?? []).map((agent) => {
            const status = KNOWN[agent.status] ?? agent.status;
            return (
              <li key={agent.instance_id || agent.id} className="rounded-xl border border-white/10 bg-nexus-panel px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <span className="font-medium">{agent.agent_type || agent.name || "Agente"}</span>
                  <span className="font-mono text-[11px] text-nexus-muted">{status}</span>
                </div>
                {(agent.current_task || agent.objective) && (
                  <p className="mt-1 text-sm text-nexus-muted">{agent.current_task || agent.objective}</p>
                )}
                {agent.error_message && <p className="mt-1 text-sm text-rose-300">{agent.error_message}</p>}
              </li>
            );
          })}
        </ul>
      </div>
    </AppShell>
  );
}
