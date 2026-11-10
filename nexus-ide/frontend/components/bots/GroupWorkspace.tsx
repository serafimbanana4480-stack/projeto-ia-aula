"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import Link from "next/link";
import { ArrowLeft, PanelRight, Plus, Users, X } from "lucide-react";
import { apiUrl } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";
import type { Bot } from "../../lib/bots";
import { groupEquivalentErrors, type GroupTranscriptMessage } from "../../lib/groupIncidents";
import { AssistantMarkdown } from "../chat/MessageBubble";
import { useThemeStore } from "../../stores/themeStore";
import GroupIncidentCard from "./GroupIncidentCard";
import ContextTabs from "./chat/ContextTabs";
import { ParticipantStrip, RunCard } from "./chat/collaboration";
import { IdentityMark, StackedMarks } from "./chat/identity";
import { RoomComposer } from "./chat/Composer";
import { DayRule, GroupTurn, HandoffRule, JumpToLatest, TypingRow } from "./chat/messages";
import { focusRun, previousAgentSpeaker, quoteDraft, runIsHot, type RoomRun } from "./chat/model";
import { RosterRow, RosterSearch, SectionLabel } from "./chat/Roster";
import { useRoomMemory } from "./chat/storage";

type Group = { id: string; name: string; bot_ids: string[]; last_message: string | null };
type GroupMessage = GroupTranscriptMessage;
type GroupEvent = { type: string; message?: GroupMessage; bot_id?: string; bot_name?: string; content?: string; status?: string; reason?: string };

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
  onSelectBot,
  initialGroupId = "",
}: {
  bots: Bot[];
  onBack: () => void;
  onOpenBot?: (botId: string) => void;
  onSelectBot?: (botId: string) => void;
  initialGroupId?: string;
}) {
  const theme = useThemeStore((state) => state.theme);
  const memory = useRoomMemory();
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(true);
  const [selected, setSelected] = useState("");
  const [messages, setMessages] = useState<GroupMessage[]>([]);
  const [name, setName] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [draft, setDraft] = useState("");
  const [focusTick, setFocusTick] = useState(0);
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
  const [runs, setRuns] = useState<RoomRun[]>([]);
  const [query, setQuery] = useState("");
  const [away, setAway] = useState(false);
  const [unseen, setUnseen] = useState(0);
  const [modelBotIds, setModelBotIds] = useState<string[] | null>(null);
  const abort = useRef<AbortController | null>(null);
  const scrollRegion = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const seenCount = useRef(0);
  const preserveHeight = useRef<number | null>(null);
  const activeGroup = useRef("");
  const selectedGroup = groups.find((group) => group.id === selected);
  const configured = bots.filter((bot) => !bot.archived && bot.provider && bot.model);
  const listedBots = bots.filter((bot) => !bot.archived);
  const conversationOpen = Boolean(selected || creating);
  const timeline = useMemo(() => groupEquivalentErrors(messages), [messages]);
  const lastUser = [...messages].reverse().find((message) => message.role === "user") ?? null;
  const endsInFailure = timeline.length > 0 && timeline[timeline.length - 1]?.kind === "incident";
  const active = runs.find((run) => run.status === "running" || run.status === "pending" || run.status === "cancelling");
  const runStatus = active?.status ?? runs[0]?.status ?? null;
  const phase = executionLabel(busy, status, endsInFailure, runStatus);
  const currentRun = focusRun(runs);
  const search = query.trim().toLocaleLowerCase("pt");
  const visibleGroups = groups.filter((group) => `${group.name} ${group.last_message ?? ""}`.toLocaleLowerCase("pt").includes(search));
  const pinnedGroups = visibleGroups.filter((group) => memory.pins.includes(group.id));

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
    if (!initialGroupId) return;
    setCreating(false);
    setSelected(initialGroupId);
  }, [initialGroupId]);

  useEffect(() => {
    let alive = true;
    void refreshGroups().catch((reason) => { if (alive) setError(reason instanceof Error ? reason.message : "Não foi possível carregar os grupos."); }).finally(() => { if (alive) setGroupsLoading(false); });
    return () => { alive = false; abort.current?.abort(); };
  }, [refreshGroups]);

  useEffect(() => {
    activeGroup.current = selected;
    setMessages([]); setError(""); setPartial(null); setHistoryReady(false); setStatus(""); setHasMore(false); setBefore(null); setRuns([]); setAway(false); setUnseen(0); follow.current = true;
    if (!selected) return;
    const wide = typeof window.matchMedia === "function" && window.matchMedia("(min-width: 1440px)").matches;
    setContextOpen(wide);
    setListOpen(false);
    let alive = true;
    let timer = 0;
    setLoading(true);
    const pullRuns = () => {
      void groupRequest<{ runs: RoomRun[] }>(`/api/bot-groups/${encodeURIComponent(selected)}/runs`)
        .then((data) => {
          if (!alive || activeGroup.current !== selected) return;
          setRuns(data.runs);
          if (runIsHot(data.runs) && !timer) timer = window.setInterval(() => { if (alive) pullRuns(); }, 3000);
          if (!runIsHot(data.runs) && timer) { window.clearInterval(timer); timer = 0; }
        })
        .catch(() => { if (alive && activeGroup.current === selected) setRuns([]); });
    };
    void refreshMessages(selected).then(() => { if (alive) setHistoryReady(true); }).catch((reason) => { if (alive) setError(reason instanceof Error ? reason.message : "Não foi possível carregar o histórico."); }).finally(() => { if (alive) setLoading(false); });
    pullRuns();
    return () => { alive = false; if (timer) window.clearInterval(timer); };
  }, [selected, refreshMessages, historyAttempt]);

  useEffect(() => {
    if (!selectedGroup) return;
    memory.markSeen(selectedGroup.id, selectedGroup.last_message ?? "");
  }, [selectedGroup, memory]);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(min-width: 1440px)");
    const closeOverlay = () => { if (!media.matches) setContextOpen(false); };
    media.addEventListener("change", closeOverlay);
    return () => media.removeEventListener("change", closeOverlay);
  }, []);

  useEffect(() => {
    const el = scrollRegion.current;
    if (!el) return;
    if (preserveHeight.current !== null) { el.scrollTop += el.scrollHeight - preserveHeight.current; preserveHeight.current = null; }
    else if (follow.current) el.scrollTop = el.scrollHeight;
  }, [messages, partial, selected]);

  useEffect(() => {
    if (follow.current) { seenCount.current = messages.length; setUnseen(0); }
    else setUnseen(Math.max(0, messages.length - seenCount.current));
  }, [messages.length]);

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
    follow.current = true; setAway(false);
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
  const modelCandidates = (modelBotIds && modelBotIds.length > 0 ? bots.filter((bot) => modelBotIds.includes(bot.id)) : participants);
  const goal = lastUser?.content.replace(/\s+/g, " ").trim() || "Ainda sem objetivo nesta conversa.";
  const quote = (author: string, content: string) => {
    setDraft((current) => quoteDraft(author, content, current));
    setFocusTick((value) => value + 1);
  };
  const replyTo = (author: string) => {
    const mention = `@${author} `;
    setDraft((current) => current.startsWith(mention) ? current : current.trim() ? `${mention}${current}` : mention);
    setFocusTick((value) => value + 1);
  };

  const renderGroup = (group: Group) => (
    <RosterRow
      key={group.id}
      id={group.id}
      name={group.name}
      role={`${group.bot_ids.length} participantes`}
      preview={group.last_message || "Sem mensagens"}
      active={selected === group.id}
      pinned={memory.pins.includes(group.id)}
      unread={memory.unread(group.id, group.last_message ?? "")}
      onSelect={() => { if (busy) return; setCreating(false); setSelected(group.id); setListOpen(false); }}
      onPin={() => memory.togglePin(group.id)}
    />
  );

  return <div className="nx-bot-room relative flex h-full min-h-0">
    {conversationOpen && listOpen && (
      <button type="button" className="fixed inset-0 z-30 bg-black/60 lg:hidden" aria-label="Fechar lista de grupos" onClick={() => setListOpen(false)} />
    )}
    <section
      aria-label="Grupos de bots"
      className={`${conversationOpen && !listOpen ? "hidden lg:flex" : "flex"} min-h-0 shrink-0 flex-col border-r border-[color:var(--nx-line)] bg-[color:var(--nx-surface-1)] ${
        conversationOpen && listOpen
          ? "fixed inset-y-0 left-0 z-40 w-[min(100%,20rem)] shadow-2xl lg:static lg:z-auto lg:w-[300px] lg:shadow-none"
          : "w-full lg:w-[300px]"
      }`}
    >
      <div className="border-b border-[color:var(--nx-line)] px-3 pb-3 pl-14 pt-4 lg:pl-3">
        <button type="button" onClick={onBack} disabled={busy} className="mb-3 flex items-center gap-1.5 text-[12px] text-[color:var(--nx-text-faint)] hover:text-[color:var(--nx-text)] disabled:opacity-40"><ArrowLeft size={14} /> Bots</button>
        <div className="flex items-center justify-between gap-2">
          <div>
            <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-[color:var(--nx-text-faint)]">NEXUS</p>
            <h1 className="text-lg font-semibold tracking-tight">Grupos</h1>
          </div>
          <button type="button" aria-label="Criar grupo" disabled={busy} onClick={() => { setCreating(true); setSelected(""); setListOpen(false); }} className="rounded-lg border border-[color:var(--nx-line)] p-2 hover:bg-[color:var(--nx-surface-3)]"><Plus size={16} /></button>
        </div>
        <p className="mt-1 text-[12px] leading-5 text-[color:var(--nx-text-faint)]">Reúne os teus bots numa conversa partilhada.</p>
        <div className="mt-3"><RosterSearch label="Pesquisar grupos" value={query} onChange={setQuery} /></div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 py-1">
        {groupsLoading && <p role="status" className="p-3 text-[13px] text-[color:var(--nx-text-dim)]">A carregar grupos…</p>}
        {!groupsLoading && error && !selected && !creating && <div role="alert" className="m-2 rounded-xl border border-[color:var(--nx-rose)]/30 p-3 text-[13px] text-[color:var(--nx-rose)]"><p>{error}</p><button type="button" className="mt-2 text-[12px] font-medium underline" onClick={() => { setGroupsLoading(true); setError(""); void refreshGroups().catch((reason) => setError(reason instanceof Error ? reason.message : "Não foi possível carregar os grupos.")).finally(() => setGroupsLoading(false)); }}>Tentar novamente</button></div>}
        {!groupsLoading && !error && groups.length === 0 && <p className="p-3 text-[13px] leading-6 text-[color:var(--nx-text-dim)]">Ainda não tens grupos. Cria um para começar.</p>}
        {pinnedGroups.length > 0 && <SectionLabel>Fixados</SectionLabel>}
        {pinnedGroups.map(renderGroup)}
        <SectionLabel>Grupos</SectionLabel>
        {visibleGroups.filter((group) => !memory.pins.includes(group.id)).map(renderGroup)}
        {onSelectBot && listedBots.length > 0 && (
          <>
            <SectionLabel>Bots</SectionLabel>
            {listedBots.filter((bot) => `${bot.name} ${bot.description}`.toLocaleLowerCase("pt").includes(search)).map((bot) => (
              <RosterRow
                key={bot.id}
                id={bot.id}
                name={bot.name}
                role={bot.description || "Função não descrita"}
                chip={bot.provider || undefined}
                preview={bot.last_message || "Conversa individual"}
                warn={!bot.provider || !bot.model}
                onSelect={() => onSelectBot(bot.id)}
              />
            ))}
          </>
        )}
      </div>
    </section>

    <section aria-label="Conversa de grupo" className={`${conversationOpen ? "flex" : "hidden lg:flex"} min-w-0 flex-1 flex-col`}>
      {creating ? (
        <form onSubmit={(event) => void create(event)} className="mx-auto w-full max-w-xl overflow-y-auto px-4 py-6 pl-14 lg:pl-6">
          <button type="button" onClick={() => setCreating(false)} className="mb-5 text-[13px] text-[color:var(--nx-text-faint)] hover:text-[color:var(--nx-text)]">← Voltar aos grupos</button>
          <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-[color:var(--nx-text-faint)]">Nova sala</p>
          <h2 className="mt-1 text-2xl font-semibold tracking-tight">Criar grupo</h2>
          <p className="mt-2 max-w-md text-[13px] leading-6 text-[color:var(--nx-text-dim)]">Escolhe entre 2 e 6 bots configurados. Cada um usa o seu próprio modelo. A inferência não é verificada ao criar o grupo.</p>
          <label className="mt-6 block text-[13px] font-medium">Nome do grupo
            <input value={name} required maxLength={80} onChange={(event) => setName(event.target.value)} className="mt-2 w-full rounded-xl border border-[color:var(--nx-line-strong)] bg-[color:var(--nx-surface-1)] px-3 py-2.5 text-[14px] outline-none focus:border-[color:var(--nx-accent)]" />
          </label>
          <fieldset className="mt-6 space-y-2">
            <legend className="mb-3 text-[13px] font-medium">Participantes ({members.length}/6)</legend>
            {configured.map((bot) => {
              const checked = members.includes(bot.id);
              return (
                <label key={bot.id} className={`flex items-center gap-3 rounded-xl border p-3 text-[13px] ${checked ? "border-[color:var(--nx-accent)] bg-[color:var(--nx-surface-2)]" : "border-[color:var(--nx-line)]"}`}>
                  <input type="checkbox" checked={checked} disabled={members.length >= 6 && !checked} onChange={(event) => setMembers((current) => event.target.checked ? [...current, bot.id] : current.filter((id) => id !== bot.id))} />
                  <IdentityMark id={bot.id} name={bot.name} size={32} />
                  <span className="min-w-0">
                    <span className="block font-medium">{bot.name}</span>
                    <span className="text-[12px] text-[color:var(--nx-text-faint)]">{bot.description || "Função não descrita"} · {bot.provider} · {bot.model}</span>
                  </span>
                </label>
              );
            })}
            {configured.length < 2 && <p className="text-[13px] text-[color:var(--nx-amber)]">Configura pelo menos dois bots com provedor e modelo.</p>}
          </fieldset>
          <button disabled={saving || members.length < 2 || !name.trim()} className="mt-6 rounded-xl bg-[color:var(--nx-accent)] px-4 py-2.5 text-[13px] font-medium text-white disabled:opacity-40">Criar grupo</button>
          {error && <p role="alert" className="mt-4 text-[13px] text-[color:var(--nx-rose)]">{error}</p>}
        </form>
      ) : selectedGroup ? <>
        <header className="relative z-20 flex items-center gap-2 border-b border-[color:var(--nx-line)] bg-[color:var(--nx-bg)] px-3 py-2.5 pl-14 lg:pl-4">
          <button type="button" onClick={() => { setListOpen(true); setContextOpen(false); }} aria-label="Abrir lista de grupos" className="inline-flex items-center gap-1 rounded-lg border border-[color:var(--nx-line)] px-2 py-1.5 text-[12px] lg:hidden"><ArrowLeft size={14} /> Grupos</button>
          <div className="hidden sm:block"><StackedMarks people={participants} liveId={partial ? participants.find((bot) => bot.name === partial.name)?.id : null} /></div>
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[15px] font-semibold tracking-tight">{selectedGroup.name}</h2>
            <p className="truncate text-[12px] text-[color:var(--nx-text-dim)]">{`Objetivo · ${goal}`}</p>
          </div>
          <span className="shrink-0 rounded-full border border-[color:var(--nx-line)] px-2 py-1 text-[11px] text-[color:var(--nx-text-dim)]">{phase}</span>
          <button type="button" aria-pressed={contextOpen} aria-label={contextOpen ? "Fechar painel de contexto" : "Abrir painel de contexto"} onClick={() => setContextOpen((open) => !open)} className="rounded-lg border border-[color:var(--nx-line)] p-2 text-[color:var(--nx-text-dim)] hover:bg-[color:var(--nx-surface-2)]"><PanelRight size={16} /></button>
        </header>
        <ParticipantStrip participants={participants} partialName={partial?.name ?? null} tasks={currentRun?.tasks ?? []} />
        <div ref={scrollRegion} onScroll={(event) => { const el = event.currentTarget; const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 80; follow.current = atBottom; setAway(!atBottom); if (atBottom) { seenCount.current = messages.length; setUnseen(0); } }} className="min-h-0 flex-1 overflow-y-auto px-3 py-4 sm:px-5" aria-label="Histórico do grupo">
          <div className="nx-bot-read mx-auto flex flex-col gap-4">
            {hasMore && <button type="button" disabled={olderLoading || busy} onClick={() => void loadOlder()} className="self-center rounded-lg px-3 py-2 text-[12px] text-[color:var(--nx-accent-bright)] hover:bg-[color:var(--nx-surface-2)] disabled:opacity-40">{olderLoading ? "A carregar…" : "Carregar mensagens anteriores"}</button>}
            {loading && <p role="status" className="text-[13px] text-[color:var(--nx-text-dim)]">A carregar histórico…</p>}
            {!loading && messages.length === 0 && (
              <div className="mx-auto mt-16 max-w-md text-center">
                <div className="mb-4 flex justify-center"><StackedMarks people={participants} /></div>
                <h3 className="text-lg font-semibold tracking-tight">Sala por estrear</h3>
                <p className="mt-2 text-[13px] leading-6 text-[color:var(--nx-text-dim)]">Envia uma mensagem para iniciar a conversa entre os participantes. O estado da execução aparece no cabeçalho e no painel de contexto.</p>
              </div>
            )}
            {timeline.map((item, index) => {
              if (item.kind === "incident") {
                return <GroupIncidentCard key={item.id} incident={item} busy={busy} onRetry={(content) => void send(content)} onChooseModel={(ids) => setModelBotIds(ids)} />;
              }
              const speaker = previousAgentSpeaker(timeline, index);
              const currentId = item.message.bot_id || item.message.bot_name || item.message.id;
              const previous = index > 0 ? timeline[index - 1] : undefined;
              const previousStamp = previous?.kind === "message" ? previous.message.created_at : undefined;
              const bot = bots.find((entry) => entry.id === item.message.bot_id);
              const turnPrompt = [...timeline.slice(0, index + 1)].reverse().find((entry) => entry.kind === "message" && entry.message.role === "user");
              return (
                <div key={item.message.id} className="flex flex-col gap-3">
                  <DayRule stamp={item.message.created_at} previous={previousStamp} />
                  {item.message.role === "assistant" && speaker && speaker.id !== currentId ? <HandoffRule from={speaker.name} to={item.message.bot_name || "Agente"} /> : null}
                  <GroupTurn
                    mine={item.message.role === "user"}
                    name={item.message.role === "user" ? "Tu" : item.message.bot_name || "Bot"}
                    botId={item.message.bot_id}
                    roleLabel={bot?.description || undefined}
                    content={item.message.content}
                    time={item.message.created_at}
                    onQuote={(text) => quote(item.message.role === "user" ? "Tu" : item.message.bot_name || "Bot", text)}
                    onReply={item.message.role === "assistant" ? () => replyTo(item.message.bot_name || "Bot") : undefined}
                    onRegenerate={item.message.role === "assistant" && turnPrompt && turnPrompt.kind === "message" ? () => void send(turnPrompt.message.content) : undefined}
                  />
                </div>
              );
            })}
            {currentRun && <RunCard run={currentRun} />}
            {partial && (
              <div>
                <TypingRow name={partial.name} label="a responder" detail="Texto ainda em curso" />
                {partial.content ? <div className="pl-11 text-[15px] leading-7"><AssistantMarkdown text={partial.content} theme={theme === "light" ? "light" : "dark"} /></div> : null}
              </div>
            )}
            {error && <p role="alert" className="rounded-xl border border-[color:var(--nx-rose)]/30 p-3 text-[13px] text-[color:var(--nx-rose)]">{error}{!historyReady && <button type="button" onClick={() => setHistoryAttempt((value) => value + 1)} className="ml-3 underline">Tentar carregar novamente</button>}</p>}
            <p role="status" className="text-[12px] text-[color:var(--nx-text-faint)]">{status}</p>
          </div>
        </div>
        <div className="relative">
          {away && <JumpToLatest count={unseen} onClick={() => { follow.current = true; setAway(false); setUnseen(0); if (scrollRegion.current) scrollRegion.current.scrollTop = scrollRegion.current.scrollHeight; }} />}
          <RoomComposer
            label="Mensagem para o grupo"
            value={draft}
            onChange={setDraft}
            onSubmit={() => void send()}
            onStop={() => abort.current?.abort()}
            busy={busy}
            disabled={loading || !historyReady}
            placeholder={busy ? "Escreve parar para interromper…" : "Escreve para o grupo…"}
            hint="Sem ferramentas nesta conversa: respostas por ordem até consenso, numa falha, ou no limite de voltas e tempo do grupo."
            footnote="Enter envia · Shift+Enter cria uma linha. @ nomeia um participante no texto; não muda a ordem."
            agents={participants.map((bot) => ({ id: bot.id, name: bot.name, role: bot.description || "Função não descrita" }))}
            focusTick={focusTick}
            sendLabel="Enviar ao grupo"
            stopLabel="Pedir paragem do grupo"
            maxLength={12000}
            pill={(
              <details className="min-w-0">
                <summary className="cursor-pointer list-none truncate text-[11px] text-[color:var(--nx-text-dim)] [&::-webkit-details-marker]:hidden">
                  {participants.length} {participants.length === 1 ? "modelo" : "modelos"} · por confirmar
                </summary>
                <div className="mt-1 space-y-1 text-[11px] leading-5 text-[color:var(--nx-text-dim)]">
                  {participants.map((bot) => (
                    <p key={bot.id}>{bot.name}: {bot.provider || "sem provedor"} · {bot.model || "sem modelo"}. {bot.provider && bot.model ? "Inferência ainda não verificada." : "Configuração em falta."}</p>
                  ))}
                </div>
              </details>
            )}
          />
        </div>
      </> : (
        <div className="m-auto max-w-md px-6 text-center">
          <Users size={28} className="mx-auto text-[color:var(--nx-text-faint)]" />
          <h2 className="mt-4 text-xl font-semibold tracking-tight">Conversas em grupo</h2>
          <p className="mt-2 text-[13px] leading-6 text-[color:var(--nx-text-dim)]">Cria um grupo para reunir os bots que já configuraste. Cada um responde com o seu provedor e modelo.</p>
          <button type="button" onClick={() => setCreating(true)} className="mt-5 rounded-xl bg-[color:var(--nx-accent)] px-4 py-2.5 text-[13px] font-medium text-white">Criar grupo</button>
          {error && <p role="alert" className="mt-4 text-[13px] text-[color:var(--nx-rose)]">{error}</p>}
        </div>
      )}
    </section>

    {contextOpen && selectedGroup && (
      <>
        <button type="button" className="fixed inset-0 z-30 bg-black/60 min-[1440px]:hidden" aria-label="Fechar painel de contexto" onClick={() => setContextOpen(false)} />
        <div className="fixed inset-y-0 right-0 z-40 w-[min(100%,22rem)] min-[1440px]:static min-[1440px]:z-auto min-[1440px]:w-[320px] min-[1440px]:shrink-0">
          <ContextTabs
            groupId={selectedGroup.id}
            groupName={selectedGroup.name}
            botIds={selectedGroup.bot_ids}
            bots={bots}
            objective={goal}
            executionLabel={phase}
            runs={runs}
            onClose={() => setContextOpen(false)}
          />
        </div>
      </>
    )}

    {modelBotIds !== null && (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" role="presentation" onMouseDown={() => setModelBotIds(null)}>
        <div role="dialog" aria-modal="true" aria-labelledby="group-model-title" className="w-full max-w-md rounded-2xl border border-[color:var(--nx-line-strong)] bg-[color:var(--nx-surface-1)] p-5" onMouseDown={(event) => event.stopPropagation()}>
          <div className="flex items-start justify-between gap-3">
            <h2 id="group-model-title" className="text-base font-semibold">Escolher outro modelo</h2>
            <button type="button" aria-label="Fechar escolha de modelo" onClick={() => setModelBotIds(null)} className="rounded-lg p-1 text-[color:var(--nx-text-faint)] hover:text-[color:var(--nx-text)]"><X size={16} /></button>
          </div>
          <p className="mt-2 text-[13px] leading-6 text-[color:var(--nx-text-dim)]">A troca não é automática. Abre o bot e escolhe outro modelo que o provedor permita. A configuração global continua em Definições.</p>
          <ul className="mt-4 space-y-2">
            {modelCandidates.length === 0 && <li className="text-[13px] text-[color:var(--nx-text-dim)]">Não há bots identificados neste incidente.</li>}
            {modelCandidates.map((bot) => (
              <li key={bot.id} className="rounded-xl border border-[color:var(--nx-line)] p-3 text-[13px]">
                <span className="block font-medium">{bot.name}</span>
                <span className="mt-1 block break-all text-[12px] text-[color:var(--nx-text-faint)]">{bot.provider || "Provedor não configurado"} · {bot.model || "Modelo não configurado"}</span>
                <span className="mt-1 block text-[12px] text-[color:var(--nx-text-faint)]">{bot.description || "Função não descrita"}</span>
                {onOpenBot ? (
                  <button type="button" className="mt-2 text-[12px] font-medium text-[color:var(--nx-accent-bright)]" onClick={() => { setModelBotIds(null); onOpenBot(bot.id); }}>Abrir {bot.name}</button>
                ) : (
                  <Link href="/bots" className="mt-2 inline-block text-[12px] font-medium text-[color:var(--nx-accent-bright)]">Voltar aos bots</Link>
                )}
              </li>
            ))}
          </ul>
          <Link href="/settings" className="mt-4 inline-block text-[12px] text-[color:var(--nx-accent-bright)]">Abrir definições do fornecedor</Link>
        </div>
      </div>
    )}
  </div>;
}
