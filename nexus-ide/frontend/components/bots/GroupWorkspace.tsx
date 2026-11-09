"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { ArrowLeft, PanelRight, Plus, Send, Square, Users, X } from "lucide-react";
import { apiUrl } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";
import type { Bot } from "../../lib/bots";
import { groupEquivalentErrors, type GroupTranscriptMessage } from "../../lib/groupIncidents";
import { AssistantMarkdown } from "../chat/MessageBubble";
import { useThemeStore } from "../../stores/themeStore";
import { BotAvatar } from "./botsUi";
import GroupContextPanel from "./GroupContextPanel";
import GroupIncidentCard from "./GroupIncidentCard";

type Group = { id: string; name: string; bot_ids: string[]; last_message: string | null };
type GroupMessage = GroupTranscriptMessage;
type GroupEvent = { type: string; message?: GroupMessage; bot_id?: string; bot_name?: string; content?: string; status?: string; reason?: string };
type RunSummary = { id: string; status: string };

async function groupRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(apiUrl(path), init);
  if (!response.ok) {
    let detail = `Erro ${response.status}`;
    try { const body = await response.json() as { detail?: unknown }; if (typeof body.detail === "string") detail = body.detail; } catch { /* Keep the HTTP status. */ }
    throw new Error(detail);
  }
  return await response.json() as T;
}

function executionLabel(busy: boolean, status: string, failed: boolean, runStatus: string | null): string {
  if (busy || runStatus === "running" || runStatus === "pending") return "Em execução";
  if (runStatus === "cancelling") return "A cancelar";
  if (/paragem/i.test(status) || runStatus === "cancelled") return "Cancelada";
  if (/conclu/i.test(status) || runStatus === "completed") return "Concluída";
  if (/interrompid|falh|erro/i.test(status) || failed || runStatus === "failed" || runStatus === "interrupted") return "Falhou";
  if (status.trim()) return status;
  return "Em espera";
}

