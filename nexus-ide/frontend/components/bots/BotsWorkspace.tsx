"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Activity, Archive, ArrowDown, ArrowLeft, Bot as BotIcon, Check, ChevronRight, Copy, Info, Loader2, Plus, Search, Send, Settings2, Square, Trash2, Users, X } from "lucide-react";
import { getProviderCatalog, getProviderModels, getSessionHistoryPage, type ProviderSpec } from "../../lib/api";
import { createBot, listBots, removeBot, updateBot, type Bot, type BotSettings } from "../../lib/bots";
import { foldRun } from "../../lib/foldRun";
import type { ChatMessage } from "../../lib/types";
import { useAgentStream } from "../../hooks/useAgentStream";
import { useProjectStore } from "../../stores/projectStore";
import GroupWorkspace from "./GroupWorkspace";
import { AssistantMarkdown } from "../chat/MessageBubble";
import { useThemeStore } from "../../stores/themeStore";
import { BotStatusPill } from "./botsUi";

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
const inputClass = "w-full rounded-xl border border-white/10 bg-[#15171d] px-3 py-2.5 text-sm text-white outline-none placeholder:text-zinc-600 focus:border-violet-400/60 focus:ring-2 focus:ring-violet-400/10";

function Avatar({ name, id = name, large = false, thinking = false }: { name: string; id?: string; large?: boolean; thinking?: boolean }) {
  let hash = 0;
  for (const character of id) hash = (hash * 31 + character.charCodeAt(0)) | 0;
  const hue = [262, 198, 168, 42, 12, 320][Math.abs(hash) % 6];
  const initial = name.trim().charAt(0).toUpperCase() || "?";
  return <span aria-hidden="true" className={`relative flex shrink-0 items-center justify-center overflow-hidden border font-semibold ${thinking ? "border-cyan-300/60" : "border-white/10"} ${large ? "h-28 w-28 rounded-[1.75rem] text-4xl" : "h-11 w-11 rounded-xl text-sm"}`} style={{ background: `hsl(${hue} 32% 22%)`, color: `hsl(${hue} 80% 86%)`, borderColor: thinking ? undefined : `hsla(${hue}, 70%, 68%, .4)` }}>
    {thinking && <span className="absolute inset-0 animate-pulse rounded-[inherit] bg-cyan-300/10" />}
    <span className="relative">{initial}</span>
  </span>;
}

function formatTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const now = new Date();
  return date.toDateString() === now.toDateString()
    ? date.toLocaleTimeString("pt-PT", { hour: "2-digit", minute: "2-digit" })
    : date.toLocaleDateString("pt-PT", { day: "2-digit", month: "short" });
}

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
    <dialog ref={dialog} onCancel={(event) => { event.preventDefault(); close(); }} aria-labelledby="bot-editor-title" className="m-auto w-[min(92vw,620px)] max-w-none rounded-2xl border border-white/10 bg-[#101116] p-0 text-zinc-100 shadow-2xl backdrop:bg-black/75">
      <form onSubmit={(event) => void submit(event)} className="max-h-[90dvh] overflow-y-auto">
        <div className="sticky top-0 z-10 flex items-start justify-between border-b border-white/10 bg-[#101116] px-6 py-5">
          <div><h2 id="bot-editor-title" className="text-lg font-semibold">{bot ? "Editar bot" : "Criar bot"}</h2><p className="mt-1 text-xs text-zinc-400">Define a identidade e o modelo desta conversa.</p></div>
          <button type="button" onClick={close} aria-label="Fechar" className="rounded-lg p-2 text-zinc-400 hover:bg-white/5 hover:text-white"><X size={18} /></button>
        </div>
        <div className="space-y-5 px-6 py-5">
          {!bot && <label className="block text-xs font-medium text-zinc-300">Ponto de partida
            <select aria-label="Ponto de partida" className={`${inputClass} mt-2`} defaultValue="Personalizado" onChange={(event) => {
              const template = TEMPLATES.find((item) => item.name === event.target.value);
              if (template) setForm((current) => ({ ...current, description: template.description, instructions: template.instructions }));
            }}>{TEMPLATES.map((template) => <option key={template.name}>{template.name}</option>)}</select>
          </label>}
          <label className="block text-xs font-medium text-zinc-300">Nome<input className={`${inputClass} mt-2`} required maxLength={80} value={form.name} onChange={(event) => set("name", event.target.value)} placeholder="Ex.: Pixel" autoFocus /></label>
          <label className="block text-xs font-medium text-zinc-300">Descrição<input className={`${inputClass} mt-2`} maxLength={500} value={form.description} onChange={(event) => set("description", event.target.value)} placeholder="Em que é que este bot te ajuda?" /></label>
          <label className="block text-xs font-medium text-zinc-300">Instruções<textarea className={`${inputClass} mt-2 min-h-24 resize-y`} maxLength={4000} value={form.instructions} onChange={(event) => set("instructions", event.target.value)} placeholder="Especialidade, estilo de resposta e objetivo…" /></label>
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-xs font-medium text-zinc-300">Provedor<select className={`${inputClass} mt-2`} value={form.provider} onChange={(event) => {
              const providerId = event.target.value;
              setForm((current) => ({ ...current, provider: providerId, model: "" }));
              setModels([]); setNotice(""); setError("");
              if (providerId) void discover(providerId);
            }}>
              <option value="">Selecionar mais tarde</option>{providers.map((provider) => <option key={provider.id} value={provider.id}>{provider.label}</option>)}
            </select></label>
            <label className="block text-xs font-medium text-zinc-300">Modelo<input list="bot-models" className={`${inputClass} mt-2`} value={form.model} onChange={(event) => set("model", event.target.value)} maxLength={128} placeholder={loadingModels ? "A carregar modelos…" : "Pesquisa ou escreve o ID do modelo"} /><datalist id="bot-models">{models.map((model) => <option key={model} value={model} />)}</datalist></label>
          </div>
          {selectedProvider && <p className="-mt-2 text-[11px] text-zinc-500">{selectedProvider.requires_key ? selectedProvider.api_key_set ? "Chave configurada no backend." : "Sem chave configurada para este provider." : "Provider local ou sem chave obrigatória."} <a href="/settings" className="text-violet-300 hover:text-violet-200">Gerir em Definições</a></p>}
          <button type="button" disabled={!form.provider || loadingModels} onClick={() => void discover(form.provider, true)} className="text-xs font-medium text-violet-300 hover:text-violet-200 disabled:opacity-40">{loadingModels ? "A consultar…" : "Atualizar modelos disponíveis"}</button>
          {notice && <p role="status" className="text-xs leading-5 text-zinc-400">{notice}</p>}
          <p className="rounded-xl border border-white/5 bg-white/[0.03] p-3 text-xs leading-5 text-zinc-400">Os bots podem usar ferramentas de leitura disponíveis. Com um projeto selecionado, podem também inspecionar os seus ficheiros. Escrita, execução e delegação estão desativadas. As credenciais e o endpoint são configurados nas definições do NEXUS.</p>
          {error && <p role="alert" className="text-sm text-red-300">{error}</p>}
        </div>
        <div className="sticky bottom-0 z-10 flex justify-end gap-3 border-t border-white/10 bg-[#101116] px-6 py-4"><button type="button" onClick={close} className="rounded-xl px-4 py-2 text-sm text-zinc-400 hover:text-white">Cancelar</button><button disabled={saving} className="rounded-xl bg-violet-500 px-4 py-2 text-sm font-medium text-white hover:bg-violet-400 disabled:opacity-50">{saving ? "A guardar…" : "Guardar bot"}</button></div>
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
    <div className={`max-w-[92%] min-w-0 rounded-2xl px-4 py-3 text-sm leading-6 sm:max-w-[78%] ${mine ? "rounded-br-md bg-[#393154] text-zinc-100" : "rounded-bl-md border border-white/[0.06] bg-[#1a1c23] text-zinc-200"}`}>
      {tools.length > 0 && <details className="mb-3 rounded-xl border border-white/[0.07] bg-black/10 text-xs text-zinc-400"><summary className="cursor-pointer px-3 py-2 font-medium text-violet-200">Atividade · {tools.length} {tools.length === 1 ? "chamada" : "chamadas"}</summary><ul className="space-y-2 border-t border-white/[0.06] px-3 py-3">{tools.map((tool) => <li key={tool.id} className="flex items-start justify-between gap-3"><span className="break-all text-zinc-300">{tool.name}</span><span className={tool.status === "error" ? "shrink-0 text-red-300" : "shrink-0 text-zinc-400"}>{tool.status === "running" ? "Em curso" : tool.status === "success" ? "Concluída" : tool.status === "error" ? "Falhou" : tool.status === "awaiting_confirmation" ? "A aguardar confirmação" : "Resultado desconhecido"}</span></li>)}</ul></details>}
      {message.content && <>
      <div className="min-w-0 break-words">
        <AssistantMarkdown text={message.content} theme={theme === "light" ? "light" : "dark"} />
      </div>
      <div className="mt-1 flex items-center justify-end gap-2 text-[10px] text-zinc-500"><time>{formatTime(message.timestamp)}</time><button type="button" aria-label="Copiar mensagem" onClick={() => void navigator.clipboard.writeText(message.content).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1200); })} className="rounded p-1 text-zinc-500 hover:text-zinc-200">{copied ? <Check size={12} /> : <Copy size={12} />}</button></div>
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
    <span className="min-w-0"><span className="block font-medium">{botName} · {label}</span><span className="mt-1 block text-violet-200/60">Atividade da conversa em curso</span></span>
    <span aria-hidden="true" className="flex gap-1"><span className="h-1 w-1 animate-pulse rounded-full bg-violet-300 motion-reduce:animate-none" /><span className="h-1 w-1 animate-pulse rounded-full bg-violet-300 motion-reduce:animate-none" /><span className="h-1 w-1 animate-pulse rounded-full bg-violet-300 motion-reduce:animate-none" /></span>
  </div>;
}

