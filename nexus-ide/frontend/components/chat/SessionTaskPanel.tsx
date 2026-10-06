"use client";

import { useEffect, useMemo, useState } from "react";
import { CheckCircle2, Circle, ListTodo, Loader2, RefreshCw, XCircle } from "lucide-react";
import { getSessionTodos, type SessionTodo } from "../../lib/api";
import { AGENT_DECLARED_TODO_CAVEAT } from "../../lib/foldRun";
import { useChatTelemetryStore } from "../../stores/chatTelemetryStore";
import type { StreamEvent } from "../../lib/types";

const LABELS = { pending: "Por fazer", in_progress: "Em curso", completed: "Marcada como concluída", cancelled: "Cancelada" };
const EMPTY_EVENTS: StreamEvent[] = [];

export default function SessionTaskPanel({ sessionId, compact = false }: { sessionId: string; compact?: boolean }) {
  const streaming = useChatTelemetryStore((state) => state.sessionId === sessionId && state.streaming);
  const events = useChatTelemetryStore((state) => state.sessionId === sessionId ? state.events : EMPTY_EVENTS);
  const [snapshot, setSnapshot] = useState<{ sessionId: string; todos: SessionTodo[]; error: string | null; loading: boolean }>({
    sessionId, todos: [], error: null, loading: Boolean(sessionId),
  });
  const [revision, setRevision] = useState(0);
  const [expanded, setExpanded] = useState(false);
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
    const refresh = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const result = await getSessionTodos(sessionId);
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
  const completed = current.todos.filter((todo) => todo.status === "completed").length;
  const actionable = current.todos.filter((todo) => todo.status !== "cancelled").length;
  const progress = actionable > 0 ? Math.round((completed / actionable) * 100) : 0;
  const shown = expanded ? current.todos : current.todos.slice(0, compact ? 4 : 8);

  return (
    <section aria-label="Checklist da sessão" className="nx-task-panel rounded-xl border border-nexus-border/60 bg-nexus-bg/25 p-3">
      <div className="flex items-center gap-2">
        <ListTodo className="h-4 w-4 text-nexus-accent-bright" />
        <h3 className="min-w-0 flex-1 text-xs font-semibold text-nexus-text">Checklist da sessão</h3>
        {actionable > 0 && <span aria-label={`${completed} de ${actionable} tarefas marcadas como concluídas`} className="font-mono text-[10px] text-nexus-muted">{completed}/{actionable}</span>}
        <button type="button" onClick={() => setRevision((value) => value + 1)} disabled={!sessionId}
          aria-label="Atualizar checklist" className="rounded-lg p-1.5 text-nexus-muted hover:bg-nexus-accent/10 hover:text-nexus-text focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:opacity-40">
          <RefreshCw className={`h-3.5 w-3.5 ${current.loading ? "animate-spin" : ""}`} />
        </button>
      </div>
      <p role="note" className="mt-1 text-[10px] leading-relaxed text-nexus-faint">
        {AGENT_DECLARED_TODO_CAVEAT}
      </p>
      {current.error && <p role="alert" className="mt-2 text-[11px] leading-relaxed text-amber-300">{current.error} {current.todos.length > 0 ? "A mostrar a última leitura." : ""}</p>}
      {current.loading ? <p role="status" className="mt-2 text-[11px] text-nexus-faint">A recuperar tarefas…</p>
        : current.todos.length === 0 && !current.error ? <p className="mt-2 text-[11px] leading-relaxed text-nexus-faint">As tarefas guardadas pelo agente aparecem aqui e sobrevivem ao refresh.</p> : null}
      {actionable > 0 && <div className="mt-2 h-1 overflow-hidden rounded-full bg-nexus-bg" role="progressbar" aria-label="Progresso declarado da checklist" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
        <div className="h-full rounded-full bg-nexus-accent transition-[width]" style={{ width: `${progress}%` }} />
      </div>}
      <ol className="mt-2 space-y-1.5">
        {shown.map((todo) => <li key={todo.id} className="flex items-start gap-2 rounded-lg px-1 py-1.5">
          {todo.status === "completed" ? <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
            : todo.status === "in_progress" ? <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-nexus-accent-bright" />
            : todo.status === "cancelled" ? <XCircle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-nexus-faint" />
            : <Circle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-nexus-faint" />}
          <div className="min-w-0 flex-1">
            <p className={`break-words text-[11px] leading-relaxed ${todo.status === "cancelled" ? "text-nexus-faint line-through" : "text-nexus-text"}`}>{todo.content}</p>
            <p className="mt-0.5 text-[10px] text-nexus-faint">{LABELS[todo.status]}</p>
          </div>
        </li>)}
      </ol>
      {current.todos.length > (compact ? 4 : 8) && <button type="button" onClick={() => setExpanded((value) => !value)} className="mt-1 rounded-lg px-2 py-1 text-[11px] text-nexus-accent-bright focus-visible:ring-2 focus-visible:ring-nexus-accent">{expanded ? "Recolher tarefas" : `Ver todas (${current.todos.length})`}</button>}
    </section>
  );
}
