"use client";

import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Activity, Archive, ArrowDown, ArrowLeft, Bot as BotIcon, Check, ChevronRight, Copy, Info, LayoutGrid, Loader2, Plus, Search, Send, Settings2, Square, Trash2, Users, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { getProviderCatalog, getProviderModels, getSessionHistoryPage, type ProviderSpec } from "../../lib/api";
import { createBot, listBots, removeBot, updateBot, type Bot, type BotSettings } from "../../lib/bots";
import { foldRun } from "../../lib/foldRun";
import type { ChatMessage } from "../../lib/types";
import { useAgentStream } from "../../hooks/useAgentStream";
import { useThemeStore } from "../../stores/themeStore";
import { useProjectStore } from "../../stores/projectStore";
import GroupWorkspace from "./GroupWorkspace";
import WorkspaceOverview from "./WorkspaceOverview";
import { BOT_INPUT as inputClass, BotAvatar as Avatar, formatBotTime as formatTime } from "./botsUi";

const MessageCodeBlock = lazy(() => import("../chat/MessageCodeBlock"));

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
const selectedKey = "nexus:bots:selected";
function rememberSelection(id: string) {
  try {
    if (id) window.localStorage.setItem(selectedKey, id);
    else window.localStorage.removeItem(selectedKey);
  } catch { /* The current selection still works with storage disabled. */ }
}

