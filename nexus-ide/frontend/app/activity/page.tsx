"use client";

import { useRouter } from "next/navigation";
import AppShell from "../../components/layout/AppShell";
import { useChatSessions } from "../../hooks/useChatSessions";

export default function ActivityPage() {
  const router = useRouter();
  const sessions = useChatSessions();

  return (
    <AppShell title="Atividade">
      <div className="mx-auto max-w-4xl">
        <h1 className="text-xl font-semibold">Atividade</h1>
        <p className="mt-1 text-sm text-nexus-muted">Sessões persistidas. Abrir uma sessão recupera o histórico guardado.</p>
        {sessions.error && <p className="mt-4 text-sm text-rose-300">{sessions.error}</p>}
        {!sessions.loading && sessions.sessions.length === 0 && !sessions.error && (
          <p className="mt-6 rounded-xl border border-white/10 p-4 text-sm text-nexus-muted">
            Ainda não há sessões. Uma conversa no Chat cria a primeira.
          </p>
        )}
        <ul className="mt-4 divide-y divide-white/8 overflow-hidden rounded-xl border border-white/10">
          {sessions.sessions.map((session) => (
            <li key={session.id}>
              <button
                type="button"
                onClick={() => {
                  sessions.setCurrentId(session.id);
                  router.push("/");
                }}
                className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left hover:bg-white/[0.04]"
              >
                <span>
                  <span className="block text-sm font-medium">{session.title || "Sem título"}</span>
                  <span className="font-mono text-[11px] text-nexus-faint">{session.id}</span>
                </span>
                <span className="text-right text-[11px] text-nexus-muted">
                  <span className="block">{session.message_count ?? 0} mensagens</span>
                  <span className="block">{session.last_active_at ? new Date(session.last_active_at).toLocaleString("pt-PT") : "—"}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </AppShell>
  );
}
