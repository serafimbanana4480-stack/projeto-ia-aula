"use client";

import { useCallback, useState } from "react";
import { Loader2, MessageSquare, Power, Trash2, XCircle } from "lucide-react";
import { apiUrl, authHeaders } from "../../lib/api";
import { usePolling } from "../../hooks/usePolling";

interface Session {
  id: string;
  mode: string;
  started_at: string;
  status: "active" | "idle" | "closed";
  title?: string;
}

const STATUS_LABEL_PT: Record<Session["status"], string> = {
  active: "Ativa",
  idle: "Inativa",
  closed: "Fechada",
};

const STATUS_COLOR: Record<Session["status"], string> = {
  active: "bg-green-400",
  idle: "bg-yellow-400",
  closed: "bg-gray-500",
};

function durationMinutes(startedAt: string): number {
  try {
    return Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 60_000));
  } catch {
    return 0;
  }
}

export default function SessionsWidget() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [terminating, setTerminating] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch(apiUrl("/api/sessions"), { headers: authHeaders() });
      if (!res.ok) {
        if (res.status === 404) {
          // Endpoint may not exist yet — show empty state instead of error
          setSessions([]);
          setError(null);
          return;
        }
        throw new Error(`HTTP ${res.status}`);
      }
      const data = (await res.json()) as Session[] | { sessions: Session[] };
      const list = Array.isArray(data) ? data : (data.sessions ?? []);
      setSessions(list);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  usePolling(fetchSessions, 5000, { immediate: true });

  const terminate = useCallback(async (id: string) => {
    setTerminating(id);
    try {
      await fetch(apiUrl(`/api/sessions/${id}`), {
        method: "DELETE",
        headers: authHeaders(),
      });
      // Optimistic update
      setSessions((prev) => prev.filter((s) => s.id !== id));
    } catch {
      // ignore — re-fetch on next poll
    } finally {
      setTerminating(null);
    }
  }, []);

  if (loading && sessions.length === 0) {
    return (
      <div className="flex h-32 items-center justify-center rounded border border-nexus-border bg-nexus-panel">
        <Loader2 className="h-4 w-4 animate-spin text-nexus-muted" aria-hidden />
      </div>
    );
  }

  if (error && sessions.length === 0) {
    return (
      <div
        role="status"
        aria-live="polite"
        className="flex items-center gap-2 rounded border border-yellow-500/30 bg-yellow-500/5 px-3 py-2 text-xs text-yellow-400"
      >
        <XCircle className="h-3.5 w-3.5" aria-hidden />
        <span>Sessões indisponíveis — {error}</span>
      </div>
    );
  }

  const active = sessions.filter((s) => s.status === "active").length;
  const idle = sessions.filter((s) => s.status === "idle").length;

  return (
    <section
      className="min-w-0 rounded border border-nexus-border bg-nexus-panel p-3"
      aria-labelledby="sessions-widget-title"
    >
      <header className="mb-2 flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-nexus-accent" aria-hidden />
          <h3 id="sessions-widget-title" className="text-sm font-semibold">
            Sessões
          </h3>
        </div>
        <div className="flex items-center gap-1.5 text-[10px]">
          <span className="rounded-full bg-green-500/15 px-2 py-0.5 font-medium text-green-400">
            {active} ativas
          </span>
          {idle > 0 && (
            <span className="rounded-full bg-yellow-500/15 px-2 py-0.5 font-medium text-yellow-400">
              {idle} inativas
            </span>
          )}
        </div>
      </header>

      {sessions.length === 0 ? (
        <div className="rounded border border-dashed border-nexus-border/50 px-3 py-6 text-center text-[11px] text-nexus-muted">
          Sem sessões ativas. Inicie uma conversa no painel de chat.
        </div>
      ) : (
        <ul className="max-h-64 space-y-1 overflow-y-auto thin-scrollbar" aria-label="Lista de sessões">
          {sessions.slice(0, 12).map((s) => (
            <li
              key={s.id}
              className="flex items-center gap-2 rounded border border-nexus-border/40 bg-nexus-bg/30 px-2 py-1.5"
            >
              <span
                className={`h-1.5 w-1.5 shrink-0 rounded-full ${STATUS_COLOR[s.status]}`}
                aria-hidden
              />
              <span className="font-mono text-[10px] text-nexus-muted">
                {s.id.slice(0, 6)}
              </span>
              <span className="flex-1 truncate text-[11px] text-nexus-text">
                {s.title || s.mode}
              </span>
              <span className="text-[10px] tabular-nums text-nexus-muted">
                {durationMinutes(s.started_at)}m
              </span>
              <span
                className="rounded px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-nexus-muted"
                aria-label={`Status: ${STATUS_LABEL_PT[s.status]}`}
              >
                {STATUS_LABEL_PT[s.status]}
              </span>
              <button
                type="button"
                onClick={() => terminate(s.id)}
                disabled={terminating === s.id}
                aria-label={`Terminar sessão ${s.id}`}
                className="rounded p-1 text-nexus-muted hover:bg-red-500/10 hover:text-red-400 disabled:opacity-50"
              >
                {terminating === s.id ? (
                  <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
                ) : (
                  <Trash2 className="h-3 w-3" aria-hidden />
                )}
              </button>
            </li>
          ))}
        </ul>
      )}

      <footer className="mt-2 flex items-center justify-between text-[10px] text-nexus-muted">
        <span>
          <Power className="inline h-3 w-3" aria-hidden /> Auto-refresh 5s
        </span>
        <span>{sessions.length} total</span>
      </footer>
    </section>
  );
}