function BotEditor({ bot, close, saved }: { bot: Bot | null; close: () => void; saved: (bot: Bot) => void }) {
  const [form, setForm] = useState<BotSettings>(bot ? {
    name: bot.name, description: bot.description, instructions: bot.instructions, provider: bot.provider, model: bot.model,
  } : blankSettings);
  const [providers, setProviders] = useState<ProviderSpec[]>([]);
  const [catalogError, setCatalogError] = useState(false);
  const [models, setModels] = useState<string[]>([]);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loadingModels, setLoadingModels] = useState(false);
  const [saving, setSaving] = useState(false);
  const [modelRevision, setModelRevision] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const selectedProvider = providers.find((provider) => provider.id === form.provider);

  useEffect(() => {
    dialog.current?.showModal();
    let active = true;
    void getProviderCatalog().then((items) => { if (active) setProviders(items); }).catch(() => {
      if (active) setCatalogError(true);
    });
    return () => { active = false; };
  }, []);

  const set = (key: keyof BotSettings, value: string) => setForm((current) => ({ ...current, [key]: value }));
  useEffect(() => {
    if (!form.provider) return;
    let active = true;
    setModels([]); setLoadingModels(true); setNotice("");
    void getProviderModels(form.provider, modelRevision > 0).then((result) => {
      if (!active) return;
      setModels(result.models.map((model) => model.id));
      setNotice(result.error ? `Não foi possível confirmar a ligação: ${result.error}` : !result.configured
        ? "Este provider não tem chave configurada; os modelos remotos podem não aparecer. Configura a chave em Definições."
        : result.cached
          ? `Catálogo em cache: ${result.models.length} modelo(s). A inferência ainda não foi verificada.`
          : `${result.models.length} modelo(s) disponíveis neste momento. A inferência ainda não foi verificada.`);
    }).catch((reason) => {
      if (active) setNotice(reason instanceof Error ? reason.message : "Não foi possível consultar os modelos.");
    }).finally(() => { if (active) setLoadingModels(false); });
    return () => { active = false; };
  }, [form.provider, modelRevision]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (saving || !form.name.trim()) return;
    setSaving(true); setError("");
    const settings = { ...form, name: form.name.trim(), model: form.model.trim() };
    try { saved(bot ? await updateBot(bot.id, settings) : await createBot(settings)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível guardar o bot."); }
    finally { setSaving(false); }
  };
  return (
    <dialog ref={dialog} onCancel={(event) => { event.preventDefault(); close(); }} aria-labelledby="bot-editor-title" className="m-auto w-[min(92vw,620px)] max-w-none rounded-2xl nx-bot-panel border p-0 text-[var(--nx-text)] shadow-2xl backdrop:bg-black/75">
      <form onSubmit={(event) => void submit(event)} className="max-h-[90dvh] overflow-y-auto">
        <div className="sticky top-0 z-10 flex items-start justify-between border-b border-[var(--nx-line)] bg-[var(--nx-surface-1)] px-6 py-5">
          <div><h2 id="bot-editor-title" className="text-lg font-semibold">{bot ? "Editar bot" : "Criar bot"}</h2><p className="mt-1 text-xs text-[var(--nx-text-dim)]">Define a identidade e o modelo desta conversa.</p></div>
          <button type="button" onClick={close} aria-label="Fechar" className="rounded-lg p-2 text-[var(--nx-text-dim)] hover:bg-[var(--nx-surface-3)] hover:text-[var(--nx-text)]"><X size={18} /></button>
        </div>
        <div className="space-y-5 px-6 py-5">
          {!bot && <label className="block text-xs font-medium text-[var(--nx-text)]">Ponto de partida
            <select aria-label="Ponto de partida" className={`${inputClass} mt-2`} defaultValue="Personalizado" onChange={(event) => {
              const template = TEMPLATES.find((item) => item.name === event.target.value);
              if (template) setForm((current) => ({ ...current, description: template.description, instructions: template.instructions }));
            }}>{TEMPLATES.map((template) => <option key={template.name}>{template.name}</option>)}</select>
          </label>}
          <label className="block text-xs font-medium text-[var(--nx-text)]">Nome<input className={`${inputClass} mt-2`} required maxLength={80} value={form.name} onChange={(event) => set("name", event.target.value)} placeholder="Ex.: Pixel" autoFocus /></label>
          <label className="block text-xs font-medium text-[var(--nx-text)]">Descrição<input className={`${inputClass} mt-2`} maxLength={500} value={form.description} onChange={(event) => set("description", event.target.value)} placeholder="Em que é que este bot te ajuda?" /></label>
          <label className="block text-xs font-medium text-[var(--nx-text)]">Instruções<textarea className={`${inputClass} mt-2 min-h-24 resize-y`} maxLength={4000} value={form.instructions} onChange={(event) => set("instructions", event.target.value)} placeholder="Especialidade, estilo de resposta e objetivo…" /></label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-xs font-medium text-[var(--nx-text)]">Provedor<select className={`${inputClass} mt-2`} value={form.provider} onChange={(event) => {
              const providerId = event.target.value;
              setForm((current) => ({ ...current, provider: providerId, model: "" }));
              setModelRevision(0); setModels([]); setNotice(""); setError(""); setLoadingModels(Boolean(providerId));
            }}>
              <option value="">Selecionar mais tarde</option>
              {form.provider && !selectedProvider && <option value={form.provider}>{form.provider}</option>}
              {providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}
            </select></label>
            <label className="block text-xs font-medium text-[var(--nx-text)]">Modelo<input list="bot-models" className={`${inputClass} mt-2`} value={form.model} onChange={(event) => set("model", event.target.value)} maxLength={128} placeholder={loadingModels ? "A carregar modelos…" : "Pesquisa ou escreve o ID do modelo"} /><datalist id="bot-models">{models.map((model) => <option key={model} value={model} />)}</datalist></label>
          </div>
          {selectedProvider && <p className="-mt-2 text-[11px] text-[var(--nx-text-faint)]">{selectedProvider.requires_key ? selectedProvider.api_key_set ? "Chave configurada no backend." : "Sem chave configurada para este provider." : "Provider local ou sem chave obrigatória."} <a href="/settings" className="text-[var(--nx-accent-bright)] hover:text-[var(--nx-accent-bright)]">Gerir em Definições</a></p>}
          <button type="button" disabled={!form.provider || loadingModels} onClick={() => setModelRevision((value) => value + 1)} className="text-xs font-medium text-[var(--nx-accent-bright)] hover:text-[var(--nx-accent-bright)] disabled:opacity-40">{loadingModels ? "A consultar…" : "Atualizar modelos disponíveis"}</button>
          {catalogError && <p role="status" className="nx-bot-note rounded-xl border p-3 text-xs">O catálogo de provedores está indisponível. Podes manter o provedor atual e escrever o ID do modelo.</p>}
          {notice && <p role="status" className="text-xs leading-5 text-[var(--nx-text-dim)]">{notice}</p>}
          <p className="rounded-xl border border-white/5 bg-white/[0.03] p-3 text-xs leading-5 text-[var(--nx-text-dim)]">Os bots podem usar ferramentas de leitura disponíveis. Com um projeto selecionado, podem também inspecionar os seus ficheiros. Escrita, execução e delegação estão desativadas. As credenciais e o endpoint são configurados nas definições do NEXUS.</p>
          {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
        </div>
        <div className="sticky bottom-0 z-10 flex justify-end gap-3 border-t border-[var(--nx-line)] bg-[var(--nx-surface-1)] px-6 py-4"><button type="button" onClick={close} className="rounded-xl px-4 py-2 text-sm text-[var(--nx-text-dim)] hover:text-[var(--nx-text)]">Cancelar</button><button disabled={saving} className="nx-bot-action nx-bot-primary">{saving ? "A guardar…" : "Guardar bot"}</button></div>
      </form>
    </dialog>
  );
}

