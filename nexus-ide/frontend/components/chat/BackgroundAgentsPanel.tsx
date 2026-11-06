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
  ChevronDown,
  ChevronRight,
  Circle,
  Users,
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
type AgentFilter = "all" | "active" | "completed" | "attention";
const VISIBLE_STATUSES = new Set(["idle", "pending", "running", "paused", "failed", "completed", "aborted"]);
const ACTIVE_STATUSES = new Set(["idle", "pending", "running", "paused"]);
const STATUS_PRIORITY: Record<string, number> = { running: 0, paused: 1, pending: 2, idle: 3, failed: 4, aborted: 5, completed: 6 };
const STATUS_LABELS: Record<string, string> = {
  idle: "Em espera",
  pending: "Na fila",
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
  if (status === "paused") return <Pause className="h-3.5 w-3.5 text-nexus-accent3" />;
  if (status === "failed" || status === "aborted") return <CircleAlert className="h-3.5 w-3.5 text-nexus-accent4" />;
  if (status === "pending" || status === "idle") return <Circle className="h-3.5 w-3.5 text-nexus-muted" />;
  return <CheckCircle2 className="h-3.5 w-3.5 text-nexus-accent2" />;
}

/** Session-scoped cards and inspector backed by AgentLifecycleManager instances. */
export default function BackgroundAgentsPanel({
  sessionId,
  onCompleted,
}: BackgroundAgentsPanelProps) {
  const reactId = useId();
  const inspectorId = `background-agent-inspector-${reactId.replace(/:/g, "")}`;
  const listId = `background-agent-list-${reactId.replace(/:/g, "")}`;
  const [expanded, setExpanded] = useState(true);
  const [filter, setFilter] = useState<AgentFilter>("all");
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
    setFilter("all");
    setExpanded(true);

    const refresh = async () => {
      if (refreshInFlight) return;
      refreshInFlight = true;
      try {
        const next = await getAgentInstances({ sessionId, includeTerminal: true });
        if (cancelled) return;
        const sessionAgents = next
          .filter((agent) => agent.mission_id === sessionId && instanceId(agent))
          .sort((a, b) => (STATUS_PRIORITY[a.status] ?? 7) - (STATUS_PRIORITY[b.status] ?? 7) || (startedAtMs(b) ?? 0) - (startedAtMs(a) ?? 0));
        let completedNow = false;
        for (const agent of sessionAgents) {
          const id = instanceId(agent);
          const previous = previousStatuses[id];
          previousStatuses[id] = agent.status;
          if (ACTIVE_STATUSES.has(previous) && TERMINAL_STATUSES.has(agent.status)) completedNow = true;
        }
        setNow(Date.now());
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
  const hasRunningAgents = visible.some((agent) => agent.status === "running");
  const visibleActionError = actionError?.sessionId === sessionId ? actionError.message : null;

  useEffect(() => {
    if (!hasRunningAgents) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, [hasRunningAgents]);

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

  const runningCount = visible.filter((agent) => agent.status === "running").length;
  const pausedCount = visible.filter((agent) => agent.status === "paused").length;
  const waitingCount = visible.filter((agent) => agent.status === "pending" || agent.status === "idle").length;
  const activeCount = visible.filter((agent) => ACTIVE_STATUSES.has(agent.status)).length;
  const completedCount = visible.filter((agent) => agent.status === "completed").length;
  const attentionCount = visible.filter((agent) => ["failed", "aborted"].includes(agent.status)).length;
  const filtered = visible.filter((agent) => filter === "all" ||
    (filter === "active" && ACTIVE_STATUSES.has(agent.status)) ||
    (filter === "completed" && agent.status === "completed") ||
    (filter === "attention" && ["failed", "aborted"].includes(agent.status)));
  const filters: { value: AgentFilter; label: string; count: number }[] = [
    { value: "all", label: "Todos", count: visible.length },
    { value: "active", label: "Ativos", count: activeCount },
    { value: "completed", label: "Concluídos", count: completedCount },
    { value: "attention", label: "Com erro / parados", count: attentionCount },
  ];

  return (
    <section
      className="nx-agent-team my-5 overflow-hidden rounded-2xl border border-nexus-border/80"
      aria-label="Agentes desta sessão"
    >
      <button
        type="button"
        onClick={() => setExpanded((value) => !value)}
        aria-expanded={expanded}
        aria-controls={expanded ? listId : undefined}
        aria-label={expanded ? "Recolher subagentes" : "Expandir subagentes"}
        className="flex w-full items-center justify-between gap-3 px-4 py-3.5 text-left transition-colors hover:bg-nexus-accent/5"
      >
        <span className="inline-flex min-w-0 items-center gap-3 text-[13px] font-semibold tracking-tight text-nexus-text">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-nexus-accent/20 bg-nexus-accent/10 text-nexus-accent-bright">
            <Users className="h-4 w-4" />
          </span>
          <span className="min-w-0">
            Equipa de agentes
            <span className="mt-1 flex flex-wrap gap-x-3 gap-y-1 text-[12px] font-normal text-nexus-muted">
              {currentSnapshot.loading && visible.length === 0 ? (
                <span>A carregar…</span>
              ) : currentSnapshot.loadError && visible.length === 0 ? (
                <span>Estado indisponível</span>
              ) : (
                <>
                  <span className="tabular-nums"><span className="font-semibold text-nexus-text">{runningCount}</span> em execução</span>
                  {pausedCount > 0 && <span className="tabular-nums"><span className="font-semibold text-nexus-text">{pausedCount}</span> em pausa</span>}
                  {waitingCount > 0 && <span className="tabular-nums"><span className="font-semibold text-nexus-text">{waitingCount}</span> em espera</span>}
                  {attentionCount > 0 && <span className="tabular-nums text-nexus-accent4"><span className="font-semibold">{attentionCount}</span> com erro / parados</span>}
                </>
              )}
            </span>
          </span>
        </span>
        <span className="flex shrink-0 items-center gap-2 text-nexus-muted">
          {hasRunningAgents && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-nexus-accent2" aria-hidden="true" />}
          <ChevronDown className={`h-4 w-4 transition-transform ${expanded ? "rotate-180" : ""}`} aria-hidden="true" />
        </span>
      </button>

      {expanded && <div id={listId} className="border-t border-nexus-border/50 p-3">
      {visible.length > 0 && (
        <div role="group" aria-label="Filtrar subagentes" className="mb-3 flex flex-wrap gap-1">
          {filters.map((item) => (
            <button
              key={item.value}
              type="button"
              aria-pressed={filter === item.value}
              onClick={() => { setFilter(item.value); setSelection(null); }}
              className={`rounded-lg px-2.5 py-2 text-[12px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent ${filter === item.value ? "bg-nexus-accent/12 font-medium text-nexus-accent-bright" : "text-nexus-muted hover:bg-nexus-card hover:text-nexus-text"}`}
            >
              {item.label} <span className="ml-1 font-mono text-[10px] opacity-70">{item.count}</span>
            </button>
          ))}
        </div>
      )}

      {currentSnapshot.loading && visible.length === 0 ? (
        <p className="flex items-center gap-1.5 text-[11px] text-nexus-muted" role="status">
          <Loader2 className="h-3 w-3 animate-spin text-nexus-accent" />
          A carregar os agentes desta sessão…
        </p>
      ) : currentSnapshot.loadError && visible.length === 0 ? (
        <p className="text-[11px] text-nexus-accent3" role="status">
          Não foi possível carregar os agentes desta sessão: {currentSnapshot.loadError}
        </p>
      ) : (
        <div className="grid max-h-[360px] gap-2 overflow-y-auto sm:grid-cols-2" role="list" aria-label="Agentes">
          {filtered.map((agent) => {
            const id = instanceId(agent);
            const isSelected = selectedId === id;
            const started = startedAtMs(agent);
            const end = timestampMs(agent.completed_at) ?? (ACTIVE_STATUSES.has(agent.status) ? now : null);
            const elapsed = started !== null && end !== null ? formatDuration(end - started) : null;
            return (
              <div role="listitem" key={id} className="min-w-0">
                <button
                  type="button"
                  onClick={() => {
                    setActionError(null);
                    setSelection(isSelected ? null : { sessionId, instanceId: id });
                  }}
                  aria-expanded={isSelected}
                  aria-controls={isSelected ? inspectorId : undefined}
                  aria-label={`${agentLabel(agent)} ${STATUS_LABELS[agent.status] ?? agent.status}`}
                  className={`nx-agent-card flex h-full w-full items-start gap-2.5 rounded-xl border px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent ${
                    isSelected
                      ? "border-nexus-accent/50 bg-nexus-accent/12 text-nexus-text"
                      : "border-nexus-border/60 bg-nexus-bg/45 text-nexus-muted hover:border-nexus-accent/30 hover:text-nexus-text"
                  }`}
                >
                  <span className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-nexus-bg/70">{statusIcon(agent.status)}</span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-[12px] font-semibold text-nexus-text">{agentLabel(agent)}</span>
                      <ChevronRight className="h-3 w-3 shrink-0 text-nexus-faint" aria-hidden="true" />
                    </span>
                    <span className="mt-0.5 block truncate text-[11px] font-medium text-nexus-muted">
                      {STATUS_LABELS[agent.status] ?? agent.status}
                    </span>
                    {(agent.current_task || agent.objective) && <span className="mt-2 block line-clamp-2 text-[12px] leading-relaxed text-nexus-muted">{agent.current_task || agent.objective}</span>}
                    {elapsed && <span className="mt-2 flex items-center gap-1 text-[11px] tabular-nums text-nexus-faint" title={TERMINAL_STATUSES.has(agent.status) ? "Tempo entre o início e o fim reportado" : "Tempo decorrido desde o início, incluindo pausas"}><Clock3 className="h-3 w-3" />{elapsed}</span>}
                  </span>
                </button>
              </div>
            );
          })}
          {filtered.length === 0 && visible.length > 0 && <p className="col-span-full py-5 text-center text-xs text-nexus-muted">Nenhum agente neste filtro.</p>}
        </div>
      )}

      {currentSnapshot.loadError && visible.length > 0 && (
        <p className="mt-1 text-[10px] text-nexus-accent3" role="status">
          Não foi possível atualizar os agentes desta sessão. A mostrar o último estado recebido.
        </p>
      )}

      {selected && (
        <aside
          id={inspectorId}
          role="region"
          aria-label={`Inspector de ${agentLabel(selected)}`}
          className="mt-2 rounded-xl border border-nexus-border/50 bg-nexus-bg/70 p-3"
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
              className="rounded-lg p-1 text-nexus-muted hover:bg-nexus-card hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </header>

          <div className="mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-[11px]">
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
              </>
            )}
            {startedAtMs(selected) !== null && (timestampMs(selected.completed_at) !== null || ACTIVE_STATUSES.has(selected.status)) && (
              <>
                <span className="flex items-center gap-1 text-nexus-muted"><Clock3 className="h-3 w-3" />Tempo desde início</span>
                <span className="tabular-nums text-nexus-text">
                  {formatDuration((timestampMs(selected.completed_at) ?? now) - startedAtMs(selected)!)}
                </span>
              </>
            )}
            {selected.error_message && (
              <>
                <span className="text-nexus-accent4">Erro</span>
                <span className="break-words text-nexus-accent4">{selected.error_message}</span>
              </>
            )}
          </div>

          {visibleActionError && <p className="mt-2 text-[10px] text-nexus-accent4" role="alert">{visibleActionError}</p>}

          <div className="mt-3 flex flex-wrap gap-1.5 border-t border-nexus-border/30 pt-2">
            {selected.status === "running" && (
              <button
                type="button"
                disabled={pendingAction?.sessionId === sessionId && pendingAction.instanceId === instanceId(selected)}
                onClick={() => void performAction(selected, "pause")}
                className="inline-flex items-center gap-1 rounded-lg border border-amber-300/25 bg-amber-300/5 px-2.5 py-1 text-[11px] font-medium text-nexus-accent3 hover:bg-amber-300/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:opacity-50"
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
                className="inline-flex items-center gap-1 rounded-lg border border-emerald-300/25 bg-emerald-300/5 px-2.5 py-1 text-[11px] font-medium text-nexus-accent2 hover:bg-emerald-300/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:opacity-50"
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
                className="inline-flex items-center gap-1 rounded-lg border border-rose-300/25 bg-rose-300/5 px-2.5 py-1 text-[11px] font-medium text-nexus-accent4 hover:bg-rose-300/10 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:opacity-50"
              >
                <X className="h-3 w-3" />Parar
              </button>
            )}
          </div>
        </aside>
      )}
      </div>}
    </section>
  );
}
