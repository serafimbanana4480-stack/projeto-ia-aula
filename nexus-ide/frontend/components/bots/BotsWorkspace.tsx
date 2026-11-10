"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Activity, Archive, Bot as BotIcon, ChevronRight, Info, Plus, Settings2, Trash2, Users, X } from "lucide-react";
import { apiUrl, getProviderCatalog, getProviderModels, getSessionHistoryPage, type ProviderSpec } from "../../lib/api";
import { authenticatedFetch } from "../../lib/auth";
import { createBot, listBots, removeBot, updateBot, type Bot, type BotSettings } from "../../lib/bots";
import { foldRun } from "../../lib/foldRun";
import type { ChatMessage } from "../../lib/types";
import { useAgentStream } from "../../hooks/useAgentStream";
import { useProjectStore } from "../../stores/projectStore";
import GroupWorkspace from "./GroupWorkspace";
import { BotStatusPill, BOT_INPUT, formatBotTime } from "./botsUi";
import { RoomComposer } from "./chat/Composer";
import { IdentityMark } from "./chat/identity";
import { DayRule, DirectMessage, JumpToLatest, TypingRow } from "./chat/messages";
import { quoteDraft } from "./chat/model";
import { RosterRow, RosterSearch, SectionLabel } from "./chat/Roster";
import { useRoomMemory } from "./chat/storage";

const TEMPLATES = [
  { name: "Personalizado", description: "Um assistente à tua medida", instructions: "" },
  { name: "Programador", description: "Desenvolvimento de software", instructions: "Ajuda a desenvolver software com explicações precisas e exemplos úteis." },
  { name: "Arquiteto", description: "Arquitetura de software", instructions: "Analisa decisões de arquitetura, alternativas e compromissos técnicos." },
  { name: "Orquestrador", description: "Coordenação de tarefas e agentes", instructions: "Transforma objetivos em etapas verificáveis, identifica dependências, atribui trabalho aos especialistas disponíveis e acompanha bloqueios. Não declares tarefas concluídas sem evidência." },
  { name: "Hacker autorizado", description: "Análise de segurança em ambientes autorizados", instructions: "Analisa apenas sistemas e ambientes para os quais o utilizador tem autorização. Delimita o âmbito, privilegia validação segura e reporta evidência, impacto e mitigação. Não executes ações destrutivas nem testes fora do âmbito autorizado." },
  { name: "UI/UX", description: "Design de interfaces e experiência", instructions: "Ajuda a avaliar interfaces, acessibilidade e experiência de utilização." },
  { name: "Investigador", description: "Investigação e análise", instructions: "Organiza investigação, distingue factos de hipóteses e identifica o que precisa de ser verificado." },
  { name: "Debugger", description: "Diagnóstico de problemas", instructions: "Ajuda a diagnosticar falhas com hipóteses, evidências e passos reproduzíveis." },
  { name: "SRE", description: "Fiabilidade e incidentes", instructions: "Investiga incidentes com foco em sinais observáveis, impacto, mitigação reversível, causa provável e prevenção. Distingue claramente evidência de hipótese." },
  { name: "Analista de dados", description: "Análise e interpretação", instructions: "Ajuda a analisar dados, explicitando pressupostos e limites." },
  { name: "Testes", description: "Qualidade e verificação", instructions: "Propõe testes relevantes e distingue resultados observados de suposições." },
  { name: "Coordenador", description: "Planeamento de projetos", instructions: "Ajuda a organizar objetivos, prioridades, dependências e critérios de conclusão." },
  { name: "Automações", description: "Desenho de fluxos", instructions: "Ajuda a desenhar automações com limites, validação e recuperação." },
  { name: "Assistente pessoal", description: "Apoio no dia a dia", instructions: "Ajuda de forma prática, clara e concisa." },
  { name: "Segurança", description: "Segurança em ambientes autorizados", instructions: "Ajuda a analisar segurança apenas em sistemas e ambientes autorizados." },
];

const blankSettings: BotSettings = { name: "", description: "", instructions: "", provider: "", model: "" };

type ListedGroup = { id: string; name: string; bot_ids: string[]; last_message: string | null };
const selectedKey = "nexus:bots:selected";