function Message({ message }: { message: ChatMessage }) {
  const [copied, setCopied] = useState(false);
  const theme = useThemeStore((state) => state.theme);
  const mine = message.role === "user";
  const tools = message.toolCalls ?? [];
  if (!message.content && tools.length === 0) return null;
  return <div className={`group flex ${mine ? "justify-end" : "justify-start"}`}>
    <div data-mine={mine} className="nx-bot-message max-w-[92%] min-w-0 rounded-2xl border px-4 py-3 text-sm leading-6 sm:max-w-[82%]">
      {tools.length > 0 && <details className="mb-3 rounded-xl border border-white/[0.07] bg-black/10 text-xs text-[var(--nx-text-dim)]"><summary className="cursor-pointer px-3 py-2 font-medium text-[var(--nx-accent-bright)]">Atividade · {tools.length} {tools.length === 1 ? "chamada" : "chamadas"}</summary><ul className="space-y-2 border-t border-white/[0.06] px-3 py-3">{tools.map((tool) => <li key={tool.id} className="flex items-start justify-between gap-3"><span className="break-all text-[var(--nx-text)]">{tool.name}</span><span className={tool.status === "error" ? "shrink-0 text-red-300" : "shrink-0 text-[var(--nx-text-dim)]"}>{tool.status === "running" ? "Em curso" : tool.status === "success" ? "Concluída" : tool.status === "error" ? "Falhou" : tool.status === "awaiting_confirmation" ? "A aguardar confirmação" : "Resultado desconhecido"}</span></li>)}</ul></details>}
      {message.content && <>
      <div className="nx-prose min-w-0 break-words [&_pre]:max-w-full [&_pre]:overflow-x-auto">
        <ReactMarkdown components={{ code({ className, children, node: _node, ...props }) {
          const language = /language-([\w-]+)/.exec(className || "")?.[1];
          return language ? <Suspense fallback={<code className={className}>{children}</code>}><MessageCodeBlock language={language} code={String(children).replace(/\n$/, "")} theme={theme === "light" ? "light" : "dark"} /></Suspense> : <code className={className} {...props}>{children}</code>;
        } }}>{message.content}</ReactMarkdown>
      </div>
      <div className="mt-1 flex items-center justify-end gap-2 text-[10px] text-[var(--nx-text-faint)]"><time>{formatTime(message.timestamp)}</time><button type="button" aria-label="Copiar mensagem" onClick={() => void navigator.clipboard.writeText(message.content).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1200); })} className="rounded p-1 text-[var(--nx-text-faint)] hover:text-zinc-200">{copied ? <Check size={12} /> : <Copy size={12} />}</button></div>
      </>}
    </div>
  </div>;
}

function WorkingIndicator({ botName, message }: { botName: string; message?: ChatMessage }) {
  const activeTool = [...(message?.toolCalls ?? [])].reverse().find((tool) => tool.status === "running");
  const waiting = (message?.toolCalls ?? []).some((tool) => tool.status === "awaiting_confirmation");
  const label = waiting ? "A aguardar confirmação" : activeTool ? `A usar ${activeTool.name}` : message?.content ? "A gerar resposta" : message?.thinking ? "A analisar a tarefa" : "A preparar resposta";
  return <div role="status" aria-live="polite" className="flex w-fit max-w-full items-center gap-3 rounded-2xl border border-violet-300/15 bg-violet-400/[0.07] px-4 py-3 text-xs text-violet-100">
    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-violet-400/10"><Loader2 size={16} className="animate-spin motion-reduce:animate-none" /></span>
    <span className="min-w-0"><span className="block font-medium">{botName} · {label}</span><span className="mt-1 block text-[var(--nx-accent-bright)]/60">Atividade da conversa em curso</span></span>
    <span aria-hidden="true" className="flex gap-1"><span className="h-1 w-1 animate-pulse rounded-full bg-violet-300 motion-reduce:animate-none" /><span className="h-1 w-1 animate-pulse rounded-full bg-violet-300 motion-reduce:animate-none" /><span className="h-1 w-1 animate-pulse rounded-full bg-violet-300 motion-reduce:animate-none" /></span>
  </div>;
}

