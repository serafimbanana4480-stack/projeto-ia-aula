"use client";

import { useEffect, useRef, useState } from "react";
import { CheckCircle2, CircleAlert, Loader2, X } from "lucide-react";
import {
  abortAgentInstance,
  getAgentInstances,
  type AgentInstance,
} from "../../lib/api";

interface BackgroundAgentsPanelProps {
  sessionId: string;
  onCompleted?: () => void;
}

function instanceId(agent: AgentInstance): string {
  return agent.instance_id || agent.id;
}

function agentLabel(agent: AgentInstance): string {
  return agent.agent_type || agent.name || "Subagente";
}

/** Small, session-scoped view of detached work; the principal chat stays usable. */
export default function BackgroundAgentsPanel({
  sessionId,
  onCompleted,
}: BackgroundAgentsPanelProps) {
  const [agents, setAgents] = useState<AgentInstance[]>([]);
  const previousStatuses = useRef<Record<string, string>>({});

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const next = await getAgentInstances({
          sessionId,
          includeTerminal: true,
        });
        if (cancelled) return;
        const sessionAgents = next
          .filter((agent) => agent.mission_id === sessionId)
          .sort((a, b) => (b.start_time || 0) - (a.start_time || 0))
          .slice(0, 6);
        const completedNow = sessionAgents.some((agent) => {
          const id = instanceId(agent);
          const previous = previousStatuses.current[id];
          previousStatuses.current[id] = agent.status;
          return previous === "running" && ["completed", "failed", "aborted"].includes(agent.status);
        });
        setAgents(sessionAgents);
        if (completedNow) onCompleted?.();
      } catch {
        // The panel is auxiliary; a temporary poll failure must not affect chat.
      }
    };
    void refresh();
    const timer = window.setInterval(refresh, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [sessionId, onCompleted]);

  const visible = agents.filter((agent) => ["running", "paused", "failed", "completed", "aborted"].includes(agent.status));
  if (visible.length === 0) return null;

  return (
    <div className="mb-2 rounded-lg border border-nexus-accent/20 bg-nexus-accent/5 px-3 py-2">
      <div className="mb-1.5 flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-accent">
          Trabalho em background
        </span>
        <span className="text-[10px] text-nexus-muted">a conversa principal continua livre</span>
      </div>
      <div className="space-y-1">
        {visible.map((agent) => {
          const id = instanceId(agent);
          const status = agent.status as string;
          const running = status === "running";
          const failed = status === "failed" || status === "aborted";
          return (
            <div key={id} className="flex items-center gap-2 text-[11px] text-nexus-muted">
              {running ? (
                <Loader2 className="h-3 w-3 shrink-0 animate-spin text-nexus-accent" />
              ) : failed ? (
                <CircleAlert className="h-3 w-3 shrink-0 text-red-400" />
              ) : (
                <CheckCircle2 className="h-3 w-3 shrink-0 text-emerald-400" />
              )}
              <span className="font-medium text-nexus-text">{agentLabel(agent)}</span>
              <span className="min-w-0 flex-1 truncate">{agent.objective || agent.current_task || agent.status}</span>
              {running && (
                <button
                  type="button"
                  onClick={() => void abortAgentInstance(id)}
                  className="rounded p-0.5 text-nexus-muted hover:bg-red-500/15 hover:text-red-300"
                  title="Parar subagente"
                  aria-label={`Parar ${agentLabel(agent)}`}
                >
                  <X className="h-3 w-3" />
                </button>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
