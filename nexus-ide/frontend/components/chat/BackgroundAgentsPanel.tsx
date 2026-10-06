"use client";

import { useEffect, useId, useRef, useState } from "react";
import {
  Bot,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Loader2,
  Pause,
  Play,
  X,
} from "lucide-react";
import {
  abortAgentInstance,
  getAgentInstances,
  pauseAgentInstance,
  resumeAgentInstance,
  type AgentInstance,
} from "../../lib/api";

interface BackgroundAgentsPanelProps {
  sessionId: string;
  onCompleted?: () => void;
}

type AgentAction = "pause" | "resume" | "abort";
interface AgentSnapshot {
  sessionId: string;
  agents: AgentInstance[];
  loading: boolean;
  loadError: string | null;
}

const TERMINAL_STATUSES = new Set(["completed", "failed", "aborted"]);
const VISIBLE_STATUSES = new Set(["running", "paused", "failed", "completed", "aborted"]);
const STATUS_LABELS: Record<string, string> = {
  running: "Em execução",
  paused: "Pausado",
  failed: "Falhou",
  completed: "Concluído",
  aborted: "Parado",
};

function instanceId(agent: AgentInstance): string {
  return agent.instance_id || agent.id || "";
}

function agentLabel(agent: AgentInstance): string {
  return agent.agent_type || agent.name || "Subagente";
}

