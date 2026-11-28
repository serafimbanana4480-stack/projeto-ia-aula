"use client";

import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowDown, ArrowLeft, Plus, Search, Send, Square, Users } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { apiUrl } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";
import type { Bot } from "../../lib/bots";
import GroupRuns from "./GroupRuns";
import { AvatarStack, BOT_INPUT, BotAvatar } from "./botsUi";

type Group = { id: string; name: string; bot_ids: string[]; last_message: string | null };
type GroupMessage = { id: string; role: "user" | "assistant" | "error"; content: string; bot_id: string | null; bot_name: string | null; created_at: string };
type GroupEvent = { type: string; message?: GroupMessage; bot_id?: string; bot_name?: string; content?: string; status?: string };

async function groupRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await authenticatedFetch(apiUrl(path), init);
  if (!response.ok) {
    let detail = `Erro ${response.status}`;
    try { const body = await response.json() as { detail?: unknown }; if (typeof body.detail === "string") detail = body.detail; } catch { /* Keep the HTTP status. */ }
    throw new Error(detail);
  }
  return await response.json() as T;
}

export default function GroupWorkspace({ bots, onBack }: { bots: Bot[]; onBack: () => void }) {
  const [groups, setGroups] = useState<Group[]>([]);
  const [groupsLoading, setGroupsLoading] = useState(true);
  const [groupsAttempt, setGroupsAttempt] = useState(0);
  const [listError, setListError] = useState("");
  const [query, setQuery] = useState("");
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  const [selected, setSelected] = useState("");
  const [messages, setMessages] = useState<GroupMessage[]>([]);
  const [name, setName] = useState("");
  const [members, setMembers] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [historyReady, setHistoryReady] = useState(false);
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [before, setBefore] = useState<string | null>(null);
  const [olderLoading, setOlderLoading] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [partial, setPartial] = useState<{ name: string; content: string; botId?: string } | null>(null);
  const abort = useRef<AbortController | null>(null);
  const scrollRegion = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const preserveHeight = useRef<number | null>(null);
  const activeGroup = useRef("");
  const selectedGroup = groups.find((group) => group.id === selected);
  const draft = drafts[selected] ?? "";
  const botById = new Map(bots.map((bot) => [bot.id, bot]));
  const setDraft = (id: string, value: string) => setDrafts((current) => ({ ...current, [id]: value }));
  const configured = bots.filter((bot) => !bot.archived && bot.provider && bot.model);

  const refreshGroups = useCallback(async (signal?: AbortSignal) => {
    const data = await groupRequest<{ groups: Group[] }>("/api/bot-groups", { signal });
    if (!signal?.aborted) {
      setGroups(data.groups);
      setListError("");
    }
  }, []);
  const refreshMessages = useCallback(async (groupId: string, resetPage = true) => {
    const data = await groupRequest<{ messages: GroupMessage[]; has_more?: boolean; next_before?: string | null }>(`/api/bot-groups/${encodeURIComponent(groupId)}/messages`);
    if (activeGroup.current === groupId) {
      setMessages((current) => { const recent = new Set(data.messages.map((item) => item.id)); return [...current.filter((item) => !recent.has(item.id)), ...data.messages]; });
      if (resetPage) { setHasMore(Boolean(data.has_more)); setBefore(data.next_before ?? null); }
    }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    setGroupsLoading(true);
    setListError("");
    void refreshGroups(controller.signal).catch((reason) => {
      if (!controller.signal.aborted) setListError(reason instanceof Error ? reason.message : "Não foi possível carregar os grupos.");
    }).finally(() => {
      if (!controller.signal.aborted) setGroupsLoading(false);
    });
    return () => controller.abort();
  }, [refreshGroups, groupsAttempt]);
  useEffect(() => () => abort.current?.abort(), []);
  useEffect(() => {
    activeGroup.current = selected;
    setMessages([]); setError(""); setPartial(null); setHistoryReady(false); setStatus(""); setHasMore(false); setBefore(null); setLoading(Boolean(selected)); setAwayFromBottom(false); preserveHeight.current = null; follow.current = true;
    if (!selected) return;
    let alive = true;
    setLoading(true);
    void refreshMessages(selected).then(() => { if (alive) setHistoryReady(true); }).catch((reason) => { if (alive) setError(reason instanceof Error ? reason.message : "Não foi possível carregar o histórico."); }).finally(() => { if (alive) setLoading(false); });
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
    event.preventDefault(); if (saving || members.length < 2 || !name.trim()) return; setSaving(true); setError("");
    try {
      const group = await groupRequest<Group>("/api/bot-groups", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: name.trim(), bot_ids: members }) });
      setGroups((current) => [group, ...current]); setSelected(group.id); setCreating(false); setName(""); setMembers([]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível criar o grupo."); }
    finally { setSaving(false); }
  }
  async function send() {
    const content = draft.trim();
    if (busy && /^(parar|para|stop|cancelar|cancela)[.!\s]*$/i.test(content)) { setDraft(selected, ""); abort.current?.abort(); return; }
    if (!selected || !content || busy || abort.current || loading || !historyReady) return;
    const groupId = selected;
    const controller = new AbortController(); abort.current = controller;
    let acknowledgement = false;
    setBusy(true); setError(""); setStatus("A iniciar conversa…"); setPartial(null); setDraft(groupId, "");
    follow.current = true; setAwayFromBottom(false);
    try {
      const response = await authenticatedFetch(apiUrl(`/api/bot-groups/${encodeURIComponent(groupId)}/messages`), { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: content }), signal: controller.signal });
      if (!response.ok || !response.body) throw new Error(`Não foi possível iniciar a conversa (erro ${response.status}).`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let completed = false;
      try {
        while (!completed) {
          const { value, done } = await reader.read();
          buffer += decoder.decode(value, { stream: !done });
          let boundary: RegExpExecArray | null;
          while (!completed && (boundary = /\r?\n\r?\n/.exec(buffer))) {
            const frame = buffer.slice(0, boundary.index);
            buffer = buffer.slice(boundary.index + boundary[0].length);
            const data = frame.split(/\r?\n/).filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).replace(/^ /, "")).join("\n");
            if (!data) continue;
            const event = JSON.parse(data) as GroupEvent;
            const eventMessage = event.message;
            if (event.type === "user_message" && eventMessage) acknowledgement = true;
            if (eventMessage && ["user_message", "agent_message", "agent_error"].includes(event.type)) {
              setMessages((current) => current.some((item) => item.id === eventMessage.id) ? current : [...current, eventMessage]);
              if (event.type !== "user_message") setPartial(null);
            }
            if (event.type === "agent_started") {
              const botName = event.bot_name || "Bot";
              setStatus(botName + " está a responder…");
              setPartial({ name: botName, content: "", botId: event.bot_id });
            }
            if (event.type === "token") setPartial((current) => ({ name: current?.name || event.bot_name || "Bot", botId: current?.botId ?? event.bot_id, content: (current?.content || "") + (event.content || "") }));
            if (event.type === "done") {
              completed = true;
              const completion: Record<string, string> = {
                completed: "Conversa concluída.",
                partial: "Conversa interrompida por falha de um bot. Vê as mensagens e volta a tentar.",
                limit: "A conversa atingiu o limite sem consenso. Podes continuar com uma nova mensagem.",
              };
              setStatus(completion[event.status ?? ""] ?? "A conversa terminou sem confirmação de sucesso.");
            }
            if (event.type === "error" || event.type === "group_error") throw new Error(event.content || "A conversa foi interrompida.");
          }
          if (done) break;
        }
        if (!completed) throw new Error("A ligação terminou antes da confirmação. Verifica o histórico antes de voltar a enviar.");
      } finally {
        void reader.cancel().catch(() => {});
      }
    } catch (reason) {
      if (controller.signal.aborted) {
        setStatus("Paragem pedida. As respostas concluídas ficam no histórico.");
      } else {
        setError(reason instanceof Error ? reason.message : "Não foi possível enviar a mensagem.");
        if (!acknowledgement) setDrafts((current) => ({ ...current, [groupId]: current[groupId] || content }));
      }
    } finally {
      abort.current = null; setPartial(null);
      try { await refreshMessages(groupId, false); }
      catch { setHistoryReady(false); setError("Não foi possível atualizar o histórico. Carrega-o novamente antes de continuar."); }
      try { await refreshGroups(); } catch { /* The conversation history remains available. */ }
      setBusy(false);
    }
  }

  const visibleGroups = groups.filter((group) => (group.name + " " + (group.last_message ?? "") + " " + group.bot_ids.map((id) => botById.get(id)?.name ?? "").join(" ")).toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const participants = selectedGroup?.bot_ids.map((id) => ({ id, name: botById.get(id)?.name ?? "Bot indisponível" })) ?? [];
  const openCreate = () => { setSelected(""); setCreating(true); setError(""); };
  const returnToList = () => { setSelected(""); setCreating(false); };
  const mobileDetail = Boolean(selected || creating);

  return (
    <div className="nx-bot-workspace flex h-full min-h-0 overflow-hidden">
      <section aria-label="Grupos de bots" className={(mobileDetail ? "hidden md:flex " : "flex ") + "nx-bot-nav w-full shrink-0 flex-col border-r md:w-[270px] xl:w-[310px]"}>
        <div className="px-4 pb-4 pt-3">
          <div className="flex min-h-9 items-center justify-between gap-2 pl-10 md:pl-0">
            <h1 className="flex items-center gap-2 text-lg font-semibold tracking-tight"><Users size={17} className="hidden text-[var(--nx-accent-bright)] md:block" /> Grupos</h1>
            <button type="button" aria-label="Criar grupo" disabled={busy} onClick={openCreate} className="nx-bot-action nx-bot-primary"><Plus size={15} /> Novo grupo</button>
          </div>
          <button type="button" onClick={onBack} disabled={busy} className="nx-bot-action mt-4 w-full justify-start"><ArrowLeft size={15} /> Voltar aos bots</button>
          <label className="relative mt-4 block">
            <Search size={15} className="pointer-events-none absolute left-3 top-3 text-[var(--nx-text-faint)]" />
            <input aria-label="Pesquisar grupos" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Pesquisar grupos" className={BOT_INPUT + " h-10 pl-9"} />
          </label>
        </div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-3 pb-4">
          {groupsLoading && <p role="status" className="px-3 py-4 text-sm text-[var(--nx-text-dim)]">A carregar grupos…</p>}
          {!groupsLoading && listError && (
            <div role="alert" className="nx-bot-error rounded-xl border p-3 text-sm">
              <p>{listError}</p>
              <button type="button" className="mt-2 text-xs font-medium underline" onClick={() => setGroupsAttempt((value) => value + 1)}>Tentar novamente</button>
            </div>
          )}
          {!groupsLoading && !listError && visibleGroups.length === 0 && (
            <p className="px-3 py-6 text-center text-sm leading-6 text-[var(--nx-text-dim)]">{query.trim() ? "Nenhum grupo encontrado." : "Ainda não tens grupos. Cria um para começar."}</p>
          )}
          {visibleGroups.map((group) => (
            <button type="button" key={group.id} disabled={busy} onClick={() => { setCreating(false); setSelected(group.id); }} aria-current={selected === group.id ? "true" : undefined} className="nx-bot-item flex w-full items-center gap-3 rounded-xl border border-transparent p-2.5 text-left disabled:opacity-60">
              <span className="nx-bot-mark inline-grid size-9 shrink-0 place-items-center rounded-xl border"><Users size={16} /></span>
              <span className="min-w-0"><span className="block truncate text-sm font-semibold">{group.name}</span><span className="mt-0.5 block truncate text-xs text-[var(--nx-text-dim)]">{group.last_message || group.bot_ids.length + " participantes"}</span></span>
            </button>
          ))}
        </div>
      </section>

      <section aria-label="Conversa de grupo" className={(mobileDetail ? "flex " : "hidden md:flex ") + "min-w-0 flex-1 flex-col"}>
        {creating ? (
          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-8">
            <form onSubmit={(event) => void create(event)} className="mx-auto max-w-2xl">
              <button type="button" onClick={returnToList} disabled={saving} className="nx-bot-action mb-5 ml-10 md:ml-0"><ArrowLeft size={15} /> Voltar aos grupos</button>
              <div className="nx-bot-card rounded-2xl border p-4 sm:p-6">
                <h2 className="text-2xl font-semibold tracking-tight">Criar grupo</h2>
                <p className="mt-2 text-sm leading-6 text-[var(--nx-text-dim)]">Escolhe entre 2 e 6 bots configurados. A ordem de seleção é a ordem pela qual respondem.</p>
                <label className="mt-5 block text-sm font-medium">Nome do grupo
                  <input value={name} required maxLength={80} onChange={(event) => setName(event.target.value)} className={BOT_INPUT + " mt-2"} placeholder="Equipa de desenvolvimento" disabled={saving} />
                </label>
                <fieldset className="mt-5 grid gap-2" disabled={saving}>
                  <legend className="mb-3 text-sm font-semibold">Participantes <span className="ml-2 text-xs text-[var(--nx-text-faint)]">{members.length}/6</span></legend>
                  {configured.map((bot) => {
                    const order = members.indexOf(bot.id);
                    return (
                      <label key={bot.id} data-selected={order !== -1} className="nx-bot-item flex cursor-pointer items-center gap-3 rounded-xl border border-[var(--nx-line)] p-3 text-sm">
                        <input type="checkbox" checked={order !== -1} disabled={members.length >= 6 && order === -1} onChange={(event) => setMembers((current) => event.target.checked ? [...current, bot.id] : current.filter((id) => id !== bot.id))} className="size-4 shrink-0 accent-[var(--nx-accent)]" />
                        <BotAvatar name={bot.name} id={bot.id} compact />
                        <span className="min-w-0 flex-1"><span className="block truncate font-semibold">{bot.name}</span><span className="block truncate text-xs text-[var(--nx-text-dim)]">{bot.provider} · {bot.model}</span></span>
                        {order !== -1 && <span aria-label={"Ordem " + (order + 1)} className="nx-bot-mark grid size-6 shrink-0 place-items-center rounded-lg border text-xs font-semibold">{order + 1}</span>}
                      </label>
                    );
                  })}
                  {configured.length < 2 && <p className="nx-bot-note rounded-xl border p-3 text-sm">Configura pelo menos dois bots com provedor e modelo. <button type="button" onClick={onBack} className="font-semibold underline">Gerir bots</button></p>}
                </fieldset>
                {error && <p role="alert" className="nx-bot-error mt-4 rounded-xl border p-3 text-sm">{error}</p>}
                <button disabled={saving || members.length < 2 || !name.trim()} className="nx-bot-action nx-bot-primary mt-5"><Plus size={16} /> {saving ? "A criar…" : "Criar grupo"}</button>
              </div>
            </form>
          </div>
        ) : selectedGroup ? (
          <>
            <header className="nx-bot-panel flex min-h-[74px] shrink-0 items-center gap-3 border-b px-4 pl-14 md:px-6">
              <button type="button" onClick={returnToList} disabled={busy} aria-label="Voltar aos grupos" className="nx-bot-action shrink-0 px-2 md:hidden"><ArrowLeft size={17} /></button>
              <span className="nx-bot-mark grid size-10 shrink-0 place-items-center rounded-xl border"><Users size={18} /></span>
              <div className="min-w-0 flex-1"><h2 className="truncate font-semibold">{selectedGroup.name}</h2><p className="mt-0.5 truncate text-xs text-[var(--nx-text-dim)]" title={participants.map(({ name }) => name).join(" · ")}>{participants.map(({ name }) => name).join(" · ")}</p></div>
              <div className="hidden sm:block"><AvatarStack items={participants} speakingId={partial?.botId} /></div>
            </header>
            <GroupRuns key={selected} groupId={selected} />
            <div ref={scrollRegion} onScroll={(event) => {
              const el = event.currentTarget;
              follow.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
              setAwayFromBottom(!follow.current);
            }} className="min-h-0 flex-1 overflow-y-auto px-4 py-5 sm:px-8" aria-label="Histórico do grupo">
              <div className="mx-auto grid max-w-3xl gap-4">
                {hasMore && <button type="button" disabled={olderLoading || busy} onClick={() => void loadOlder()} className="nx-bot-action justify-self-center">{olderLoading ? "A carregar…" : "Carregar mensagens anteriores"}</button>}
                {loading && <p role="status" className="text-sm text-[var(--nx-text-dim)]">A carregar histórico…</p>}
                {historyReady && messages.length === 0 && !busy && <p className="nx-bot-note mt-6 rounded-2xl border px-5 py-6 text-center text-sm">Envia uma mensagem para iniciar a conversa entre os participantes.</p>}
                {messages.map((message) => (
                  <article key={message.id} data-mine={message.role === "user"} className={(message.role === "error" ? "nx-bot-error " : "nx-bot-message ") + "min-w-0 rounded-2xl border p-4"}>
                    <div className="mb-2 flex items-center gap-2">
                      {message.bot_name && <BotAvatar name={message.bot_name} id={message.bot_id ?? undefined} compact />}
                      <p className="text-xs font-semibold text-[var(--nx-accent-bright)]">{message.role === "user" ? "Tu" : message.bot_name || "Bot"}{message.role === "error" ? " · falhou" : ""}</p>
                    </div>
                    <div className="nx-prose break-words text-sm leading-6 [&_pre]:max-w-full [&_pre]:overflow-x-auto"><ReactMarkdown>{message.content}</ReactMarkdown></div>
                  </article>
                ))}
                {partial?.content && <article className="nx-bot-message min-w-0 rounded-2xl border p-4"><p className="mb-2 text-xs font-semibold text-[var(--nx-accent-bright)]">{partial.name}</p><p className="whitespace-pre-wrap text-sm leading-6">{partial.content}</p></article>}
                {error && <div role="alert" className="nx-bot-error rounded-xl border p-3 text-sm"><p>{error}</p>{!historyReady && <button type="button" onClick={() => setHistoryAttempt((value) => value + 1)} className="nx-bot-action mt-2">Tentar carregar novamente</button>}</div>}
                <p role="status" className="text-xs text-[var(--nx-text-dim)]">{status}</p>
              </div>
            </div>
            <div className="relative shrink-0 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 sm:px-7">
              <div className="mx-auto max-w-3xl">
                {awayFromBottom && <button type="button" onClick={() => {
                  follow.current = true;
                  setAwayFromBottom(false);
                  const region = scrollRegion.current;
                  if (region) region.scrollTop = region.scrollHeight;
                }} className="nx-bot-action absolute -top-11 left-1/2 -translate-x-1/2 shadow-lg"><ArrowDown size={15} /> Ir para o fim</button>}
                <div className="nx-bot-composer flex items-end gap-2 rounded-2xl border p-2">
                  <textarea aria-label="Mensagem para o grupo" maxLength={12000} value={draft} onChange={(event) => setDraft(selected, event.target.value)}
                    onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void send(); } }}
                    rows={2} disabled={loading || !historyReady} placeholder={busy ? "Escreve parar para interromper…" : "Escreve para o grupo…"}
                    className="max-h-40 min-h-[52px] min-w-0 flex-1 resize-y bg-transparent px-2 py-2.5 text-sm outline-none placeholder:text-[var(--nx-text-faint)] disabled:opacity-60" />
                  {busy ? <button type="button" onClick={() => abort.current?.abort()} aria-label="Pedir paragem do grupo" className="nx-bot-action px-3"><Square size={15} fill="currentColor" /></button>
                    : <button type="button" disabled={!draft.trim() || loading || !historyReady} onClick={() => void send()} aria-label="Enviar ao grupo" className="nx-bot-action nx-bot-primary px-3"><Send size={16} /></button>}
                </div>
                <div className="flex flex-wrap justify-between gap-1 pt-2 text-[11px] text-[var(--nx-text-faint)]"><span>Até oito rondas por mensagem</span><span className="hidden sm:inline">Enter envia · Shift + Enter muda de linha</span></div>
              </div>
            </div>
          </>
        ) : (
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-8 sm:px-10">
            <div className="nx-bot-hero relative isolate mx-auto max-w-5xl overflow-hidden rounded-3xl border p-6 sm:p-9">
              <div aria-hidden="true" className="nx-bot-pattern" />
              <span className="nx-bot-mark inline-grid size-11 place-items-center rounded-xl border"><Users size={22} /></span>
              <h2 className="mt-5 text-3xl font-semibold tracking-tight">Conversas em grupo</h2>
              <p className="mt-2 max-w-md text-sm leading-6 text-[var(--nx-text-dim)]">Reúne diferentes modelos numa conversa partilhada e acompanha a contribuição de cada bot.</p>
              <button type="button" onClick={openCreate} className="nx-bot-action nx-bot-primary mt-6"><Plus size={16} /> Criar grupo</button>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