export default function BotsWorkspace() {
  const [bots, setBots] = useState<Bot[]>([]);
  const [showGroups, setShowGroups] = useState(false);
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
      const saved = window.localStorage.getItem(selectedKey);
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
  const unconfiguredCount = bots.filter((item) => !item.archived && (!item.provider || !item.model)).length;
  const search = query.trim().toLocaleLowerCase();
  const visible = bots.filter((item) => (filter === "archived" ? item.archived : !item.archived) && `${item.name} ${item.description} ${item.provider} ${item.model} ${item.last_message ?? ""}`.toLocaleLowerCase().includes(search));
  const retryBots = async () => {
    setLoading(true); setError("");
    try { await reload(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível carregar os bots."); }
    finally { setLoading(false); }
  };
  const choose = (item: Bot) => { setSelected(item.id); setMobileChat(true); setDetails(false); setError(""); window.localStorage.setItem(selectedKey, item.id); };
  const submit = async () => {
    const value = (drafts[session] ?? "").trim();
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
    try { await removeBot(bot.id); setBots((items) => items.filter((item) => item.id !== bot.id)); setSelected(""); setMobileChat(false); setDetails(false); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Não foi possível remover o bot."); }
  };

  if (showGroups) return <GroupWorkspace bots={bots} onBack={() => setShowGroups(false)} onOpenBot={(id) => {
    const item = bots.find((bot) => bot.id === id);
    setShowGroups(false);
    if (!item) return;
    choose(item);
    setEditor(item);
  }} />;

  return <div className="relative flex h-full min-h-0 overflow-hidden bg-[#101116] text-zinc-100">
    <section aria-label="Lista de conversas" className={`${mobileChat ? "hidden lg:flex" : "flex"} w-full shrink-0 flex-col border-r border-white/[0.07] bg-[#13141a] lg:w-[300px] xl:w-[320px]`}>
      <div className="px-4 pb-4 pl-14 pt-[max(1.1rem,env(safe-area-inset-top))] lg:pl-5">
        <div className="flex items-center justify-between"><div><p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-violet-300/80">NEXUS</p><h1 className="mt-1 text-2xl font-semibold tracking-tight">Bots</h1><p className="mt-1 text-xs text-zinc-400">O teu espaço de assistentes</p></div><button type="button" onClick={() => setEditor("new")} aria-label="Criar bot" className="flex h-10 w-10 items-center justify-center rounded-xl border border-violet-300/25 bg-violet-500/15 text-violet-200 transition hover:bg-violet-500/25 focus-visible:outline focus-visible:outline-2 focus-visible:outline-violet-300"><Plus size={19} /></button></div>
        <button type="button" disabled={streaming || busyOtherSession} onClick={() => setShowGroups(true)} className="mt-4 flex w-full items-center gap-3 rounded-xl border border-violet-400/20 bg-violet-400/[0.07] px-3 py-3 text-left text-sm text-violet-200 hover:bg-violet-400/10 disabled:opacity-40"><Users size={17} /> Conversas de grupo <ChevronRight size={15} className="ml-auto" /></button>
        <label className="relative mt-5 block"><Search size={16} className="pointer-events-none absolute left-3 top-3 text-zinc-500" /><input aria-label="Pesquisar conversas" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Pesquisar conversas" className={`${inputClass} h-10 pl-9`} /></label>
        <div role="tablist" aria-label="Filtrar conversas" className="mt-4 flex gap-1 border-b border-white/[0.07]">{([["all", "Ativos", activeCount], ["archived", "Arquivados", archivedCount]] as const).map(([id, label, count]) => <button key={id} role="tab" aria-selected={filter === id} onClick={() => setFilter(id)} className={`border-b-2 px-3 pb-2.5 text-xs ${filter === id ? "border-violet-400 text-violet-200" : "border-transparent text-zinc-500 hover:text-zinc-200"}`}><span>{label}</span> <span aria-hidden="true" className="ml-1 rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px]">{count}</span></button>)}</div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-4">
        {error && !bot && <div role="alert" className="mx-2 mb-3 rounded-xl border border-red-400/20 bg-red-400/5 p-3 text-xs leading-5 text-red-200"><p>{error}</p><button type="button" onClick={() => void retryBots()} className="mt-2 font-semibold underline underline-offset-4">Tentar carregar novamente</button></div>}
        {loading ? <div role="status" className="space-y-3 p-3">{[1, 2, 3].map((n) => <div key={n} className="h-14 animate-pulse rounded-xl bg-white/[0.04]" />)}<span className="sr-only">A carregar bots</span></div> : error && !bot ? null : visible.length === 0 ? <div className="px-4 py-10 text-center text-sm leading-6 text-zinc-500">{query ? "Nenhuma conversa encontrada." : filter === "archived" ? "Ainda não tens bots arquivados." : "Ainda não tens bots. Cria o primeiro para começar."}</div> : visible.map((item) => <button key={item.id} type="button" onClick={() => choose(item)} aria-current={selected === item.id ? "true" : undefined} className={`flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left transition-colors ${selected === item.id ? "bg-violet-400/[0.12] ring-1 ring-inset ring-violet-300/20" : "hover:bg-white/[0.04]"}`}><Avatar name={item.name} id={item.id} /><span className="min-w-0 flex-1"><span className="flex items-center justify-between gap-2"><span className="truncate text-sm font-medium">{item.name}</span><time className="shrink-0 text-[10px] text-zinc-500">{item.last_message ? formatTime(item.last_active_at) : ""}</time></span><span className="mt-1 block truncate text-xs text-zinc-500">{item.last_message || item.description || "Começa uma conversa"}</span>{(!item.provider || !item.model) && <span className="mt-1.5 block text-[10px] font-medium text-amber-300">Configuração em falta</span>}</span></button>)}
      </div>
      <div className="border-t border-white/[0.07] px-5 py-4 text-[11px] leading-5 text-zinc-500">Histórico guardado na tua instalação NEXUS.</div>
    </section>

    <section aria-label="Conversa" className={`${mobileChat ? "flex" : "hidden lg:flex"} relative min-w-0 flex-1 flex-col bg-[#101116]`}>
      {bot ? <>
        <header className="flex min-h-[80px] items-center gap-3 border-b border-white/[0.07] bg-[#15161d] px-4 pl-14 pt-[env(safe-area-inset-top)] lg:pl-6"><button type="button" aria-label="Voltar às conversas" onClick={() => setMobileChat(false)} className="inline-flex items-center gap-1 rounded-lg px-1 py-1 text-xs text-zinc-300 hover:text-white lg:hidden"><ArrowLeft size={16} /> Bots</button><Avatar name={bot.name} id={bot.id} thinking={streaming} /><div className="min-w-0 flex-1"><h2 className="truncate text-sm font-semibold">{bot.name}</h2><p className="mt-1 truncate text-xs text-zinc-400">{streaming ? "A responder…" : bot.description || "Função não descrita"}{bot.provider && bot.model ? ` · ${bot.provider} · ${bot.model}` : ""}</p><div className="mt-1"><BotStatusPill tone={streaming ? "live" : bot.provider && bot.model ? "neutral" : "warn"}>{streaming ? "A responder" : bot.provider && bot.model ? "Inferência não verificada" : "Configuração em falta"}</BotStatusPill></div></div><button type="button" onClick={() => setEditor(bot)} className="hidden rounded-lg border border-white/10 px-3 py-2 text-xs text-zinc-300 hover:bg-white/5 sm:block">Editar bot</button><button type="button" aria-label="Informações do bot" aria-pressed={details} onClick={() => setDetails((open) => !open)} className="rounded-xl p-2.5 text-zinc-400 hover:bg-white/5 hover:text-white"><Info size={19} /></button></header>
        <div ref={scrollRegion} aria-label="Mensagens da conversa" onScroll={(event) => { const el = event.currentTarget; followMessages.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80; setAwayFromBottom(!followMessages.current); }} className="min-h-0 flex-1 overflow-y-auto bg-[radial-gradient(ellipse_at_top,rgba(139,92,246,0.06),transparent_55%)] px-4 py-6 sm:px-8"><div className="mx-auto flex max-w-3xl flex-col gap-4">
          {historyPages[session]?.hasMore && <button type="button" onClick={() => void loadOlder()} disabled={olderLoading || streaming} className="self-center rounded-lg px-3 py-2 text-xs text-violet-300 hover:bg-white/5 disabled:opacity-50">{olderLoading ? "A carregar…" : "Carregar mensagens anteriores"}</button>}
          {historyLoading ? <p role="status" className="text-sm text-zinc-400">A carregar conversa…</p> : historyErrors[session] ? <div role="alert" className="rounded-xl border border-red-400/30 bg-red-400/5 p-4 text-sm text-red-200"><p>Não foi possível carregar o histórico: {historyErrors[session]}</p><button type="button" onClick={() => setHistoryAttempt((attempt) => attempt + 1)} className="mt-3 rounded-lg border border-red-300/30 px-3 py-2 font-medium hover:bg-red-300/10">Tentar novamente</button></div> : messages.length === 0 ? <div className="flex min-h-[45vh] flex-col items-center justify-center text-center"><Avatar name={bot.name} id={bot.id} large /><h3 className="mt-5 text-lg font-semibold">Olá, sou {bot.name}</h3><p className="mt-2 max-w-sm text-sm leading-6 text-zinc-500">{bot.description || "Envia uma mensagem para começar."}</p><p className="mt-4 text-xs text-zinc-400">{currentProject ? `Leitura e análise limitadas a ${currentProject.name}.` : "Seleciona um projeto na barra lateral para permitir leitura e análise dos seus ficheiros."} As ferramentas de leitura disponíveis dependem da configuração; escrita e execução estão desligadas.</p>{(!bot.provider || !bot.model) && <button type="button" onClick={() => setEditor(bot)} className="mt-5 rounded-xl border border-amber-300/30 bg-amber-300/10 px-4 py-2.5 text-sm font-medium text-amber-200 hover:bg-amber-300/20">Configurar modelo</button>}</div> : messages.map((message, index) => <Message key={`${message.id}-${index}`} message={message} />)}
          {streaming && <WorkingIndicator botName={bot.name} message={liveAssistant} />}
          {(error || streamError) && <p role="alert" className="rounded-xl border border-red-400/20 bg-red-400/5 p-3 text-sm text-red-300">{error || streamError}</p>}
          {sendNotices[session] && <p role="status" className="rounded-xl border border-amber-400/25 bg-amber-400/5 p-3 text-sm text-amber-200">{sendNotices[session]}</p>}
          <div ref={bottom} />
        </div></div>
        <div className="relative border-t border-white/[0.05] px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))] pt-3 sm:px-7"><div className="mx-auto max-w-3xl">{awayFromBottom && <button type="button" onClick={() => { followMessages.current = true; setAwayFromBottom(false); bottom.current?.scrollIntoView({ block: "end", behavior: "smooth" }); }} className="absolute -top-12 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-full border border-violet-300/20 bg-[#252231] px-4 py-2 text-xs font-medium text-violet-100 shadow-lg hover:bg-[#302b40]"><ArrowDown size={14} /> Ir para o fim</button>}<div className="flex items-end gap-2 rounded-2xl border border-white/10 bg-[#1a1b22] p-2 shadow-[0_12px_32px_rgba(0,0,0,0.18)] transition focus-within:border-violet-400/50 focus-within:ring-2 focus-within:ring-violet-400/10"><textarea aria-label="Mensagem" rows={2} value={drafts[session] ?? ""} onChange={(event) => setDrafts((current) => ({ ...current, [session]: event.target.value }))} onKeyDown={onKey} placeholder={bot.provider && bot.model ? `Mensagem para ${bot.name}` : "Configura o modelo para conversar"} disabled={!bot.provider || !bot.model || busyOtherSession || Boolean(historyErrors[session])} className="max-h-40 min-h-[52px] flex-1 resize-y bg-transparent px-2 py-2.5 text-sm outline-none placeholder:text-zinc-500 disabled:opacity-50" />{streaming ? <button type="button" onClick={cancel} aria-label="Pedir paragem" className="rounded-xl bg-zinc-700 p-3 text-white hover:bg-zinc-600"><Square size={16} fill="currentColor" /></button> : <button type="button" onClick={() => void submit()} disabled={!bot.provider || !bot.model || !(drafts[session] ?? "").trim() || historyLoading || busyOtherSession || !Object.hasOwn(history, session)} aria-label="Enviar mensagem" className="rounded-xl bg-violet-500 p-3 text-white hover:bg-violet-400 disabled:opacity-30"><Send size={16} /></button>}</div><div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 pt-2 text-[11px] text-zinc-500"><span className="flex min-w-0 items-center gap-1.5"><Activity size={12} /> {currentProject ? `Projeto: ${currentProject.name} · ferramentas de leitura` : "Sem projeto selecionado"}</span><span>Enter envia · Shift + Enter muda de linha</span></div><p className="pt-1 text-[11px] text-zinc-500">As respostas podem conter erros.</p></div></div>
      </> : <div className="flex flex-1 items-center justify-center overflow-y-auto px-6 py-10"><div className="w-full max-w-2xl"><div className="rounded-3xl border border-violet-300/15 bg-gradient-to-br from-violet-400/[0.12] via-[#191923] to-[#14151b] p-7 sm:p-10"><span className="inline-flex rounded-2xl border border-violet-300/15 bg-violet-400/10 p-3 text-violet-200"><BotIcon size={25} /></span><p className="mt-6 text-[10px] font-semibold uppercase tracking-[0.2em] text-violet-300">O teu espaço de trabalho</p><h2 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">As tuas conversas, num só lugar</h2><p className="mt-3 max-w-md text-sm leading-6 text-zinc-400">Cria assistentes para tarefas diferentes, retoma uma conversa ou junta perspetivas num grupo.</p><div className="mt-6 flex flex-wrap gap-3"><button type="button" onClick={() => setEditor("new")} className="flex items-center gap-2 rounded-xl bg-violet-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-violet-400"><Plus size={16} /> Criar bot</button><button type="button" disabled={streaming || busyOtherSession} onClick={() => setShowGroups(true)} className="flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-4 py-2.5 text-sm text-zinc-200 hover:bg-white/10 disabled:opacity-40"><Users size={16} /> Abrir grupos</button></div></div><div className="mt-4 grid grid-cols-2 gap-3"><div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4"><p className="text-xs text-zinc-400">Bots ativos</p><p className="mt-2 text-2xl font-semibold">{loading || error ? "—" : activeCount}</p></div><div className="rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4"><p className="text-xs text-zinc-400">Por configurar</p><p className="mt-2 text-2xl font-semibold">{loading || error ? "—" : unconfiguredCount}</p><p className="mt-1 text-xs text-zinc-500">Sem provedor ou modelo</p></div></div></div></div>}
    </section>

    {bot && details && <aside aria-label="Informações do bot" className="absolute inset-y-0 right-0 z-20 flex w-[min(100%,350px)] flex-col border-l border-white/10 bg-[#17181e] shadow-2xl xl:relative xl:shadow-none">
      <div className="flex items-center justify-between border-b border-white/[0.07] px-5 py-5"><div><h2 className="text-sm font-semibold">Informações do bot</h2><p className="mt-1 text-xs text-zinc-500">Perfil e configuração</p></div><button type="button" onClick={() => setDetails(false)} aria-label="Fechar informações" className="rounded-lg p-2 text-zinc-400 hover:bg-white/5 hover:text-white"><X size={18} /></button></div>
      <div className="flex-1 overflow-y-auto p-5">
        <div className="flex flex-col items-center pb-6 text-center"><Avatar name={bot.name} id={bot.id} large /><h3 className="mt-4 text-lg font-semibold">{bot.name}</h3><p className="mt-1 max-w-full break-words text-sm leading-5 text-zinc-400">{bot.description || "Adiciona uma descrição para identificares a função deste bot."}</p><span className={`mt-3 rounded-full border px-2.5 py-1 text-[11px] font-medium ${bot.provider && bot.model ? "border-violet-300/20 bg-violet-400/10 text-violet-200" : "border-amber-300/20 bg-amber-400/10 text-amber-200"}`}>{bot.provider && bot.model ? "Modelo configurado" : "Configuração em falta"}</span></div>
        <div className="space-y-4 rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4"><h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">Configuração</h4><dl className="space-y-3 text-xs"><div><dt className="text-zinc-500">Provedor</dt><dd className="mt-1 break-all text-sm text-zinc-200">{bot.provider || "Não configurado"}</dd></div><div><dt className="text-zinc-500">Modelo</dt><dd className="mt-1 break-all text-sm text-zinc-200">{bot.model || "Não configurado"}</dd></div></dl></div>
        <div className="mt-4 rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4"><h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">Instruções</h4><p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6 text-zinc-300">{bot.instructions || "Sem instruções personalizadas."}</p></div>
        <div className="mt-4 rounded-2xl border border-white/[0.07] bg-white/[0.025] p-4"><h4 className="text-xs font-semibold uppercase tracking-wider text-zinc-400">Acesso</h4><p className="mt-3 text-xs leading-5 text-zinc-400">Ferramentas de leitura disponíveis conforme a configuração. {currentProject ? `Projeto selecionado: ${currentProject.name}.` : "Seleciona um projeto para permitir a leitura dos seus ficheiros."} Escrita, execução e delegação estão desativadas.</p></div>
        <div className="mt-4 space-y-1"><button type="button" onClick={() => setEditor(bot)} className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm text-zinc-300 hover:bg-white/5"><Settings2 size={17} /> Editar configuração <ChevronRight size={15} className="ml-auto" /></button><button type="button" onClick={() => void changeArchive()} className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm text-zinc-300 hover:bg-white/5"><Archive size={17} /> {bot.archived ? "Retirar do arquivo" : "Arquivar conversa"}</button><button type="button" onClick={() => void remove()} className="flex w-full items-center gap-3 rounded-xl px-3 py-3 text-left text-sm text-red-300 hover:bg-white/5"><Trash2 size={17} /> Remover bot</button></div>
      </div>
    </aside>}
    {editor && <BotEditor bot={editor === "new" ? null : editor} close={() => setEditor(null)} saved={(item) => { setBots((items) => [item, ...items.filter((existing) => existing.id !== item.id)]); setEditor(null); choose(item); }} />}
  </div>;
}
