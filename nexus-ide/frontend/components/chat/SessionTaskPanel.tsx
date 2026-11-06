"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Circle, Loader2, RefreshCw, XCircle } from "lucide-react";
import { getSessionTodos, updateSessionTodo, type SessionTodo } from "../../lib/api";
import { AGENT_DECLARED_TODO_CAVEAT } from "../../lib/foldRun";
import { useChatTelemetryStore } from "../../stores/chatTelemetryStore";
import type { StreamEvent } from "../../lib/types";
import TodoTree from "./TodoTree";

const STATUS_LABEL: Record<SessionTodo["status"], string> = {
  pending: "pendente",
  in_progress: "em curso",
  completed: "concluída",
  cancelled: "cancelada",
  blocked: "bloqueada",
  failed: "falhou",
};

const PRIORITY_LABEL: Record<string, string> = {
  low: "baixa",
  medium: "média",
  normal: "normal",
  high: "alta",
  critical: "crítica",
};

const EMPTY_EVENTS: StreamEvent[] = [];

/** Count only rows the runtime returned. A missing error is not a completed task. */
export function declaredTodoCount(todos: readonly SessionTodo[]): { done: number; total: number } {
  return {
    done: todos.reduce((count, todo) => count + (todo.status === "completed" ? 1 : 0), 0),
    total: todos.length,
  };
}

function progressPhrase(done: number, total: number): string {
  return `${done} de ${total} ${done === 1 ? "concluída" : "concluídas"}`;
}

function priorityPhrase(priority: string | undefined): string | null {
  if (typeof priority !== "string") return null;
  const value = priority.trim();
  if (!value) return null;
  return `prioridade ${PRIORITY_LABEL[value.toLowerCase()] ?? value}`;
}

function statusLabel(status: string): string {
  return status in STATUS_LABEL ? STATUS_LABEL[status as SessionTodo["status"]] : status;
}

function sessionStatusClass(status: string): string {
  if (status === "completed") return "bg-emerald-400/12 text-nexus-accent2";
  if (status === "in_progress") return "bg-nexus-accent/15 text-nexus-accent-bright";
  if (status === "cancelled") return "bg-nexus-bg text-nexus-faint";
  return "bg-nexus-bg text-nexus-muted";
}

// Shared across every mounted panel (sidebar + inline compact copy): one
// in-flight request and a minimum gap per session. Without it the panels
// re-fired on every effect re-run and a long run produced bursts of ~15
// requests in 2s, tripping the backend's 60/min limit (429 without CORS
// headers -> console "blocked by CORS policy" storm).
const TODO_MIN_GAP_MS = 2500;
const todoFetches = new Map<string, { at: number; pending: Promise<Awaited<ReturnType<typeof getSessionTodos>>> | null; last: Awaited<ReturnType<typeof getSessionTodos>> | null; backoffUntil: number }>();

/** Drop cached checklist snapshots when the surrounding session context is reset. */
export function clearSessionTodoCache(): void {
  todoFetches.clear();
}

async function fetchTodosShared(sessionId: string, force: boolean) {
  const now = Date.now();
  const entry = todoFetches.get(sessionId) ?? { at: 0, pending: null, last: null, backoffUntil: 0 };
  todoFetches.set(sessionId, entry);
  if (entry.pending) return entry.pending;
  if (entry.last && (now < entry.backoffUntil || (!force && now - entry.at < TODO_MIN_GAP_MS))) return entry.last;
  entry.at = now;
  entry.pending = getSessionTodos(sessionId)
    .then((result) => {
      if (!result || typeof result !== "object" || !Array.isArray(result.todos)) {
        throw new Error("A resposta da checklist da sessão é inválida.");
      }
      entry.last = { ...result, todos: result.todos };
      entry.backoffUntil = 0;
      return entry.last;
    })
    .catch((error) => { entry.backoffUntil = Date.now() + 30000; throw error; })
    .finally(() => { entry.pending = null; });
  return entry.pending;
}

