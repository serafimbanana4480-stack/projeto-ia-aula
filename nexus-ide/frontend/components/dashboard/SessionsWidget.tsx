"use client";

import { useCallback, useState, type ReactNode } from "react";
import { Loader2, MessageSquare, Power, Trash2, XCircle } from "lucide-react";
import { apiUrl, authHeaders } from "../../lib/api";
import { usePolling } from "../../hooks/usePolling";
import { Surface, SurfaceHeader } from "../ui/Surface";
import { Badge, StatusDot, EmptyState } from "../ui/Primitives";

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

const STATUS_TONE: Record<Session["status"], "success" | "warning" | "neutral"> = {
  active: "success",
  idle: "warning",
  closed: "neutral",
};

function durationMinutes(startedAt: string): number {
  try {
    return Math.max(0, Math.floor((Date.now() - new Date(startedAt).getTime()) / 60_000));
  } catch {
    return 0;
  }
}

function WidgetShell({ children }: { children: ReactNode }) {
  return (
    <Surface elevation={1} padding="sm">
      <SurfaceHeader
        icon={<MessageSquare className="h-4 w-4" />}
        title="Sessões"
        subtitle="Conversas ativas com agentes"
      />
      {children}
    </Surface>
  );
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
      <WidgetShell>
        <div className="mt-3 space-y-1.5">
          <div className="nx-shimmer h-8 rounded-lg" />
          <div className="nx-shimmer h-8 rounded-lg" />
          <div className="nx-shimmer h-8 rounded-lg" />
        </div>
      </WidgetShell>
    );
  }

  if (error && sessions.length === 0) {
    return (
      <WidgetShell>
        <div className="mt-3" role="status" aria-live="polite">
          <EmptyState
            compact
            icon={<XCircle className="h-5 w-5" />}
            title="Sessões indisponíveis"
            hint={error}
          />
        </div>
      </WidgetShell>
    );
  }

  const active = sessions.filter((s) => s.status === "active").length;
  const idle = sessions.filter((s) => s.status === "idle").length;

  return (
    <Surface elevation={1} padding="sm">
      <SurfaceHeader
        icon={<MessageSquare className="h-4 w-4" />}
        title="Sessões"
        subtitle="Conversas ativas com agentes"
        action={
          <div className="flex items-center gap-1.5 text-[10px]">
            <Badge tone="success">{active} ativas</Badge>
            {idle > 0 && <Badge tone="warning">{idle} inativas</Badge>}
          </div>
        }
      />

      {sessions.length === 0 ? (
        <div className="mt-3">
          <EmptyState
            compact
            icon={<MessageSquare className="h-5 w-5" />}
            title="Sem sessões ativas"
            hint="Inicia uma conversa no painel de chat para veres sessões aqui."
          />
        </div>
      ) : (
        <ul
          className="nx-inset mt-3 max-h-64 divide-y divide-[var(--nx-line)] overflow-y-auto rounded-lg thin-scrollbar"
          aria-label="Lista de sessões"
        >
          {sessions.slice(0, 12).map((s) => (
            <li key={s.id} className="flex items-center gap-2 px-2.5 py-1.5">
              <StatusDot tone={STATUS_TONE[s.status]} pulse={s.status === "active"} />
              <span className="font-mono text-[10px] text-nexus-faint">{s.id.slice(0, 6)}</span>
              <span className="flex-1 truncate text-[11px] text-nexus-text" title={s.title || s.mode}>
                {s.title || s.mode}
              </span>
              <span className="text-[10px] tabular-nums text-nexus-muted">
                {durationMinutes(s.started_at)}m
              </span>
              <Badge tone={STATUS_TONE[s.status]}>{STATUS_LABEL_PT[s.status]}</Badge>
              <button
                type="button"
                onClick={() => terminate(s.id)}
                disabled={terminating === s.id}
                aria-label={`Terminar sessão ${s.id}`}
                className="rounded p-1 text-nexus-faint hover:bg-rose-500/10 hover:text-rose-400 disabled:opacity-50"
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

      <div className="mt-2 flex items-center justify-between text-[10px] text-nexus-faint">
        <span>
          <Power className="inline h-3 w-3" aria-hidden /> Auto-atualização 5s
        </span>
        <span className="tabular-nums">{sessions.length} total</span>
      </div>
    </Surface>
  );
}
