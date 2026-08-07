"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity, Bot, RefreshCw, Wifi, WifiOff } from "lucide-react";
import { apiUrl, authHeaders } from "../../lib/api";

type Message = {
  id: string;
  agent: string;
  content: string;
  timestamp: string;
  type: string;
};

type Agent = {
  id: string;
  name: string;
  status?: string;
};

function colorFor(value: string): string {
  const palette = ["#8b5cf6", "#06b6d4", "#10b981", "#f59e0b", "#ec4899", "#f97316"];
  let hash = 0;
  for (let i = 0; i < value.length; i += 1) hash = (hash * 31 + value.charCodeAt(i)) | 0;
  return palette[Math.abs(hash) % palette.length];
}

function agentFromPayload(value: Record<string, unknown>): Agent | null {
  const id = String(value.id ?? value.agent_id ?? value.name ?? "");
  const name = String(value.name ?? value.agent_id ?? value.id ?? "");
  return id && name ? { id, name, status: typeof value.status === "string" ? value.status : undefined } : null;
}

export default function SimpleDashboard() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [agents, setAgents] = useState<Agent[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    const loadAgents = async () => {
      try {
        const response = await fetch(apiUrl("/api/agents/instances"), { headers: authHeaders() });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json() as { agents?: unknown[] };
        const received = (payload.agents ?? [])
          .filter((item): item is Record<string, unknown> => typeof item === "object" && item !== null)
          .map(agentFromPayload)
          .filter((agent): agent is Agent => agent !== null);
        if (active) setAgents(received);
      } catch (cause) {
        if (active) setError(cause instanceof Error ? cause.message : "Não foi possível carregar os agentes.");
      } finally {
        if (active) setLoading(false);
      }
    };

    void loadAgents();
    return () => { active = false; };
  }, []);

  useEffect(() => {
    const stream = new EventSource(apiUrl("/api/autonomous-tasks/stream"));
    stream.onopen = () => setConnected(true);
    stream.onerror = () => setConnected(false);
    stream.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data) as Record<string, unknown>;
        if (!data.type || data.type === "heartbeat") return;
        const task = typeof data.task === "object" && data.task !== null ? data.task as Record<string, unknown> : {};
        const source = String(data.agent ?? task.agent ?? "Sistema");
        const content = String(data.content ?? task.goal ?? data.message ?? "");
        if (!content) return;
        setMessages((previous) => [
          ...previous.slice(-49),
          { id: crypto.randomUUID(), agent: source, content, timestamp: new Date().toISOString(), type: String(data.type) },
        ]);
      } catch {
        // Ignore malformed SSE frames; they are not user-visible events.
      }
    };
    return () => stream.close();
  }, []);

  const visibleMessages = useMemo(
    () => selectedAgent ? messages.filter((message) => message.agent === selectedAgent) : messages,
    [messages, selectedAgent],
  );

  if (loading) {
    return <div className="flex min-h-screen items-center justify-center bg-slate-950 text-sm text-slate-400">A carregar dados do sistema…</div>;
  }

  return (
    <main className="min-h-screen bg-slate-950 px-6 py-8 text-slate-100">
      <div className="mx-auto max-w-6xl">
        <header className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-bold">Atividade de agentes</h1>
            <p className="mt-1 text-sm text-slate-400">Eventos e estado recebidos do backend.</p>
          </div>
          <span className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-medium ${
            connected ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300" : "border-slate-700 bg-slate-900 text-slate-400"
          }`}>
            {connected ? <Wifi className="h-3.5 w-3.5" /> : <WifiOff className="h-3.5 w-3.5" />}
            {connected ? "Em direto" : "Sem ligação"}
          </span>
        </header>

        {error ? <div className="mb-5 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-200">{error}</div> : null}

        <section className="mb-5 flex flex-wrap gap-2">
          <button type="button" onClick={() => setSelectedAgent(null)} className={`rounded-full px-3 py-1.5 text-xs ${selectedAgent === null ? "bg-violet-600 text-white" : "bg-slate-800 text-slate-300 hover:bg-slate-700"}`}>Todos</button>
          {agents.map((agent) => (
            <button key={agent.id} type="button" onClick={() => setSelectedAgent(agent.name)} className={`flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs ${selectedAgent === agent.name ? "border-violet-400 bg-violet-500/15 text-white" : "border-slate-700 bg-slate-900 text-slate-300 hover:bg-slate-800"}`}>
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colorFor(agent.id) }} />
              {agent.name}
            </button>
          ))}
        </section>

        <div className="grid gap-5 lg:grid-cols-[1.7fr_1fr]">
          <section className="rounded-xl border border-slate-800 bg-slate-900/50">
            <div className="flex items-center justify-between border-b border-slate-800 px-5 py-3">
              <div className="flex items-center gap-2 text-sm font-semibold"><Activity className="h-4 w-4 text-violet-300" />Eventos recentes</div>
              <span className="text-xs text-slate-400">{visibleMessages.length}</span>
            </div>
            <div className="max-h-[600px] space-y-2 overflow-y-auto p-3">
              {visibleMessages.length ? visibleMessages.map((message) => (
                <article key={message.id} className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
                  <div className="mb-1 flex items-center justify-between gap-3 text-xs">
                    <span className="font-semibold" style={{ color: colorFor(message.agent) }}>{message.agent}</span>
                    <span className="shrink-0 text-slate-500">{new Date(message.timestamp).toLocaleTimeString()}</span>
                  </div>
                  <p className="break-words text-sm text-slate-300">{message.content}</p>
                </article>
              )) : <p className="px-2 py-10 text-center text-sm text-slate-500">Ainda não chegaram eventos reais.</p>}
            </div>
          </section>

          <section className="rounded-xl border border-slate-800 bg-slate-900/50 p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Bot className="h-4 w-4 text-violet-300" />Agentes registados</div>
            {agents.length ? <div className="space-y-2">{agents.map((agent) => (
              <div key={agent.id} className="flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
                <span className="h-2.5 w-2.5 rounded-full" style={{ backgroundColor: colorFor(agent.id) }} />
                <div className="min-w-0 flex-1"><div className="truncate text-sm font-medium">{agent.name}</div><div className="text-xs text-slate-500">{agent.status || "estado não reportado"}</div></div>
              </div>
            ))}</div> : <p className="py-8 text-center text-sm text-slate-500">O backend não reportou agentes.</p>}
            <button type="button" onClick={() => window.location.reload()} className="mt-4 flex items-center gap-1.5 text-xs text-violet-300 hover:text-violet-200"><RefreshCw className="h-3.5 w-3.5" />Atualizar</button>
          </section>
        </div>
      </div>
    </main>
  );
}