export default function BotsWorkspace() {
  const [bots, setBots] = useState<Bot[]>([]);
  const [showGroups, setShowGroups] = useState(false);
  const [groupsVisited, setGroupsVisited] = useState(false);
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
  const [awayFromBottom, setAwayFromBottom] = useState(false);
  const submitting = useRef(false);
  const bottom = useRef<HTMLDivElement>(null);
  const scrollRegion = useRef<HTMLDivElement>(null);
  const previousScrollHeight = useRef<{ session: string; height: number } | null>(null);
  const followMessages = useRef(true);
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
      let saved: string | null = null;
      try { saved = window.localStorage.getItem(selectedKey); } catch { /* Storage is optional. */ }
      const restored = items.find((item) => item.id === saved);
      if (restored) { setSelected(restored.id); setFilter(restored.archived ? "archived" : "all"); }
    }).catch((reason) => { if (alive) setError(reason instanceof Error ? reason.message : "Não foi possível carregar os bots."); }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);
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
    if (lastScrollSession.current !== session) {
      lastScrollSession.current = session;
      followMessages.current = true;
      setAwayFromBottom(false);
    }
    if (previousScrollHeight.current?.session === session && scrollRegion.current) {
      scrollRegion.current.scrollTop += scrollRegion.current.scrollHeight - previousScrollHeight.current.height;
      previousScrollHeight.current = null;
    } else {
      previousScrollHeight.current = null;
      if (followMessages.current) bottom.current?.scrollIntoView({ block: "end" });
    }
  }, [session, messages.length, events]);
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
  const search = query.trim().toLocaleLowerCase();
  const visible = bots.filter((item) => (filter === "archived" ? item.archived : !item.archived) && `${item.name} ${item.description} ${item.provider} ${item.model} ${item.last_message ?? ""}`.toLocaleLowerCase().includes(search));
  const retryBots = async () => {
    setLoading(true); setError("");
    try { await reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível carregar os bots."); }
    finally { setLoading(false); }
  };
  const choose = (item: Bot) => {
    setSelected(item.id);
    setFilter(item.archived ? "archived" : "all");
    setMobileChat(true);
    setDetails(false);
    setError("");
    rememberSelection(item.id);
  };
  const overview = () => {
    setSelected("");
    setMobileChat(false);
    setDetails(false);
    rememberSelection("");
  };
  const submit = async () => {
    const value = (drafts[session] ?? "").trim();
    if (!value || !canSend || streaming || submitting.current) return;
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
  const onKey = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); void submit(); }
  };
  const changeArchive = async () => {
    if (!bot) return;
    try { const changed = await updateBot(bot.id, { archived: !bot.archived }); setBots((items) => items.map((item) => item.id === changed.id ? changed : item)); setFilter(changed.archived ? "archived" : "all"); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível arquivar."); }
  };
  const remove = async () => {
    if (!bot || !window.confirm(`Remover ${bot.name} da lista? O histórico fica guardado.`)) return;
    try { await removeBot(bot.id); setBots((items) => items.filter((item) => item.id !== bot.id)); overview(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível remover o bot."); }
  };


  const openGroups = () => { setGroupsVisited(true); setShowGroups(true); };

  const canSend = Boolean(bot?.provider && bot.model && history[session] && !busyOtherSession && !historyLoading && !historyErrors[session]);

  return (
    <>
    {groupsVisited && <div hidden={!showGroups} className="h-full"><GroupWorkspace bots={bots} onBack={() => setShowGroups(false)} /></div>}
    <div className={showGroups ? "hidden" : "nx-bot-workspace relative flex h-full min-h-0 overflow-hidden"}>
      <section aria-label="Lista de conversas" className={(mobileChat ? "hidden md:flex " : "flex ") + "nx-bot-nav w-full shrink-0 flex-col border-r md:w-[270px] xl:w-[310px]"}>
        <div className="px-4 pb-3 pt-3">
          <div className="flex min-h-9 items-center justify-between gap-3 pl-10 md:pl-0">
            <h1 className="flex min-w-0 items-center gap-2 text-lg font-semibold tracking-tight"><BotIcon size={18} className="hidden shrink-0 text-[var(--nx-accent-bright)] md:block" /> Bots</h1>
            <button type="button" onClick={() => setEditor("new")} className="nx-bot-action nx-bot-primary shrink-0"><Plus size={15} /> Criar bot</button>
          </div>
          <nav aria-label="Área de bots" className="mt-4 grid grid-cols-2 gap-2">
            <button type="button" onClick={() => { overview(); setMobileChat(true); }} aria-current={!bot ? "true" : undefined} className="nx-bot-action nx-bot-item px-2">
              <LayoutGrid size={15} /> Visão geral
            </button>
            <button type="button" disabled={streaming || busyOtherSession} onClick={openGroups} className="nx-bot-action px-2">
              <Users size={15} /> Grupos
            </button>
          </nav>
          <label className="relative mt-4 block">
            <Search size={15} className="pointer-events-none absolute left-3 top-3 text-[var(--nx-text-faint)]" />
            <input aria-label="Pesquisar conversas" type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Pesquisar conversas" className={inputClass + " h-10 pl-9"} />
          </label>
          <div role="tablist" aria-label="Filtrar conversas" className="mt-3 grid grid-cols-2 gap-1 rounded-xl bg-[var(--nx-surface-3)] p-1">
            {([["all", "Ativos", activeCount], ["archived", "Arquivados", archivedCount]] as const).map(([id, label, count]) => (
              <button key={id} role="tab" aria-selected={filter === id} data-selected={filter === id} onClick={() => setFilter(id)} className="nx-bot-item rounded-lg border border-transparent px-2 py-1.5 text-xs font-medium text-[var(--nx-text-dim)]">
                {label} <span aria-hidden="true" className="ml-1 tabular-nums text-[var(--nx-text-faint)]">{count}</span>
              </button>
            ))}
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-4">
          {error && !bot && <div role="alert" className="nx-bot-error mb-3 rounded-xl border p-3 text-xs leading-5"><p>{error}</p><button type="button" onClick={() => void retryBots()} className="mt-2 font-semibold underline underline-offset-4">Tentar carregar novamente</button></div>}
          {loading ? (
            <div role="status" className="space-y-2 px-1 pt-1">
              {[1, 2, 3].map((n) => <div key={n} className="h-14 rounded-xl bg-[var(--nx-surface-3)] motion-safe:animate-pulse" />)}
              <span className="sr-only">A carregar bots</span>
            </div>
          ) : error && !bot ? null : visible.length === 0 ? (
            <div className="px-3 py-8 text-center text-sm leading-6 text-[var(--nx-text-dim)]">
              {search ? "Nenhuma conversa encontrada." : filter === "archived" ? "Ainda não tens bots arquivados." : "Ainda não tens bots. Cria o primeiro para começar."}
            </div>
          ) : (
            <div className="space-y-1">
              {visible.map((item) => (
                <button key={item.id} type="button" onClick={() => choose(item)} aria-current={selected === item.id ? "true" : undefined} className="nx-bot-item flex w-full items-center gap-3 rounded-xl border border-transparent p-2.5 text-left">
                  <Avatar name={item.name} id={item.id} compact thinking={selected === item.id && streaming} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-semibold">{item.name}</span>
                      {item.last_message && <time className="shrink-0 text-[10px] text-[var(--nx-text-faint)]">{formatTime(item.last_active_at)}</time>}
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-[var(--nx-text-dim)]">
                      {item.last_message || item.description || item.model || "Modelo por configurar"}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
        <div className="hidden border-t border-[var(--nx-line)] px-4 py-3 text-xs text-[var(--nx-text-faint)] md:block">Histórico guardado nesta instalação.</div>
      </section>

      <section aria-label={bot ? "Conversa" : "Visão geral dos bots"} className={(mobileChat ? "flex " : "hidden md:flex ") + "relative min-w-0 flex-1 flex-col"}>
        {bot ? (
          <>
            <header className="nx-bot-panel flex min-h-[74px] shrink-0 items-center gap-3 border-b px-4 pl-14 md:px-6">
              <button type="button" aria-label="Voltar às conversas" onClick={() => { setMobileChat(false); setDetails(false); }} className="nx-bot-action shrink-0 px-2 md:hidden"><ArrowLeft size={17} /></button>
              <Avatar name={bot.name} id={bot.id} thinking={streaming} />
              <div className="min-w-0 flex-1">
                <h2 className="truncate text-base font-semibold">{bot.name}</h2>
                <p className="mt-0.5 truncate text-xs text-[var(--nx-text-dim)]">{streaming ? "A responder…" : bot.provider && bot.model ? bot.provider + " · " + bot.model : "Modelo por configurar"}</p>
              </div>
              <button type="button" onClick={() => setEditor(bot)} disabled={streaming} className="nx-bot-action hidden sm:inline-flex">Editar bot</button>
              <button type="button" aria-label="Informações do bot" aria-pressed={details} onClick={() => setDetails((open) => !open)} className="nx-bot-action shrink-0 px-2.5"><Info size={18} /></button>
            </header>
            <div ref={scrollRegion} aria-label="Mensagens da conversa" onScroll={(event) => {
              const el = event.currentTarget;
              followMessages.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
              setAwayFromBottom(!followMessages.current);
            }} className="min-h-0 flex-1 overflow-y-auto px-4 py-6 sm:px-8">
              <div className="mx-auto flex max-w-3xl flex-col gap-4">
                {historyPages[session]?.hasMore && <button type="button" onClick={() => void loadOlder()} disabled={olderLoading || streaming} className="nx-bot-action self-center">{olderLoading ? "A carregar…" : "Carregar mensagens anteriores"}</button>}
                {historyErrors[session] ? (
                  <div role="alert" className="nx-bot-error rounded-xl border p-4 text-sm">
                    <p>Não foi possível carregar o histórico: {historyErrors[session]}</p>
                    <button type="button" onClick={() => setHistoryAttempt((attempt) => attempt + 1)} className="nx-bot-action mt-3">Tentar novamente</button>
                  </div>
                ) : !history[session] ? <p role="status" className="text-sm text-[var(--nx-text-dim)]">A carregar conversa…</p> : messages.length === 0 ? (
                  <div className="flex min-h-[40vh] flex-col items-center justify-center px-2 text-center">
                    <Avatar name={bot.name} id={bot.id} large />
                    <h3 className="mt-5 text-2xl font-semibold tracking-tight">Olá, sou {bot.name}</h3>
                    <p className="mt-2 max-w-sm text-sm leading-6 text-[var(--nx-text-dim)]">{bot.description || "Envia uma mensagem para começar."}</p>
                    {(!bot.provider || !bot.model) && <button type="button" onClick={() => setEditor(bot)} className="nx-bot-action nx-bot-primary mt-5"><Settings2 size={16} /> Configurar modelo</button>}
                  </div>
                ) : messages.map((message, index) => <Message key={message.id + "-" + index} message={message} />)}
                {streaming && <WorkingIndicator botName={bot.name} message={liveAssistant} />}
                {(error || streamError) && <p role="alert" className="nx-bot-error rounded-xl border p-3 text-sm">{error || streamError}</p>}
                {sendNotices[session] && <p role="status" className="nx-bot-note rounded-xl border p-3 text-sm">{sendNotices[session]}</p>}
                <div ref={bottom} />
              </div>
            </div>
            <div className="relative shrink-0 px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-2 sm:px-7">
              <div className="mx-auto max-w-3xl">
                {awayFromBottom && <button type="button" onClick={() => {
                  followMessages.current = true;
                  setAwayFromBottom(false);
                  bottom.current?.scrollIntoView({ block: "end", behavior: window.matchMedia?.("(prefers-reduced-motion: reduce)")?.matches ? "auto" : "smooth" });
                }} className="nx-bot-action absolute -top-11 left-1/2 -translate-x-1/2 shadow-lg"><ArrowDown size={15} /> Ir para o fim</button>}
                <div className="nx-bot-composer flex items-end gap-2 rounded-2xl border p-2">
                  <textarea aria-label="Mensagem" rows={2} value={drafts[session] ?? ""} onChange={(event) => setDrafts((current) => ({ ...current, [session]: event.target.value }))} onKeyDown={onKey}
                    placeholder={bot.provider && bot.model ? "Mensagem para " + bot.name : "Configura o modelo para conversar"} disabled={!canSend}
                    className="max-h-40 min-h-[52px] min-w-0 flex-1 resize-y bg-transparent px-2 py-2.5 text-sm outline-none placeholder:text-[var(--nx-text-faint)] disabled:opacity-60" />
                  {streaming ? <button type="button" onClick={cancel} aria-label="Pedir paragem" className="nx-bot-action px-3"><Square size={15} fill="currentColor" /></button>
                    : <button type="button" onClick={() => void submit()} disabled={!canSend || !(drafts[session] ?? "").trim()} aria-label="Enviar mensagem" className="nx-bot-action nx-bot-primary px-3"><Send size={16} /></button>}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 pt-2 text-[11px] text-[var(--nx-text-faint)]">
                  <span className="inline-flex min-w-0 items-center gap-1.5"><Activity size={12} className="shrink-0" />{busyOtherSession ? "Outra conversa está a responder" : currentProject ? currentProject.name + " · ferramentas de leitura" : "Sem projeto selecionado"}</span>
                  <span className="hidden sm:inline">Enter envia · Shift + Enter muda de linha</span>
                </div>
              </div>
            </div>
          </>
        ) : <WorkspaceOverview bots={bots} loading={loading} failed={Boolean(error)} groupDisabled={streaming || busyOtherSession} onCreate={() => setEditor("new")} onGroups={openGroups} onChoose={choose} onBack={() => setMobileChat(false)} />}
      </section>

      {bot && details && (
        <aside aria-label="Informações do bot" className="nx-bot-panel absolute inset-y-0 right-0 z-20 flex w-[min(100%,320px)] flex-col border-l shadow-2xl xl:relative xl:shadow-none">
          <div className="flex shrink-0 items-center justify-between border-b border-[var(--nx-line)] p-4">
            <h2 className="text-sm font-semibold">Informações do bot</h2>
            <button type="button" onClick={() => setDetails(false)} aria-label="Fechar informações" className="nx-bot-action px-2.5"><X size={17} /></button>
          </div>
          <div className="flex-1 overflow-y-auto p-4">
            <div className="flex items-center gap-3 pb-4">
              <Avatar name={bot.name} id={bot.id} />
              <div className="min-w-0"><h3 className="text-base font-semibold">{bot.name}</h3><p className="text-xs text-[var(--nx-text-dim)]">{bot.provider && bot.model ? "Modelo configurado" : "Configuração em falta"}</p></div>
            </div>
            <dl className="nx-bot-note space-y-3 rounded-xl border p-3 text-sm">
              <div><dt className="text-xs text-[var(--nx-text-faint)]">Provedor</dt><dd className="mt-0.5 break-all">{bot.provider || "Não configurado"}</dd></div>
              <div><dt className="text-xs text-[var(--nx-text-faint)]">Modelo</dt><dd className="mt-0.5 break-all">{bot.model || "Não configurado"}</dd></div>
            </dl>
            <h4 className="mt-5 text-sm font-semibold">Instruções</h4>
            <p className="mt-1 whitespace-pre-wrap text-sm leading-6 text-[var(--nx-text-dim)]">{bot.instructions || "Sem instruções personalizadas."}</p>
            <h4 className="mt-5 text-sm font-semibold">Acesso</h4>
            <p className="mt-1 text-xs leading-5 text-[var(--nx-text-dim)]">Ferramentas de leitura disponíveis conforme a configuração. {currentProject ? "Projeto selecionado: " + currentProject.name + "." : "Seleciona um projeto para permitir a leitura dos seus ficheiros."} Escrita, execução e delegação estão desativadas.</p>
            <div className="mt-5 grid gap-2">
              <button type="button" disabled={streaming} onClick={() => setEditor(bot)} className="nx-bot-action justify-start"><Settings2 size={16} /> Editar configuração <ChevronRight size={15} className="ml-auto" /></button>
              <button type="button" disabled={streaming} onClick={() => void changeArchive()} className="nx-bot-action justify-start"><Archive size={16} /> {bot.archived ? "Retirar do arquivo" : "Arquivar conversa"}</button>
              <button type="button" disabled={streaming} onClick={() => void remove()} className="nx-bot-action justify-start"><Trash2 size={16} /> Remover bot</button>
            </div>
          </div>
        </aside>
      )}
      {editor && <BotEditor bot={editor === "new" ? null : editor} close={() => setEditor(null)} saved={(item) => {
        setBots((items) => [item, ...items.filter((existing) => existing.id !== item.id)]);
        setEditor(null);
        choose(item);
      }} />}
    </div>
    </>
  );
}