function timestampMs(value: number | string | undefined): number | null {
  if (typeof value === "number" && Number.isFinite(value) && value > 0) {
    return value < 100_000_000_000 ? value * 1_000 : value;
  }
  if (typeof value === "string") {
    const parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function startedAtMs(agent: AgentInstance): number | null {
  return timestampMs(agent.start_time) ?? timestampMs(agent.started_at);
}

function formatTime(value: number): string {
  return new Intl.DateTimeFormat("pt-PT", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(value);
}

function formatDuration(milliseconds: number): string {
  const seconds = Math.max(0, Math.floor(milliseconds / 1_000));
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes} min ${seconds % 60} s`;
  return `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

function statusIcon(status: string) {
  if (status === "running") return <Loader2 className="h-3.5 w-3.5 animate-spin text-nexus-accent" />;
  if (status === "paused") return <Pause className="h-3.5 w-3.5 text-amber-300" />;
  if (status === "failed" || status === "aborted") return <CircleAlert className="h-3.5 w-3.5 text-rose-400" />;
  return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />;
}

/** Session-scoped cards and inspector backed by AgentLifecycleManager instances. */
export default function BackgroundAgentsPanel({
  sessionId,
  onCompleted,
}: BackgroundAgentsPanelProps) {
  const reactId = useId();
  const inspectorId = `background-agent-inspector-${reactId.replace(/:/g, "")}`;
  const [snapshot, setSnapshot] = useState<AgentSnapshot>(() => ({
    sessionId,
    agents: [],
    loading: true,
    loadError: null,
  }));
  const [selection, setSelection] = useState<{ sessionId: string; instanceId: string } | null>(null);
  const [pendingAction, setPendingAction] = useState<{ sessionId: string; instanceId: string } | null>(null);
  const [actionError, setActionError] = useState<{ sessionId: string; message: string } | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const onCompletedRef = useRef(onCompleted);
  onCompletedRef.current = onCompleted;

  useEffect(() => {
    let cancelled = false;
    let refreshInFlight = false;
    const previousStatuses: Record<string, string> = {};
    setSnapshot({ sessionId, agents: [], loading: true, loadError: null });
    setSelection(null);
    setPendingAction(null);
    setActionError(null);

    const refresh = async () => {
      if (refreshInFlight) return;
      refreshInFlight = true;
      try {
        const next = await getAgentInstances({ sessionId, includeTerminal: true });
        if (cancelled) return;
        const sessionAgents = next
          .filter((agent) => agent.mission_id === sessionId && instanceId(agent))
          .sort((a, b) => (startedAtMs(b) ?? 0) - (startedAtMs(a) ?? 0));
        const completedNow = sessionAgents.some((agent) => {
          const id = instanceId(agent);
          const previous = previousStatuses[id];
          previousStatuses[id] = agent.status;
          return ["running", "paused"].includes(previous) && TERMINAL_STATUSES.has(agent.status);
        });
        setSnapshot({ sessionId, agents: sessionAgents, loading: false, loadError: null });
        setSelection((current) =>
          current?.sessionId === sessionId && sessionAgents.some((agent) => instanceId(agent) === current.instanceId)
            ? current
            : null,
        );
        if (completedNow) onCompletedRef.current?.();
      } catch (reason) {
        if (cancelled) return;
        const message = reason instanceof Error ? reason.message : "Não foi possível carregar agentes.";
        setSnapshot((current) => ({
          sessionId,
          agents: current.sessionId === sessionId ? current.agents : [],
          loading: false,
          loadError: message,
        }));
      } finally {
        refreshInFlight = false;
      }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 2_500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [sessionId]);

  const currentSnapshot: AgentSnapshot = snapshot.sessionId === sessionId
    ? snapshot
    : { sessionId, agents: [], loading: true, loadError: null };
  const visible = currentSnapshot.agents.filter((agent) => VISIBLE_STATUSES.has(agent.status));
  const selectedId = selection?.sessionId === sessionId ? selection.instanceId : null;
  const selected = visible.find((agent) => instanceId(agent) === selectedId) ?? null;
  const selectedAgentId = selected ? instanceId(selected) : null;
  const selectedAgentStatus = selected?.status;
  const visibleActionError = actionError?.sessionId === sessionId ? actionError.message : null;

  useEffect(() => {
    if (selectedAgentStatus !== "running") return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [selectedAgentId, selectedAgentStatus]);

  if (visible.length === 0 && !currentSnapshot.loading && !currentSnapshot.loadError) return null;

  const performAction = async (agent: AgentInstance, action: AgentAction) => {
    const id = instanceId(agent);
    if (!id) return;
    setPendingAction({ sessionId, instanceId: id });
    setActionError(null);
    try {
      const response = action === "pause"
        ? await pauseAgentInstance(id)
        : action === "resume"
          ? await resumeAgentInstance(id)
          : await abortAgentInstance(id);
      if (!response.success || !response.instance) {
        throw new Error("O backend não confirmou a operação.");
      }
      if (instanceId(response.instance) !== id || response.instance.mission_id !== sessionId) {
        throw new Error("A resposta da operação não corresponde ao agente desta sessão.");
      }
      setSnapshot((current) => current.sessionId === sessionId
        ? {
            ...current,
            agents: current.agents.map((entry) => instanceId(entry) === id ? response.instance : entry),
          }
        : current,
      );
    } catch (reason) {
      setActionError({
        sessionId,
        message: reason instanceof Error ? reason.message : "A operação falhou.",
      });
    } finally {
      setPendingAction((current) =>
        current?.sessionId === sessionId && current.instanceId === id ? null : current,
      );
    }
  };

  return (
    <section
      className="mb-2 rounded-lg border border-nexus-accent/20 bg-nexus-accent/5 px-3 py-2"
      aria-label="Agentes desta sessão"
    >
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-accent">
          Agentes da sessão
        </span>
        <span className="text-[10px] text-nexus-muted">
          {visible.filter((agent) => agent.status === "running").length} em execução
        </span>
      </div>

      {currentSnapshot.loading && visible.length === 0 ? (
        <p className="flex items-center gap-1.5 text-[10px] text-nexus-muted" role="status">
          <Loader2 className="h-3 w-3 animate-spin text-nexus-accent" />
          A carregar os agentes desta sessão…
        </p>
      ) : currentSnapshot.loadError && visible.length === 0 ? (
        <p className="text-[10px] text-amber-200" role="status">
          Não foi possível carregar os agentes desta sessão: {currentSnapshot.loadError}
        </p>
      ) : (
        <div className="flex gap-1.5 overflow-x-auto pb-1" role="list" aria-label="Agentes">
          {visible.map((agent) => {
            const id = instanceId(agent);
            const isSelected = selectedId === id;
            return (
              <div role="listitem" key={id} className="shrink-0">
                <button
                  type="button"
                  onClick={() => {
                    setActionError(null);
                    setSelection(isSelected ? null : { sessionId, instanceId: id });
                  }}
                  aria-expanded={isSelected}
                  aria-controls={inspectorId}
                  className={`flex max-w-[240px] items-center gap-1.5 rounded-md border px-2 py-1.5 text-left text-[10px] transition-colors ${
                    isSelected
                      ? "border-nexus-accent/50 bg-nexus-accent/10 text-nexus-text"
                      : "border-nexus-border/50 bg-nexus-bg/40 text-nexus-muted hover:text-nexus-text"
                  }`}
                >
                  {statusIcon(agent.status)}
                  <span className="font-medium">{agentLabel(agent)}</span>
                  <span className="truncate text-nexus-muted">{STATUS_LABELS[agent.status] ?? agent.status}</span>
                </button>
              </div>
            );
          })}
        </div>
      )}

      {currentSnapshot.loadError && visible.length > 0 && (
        <p className="mt-1 text-[10px] text-amber-200" role="status">
          Não foi possível atualizar os agentes desta sessão. A mostrar o último estado recebido.
        </p>
      )}

      {selected && (
        <aside
          id={inspectorId}
          role="region"
          aria-label={`Inspector de ${agentLabel(selected)}`}
          className="mt-2 rounded-md border border-nexus-border/50 bg-nexus-bg/70 p-3"
        >
          <header className="flex items-start gap-2">
            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-nexus-accent/10 text-nexus-accent">
              <Bot className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
              <h3 className="text-[11px] font-semibold text-nexus-text">{agentLabel(selected)}</h3>
              <p className="mt-0.5 break-all font-mono text-[9px] text-nexus-muted">{instanceId(selected)}</p>
            </div>
            <button
              type="button"
              onClick={() => setSelection(null)}
              aria-label={`Fechar inspector de ${agentLabel(selected)}`}
              className="rounded p-1 text-nexus-muted hover:bg-nexus-card hover:text-nexus-text"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </header>

          <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2 text-[10px]">
            <span className="text-nexus-muted">Estado</span>
            <span className="flex items-center gap-1 text-nexus-text">
              {statusIcon(selected.status)}{STATUS_LABELS[selected.status] ?? selected.status}
            </span>
            {selected.objective && <><span className="text-nexus-muted">Objetivo</span><span className="break-words text-nexus-text">{selected.objective}</span></>}
            {selected.current_task && <><span className="text-nexus-muted">Tarefa atual</span><span className="break-words text-nexus-text">{selected.current_task}</span></>}
            {selected.mission_id && <><span className="text-nexus-muted">Missão / sessão</span><span className="break-all font-mono text-nexus-text">{selected.mission_id}</span></>}
            {selected.parent_task_id && <><span className="text-nexus-muted">ID da tarefa associada</span><span className="break-all font-mono text-nexus-text">{selected.parent_task_id}</span></>}
            {startedAtMs(selected) !== null && (
              <>
                <span className="text-nexus-muted">Início</span>
                <span className="text-nexus-text">{formatTime(startedAtMs(selected)!)}</span>
                <span className="flex items-center gap-1 text-nexus-muted"><Clock3 className="h-3 w-3" />Tempo desde início</span>
                <span className="tabular-nums text-nexus-text">
                  {formatDuration((timestampMs(selected.completed_at) ?? now) - startedAtMs(selected)!)}
                </span>
              </>
            )}
            {selected.error_message && (
              <>
                <span className="text-rose-300">Erro</span>
                <span className="break-words text-rose-200">{selected.error_message}</span>
              </>
            )}
          </div>

          {visibleActionError && <p className="mt-2 text-[10px] text-rose-300" role="alert">{visibleActionError}</p>}

          <div className="mt-3 flex flex-wrap gap-1.5 border-t border-nexus-border/30 pt-2">
            {selected.status === "running" && (
              <button
                type="button"
                disabled={pendingAction?.sessionId === sessionId && pendingAction.instanceId === instanceId(selected)}
                onClick={() => void performAction(selected, "pause")}
                className="inline-flex items-center gap-1 rounded border border-amber-300/20 px-2 py-1 text-[10px] text-amber-200 hover:bg-amber-300/10 disabled:opacity-50"
              >
                <Pause className="h-3 w-3" />
                {pendingAction?.sessionId === sessionId && pendingAction.instanceId === instanceId(selected) ? "A atualizar…" : "Pausar"}
              </button>
            )}
            {selected.status === "paused" && (
              <button
                type="button"
                disabled={pendingAction?.sessionId === sessionId && pendingAction.instanceId === instanceId(selected)}
                onClick={() => void performAction(selected, "resume")}
                className="inline-flex items-center gap-1 rounded border border-emerald-300/20 px-2 py-1 text-[10px] text-emerald-200 hover:bg-emerald-300/10 disabled:opacity-50"
              >
                <Play className="h-3 w-3" />
                {pendingAction?.sessionId === sessionId && pendingAction.instanceId === instanceId(selected) ? "A atualizar…" : "Retomar"}
              </button>
            )}
            {["running", "paused"].includes(selected.status) && (
              <button
                type="button"
                disabled={pendingAction?.sessionId === sessionId && pendingAction.instanceId === instanceId(selected)}
                onClick={() => void performAction(selected, "abort")}
                className="inline-flex items-center gap-1 rounded border border-rose-300/20 px-2 py-1 text-[10px] text-rose-200 hover:bg-rose-300/10 disabled:opacity-50"
              >
                <X className="h-3 w-3" />Parar
              </button>
            )}
          </div>
        </aside>
      )}
    </section>
  );
}