export default function SessionTaskPanel({ sessionId, compact = false }: { sessionId: string; compact?: boolean }) {
  const streaming = useChatTelemetryStore((state) => state.sessionId === sessionId && state.streaming);
  const events = useChatTelemetryStore((state) =>
    state.sessionId === sessionId && Array.isArray(state.events) ? state.events : EMPTY_EVENTS,
  );
  const [snapshot, setSnapshot] = useState<{ sessionId: string; todos: SessionTodo[]; error: string | null; loading: boolean }>({
    sessionId, todos: [], error: null, loading: Boolean(sessionId),
  });
  const [revision, setRevision] = useState(0);
  const [expanded, setExpanded] = useState(false);
  const [activeId, setActiveId] = useState<string | number | null>(null);
  // A successful todo call refreshes the durable source immediately. Do not
  // infer success from a narrated plan or a tool call that has no result.
  const todoRevision = useMemo(() => events.filter((event) =>
    event.type === "tool_result" && ["todo_write", "todo_list"].includes(event.tool_name ?? ""),
  ).length, [events]);

  useEffect(() => {
    if (!sessionId || sessionId === "default" || sessionId.startsWith("local-")) {
      setSnapshot({ sessionId, todos: [], error: null, loading: false });
      return;
    }
    let disposed = false;
    let inFlight = false;
    let firstRun = true;
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      const force = firstRun && revision > 0;
      firstRun = false;
      try {
        const result = await fetchTodosShared(sessionId, force);
        if (!disposed) setSnapshot({ sessionId, todos: result.todos, error: null, loading: false });
      } catch (reason) {
        if (!disposed) setSnapshot((previous) => ({
          sessionId, todos: previous.sessionId === sessionId ? previous.todos : [], loading: false,
          error: reason instanceof Error ? reason.message : "Não foi possível ler a checklist.",
        }));
      } finally { inFlight = false; }
    };
    void refresh();
    const timer = streaming ? window.setInterval(() => void refresh(), 5000) : null;
    return () => { disposed = true; if (timer !== null) window.clearInterval(timer); };
  }, [sessionId, streaming, todoRevision, revision]);

  const current = snapshot.sessionId === sessionId ? snapshot : { todos: [], error: null, loading: true };
  const hierarchical = current.todos.some((todo) => todo.type === "category" || todo.type === "objective" || todo.parent_id != null);
  const { done, total } = declaredTodoCount(current.todos);
  const limit = compact ? 4 : 8;
  const shown = expanded ? current.todos : current.todos.slice(0, limit);
  const focusedId = shown.some((todo) => todo.id === activeId) ? activeId : shown[0]?.id ?? null;

  const moveFocus = (currentIndex: number, key: string) => {
    if (key !== "ArrowDown" && key !== "ArrowUp" && key !== "Home" && key !== "End") return;
    const next = key === "Home" ? 0
      : key === "End" ? shown.length - 1
      : key === "ArrowDown" ? Math.min(shown.length - 1, currentIndex + 1)
      : Math.max(0, currentIndex - 1);
    const todo = shown[next];
    if (!todo) return;
    setActiveId(todo.id);
    document.getElementById(`session-task-${todo.id}`)?.focus();
  };

  return (
    <section aria-label="Checklist da sessão" className="nx-task-panel nx-work-surface rounded-xl border border-nexus-border/60 px-2.5 py-2">
      <div className="flex items-center gap-2">
        <h3 className="text-[11px] font-semibold tracking-tight text-nexus-text">Missão</h3>
        {total > 0 && !hierarchical && (
          <p className="min-w-0 flex-1 truncate text-[11px] tabular-nums text-nexus-muted">{progressPhrase(done, total)}</p>
        )}
        <button
          type="button"
          onClick={() => setRevision((value) => value + 1)}
          disabled={!sessionId}
          aria-label="Atualizar checklist"
          className="ml-auto rounded-lg p-1.5 text-nexus-muted hover:bg-nexus-accent/10 hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:opacity-40"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${current.loading ? "animate-spin motion-reduce:animate-none" : ""}`} />
        </button>
      </div>
      <p role="note" className="mt-1 text-[10px] leading-snug text-nexus-faint">
        {AGENT_DECLARED_TODO_CAVEAT}
      </p>
      {current.error && (
        <p role="alert" className="mt-1.5 text-[11px] leading-snug text-nexus-accent3">
          {current.error} {current.todos.length > 0 ? "A mostrar a última leitura." : ""}
        </p>
      )}
      {current.loading ? <p role="status" className="mt-1.5 text-[11px] text-nexus-faint">A recuperar tarefas…</p>
        : total === 0 && !current.error ? (
          <p className="mt-1.5 text-[11px] leading-snug text-nexus-faint">Ainda não há tarefas nesta sessão.</p>
        ) : null}
      {hierarchical && <TodoTree key={sessionId} todos={current.todos} onToggle={async (todo) => {
        await updateSessionTodo(sessionId, String(todo.id), { status: todo.status === "completed" ? "pending" : "completed" })
          .then((result) => {
            todoFetches.delete(sessionId);
            setSnapshot((previous) => previous.sessionId === sessionId ? { sessionId, todos: result.todos, error: null, loading: false } : previous);
          })
          .catch((reason: unknown) => setSnapshot((previous) => previous.sessionId === sessionId ? { ...previous, error: reason instanceof Error ? reason.message : "Não foi possível atualizar a tarefa." } : previous));
      }} />}
      {!hierarchical && shown.length > 0 && (
        <ul role="list" aria-label="Tarefas da sessão" className="mt-1.5 space-y-0.5">
          {shown.map((todo, index) => {
            const priority = priorityPhrase(todo.priority);
            const label = statusLabel(todo.status);
            const active = todo.status === "in_progress";
            const name = [label, todo.content, priority].filter(Boolean).join(", ");
            return (
              <li
                key={todo.id}
                id={`session-task-${todo.id}`}
                data-status={todo.status}
                role="listitem"
                aria-label={name}
                tabIndex={todo.id === focusedId ? 0 : -1}
                aria-current={active ? "step" : undefined}
                onFocus={() => setActiveId(todo.id)}
                onKeyDown={(event) => {
                  if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "Home" && event.key !== "End") return;
                  event.preventDefault();
                  moveFocus(index, event.key);
                }}
                className={`flex items-start gap-2 rounded-md px-1.5 py-1.5 outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent ${
                  active ? "bg-nexus-accent/10 ring-1 ring-inset ring-nexus-accent/30" : ""
                }`}
              >
                <span className="mt-[3px] shrink-0"><StatusMark status={todo.status} /></span>
                <span className="min-w-0 flex-1">
                  <span className={`block break-words text-[12px] leading-snug ${
                    todo.status === "completed" ? "text-nexus-muted" : todo.status === "cancelled" ? "text-nexus-muted" : "text-nexus-text"
                  }`}>{todo.content}</span>
                  <span className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span className={`rounded-full px-1.5 py-px text-[10px] font-medium ${sessionStatusClass(todo.status)}`}>{label}</span>
                    {priority && <span className="text-[10px] text-nexus-faint">{priority}</span>}
                  </span>
                </span>
              </li>
            );
          })}
        </ul>
      )}
      {!hierarchical && current.todos.length > limit && (
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="mt-1 rounded-lg px-1.5 py-1 text-[11px] text-nexus-accent-bright focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
        >
          {expanded ? "Recolher tarefas" : `Ver todas (${current.todos.length})`}
        </button>
      )}
    </section>
  );
}

function StatusMark({ status }: { status: SessionTodo["status"] | string }) {
  const className = "h-3 w-3 shrink-0 self-center";
  if (status === "completed") return <CheckCircle2 className={`${className} text-nexus-accent2`} aria-hidden="true" />;
  if (status === "in_progress") return <Loader2 className={`${className} animate-spin text-nexus-accent-bright motion-reduce:animate-none`} aria-hidden="true" />;
  if (status === "cancelled") return <XCircle className={`${className} text-nexus-faint`} aria-hidden="true" />;
  return <Circle className={`${className} text-nexus-faint`} aria-hidden="true" />;
}