function BotEditor({ bot, close, saved }: { bot: Bot | null; close: () => void; saved: (bot: Bot) => void }) {
  const [form, setForm] = useState<BotSettings>(bot ? {
    name: bot.name, description: bot.description, instructions: bot.instructions, provider: bot.provider, model: bot.model,
  } : blankSettings);
  const [providers, setProviders] = useState<ProviderSpec[]>([]);
  const [models, setModels] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loadingModels, setLoadingModels] = useState(false);
  const [saving, setSaving] = useState(false);
  const dialog = useRef<HTMLDialogElement>(null);
  const selectedProvider = providers.find((provider) => provider.id === form.provider);

  useEffect(() => {
    dialog.current?.showModal();
    let active = true;
    void getProviderCatalog().then((items) => { if (active) setProviders(items); }).catch(() => {
      if (active) setNotice("Não foi possível carregar os provedores. Verifica a ligação ao backend.");
    });
    return () => { active = false; };
  }, []);

  const set = (key: keyof BotSettings, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const discover = async (providerId = form.provider, refresh = false) => {
    if (!providerId || loadingModels) return;
    setLoadingModels(true); setError(""); setNotice("");
    try {
      const result = await getProviderModels(providerId, refresh);
      setModels(result.models.map((model) => model.id));
      setNotice(result.error ? `Não foi possível confirmar a ligação: ${result.error}` : !result.configured
        ? "Este provider não tem chave configurada; os modelos remotos podem não aparecer. Configura a chave em Definições."
        : result.cached
          ? `Catálogo em cache: ${result.models.length} modelo(s). A inferência ainda não foi verificada.`
          : `${result.models.length} modelo(s) disponíveis neste momento. A inferência ainda não foi verificada.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Não foi possível consultar os modelos.");
    } finally { setLoadingModels(false); }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setSaving(true); setError("");
    try { saved(bot ? await updateBot(bot.id, form) : await createBot(form)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível guardar o bot."); }
    finally { setSaving(false); }
  };
  return (
    <dialog ref={dialog} onCancel={(event) => { event.preventDefault(); close(); }} aria-labelledby="bot-editor-title" className="m-auto w-[min(92vw,620px)] max-w-none rounded-2xl border border-[color:var(--nx-line-strong)] bg-[color:var(--nx-surface-1)] p-0 text-[color:var(--nx-text)] shadow-2xl backdrop:bg-black/70">
      <form onSubmit={(event) => void submit(event)} className="max-h-[90dvh] overflow-y-auto">
        <div className="sticky top-0 z-10 flex items-start justify-between border-b border-[color:var(--nx-line)] bg-[color:var(--nx-surface-1)] px-6 py-5">
          <div><h2 id="bot-editor-title" className="text-lg font-semibold">{bot ? "Editar bot" : "Criar bot"}</h2><p className="mt-1 text-[12px] text-[color:var(--nx-text-faint)]">Define a identidade e o modelo desta conversa.</p></div>
          <button type="button" onClick={close} aria-label="Fechar" className="rounded-lg p-2 text-[color:var(--nx-text-faint)] hover:bg-[color:var(--nx-surface-3)] hover:text-[color:var(--nx-text)]"><X size={18} /></button>
        </div>
        <div className="space-y-5 px-6 py-5">
          {!bot && <label className="block text-[12px] font-medium">Ponto de partida
            <select aria-label="Ponto de partida" className={`${BOT_INPUT} mt-2`} defaultValue="Personalizado" onChange={(event) => {
              const template = TEMPLATES.find((item) => item.name === event.target.value);
              if (template) setForm((current) => ({ ...current, description: template.description, instructions: template.instructions }));
            }}>{TEMPLATES.map((template) => <option key={template.name}>{template.name}</option>)}</select>
          </label>}
          <label className="block text-[12px] font-medium">Nome<input className={`${BOT_INPUT} mt-2`} required maxLength={80} value={form.name} onChange={(event) => set("name", event.target.value)} placeholder="Ex.: Pixel" autoFocus /></label>
          <label className="block text-[12px] font-medium">Descrição<input className={`${BOT_INPUT} mt-2`} maxLength={500} value={form.description} onChange={(event) => set("description", event.target.value)} placeholder="Em que é que este bot te ajuda?" /></label>
          <label className="block text-[12px] font-medium">Instruções<textarea className={`${BOT_INPUT} mt-2 min-h-24 resize-y`} maxLength={4000} value={form.instructions} onChange={(event) => set("instructions", event.target.value)} placeholder="Especialidade, estilo de resposta e objetivo…" /></label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-[12px] font-medium">Provedor<select className={`${BOT_INPUT} mt-2`} value={form.provider} onChange={(event) => {
              const providerId = event.target.value;
              setForm((current) => ({ ...current, provider: providerId, model: "" }));
              setModels([]); setNotice(""); setError("");
              if (providerId) void discover(providerId);
            }}>
              <option value="">Selecionar mais tarde</option>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}
            </select></label>
            <label className="block text-[12px] font-medium">Modelo<input list="bot-models" className={`${BOT_INPUT} mt-2`} value={form.model} onChange={(event) => set("model", event.target.value)} maxLength={128} placeholder={loadingModels ? "A carregar modelos…" : "Pesquisa ou escreve o ID do modelo"} /><datalist id="bot-models">{models.map((model) => <option key={model} value={model} />)}</datalist></label>
          </div>
          {selectedProvider && <p className="-mt-2 text-[11px] text-[color:var(--nx-text-faint)]">{selectedProvider.requires_key ? selectedProvider.api_key_set ? "Chave configurada no backend." : "Sem chave configurada para este provider." : "Provider local ou sem chave obrigatória."} <a href="/settings" className="text-[color:var(--nx-accent-bright)]">Gerir em Definições</a></p>}
          <button type="button" disabled={!form.provider || loadingModels} onClick={() => void discover(form.provider, true)} className="text-[12px] font-medium text-[color:var(--nx-accent-bright)] disabled:opacity-40">{loadingModels ? "A consultar…" : "Atualizar modelos disponíveis"}</button>
          {notice && <p role="status" className="text-[12px] leading-5 text-[color:var(--nx-text-dim)]">{notice}</p>}
          <p className="rounded-xl border border-[color:var(--nx-line)] bg-[color:var(--nx-bg)] p-3 text-[12px] leading-5 text-[color:var(--nx-text-dim)]">Os bots podem usar ferramentas de leitura disponíveis. Com um projeto selecionado, podem também inspecionar os seus ficheiros. Escrita, execução e delegação estão desativadas. As credenciais e o endpoint são configurados nas definições do NEXUS.</p>
          {error && <p role="alert" className="text-[13px] text-[color:var(--nx-rose)]">{error}</p>}
        </div>
        <div className="sticky bottom-0 z-10 flex justify-end gap-3 border-t border-[color:var(--nx-line)] bg-[color:var(--nx-surface-1)] px-6 py-4"><button type="button" onClick={close} className="rounded-xl px-4 py-2 text-[13px] text-[color:var(--nx-text-dim)]">Cancelar</button><button disabled={saving} className="rounded-xl bg-[color:var(--nx-accent)] px-4 py-2 text-[13px] font-medium text-white disabled:opacity-50">{saving ? "A guardar…" : "Guardar bot"}</button></div>
      </form>
    </dialog>
  );
}

function workingLabel(message?: ChatMessage): string {
  const activeTool = [...(message?.toolCalls ?? [])].reverse().find((tool) => tool.status === "running");
  const waiting = (message?.toolCalls ?? []).some((tool) => tool.status === "awaiting_confirmation");
  if (waiting) return "A aguardar confirmação";
  if (activeTool) return `A usar ${activeTool.name}`;
  if (message?.content) return "A gerar resposta";
  if (message?.thinking) return "A analisar a tarefa";
  return "A preparar resposta";
}

export default function BotsWorkspace() {
  const memory = useRoomMemory();
  const [bots, setBots] = useState<Bot[]>([]);
  const [groups, setGroups] = useState<ListedGroup[]>([]);
  const [groupsNote, setGroupsNote] = useState("");
  const [showGroups, setShowGroups] = useState(false);
  const [openGroupId, setOpenGroupId] = useState("");
  const [selected, setSelected] = useState("");
  const [mobileChat, setMobileChat] = useState(false);
  const [filter, setFilter] = useState<"all" | "archived">("all");
  const [query, setQuery] = useState("");
  const [editor, setEditor] = useState<Bot | "new" | null>(null);
  const [details, setDetails] = useState(false);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyErrors, setHistoryErrors] = useState<Record<string, string>>({});
  const [historyAttempt, setHistoryAttempt] = useState(0);
  const [olderLoading, setOlderLoading] = useState(false);
  const [error, setError] = useState("");
  const [history, setHistory] = useState<Record<string, ChatMessage[]>>({});
  const [historyPages, setHistoryPages] = useState<Record<string, { hasMore: boolean; cursor: string | null }>>({});
  const [pending, setPending] = useState<Record<string, ChatMessage[]>>({});
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [sendNotices, setSendNotices] = useState<Record<string, string>>({});
  const [focusTick, setFocusTick] = useState(0);
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  const [unseen, setUnseen] = useState(0);
  const submitting = useRef(false);
  const bottom = useRef<HTMLDivElement>(null);
  const scrollRegion = useRef<HTMLDivElement>(null);
  const previousScrollHeight = useRef<{ session: string; height: number } | null>(null);
  const followMessages = useRef(true);
  const seenCount = useRef(0);
  const lastScrollSession = useRef("");
  const bot = bots.find((item) => item.id === selected);
  const session = bot?.session_id ?? "";
  const currentSession = useRef(session);
  currentSession.current = session;
  const { events, streaming, busyOtherSession, error: streamError, send, cancel } = useAgentStream(session);
  const currentProject = useProjectStore((state) => state.currentProject);

  const reload = useCallback(async () => {
    const items = await listBots(); setBots(items); return items;
  }, []);
  useEffect(() => {
    let alive = true;
    void listBots().then((items) => {
      if (!alive) return;
      setBots(items);
      const saved = window.localStorage.getItem(selectedKey);
      const restored = items.find((item) => item.id === saved);
      if (restored) { setSelected(restored.id); setFilter(restored.archived ? "archived" : "all"); setMobileChat(true); }
    }).catch((reason) => { if (alive) setError(reason instanceof Error ? reason.message : "Não foi possível carregar os bots."); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);
  useEffect(() => {
    if (showGroups) return;
    const controller = new AbortController();
    let alive = true;
    void authenticatedFetch(apiUrl("/api/bot-groups"), { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Grupos indisponíveis");
        const data = await response.json() as { groups: ListedGroup[] };
        if (alive) { setGroups(data.groups); setGroupsNote(""); }
      })
      .catch(() => { if (alive && !controller.signal.aborted) setGroupsNote("Não foi possível listar as salas."); });
    return () => { alive = false; controller.abort(); };
  }, [showGroups]);
  useEffect(() => {
    if (!session || Object.hasOwn(history, session)) { setHistoryLoading(false); return; }
    let alive = true; setHistoryLoading(true);
    setHistoryErrors((current) => ({ ...current, [session]: "" }));
    void getSessionHistoryPage(session, 100).then((page) => { if (alive) {
      setHistory((current) => ({ ...current, [session]: page.messages.filter((message) => message.role === "user" || message.role === "assistant") }));
      setHistoryPages((current) => ({ ...current, [session]: { hasMore: page.has_more, cursor: page.next_cursor } }));
    } })
      .catch((reason) => { if (alive) setHistoryErrors((current) => ({ ...current, [session]: reason instanceof Error ? reason.message : "Não foi possível carregar a conversa." })); })
      .finally(() => { if (alive) setHistoryLoading(false); });
    return () => { alive = false; };
  }, [session, history, historyAttempt]);
  const live = useMemo(() => foldRun(pending[session] ?? [], events).messages, [pending, session, events]);
  const messages = [...(history[session] ?? []), ...live];
  const liveAssistant = [...live].reverse().find((message) => message.role === "assistant");
  useEffect(() => {
    if (bot) memory.markSeen(bot.id, `${bot.last_active_at}|${bot.last_message ?? ""}`);
  }, [bot, memory]);
  useEffect(() => {
    if (lastScrollSession.current !== session) {
      lastScrollSession.current = session;
      followMessages.current = true;
      setAwayFromBottom(false);
      setUnseen(0);
    }
    if (previousScrollHeight.current?.session === session && scrollRegion.current) {
      scrollRegion.current.scrollTop += scrollRegion.current.scrollHeight - previousScrollHeight.current.height;
      previousScrollHeight.current = null;
    } else {
      previousScrollHeight.current = null;
      if (followMessages.current) bottom.current?.scrollIntoView({ block: "end" });
    }
  }, [session, messages.length, events]);
  useEffect(() => {
    if (followMessages.current) { seenCount.current = messages.length; setUnseen(0); }
    else setUnseen(Math.max(0, messages.length - seenCount.current));
  }, [messages.length]);
  const loadOlder = async () => {
    const page = historyPages[session];
    if (!page?.hasMore || !page.cursor || olderLoading || streaming) return;
    const ownerSession = session;
    setOlderLoading(true); setError("");
    try {
      const older = await getSessionHistoryPage(ownerSession, 100, page.cursor);
      if (scrollRegion.current && currentSession.current === ownerSession) {
        previousScrollHeight.current = { session: ownerSession, height: scrollRegion.current.scrollHeight };
      }
      setHistory((current) => {
        const existing = current[ownerSession] ?? [];
        const known = new Set(existing.map((message) => message.id));
        return { ...current, [ownerSession]: [...older.messages.filter((message) => (message.role === "user" || message.role === "assistant") && !known.has(message.id)), ...existing] };
      });
      setHistoryPages((current) => ({ ...current, [ownerSession]: { hasMore: older.has_more, cursor: older.next_cursor } }));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível carregar as mensagens anteriores."); }
    finally { setOlderLoading(false); }
  };
  const activeCount = bots.filter((item) => !item.archived).length;
  const archivedCount = bots.length - activeCount;
  const unconfiguredCount = bots.filter((item) => !item.archived && (!item.provider || !item.model)).length;
  const search = query.trim().toLocaleLowerCase();
  const visible = bots.filter((item) => (filter === "archived" ? item.archived : !item.archived) && `${item.name} ${item.description} ${item.provider} ${item.model} ${item.last_message ?? ""}`.toLocaleLowerCase().includes(search));
  const pinnedBots = visible.filter((item) => memory.pins.includes(item.id));
  const visibleGroups = groups.filter((group) => `${group.name} ${group.last_message ?? ""}`.toLocaleLowerCase().includes(search));
  const retryBots = async () => {
    setLoading(true); setError("");
    try { await reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível carregar os bots."); }
    finally { setLoading(false); }
  };
  const choose = (item: Bot) => { setSelected(item.id); setMobileChat(true); setDetails(false); setError(""); window.localStorage.setItem(selectedKey, item.id); };
  const deliver = async (value: string) => {
    if (!value || !bot || streaming || busyOtherSession || historyLoading || submitting.current || !Object.hasOwn(history, session)) return;
    const ownSession = session;
    submitting.current = true;
    setSendNotices((current) => ({ ...current, [ownSession]: "" }));
    setDrafts((current) => ({ ...current, [ownSession]: "" }));
    setPending((current) => ({ ...current, [ownSession]: [...(current[ownSession] ?? []), { id: crypto.randomUUID(), role: "user", content: value, timestamp: new Date().toISOString() }] }));
    followMessages.current = true;
    setAwayFromBottom(false);
    try {
      const sent = await send(value, "chat", "", currentProject?.path || "");
      if (!sent) {
        setDrafts((current) => ({ ...current, [ownSession]: current[ownSession] || value }));
        setSendNotices((current) => ({ ...current, [ownSession]: "Não foi possível confirmar o envio. O texto foi preservado; verifica o histórico antes de tentar novamente." }));
      }
      void reload().catch(() => { if (currentSession.current === ownSession) setError("Não foi possível atualizar a lista de conversas."); });
    } catch {
      setDrafts((current) => ({ ...current, [ownSession]: current[ownSession] || value }));
      setSendNotices((current) => ({ ...current, [ownSession]: "A ligação falhou e o envio não foi confirmado. O texto foi preservado; verifica o histórico antes de tentar novamente." }));
    } finally { submitting.current = false; }
  };
  const quote = (author: string, content: string) => {
    setDrafts((current) => ({ ...current, [session]: quoteDraft(author, content, current[session] ?? "") }));
    setFocusTick((value) => value + 1);
  };
  const replyTo = (author: string) => {
    const mention = `@${author} `;
    setDrafts((current) => {
      const draft = current[session] ?? "";
      return { ...current, [session]: draft.startsWith(mention) ? draft : draft.trim() ? `${mention}${draft}` : mention };
    });
    setFocusTick((value) => value + 1);
  };
  const changeArchive = async () => {
    if (!bot) return;
    try { const changed = await updateBot(bot.id, { archived: !bot.archived }); setBots((items) => items.map((item) => item.id === changed.id ? changed : item)); setFilter(changed.archived ? "archived" : "all"); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível arquivar."); }
  };
  const remove = async () => {
    if (!bot || !window.confirm(`Remover ${bot.name} da lista? O histórico fica guardado.`)) return;
    try { await removeBot(bot.id); setBots((items) => items.filter((item) => item.id !== bot.id)); setSelected(""); setMobileChat(false); setDetails(false); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível remover o bot."); }
  };
  const openGroups = (groupId = "") => {
    if (streaming || busyOtherSession) return;
    setOpenGroupId(groupId);
    setShowGroups(true);
  };

  if (showGroups) return <GroupWorkspace bots={bots} initialGroupId={openGroupId} onBack={() => setShowGroups(false)} onSelectBot={(id) => {
    const item = bots.find((entry) => entry.id === id);
    setShowGroups(false);
    if (item) choose(item);
  }} onOpenBot={(id) => {
    const item = bots.find((entry) => entry.id === id);
    setShowGroups(false);
    if (!item) return;
    choose(item);
    setEditor(item);
  }} />;

  const renderBot = (item: Bot) => (
    <RosterRow
      key={item.id}
      id={item.id}
      name={item.name}
      role={item.description || "Função não descrita"}
      chip={item.provider || undefined}
      preview={item.last_message || "Começa uma conversa"}
      time={item.last_message ? formatBotTime(item.last_active_at) : ""}
      active={selected === item.id}
      live={selected === item.id && streaming}
      warn={!item.provider || !item.model}
      pinned={memory.pins.includes(item.id)}
      unread={memory.unread(item.id, `${item.last_active_at}|${item.last_message ?? ""}`)}
      onSelect={() => choose(item)}
      onPin={() => memory.togglePin(item.id)}
    />
  );

  return <div className="nx-bot-room relative flex h-full min-h-0 overflow-hidden">
    <section aria-label="Lista de conversas" className={`${mobileChat ? "hidden lg:flex" : "flex"} w-full shrink-0 flex-col border-r border-[color:var(--nx-line)] bg-[color:var(--nx-surface-1)] lg:w-[300px] xl:w-[320px]`}>
      <div className="px-3 pb-3 pl-14 pt-[max(1rem,env(safe-area-inset-top))] lg:pl-3">
        <div className="flex items-center justify-between">
          <div>
            <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-[color:var(--nx-text-faint)]">NEXUS</p>
            <h1 className="text-lg font-semibold tracking-tight">Bots</h1>
          </div>
          <div className="flex items-center gap-1.5">
            <button type="button" aria-label="Conversas de grupo" disabled={streaming || busyOtherSession} onClick={() => openGroups()} className="inline-flex items-center gap-1.5 rounded-lg border border-[color:var(--nx-line)] px-2.5 py-2 text-[12px] text-[color:var(--nx-text-dim)] hover:bg-[color:var(--nx-surface-3)] disabled:opacity-40"><Users size={14} /> Grupos</button>
            <button type="button" onClick={() => setEditor("new")} aria-label="Criar bot" className="flex h-9 w-9 items-center justify-center rounded-lg bg-[color:var(--nx-accent)] text-white hover:bg-[color:var(--nx-accent-bright)]"><Plus size={16} /></button>
          </div>
        </div>
        <div className="mt-3"><RosterSearch label="Pesquisar conversas" value={query} onChange={setQuery} /></div>
        <div role="tablist" aria-label="Filtrar conversas" className="mt-3 flex gap-1">{([["all", "Ativos", activeCount], ["archived", "Arquivados", archivedCount]] as const).map(([id, label, count]) => <button key={id} type="button" role="tab" aria-selected={filter === id} onClick={() => setFilter(id)} className={`rounded-md px-2.5 py-1 text-[12px] ${filter === id ? "bg-[color:var(--nx-surface-3)] text-[color:var(--nx-text)]" : "text-[color:var(--nx-text-faint)] hover:text-[color:var(--nx-text)]"}`}><span>{label}</span> <span aria-hidden="true" className="ml-1 text-[10px] text-[color:var(--nx-text-faint)]">{count}</span></button>)}</div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-1.5 pb-3">
        {error && !bot && <div role="alert" className="mx-2 mb-3 rounded-xl border border-[color:var(--nx-rose)]/30 p-3 text-[12px] leading-5 text-[color:var(--nx-rose)]"><p>{error}</p><button type="button" onClick={() => void retryBots()} className="mt-2 font-semibold underline underline-offset-4">Tentar carregar novamente</button></div>}
        {loading ? <div role="status" className="space-y-2 p-2">{[1, 2, 3].map((n) => <div key={n} className="h-14 animate-pulse rounded-lg bg-[color:var(--nx-surface-2)]" />)}<span className="sr-only">A carregar bots</span></div> : error && !bot ? null : <>
          {pinnedBots.length > 0 && <SectionLabel>Fixados</SectionLabel>}
          {pinnedBots.map(renderBot)}
          {(visibleGroups.length > 0 || groupsNote) && (
            <>
              <SectionLabel>Grupos</SectionLabel>
              {groupsNote ? <p className="px-3 py-2 text-[12px] leading-5 text-[color:var(--nx-text-faint)]">{groupsNote}</p> : visibleGroups.map((group) => (
                <RosterRow key={group.id} id={group.id} name={group.name} role={`${group.bot_ids.length} participantes`} preview={group.last_message || "Sala de grupo"} pinned={memory.pins.includes(group.id)} unread={memory.unread(group.id, group.last_message ?? "")} onSelect={() => openGroups(group.id)} onPin={() => memory.togglePin(group.id)} />
              ))}
            </>
          )}
          <SectionLabel>Bots</SectionLabel>
          {visible.filter((item) => !memory.pins.includes(item.id)).length === 0 && pinnedBots.length === 0 ? <p className="px-3 py-8 text-center text-[13px] leading-6 text-[color:var(--nx-text-faint)]">{query ? "Nenhuma conversa encontrada." : filter === "archived" ? "Ainda não tens bots arquivados." : "Ainda não tens bots. Cria o primeiro para começar."}</p> : visible.filter((item) => !memory.pins.includes(item.id)).map(renderBot)}
        </>}
      </div>
    </section>

    <section aria-label="Conversa" className={`${mobileChat ? "flex" : "hidden lg:flex"} relative min-w-0 flex-1 flex-col`}>
      {bot ? <>
        <header className="flex min-h-[64px] items-center gap-3 border-b border-[color:var(--nx-line)] px-3 py-2 pl-14 lg:pl-4">
          <button type="button" aria-label="Voltar às conversas" onClick={() => setMobileChat(false)} className="inline-flex items-center gap-1 rounded-lg px-1 py-1 text-[12px] text-[color:var(--nx-text-dim)] lg:hidden">Bots</button>
          <IdentityMark id={bot.id} name={bot.name} size={36} live={streaming} tone={streaming ? "live" : !bot.provider || !bot.model ? "warn" : "idle"} labelled />
          <div className="min-w-0 flex-1">
            <h2 className="truncate text-[15px] font-semibold tracking-tight">{bot.name}</h2>
            <p className="truncate text-[12px] text-[color:var(--nx-text-dim)]">{streaming ? "A responder…" : bot.description || "Função não descrita"}{bot.provider && bot.model ? ` · ${bot.provider} · ${bot.model}` : ""}</p>
            <div className="mt-1"><BotStatusPill tone={streaming ? "live" : bot.provider && bot.model ? "neutral" : "warn"}>{streaming ? "A responder" : bot.provider && bot.model ? "Inferência não verificada" : "Configuração em falta"}</BotStatusPill></div>
          </div>
          <button type="button" onClick={() => setEditor(bot)} className="hidden rounded-lg border border-[color:var(--nx-line)] px-2.5 py-1.5 text-[12px] text-[color:var(--nx-text-dim)] hover:bg-[color:var(--nx-surface-2)] sm:block">Editar bot</button>
          <button type="button" aria-label="Informações do bot" aria-pressed={details} onClick={() => setDetails((open) => !open)} className="rounded-lg border border-[color:var(--nx-line)] p-2 text-[color:var(--nx-text-dim)] hover:bg-[color:var(--nx-surface-2)]"><Info size={16} /></button>
        </header>
        <div ref={scrollRegion} aria-label="Mensagens da conversa" onScroll={(event) => { const el = event.currentTarget; followMessages.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; setAwayFromBottom(!followMessages.current); if (followMessages.current) { seenCount.current = messages.length; setUnseen(0); } }} className="min-h-0 flex-1 overflow-y-auto px-3 py-5 sm:px-6">
          <div className="nx-bot-read mx-auto flex flex-col gap-4">
            {historyPages[session]?.hasMore && <button type="button" onClick={() => void loadOlder()} disabled={olderLoading || streaming} className="self-center rounded-lg px-3 py-2 text-[12px] text-[color:var(--nx-accent-bright)] hover:bg-[color:var(--nx-surface-2)] disabled:opacity-50">{olderLoading ? "A carregar…" : "Carregar mensagens anteriores"}</button>}
            {historyLoading ? <p role="status" className="text-[13px] text-[color:var(--nx-text-dim)]">A carregar conversa…</p> : historyErrors[session] ? <div role="alert" className="rounded-xl border border-[color:var(--nx-rose)]/30 p-4 text-[13px] text-[color:var(--nx-rose)]"><p>Não foi possível carregar o histórico: {historyErrors[session]}</p><button type="button" onClick={() => setHistoryAttempt((attempt) => attempt + 1)} className="mt-3 rounded-lg border border-[color:var(--nx-rose)]/40 px-3 py-2 font-medium">Tentar novamente</button></div> : messages.length === 0 ? (
              <div className="flex min-h-[45vh] flex-col items-center justify-center text-center">
                <IdentityMark id={bot.id} name={bot.name} size={84} labelled />
                <h3 className="mt-5 text-xl font-semibold tracking-tight">Olá, sou {bot.name}</h3>
                <p className="mt-2 max-w-sm text-[14px] leading-6 text-[color:var(--nx-text-dim)]">{bot.description || "Envia uma mensagem para começar."}</p>
                <p className="mt-4 max-w-md text-[12px] leading-5 text-[color:var(--nx-text-faint)]">{currentProject ? `Leitura e análise limitadas a ${currentProject.name}.` : "Seleciona um projeto na barra lateral para permitir leitura e análise dos seus ficheiros."} As ferramentas de leitura disponíveis dependem da configuração; escrita e execução estão desligadas.</p>
                {(!bot.provider || !bot.model) && <button type="button" onClick={() => setEditor(bot)} className="mt-5 rounded-xl border border-[color:var(--nx-amber)]/40 px-4 py-2.5 text-[13px] font-medium text-[color:var(--nx-amber)]">Configurar modelo</button>}
              </div>
            ) : messages.map((message, index) => {
              const previous = messages[index - 1];
              const priorUser = [...messages.slice(0, index)].reverse().find((entry) => entry.role === "user" && entry.content);
              return (
                <div key={`${message.id}-${index}`} className="flex flex-col gap-3">
                  <DayRule stamp={message.timestamp} previous={previous?.timestamp} />
                  <DirectMessage
                    message={message}
                    author={message.role === "user" ? "Tu" : bot.name}
                    authorId={message.role === "user" ? "user" : bot.id}
                    roleLabel={message.role === "assistant" ? bot.description || undefined : undefined}
                    onQuote={message.content ? (text) => quote(message.role === "user" ? "Tu" : bot.name, text) : undefined}
                    onReply={message.role === "assistant" ? () => replyTo(bot.name) : undefined}
                    onRegenerate={message.role === "assistant" && priorUser ? () => void deliver(priorUser.content) : undefined}
                  />
                </div>
              );
            })}
            {streaming && <TypingRow name={bot.name} id={bot.id} label={workingLabel(liveAssistant)} detail="Atividade da conversa em curso" />}
            {(error || streamError) && <p role="alert" className="rounded-xl border border-[color:var(--nx-rose)]/30 p-3 text-[13px] text-[color:var(--nx-rose)]">{error || streamError}</p>}
            {sendNotices[session] && <p role="status" className="rounded-xl border border-[color:var(--nx-amber)]/30 p-3 text-[13px] text-[color:var(--nx-amber)]">{sendNotices[session]}</p>}
            <div ref={bottom} />
          </div>
        </div>
        <div className="relative">
          {awayFromBottom && <JumpToLatest count={unseen} onClick={() => { followMessages.current = true; setAwayFromBottom(false); setUnseen(0); bottom.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }} />}
          <RoomComposer
            label="Mensagem"
            value={drafts[session] ?? ""}
            onChange={(value) => setDrafts((current) => ({ ...current, [session]: value }))}
            onSubmit={() => void deliver((drafts[session] ?? "").trim())}
            onStop={cancel}
            busy={streaming}
            disabled={!bot.provider || !bot.model || busyOtherSession || Boolean(historyErrors[session]) || historyLoading || !Object.hasOwn(history, session)}
            placeholder={bot.provider && bot.model ? `Mensagem para ${bot.name}` : "Configura o modelo para conversar"}
            footnote="Enter envia · Shift + Enter muda de linha. As respostas podem conter erros."
            focusTick={focusTick}
            sendLabel="Enviar mensagem"
            stopLabel="Pedir paragem"
            agents={bots.filter((item) => !item.archived && item.id !== bot.id).map((item) => ({ id: item.id, name: item.name, role: item.description || "Função não descrita" }))}
            pill={(
              <span className="inline-flex max-w-full items-center gap-1.5 truncate text-[11px] text-[color:var(--nx-text-faint)]">
                <Activity size={12} />
                {bot.provider && bot.model ? `${bot.provider} · ${bot.model}` : "Sem modelo"}
                <span className="hidden sm:inline">· {currentProject ? currentProject.name : "Sem projeto selecionado"}</span>
              </span>
            )}
          />
        </div>
      </> : (
        <div className="flex flex-1 items-center justify-center overflow-y-auto px-6 py-10">
          <div className="w-full max-w-lg">
            <span className="inline-flex rounded-2xl border border-[color:var(--nx-line)] bg-[color:var(--nx-surface-1)] p-3 text-[color:var(--nx-text-dim)]"><BotIcon size={22} /></span>
            <p className="mt-6 text-[10px] font-medium uppercase tracking-[0.16em] text-[color:var(--nx-text-faint)]">Sala de bots</p>
            <h2 className="mt-2 text-2xl font-semibold tracking-tight">As tuas conversas, num só lugar</h2>
            <p className="mt-3 max-w-md text-[14px] leading-6 text-[color:var(--nx-text-dim)]">Cria assistentes para tarefas diferentes, retoma uma conversa ou junta perspetivas num grupo.</p>
            <div className="mt-6 flex flex-wrap gap-2">
              <button type="button" onClick={() => setEditor("new")} className="inline-flex items-center gap-2 rounded-xl bg-[color:var(--nx-accent)] px-4 py-2.5 text-[13px] font-medium text-white"><Plus size={15} /> Criar bot</button>
              <button type="button" disabled={streaming || busyOtherSession} onClick={() => openGroups()} className="inline-flex items-center gap-2 rounded-xl border border-[color:var(--nx-line)] px-4 py-2.5 text-[13px] disabled:opacity-40"><Users size={15} /> Abrir grupos</button>
            </div>
            <dl className="mt-8 flex gap-8 text-[13px]">
              <div><dt className="text-[color:var(--nx-text-faint)]">Bots ativos</dt><dd className="mt-1 text-xl font-semibold">{loading || error ? "—" : activeCount}</dd></div>
              <div><dt className="text-[color:var(--nx-text-faint)]">Por configurar</dt><dd className="mt-1 text-xl font-semibold">{loading || error ? "—" : unconfiguredCount}</dd><dd className="text-[11px] text-[color:var(--nx-text-faint)]">Sem provedor ou modelo</dd></div>
            </dl>
          </div>
        </div>
      )}
    </section>

    {bot && details && <aside aria-label="Informações do bot" className="nx-bot-drawer absolute inset-y-0 right-0 z-20 flex w-[min(100%,340px)] flex-col border-l border-[color:var(--nx-line)] bg-[color:var(--nx-surface-1)] shadow-2xl xl:relative xl:shadow-none">
      <div className="flex items-center justify-between border-b border-[color:var(--nx-line)] px-4 py-3">
        <div><h2 className="text-[13px] font-semibold">Informações do bot</h2><p className="text-[11px] text-[color:var(--nx-text-faint)]">Perfil e configuração</p></div>
        <button type="button" onClick={() => setDetails(false)} aria-label="Fechar informações" className="rounded-lg p-2 text-[color:var(--nx-text-faint)] hover:bg-[color:var(--nx-surface-3)]"><X size={16} /></button>
      </div>
      <div className="flex-1 overflow-y-auto p-4">
        <div className="flex flex-col items-center pb-5 text-center">
          <IdentityMark id={bot.id} name={bot.name} size={72} labelled />
          <h3 className="mt-3 text-lg font-semibold">{bot.name}</h3>
          <p className="mt-1 max-w-full break-words text-[13px] leading-5 text-[color:var(--nx-text-dim)]">{bot.description || "Adiciona uma descrição para identificares a função deste bot."}</p>
          <span className="mt-3"><BotStatusPill tone={bot.provider && bot.model ? "neutral" : "warn"}>{bot.provider && bot.model ? "Modelo configurado" : "Configuração em falta"}</BotStatusPill></span>
        </div>
        <div className="space-y-3 rounded-xl border border-[color:var(--nx-line)] p-3 text-[12px]">
          <h4 className="text-[10px] font-medium uppercase tracking-[0.14em] text-[color:var(--nx-text-faint)]">Configuração</h4>
          <p><span className="text-[color:var(--nx-text-faint)]">Provedor</span><span className="mt-0.5 block break-all text-[13px]">{bot.provider || "Não configurado"}</span></p>
          <p><span className="text-[color:var(--nx-text-faint)]">Modelo</span><span className="mt-0.5 block break-all text-[13px]">{bot.model || "Não configurado"}</span></p>
        </div>
        <div className="mt-3 rounded-xl border border-[color:var(--nx-line)] p-3">
          <h4 className="text-[10px] font-medium uppercase tracking-[0.14em] text-[color:var(--nx-text-faint)]">Instruções</h4>
          <p className="mt-2 whitespace-pre-wrap break-words text-[13px] leading-6">{bot.instructions || "Sem instruções personalizadas."}</p>
        </div>
        <div className="mt-3 rounded-xl border border-[color:var(--nx-line)] p-3">
          <h4 className="text-[10px] font-medium uppercase tracking-[0.14em] text-[color:var(--nx-text-faint)]">Acesso</h4>
          <p className="mt-2 text-[12px] leading-5 text-[color:var(--nx-text-dim)]">Ferramentas de leitura disponíveis conforme a configuração. {currentProject ? `Projeto selecionado: ${currentProject.name}.` : "Seleciona um projeto para permitir a leitura dos seus ficheiros."} Escrita, execução e delegação estão desativadas.</p>
        </div>
        <div className="mt-3 space-y-1">
          <button type="button" onClick={() => setEditor(bot)} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[13px] hover:bg-[color:var(--nx-surface-2)]"><Settings2 size={15} /> Editar configuração <ChevronRight size={14} className="ml-auto" /></button>
          <button type="button" onClick={() => void changeArchive()} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[13px] hover:bg-[color:var(--nx-surface-2)]"><Archive size={15} /> {bot.archived ? "Retirar do arquivo" : "Arquivar conversa"}</button>
          <button type="button" onClick={() => void remove()} className="flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-[13px] text-[color:var(--nx-rose)] hover:bg-[color:var(--nx-surface-2)]"><Trash2 size={15} /> Remover bot</button>
        </div>
      </div>
    </aside>}
    {editor && <BotEditor bot={editor === "new" ? null : editor} close={() => setEditor(null)} saved={(item) => { setBots((items) => [item, ...items.filter((existing) => existing.id !== item.id)]); setEditor(null); choose(item); }} />}
  </div>;
}