export default function GroupWorkspace({
  bots,
  onBack,
  onOpenBot,
}: {
  bots: Bot[];
  onBack: () => void;
  onOpenBot?: (botId: string) => void;
}) {
  const theme = useThemeStore((state) => state.theme);
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(true);
  const [selected, setSelected] = useState("");
  const [messages, setMessages] = useState<GroupMessage[]>([]);
  const [name, setName] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [historyReady, setHistoryReady] = useState(false);
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [before, setBefore] = useState<string | null>(null);
  const [olderLoading, setOlderLoading] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [partial, setPartial] = useState<{ name: string; content: string } | null>(null);
  const [listOpen, setListOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const [runStatus, setRunStatus] = useState<string | null>(null);
  const [modelBotIds, setModelBotIds] = useState<string[] | null>(null);
  const abort = useRef<AbortController | null>(null);
  const scrollRegion = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const preserveHeight = useRef<number | null>(null);
  const activeGroup = useRef("");
  const selectedGroup = groups.find((group) => group.id === selected);
  const configured = bots.filter((bot) => !bot.archived && bot.provider && bot.model);
  const conversationOpen = Boolean(selected || creating);
  const timeline = useMemo(() => groupEquivalentErrors(messages), [messages]);
  const lastUser = [...messages].reverse().find((message) => message.role === "user") ?? null;
  const endsInFailure = timeline.length > 0 && timeline[timeline.length - 1]?.kind === "incident";
  const phase = executionLabel(busy, status, endsInFailure, runStatus);

  const refreshGroups = useCallback(async () => {
    const data = await groupRequest<{ groups: Group[] }>("/api/bot-groups");
    setGroups(data.groups);
  }, []);
  const refreshMessages = useCallback(async (groupId: string, resetPage = true) => {
    const data = await groupRequest<{ messages: GroupMessage[]; has_more?: boolean; next_before?: string | null }>(`/api/bot-groups/${encodeURIComponent(groupId)}/messages`);
    if (activeGroup.current === groupId) {
      setMessages((current) => { const recent = new Set(data.messages.map((item) => item.id)); return [...current.filter((item) => !recent.has(item.id)), ...data.messages]; });
      if (resetPage) { setHasMore(Boolean(data.has_more)); setBefore(data.next_before ?? null); }
    }
  }, []);
  useEffect(() => {
    let alive = true;
    void refreshGroups().catch((reason) => { if (alive) setError(reason instanceof Error ? reason.message : "Não foi possível carregar os grupos."); }).finally(() => { if (alive) setGroupsLoading(false); });
    return () => { alive = false; abort.current?.abort(); };
  }, [refreshGroups]);
  useEffect(() => {
    activeGroup.current = selected;
    setMessages([]); setError(""); setPartial(null); setHistoryReady(false); setStatus(""); setHasMore(false); setBefore(null); setRunStatus(null); follow.current = true;
    if (!selected) return;
    const wide = typeof window.matchMedia === "function" && window.matchMedia("(min-width: 1440px)").matches;
    setContextOpen(wide);
    setListOpen(false);
    let alive = true;
    setLoading(true);
    void refreshMessages(selected).then(() => { if (alive) setHistoryReady(true); }).catch((reason) => { if (alive) setError(reason instanceof Error ? reason.message : "Não foi possível carregar o histórico."); }).finally(() => { if (alive) setLoading(false); });
    void groupRequest<{ runs: RunSummary[] }>(`/api/bot-groups/${encodeURIComponent(selected)}/runs`)
      .then((data) => {
        if (!alive) return;
        const active = data.runs.find((run) => run.status === "running" || run.status === "pending" || run.status === "cancelling");
        setRunStatus(active?.status ?? data.runs[0]?.status ?? null);
      })
      .catch(() => { if (alive) setRunStatus(null); });
    return () => { alive = false; };
  }, [selected, refreshMessages, historyAttempt]);
  useEffect(() => {
    const el = scrollRegion.current;
    if (!el) return;
    if (preserveHeight.current !== null) { el.scrollTop += el.scrollHeight - preserveHeight.current; preserveHeight.current = null; }
    else if (follow.current) el.scrollTop = el.scrollHeight;
  }, [messages, partial, selected]);

  async function loadOlder() {
    if (!selected || !before || olderLoading || busy) return;
    setOlderLoading(true);
    try {
      const data = await groupRequest<{ messages: GroupMessage[]; has_more: boolean; next_before: string | null }>(`/api/bot-groups/${encodeURIComponent(selected)}/messages?before=${encodeURIComponent(before)}`);
      if (activeGroup.current !== selected) return;
      preserveHeight.current = scrollRegion.current?.scrollHeight ?? null;
      setMessages((current) => { const known = new Set(current.map((item) => item.id)); return [...data.messages.filter((item) => !known.has(item.id)), ...current]; });
      setHasMore(data.has_more); setBefore(data.next_before);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível carregar mensagens anteriores."); }
    finally { setOlderLoading(false); }
  }

  async function create(event: FormEvent) {
    event.preventDefault(); if (saving) return; setSaving(true); setError("");
    try {
      const group = await groupRequest<Group>("/api/bot-groups", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, bot_ids: members }) });
      setGroups((current) => [group, ...current]); setSelected(group.id); setCreating(false); setName(""); setMembers([]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível criar o grupo."); }
    finally { setSaving(false); }
  }
  async function send(override?: string) {
    const content = (override ?? draft).trim();
    if (busy && /^(parar|para|stop|cancelar|cancela)[.!\s]*$/i.test(content)) { setDraft(""); abort.current?.abort(); return; }
    if (!selected || !content || busy || abort.current || loading || !historyReady) return;
    const groupId = selected;
    const controller = new AbortController(); abort.current = controller;
    setBusy(true); setError(""); setStatus("A iniciar conversa…"); setPartial(null); if (!override) setDraft("");
    try {
      const response = await authenticatedFetch(apiUrl(`/api/bot-groups/${encodeURIComponent(groupId)}/messages`), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: content }), signal: controller.signal });
      if (!response.ok || !response.body) throw new Error(`Não foi possível iniciar a conversa (erro ${response.status}).`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      while (true) {
        const chunk = await reader.read();
        buffer = (buffer + decoder.decode(chunk.value, { stream: !chunk.done })).replace(/\r\n/g, "\n");
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
          const data = frame.split("\n").filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
          if (!data) continue;
          const event = JSON.parse(data) as GroupEvent;
          if (event.type === "user_message" && event.message) setMessages((current) => [...current, event.message!]);
          if (event.type === "agent_started") { setStatus(`${event.bot_name || "Bot"} está a responder…`); setPartial({ name: event.bot_name || "Bot", content: "" }); }
          if (event.type === "token") setPartial((current) => ({ name: current?.name || event.bot_name || "Bot", content: (current?.content || "") + (event.content || "") }));
          if ((event.type === "agent_message" || event.type === "agent_error") && event.message) { setMessages((current) => [...current, event.message!]); setPartial(null); }
          if (event.type === "done") { completed = true; setStatus(event.status === "completed" ? "Conversa concluída." : event.status === "partial" ? "Conversa interrompida por falha de um bot. Vê as mensagens e volta a tentar." : event.reason ? `${event.reason} As respostas já emitidas ficam guardadas.` : "A conversa terminou sem confirmação de sucesso."); }
          if (event.type === "error" || event.type === "group_error") throw new Error(event.content || "A conversa foi interrompida.");
        }
        if (chunk.done) break;
      }
      if (!completed) throw new Error("A ligação terminou antes da confirmação. Verifica o histórico antes de voltar a enviar.");
    } catch (reason) {
      if (controller.signal.aborted) setStatus("Paragem pedida. As respostas concluídas ficam no histórico.");
      else { setError(reason instanceof Error ? reason.message : "Não foi possível enviar a mensagem."); if (!override) setDraft((current) => current || content); }
    } finally {
      abort.current = null; setPartial(null);
      try { await refreshMessages(groupId, false); }
      catch { setHistoryReady(false); setError("Não foi possível atualizar o histórico. Carrega-o novamente antes de continuar."); }
      try { await refreshGroups(); } catch { /* The conversation history remains available. */ }
      setBusy(false);
    }
  }

  const participants = selectedGroup?.bot_ids.map((id) => bots.find((bot) => bot.id === id)).filter((bot): bot is Bot => Boolean(bot)) ?? [];
  const modelCandidates = (modelBotIds && modelBotIds.length > 0
    ? bots.filter((bot) => modelBotIds.includes(bot.id))
    : participants);

  return <div className="relative flex h-full min-h-0 bg-[#101116] text-zinc-100">
    {conversationOpen && listOpen && (
      <button type="button" className="fixed inset-0 z-30 bg-black/55 lg:hidden" aria-label="Fechar lista de grupos" onClick={() => setListOpen(false)} />
    )}
    <section
      aria-label="Grupos de bots"
      className={`${conversationOpen && !listOpen ? "hidden lg:flex" : "flex"} min-h-0 shrink-0 flex-col border-r border-white/10 bg-[#13141a] ${
        conversationOpen && listOpen
          ? "fixed inset-y-0 left-0 z-40 w-[min(100%,20rem)] shadow-2xl lg:static lg:z-auto lg:w-[280px] lg:shadow-none"
          : "w-full lg:w-[280px]"
      }`}
    >
      <div className="border-b border-white/10 p-4 pl-14 lg:pl-4">
        <button type="button" onClick={onBack} disabled={busy} className="mb-4 flex items-center gap-2 text-xs text-zinc-400 hover:text-white disabled:opacity-40"><ArrowLeft size={15} /> Bots</button>
        <div className="flex items-center justify-between gap-2">
          <div><p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-violet-300">NEXUS</p><h1 className="mt-1 text-xl font-semibold">Grupos</h1></div>
          <button type="button" aria-label="Criar grupo" disabled={busy} onClick={() => { setCreating(true); setSelected(""); setListOpen(false); }} className="rounded-xl border border-white/10 p-2.5 hover:bg-white/10"><Plus size={18} /></button>
        </div>
        <p className="mt-2 text-xs leading-5 text-zinc-400">Reúne os teus bots numa conversa partilhada.</p>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {groupsLoading && <p role="status" className="p-4 text-sm text-zinc-400">A carregar grupos…</p>}
        {!groupsLoading && error && !selected && !creating && <div role="alert" className="m-2 rounded-xl border border-red-400/20 bg-red-400/5 p-3 text-sm text-red-200"><p>{error}</p><button type="button" className="mt-2 text-xs font-medium underline" onClick={() => { setGroupsLoading(true); setError(""); void refreshGroups().catch((reason) => setError(reason instanceof Error ? reason.message : "Não foi possível carregar os grupos.")).finally(() => setGroupsLoading(false)); }}>Tentar novamente</button></div>}
        {!groupsLoading && !error && groups.length === 0 && <p className="p-4 text-sm text-zinc-400">Ainda não tens grupos. Cria um para começar.</p>}
        {groups.map((group) => <button type="button" key={group.id} disabled={busy} onClick={() => { setCreating(false); setSelected(group.id); setListOpen(false); }} aria-current={selected === group.id ? "true" : undefined} className={`flex w-full items-center gap-3 rounded-xl p-3 text-left disabled:opacity-50 ${selected === group.id ? "bg-white/10" : "hover:bg-white/5"}`}><span className="rounded-xl bg-violet-400/10 p-2 text-violet-300"><Users size={16} /></span><span className="min-w-0"><span className="block truncate text-sm font-medium">{group.name}</span><span className="block truncate text-xs text-zinc-400">{group.last_message || `${group.bot_ids.length} participantes`}</span></span></button>)}
      </div>
    </section>

    <section aria-label="Conversa de grupo" className={`${conversationOpen ? "flex" : "hidden lg:flex"} min-w-0 flex-1 flex-col`}>
      {creating ? <form onSubmit={(event) => void create(event)} className="mx-auto w-full max-w-xl overflow-y-auto p-6 pl-14 lg:pl-6"><button type="button" onClick={() => setCreating(false)} className="mb-6 text-sm text-zinc-400 hover:text-white">← Voltar aos grupos</button><h2 className="text-xl font-semibold">Criar grupo</h2><p className="mt-2 text-sm text-zinc-400">Escolhe entre 2 e 6 bots configurados. Cada um usa o seu próprio modelo.</p><label className="mt-6 block text-sm">Nome do grupo<input value={name} required maxLength={80} onChange={(event) => setName(event.target.value)} className="mt-2 w-full rounded-xl border border-white/10 bg-white/5 px-4 py-3 outline-none focus:border-violet-400" /></label><fieldset className="mt-6 space-y-2"><legend className="mb-3 text-sm font-medium">Participantes ({members.length}/6)</legend>{configured.map((bot) => <label key={bot.id} className="flex items-center gap-3 rounded-xl border border-white/10 p-3 text-sm"><input type="checkbox" checked={members.includes(bot.id)} disabled={members.length >= 6 && !members.includes(bot.id)} onChange={(event) => setMembers((current) => event.target.checked ? [...current, bot.id] : current.filter((id) => id !== bot.id))} /><span><span className="block font-medium">{bot.name}</span><span className="text-xs text-zinc-400">{bot.description || "Função não descrita"} · {bot.provider} · {bot.model}</span></span></label>)}{configured.length < 2 && <p className="text-sm text-amber-200">Configura pelo menos dois bots com provedor e modelo.</p>}</fieldset><button disabled={saving || members.length < 2 || !name.trim()} className="mt-6 rounded-xl bg-violet-500 px-4 py-3 text-sm font-medium disabled:opacity-40">Criar grupo</button>{error && <p role="alert" className="mt-4 text-sm text-red-300">{error}</p>}</form> : selectedGroup ? <>
        <header className="relative z-50 flex items-center gap-3 border-b border-white/10 bg-[#101116] px-3 py-3 pl-14 lg:pl-4">
          <button type="button" onClick={() => { setListOpen(true); setContextOpen(false); }} aria-label="Abrir lista de grupos" className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 px-2 py-1.5 text-xs text-zinc-200 hover:bg-white/5 lg:hidden"><ArrowLeft size={14} /> Grupos</button>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-sm font-semibold">{selectedGroup.name}</h2>
            <span className="mt-0.5 block truncate text-[11px] text-zinc-400">{participants.map((bot) => bot.name).join(" · ") || "Participantes indisponíveis"} · {phase}</span>
          </div>
          <div className="hidden items-center sm:flex">{participants.slice(0, 4).map((bot) => <span key={bot.id} className="-ml-1.5 first:ml-0" title={`${bot.name}: ${bot.description || "Função não descrita"}`}><BotAvatar name={bot.name} id={bot.id} compact /></span>)}</div>
          <button type="button" aria-pressed={contextOpen} aria-label={contextOpen ? "Fechar painel de contexto" : "Abrir painel de contexto"} onClick={() => setContextOpen((open) => !open)} className="rounded-lg border border-white/10 p-2 text-zinc-300 hover:bg-white/5"><PanelRight size={16} /></button>
        </header>
        <div ref={scrollRegion} onScroll={(event) => { const el = event.currentTarget; follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; }} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-5 sm:px-6" aria-label="Histórico do grupo">
          {hasMore && <button type="button" disabled={olderLoading || busy} onClick={() => void loadOlder()} className="mx-auto block rounded-lg px-3 py-2 text-xs text-violet-300 hover:bg-white/5 disabled:opacity-40">{olderLoading ? "A carregar…" : "Carregar mensagens anteriores"}</button>}
          {loading && <p role="status" className="text-sm text-zinc-400">A carregar histórico…</p>}
          {!loading && messages.length === 0 && <p className="mx-auto mt-16 max-w-md text-center text-sm leading-6 text-zinc-400">Envia uma mensagem para iniciar a conversa entre os participantes. O estado da execução aparece no cabeçalho e no painel de contexto.</p>}
          {timeline.map((item) => item.kind === "incident" ? (
            <GroupIncidentCard key={item.id} incident={item} busy={busy} onRetry={(content) => void send(content)} onChooseModel={(ids) => setModelBotIds(ids)} />
          ) : (
            <article key={item.message.id} className={`mx-auto max-w-3xl rounded-2xl border p-4 ${item.message.role === "user" ? "border-violet-400/20 bg-violet-400/10" : "border-white/10 bg-white/[0.03]"}`}>
              <div className="mb-2 flex items-center gap-2">
                <p className="text-xs font-semibold text-violet-300">{item.message.role === "user" ? "Tu" : item.message.bot_name || "Bot"}</p>
                {item.message.role === "assistant" ? <span className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">Agente</span> : null}
                {item.message.role === "user" ? <span className="text-[10px] font-medium uppercase tracking-wide text-zinc-500">Utilizador</span> : null}
              </div>
              <div className="break-words text-sm leading-6 text-zinc-200"><AssistantMarkdown text={item.message.content} theme={theme === "light" ? "light" : "dark"} /></div>
            </article>
          ))}
          {partial && <article className="mx-auto max-w-3xl rounded-2xl border border-white/10 bg-white/[0.03] p-4"><p className="mb-2 text-xs font-semibold text-violet-300">{partial.name} · a responder</p><div className="text-sm leading-6"><AssistantMarkdown text={partial.content || "…"} theme={theme === "light" ? "light" : "dark"} /></div></article>}
          {error && <p role="alert" className="mx-auto max-w-3xl rounded-xl border border-red-400/20 p-3 text-sm text-red-300">{error}{!historyReady && <button type="button" onClick={() => setHistoryAttempt((value) => value + 1)} className="ml-3 underline">Tentar carregar novamente</button>}</p>}
          <p role="status" className="mx-auto max-w-3xl text-xs text-zinc-400">{status}</p>
        </div>
        <div className="border-t border-white/10 p-3 sm:p-4">
          <div className="mx-auto max-w-3xl">
            <p className="mb-2 text-[11px] leading-5 text-zinc-500">Sem ferramentas nesta conversa: respostas por ordem até consenso, numa falha, ou no limite de voltas e tempo do grupo.</p>
            <div className="flex items-end gap-2 rounded-2xl border border-white/10 bg-white/5 p-2 focus-within:border-violet-400/60">
              <textarea aria-label="Mensagem para o grupo" maxLength={12000} value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }} rows={2} disabled={loading || !historyReady} placeholder={busy ? "Escreve parar para interromper…" : "Escreve para o grupo…"} className="max-h-40 min-h-12 flex-1 resize-y bg-transparent p-2 text-sm outline-none" />
              {busy ? <button type="button" onClick={() => abort.current?.abort()} aria-label="Pedir paragem do grupo" className="rounded-xl bg-zinc-700 p-3"><Square size={16} /></button> : <button type="button" disabled={!draft.trim() || loading || !historyReady} onClick={() => void send()} aria-label="Enviar ao grupo" className="rounded-xl bg-violet-500 p-3 disabled:opacity-40"><Send size={16} /></button>}
            </div>
            <p className="mt-2 text-xs text-zinc-500">Enter envia · Shift+Enter cria uma linha</p>
          </div>
        </div>
      </> : <div className="m-auto max-w-md px-6 text-center"><Users size={36} className="mx-auto text-violet-300" /><h2 className="mt-4 text-xl font-semibold">Conversas em grupo</h2><p className="mt-2 text-sm leading-6 text-zinc-400">Cria um grupo para reunir os bots que já configuraste. Cada um responde com o seu provedor e modelo.</p><button type="button" onClick={() => setCreating(true)} className="mt-5 rounded-xl bg-violet-500 px-4 py-2.5 text-sm">Criar grupo</button>{error && <p role="alert" className="mt-4 text-sm text-red-300">{error}</p>}</div>}
    </section>

    {contextOpen && selectedGroup && (
      <>
        <button type="button" className="fixed inset-0 z-30 bg-black/55 min-[1440px]:hidden" aria-label="Fechar painel de contexto" onClick={() => setContextOpen(false)} />
        <div className="fixed inset-y-0 right-0 z-40 w-[min(100%,22rem)] min-[1440px]:static min-[1440px]:z-auto min-[1440px]:w-[320px] min-[1440px]:shrink-0">
          <GroupContextPanel
            group={selectedGroup}
            bots={bots}
            objective={lastUser?.content || "Ainda sem objetivo nesta conversa."}
            executionLabel={phase}
            onClose={() => setContextOpen(false)}
          />
        </div>
      </>
    )}

    {modelBotIds !== null && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="presentation" onMouseDown={() => setModelBotIds(null)}>
        <div role="dialog" aria-modal="true" aria-labelledby="group-model-title" className="w-full max-w-md rounded-2xl border border-white/10 bg-[#15161d] p-5" onMouseDown={(event) => event.stopPropagation()}>
          <div className="flex items-start justify-between gap-3">
            <h2 id="group-model-title" className="text-base font-semibold">Escolher outro modelo</h2>
            <button type="button" aria-label="Fechar escolha de modelo" onClick={() => setModelBotIds(null)} className="rounded-lg p-1 text-zinc-400 hover:text-white"><X size={16} /></button>
          </div>
          <p className="mt-2 text-sm leading-6 text-zinc-400">A troca não é automática. Abre o bot e escolhe outro modelo que o provedor permita. A configuração global continua em Definições.</p>
          <ul className="mt-4 space-y-2">
            {modelCandidates.length === 0 && <li className="text-sm text-zinc-400">Não há bots identificados neste incidente.</li>}
            {modelCandidates.map((bot) => (
              <li key={bot.id} className="rounded-xl border border-white/10 p-3 text-sm">
                <p className="font-medium">{bot.name}</p>
                <p className="mt-1 break-all text-xs text-zinc-400">{bot.provider || "Provedor não configurado"} · {bot.model || "Modelo não configurado"}</p>
                <p className="mt-1 text-xs text-zinc-500">{bot.description || "Função não descrita"}</p>
                {onOpenBot ? (
                  <button type="button" className="mt-2 text-xs font-medium text-violet-300 hover:text-violet-200" onClick={() => { setModelBotIds(null); onOpenBot(bot.id); }}>Abrir {bot.name}</button>
                ) : (
                  <Link href="/bots" className="mt-2 inline-block text-xs font-medium text-violet-300">Voltar aos bots</Link>
                )}
              </li>
            ))}
          </ul>
          <Link href="/settings" className="mt-4 inline-block text-xs text-violet-300 hover:text-violet-200">Abrir definições do fornecedor</Link>
        </div>
      </div>
    )}
  </div>;
}
