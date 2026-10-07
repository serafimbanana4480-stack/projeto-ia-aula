"use client";
import { useMemo, useState, useEffect, useRef, useCallback, createContext, useContext, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { useAgentStream } from "../../hooks/useAgentStream";
import { useChatSessions } from "../../hooks/useChatSessions";
import { useToast } from "./Toast";
import { ApiError, getSessionHistoryPage, getSessionRuns, createPlan, continuePlan, approvePlan, executePlan, getPlanStatus, cancelPlan, getProvidersStatus, steerChatRun } from "../../lib/api";
import type { PlanCreateResult, PlanStatus as PlanStatusType } from "../../lib/api";
import { useModeStore, type Mode } from "../../stores/modeStore";
import { useModelStore } from "../../stores/modelStore";
import { useProjectStore } from "../../stores/projectStore";
import { useThemeStore } from "../../stores/themeStore";
import { initMetricsStream } from "../../stores/metricsStore";
import { useKeyboardShortcuts } from "../../hooks/useKeyboardShortcuts";
import MessageBubble from "./MessageBubble";
import BackgroundAgentsPanel from "./BackgroundAgentsPanel";
import PlanExecutionPanel from "./PlanExecutionPanel";
import RuntimeReadinessBanner from "../dashboard/RuntimeReadinessBanner";
import ModelSelector from "./ModelSelector";
import VirtualMessageList from "./VirtualMessageList";
import SessionList from "./SessionList";
import AdvancedModeHeaderIndicator from "./AdvancedModeHeaderIndicator";
import { useAdvancedModeStore } from "../../stores/advancedModeStore";
import {
  Sparkles,
  Plus,
  Share2,
  PanelRightClose,
  PanelRightOpen,
  Paperclip,
  Mic,
  StopCircle,
  RotateCcw,
  Check,
  XCircle,
  Loader2,
  ListChecks,
  AlertCircle,
  AlertTriangle,
  WifiOff,
  Code,
  Bug,
  MessageCircle,
  Users,
  Brain,
  Zap,
  BarChart3,
  ChevronDown,
  X,
  Search,
  MessageSquare,
  MoreHorizontal,
  Crosshair,
  AtSign,
  ArrowUp,
  Image as ImageIcon,
  FileText,
  Database,
} from "lucide-react";
import type { ChatMessage, StreamEvent } from "../../lib/types";
import { log } from "../../lib/log";
import { stripAnsiCodes } from "../../lib/utils";
import { foldRun } from "../../lib/foldRun";
import { sanitizeAssistantContent } from "../../lib/chatPresentation";
import { restoreRunTimelines } from "../../lib/sessionRecovery";
import { dedupeAndOrder, type RuntimeEventLike } from "../../lib/eventOrdering";
import { getChatComposerPlaceholder, isChatComposerSendDisabled } from "../../lib/chatComposer";
import { useChatInput } from "../../hooks/useChatInput";
import {
  composeChatMessageWithAttachments,
  getChatAttachmentRejection,
  MAX_CHAT_ATTACHMENTS,
} from "../../lib/chatAttachments";

interface ChatPanelProps {
  rightOpen?: boolean;
  setRightOpen?: (open: boolean) => void;
}

function chunkHistory(messages: ChatMessage[], pageSize = 100): ChatMessage[][] {
  const pages: ChatMessage[][] = [];
  for (let index = 0; index < messages.length; index += pageSize) {
    pages.push(messages.slice(index, index + pageSize));
  }
  return pages;
}

interface MessageSearchResult {
  message: ChatMessage;
}

interface SearchHistoryPage {
  beforeCursor: string;
  pageKey: string;
}

interface SearchNavigationTarget {
  messageId: string;
  messageListId: string;
}

function getPlanErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) {
    if (error.responseText) {
      try {
        const payload = JSON.parse(error.responseText) as {
          detail?: unknown;
          error?: unknown;
        };
        if (typeof payload.detail === "string") return payload.detail;
        if (typeof payload.error === "string") return payload.error;
      } catch {
        // Keep the HTTP status message below when the response isn't JSON.
      }
    }
    if (error.status === 404) {
      return "O plano ou a sessão já não existe. Atualiza a conversa e tenta novamente.";
    }
    if (error.status === 409) {
      return "O estado do plano mudou. Atualiza a conversa antes de tentar outra vez.";
    }
    return error.message || fallback;
  }
  return error instanceof Error && error.message ? error.message : fallback;
}

type ThinkingStrength = "low" | "medium" | "high";

interface ModeConfig {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  color: string;
}

const MODE_CONFIG: Record<string, ModeConfig> = {
  auto: { icon: Sparkles, label: "Auto", color: "text-nexus-accent bg-nexus-accent/10 border-nexus-accent/40" },
  coder: { icon: Code, label: "Coder", color: "text-emerald-400 bg-emerald-400/10 border-emerald-400/40" },
  analyst: { icon: BarChart3, label: "Analyst", color: "text-amber-400 bg-amber-400/10 border-amber-400/40" },
  reviewer: { icon: Check, label: "Review", color: "text-lime-400 bg-lime-400/10 border-lime-400/40" },
  fast: { icon: Zap, label: "Fast", color: "text-yellow-400 bg-yellow-400/10 border-yellow-400/40" },
  deep: { icon: Brain, label: "Deep", color: "text-purple-400 bg-purple-400/10 border-purple-400/40" },
  plan: { icon: ListChecks, label: "Plano", color: "text-sky-400 bg-sky-400/10 border-sky-400/40" },
  debug: { icon: Bug, label: "Debug", color: "text-red-400 bg-red-400/10 border-red-400/40" },
  ask: { icon: MessageCircle, label: "Ask", color: "text-blue-400 bg-blue-400/10 border-blue-400/40" },
  swarm: { icon: Users, label: "Swarm", color: "text-teal-400 bg-teal-400/10 border-teal-400/40" },
  dashboard: { icon: BarChart3, label: "Dashboard", color: "text-orange-400 bg-orange-400/10 border-orange-400/40" },
};

const THINKING_STRENGTH_OPTIONS: { value: ThinkingStrength; label: string; icon: React.ComponentType<{ className?: string }>; description: string }[] = [
  { value: "low", label: "Rápido", icon: Zap, description: "Low thinking" },
  { value: "medium", label: "Médio", icon: Brain, description: "Medium thinking" },
  { value: "high", label: "Alto", icon: Sparkles, description: "High thinking" },
];

/* ── AI workspace conversation-first foundation ─────────────────────────── */

export type ChatDensity = "minimal" | "standard" | "developer";

const DENSITY_OPTIONS: { value: ChatDensity; label: string; hint: string }[] = [
  { value: "minimal", label: "Minimal", hint: "Só resumo (ex. “Trabalhou 2m14s”)" },
  { value: "standard", label: "Standard", hint: "Resumo + chips" },
  { value: "developer", label: "Developer", hint: "Timeline completa + tokens + latência" },
];

function readDensity(): ChatDensity {
  if (typeof window === "undefined") return "standard";
  const stored = window.localStorage.getItem("nexus.density");
  return stored === "minimal" || stored === "developer" ? stored : "standard";
}

export const ChatDensityContext = createContext<ChatDensity>("standard");

export function useChatDensity(): ChatDensity {
  return useContext(ChatDensityContext);
}

export function toggleFocusMode() {
  if (typeof document === "undefined") return false;
  const next = !document.body.classList.contains("nexus-focus");
  document.body.classList.toggle("nexus-focus", next);
  window.dispatchEvent(
    new CustomEvent<{ focus: boolean }>("nexus:focus-toggle", { detail: { focus: next } }),
  );
  return next;
}

interface LivePhase {
  /** Temporal status line shown above the list while streaming. */
  line: string;
  /** Distinct agents seen in this run (for the “●N agentes” centre chip). */
  agents: string[];
}

function deriveLivePhases(streamEvents: StreamEvent[]): LivePhase {
  const agents = new Set<string>();
  let sawUnderstand = false;
  let sawPlan = false;
  let sawExplore = false;
  let lastTool = "";
  let lastAgent = "";
  for (const e of streamEvents) {
    switch (e.type) {
      case "mission_brief":
      case "routing":
        sawUnderstand = true;
        break;
      case "mission_plan":
      case "mission_wave":
        sawPlan = true;
        sawUnderstand = true;
        break;
      case "thinking":
        sawUnderstand = true;
        if (e.agent) {
          agents.add(String(e.agent));
          lastAgent = String(e.agent);
        }
        break;
      case "agent_started":
      case "agent_finished":
      case "mission_agent":
        sawUnderstand = true;
        if (e.agent) {
          agents.add(String(e.agent));
          lastAgent = String(e.agent);
        }
        break;
      case "tool_call":
      case "tool_result":
      case "tool_error":
        sawExplore = true;
        if (e.agent) agents.add(String(e.agent));
        if (e.tool_name) lastTool = String(e.tool_name);
        break;
      case "mission_decision":
      case "mission_verification":
        sawPlan = true;
        break;
      case "progress":
        sawExplore = true;
        break;
      default:
        break;
    }
  }
  const steps: string[] = [];
  steps.push(sawUnderstand ? "A compreender pedido" : "A compreender pedido");
  if (sawPlan || sawExplore || agents.size > 0) steps.push("A criar plano");
  if (sawExplore) steps.push("A explorar");
  if (lastTool) steps.push(`a usar ${lastTool}`);
  else if (lastAgent) steps.push(`${lastAgent} a trabalhar`);
  if (agents.size > 0) steps.push(`${agents.size} agente${agents.size === 1 ? "" : "s"}`);
  return { line: steps.join("  →  "), agents: [...agents] };
}

const MENTION_GROUPS: { group: string; items: { name: string; hint: string }[] }[] = [
  {
    group: "Contexto",
    items: [
      { name: "file", hint: "ficheiro do projeto" },
      { name: "project", hint: "projeto inteiro" },
      { name: "folder", hint: "pasta" },
    ],
  },
  {
    group: "Agentes",
    items: [
      { name: "auto", hint: "encaminhamento automático" },
      { name: "coder", hint: "escreve código" },
      { name: "analyzer", hint: "analisa" },
      { name: "architect", hint: "desenha" },
      { name: "reviewer", hint: "revê" },
      { name: "debugger", hint: "depura" },
      { name: "researcher", hint: "pesquisa" },
      { name: "optimizer", hint: "otimiza" },
    ],
  },
  {
    group: "Sistemas",
    items: [
      { name: "db", hint: "base de dados" },
      { name: "memory", hint: "memória" },
      { name: "terminal", hint: "terminal" },
    ],
  },
];

const SLASH_GROUPS: { group: string; aliases: string[] }[] = [
  { group: "Entender", aliases: ["analyze", "research", "review"] },
  { group: "Agir", aliases: ["plan", "build", "test", "debug"] },
];

const ATTACH_OPTIONS: { id: string; label: string; hint: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { id: "ficheiro", label: "Ficheiro de texto", hint: "até 50 KB · imagens e binários não são enviados", icon: FileText },
  { id: "contexto", label: "Contexto", hint: "cola o projeto via @project", icon: Database },
];

const IMAGE_EXT_RE = /\.(png|jpe?g|webp|gif)$/i;

function formatKB(size: number): string {
  return `${(size / 1024).toFixed(0)} KB`;
}

function formatRecente(iso: string): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const dt = Date.now() - t;
  if (dt < 0) return "agora";
  const s = Math.floor(dt / 1000);
  if (s < 60) return `há ${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `há ${m}min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `há ${h}h`;
  const d = Math.floor(h / 24);
  if (d === 1) return "ontem";
  return `há ${d}d`;
}

/** Cursor-style file pill: ícone por extensão, thumbnail 28px p/ imagens, remover acessível. */
function AttachmentChip({ file, index, onRemove }: { file: File; index: number; onRemove: (i: number) => void }) {
  const isImage = file.type.startsWith("image/") || IMAGE_EXT_RE.test(file.name);
  const isCode = getChatAttachmentRejection(file) === null;
  const [thumb, setThumb] = useState<string | null>(null);
  useEffect(() => {
    if (!isImage) return;
    const url = URL.createObjectURL(file);
    setThumb(url);
    return () => URL.revokeObjectURL(url);
  }, [file, isImage]);
  const KindIcon = isImage ? ImageIcon : isCode ? Code : FileText;
  return (
    <motion.div
      role="listitem"
      initial={{ scale: 0.95, opacity: 0 }}
      animate={{ scale: 1, opacity: 1 }}
      exit={{ scale: 0.95, opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="flex max-w-[220px] items-center gap-1.5 rounded-lg border border-nexus-accent/25 bg-nexus-accent/5 py-1 pl-1.5 pr-1 text-[11px] text-nexus-text shadow-sm"
      title={`${file.name} · ${formatKB(file.size)}`}
    >
      {thumb ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={thumb} alt="" aria-hidden="true" className="h-7 w-7 shrink-0 rounded-md object-cover" />
      ) : (
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-nexus-accent/10 text-nexus-accent/80">
          <KindIcon className="h-3.5 w-3.5" />
        </span>
      )}
      <span className="min-w-0 flex-1 leading-tight">
        <span className="block max-w-[140px] truncate font-medium">{file.name}</span>
        <span className="block text-[10px] text-nexus-muted">{formatKB(file.size)}</span>
      </span>
      <button
        type="button"
        onClick={() => onRemove(index)}
        onKeyDown={(e) => {
          if (e.key === "Delete" || e.key === "Backspace") {
            e.preventDefault();
            onRemove(index);
          }
        }}
        className="shrink-0 rounded-full p-1 text-nexus-muted transition-colors hover:bg-nexus-border/50 hover:text-nexus-text"
        aria-label={`Remover ${file.name}`}
        title="Remover anexo"
      >
        <X className="h-3 w-3" />
      </button>
    </motion.div>
  );
}

/** Compact single-button mode picker: one click opens every available mode. */
export function ModeDropdown() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const { currentMode, modes, modesLoaded, setMode } = useModeStore();

  useEffect(() => {
    if (!open) return;
    const handlePointerDown = (event: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handlePointerDown);
    menuRef.current
      ?.querySelector<HTMLButtonElement>('[role="option"][aria-selected="true"]')
      ?.focus();
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
    };
  }, [open]);

  const handleMenuKeys = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      triggerRef.current?.focus();
      return;
    }

    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    const options = Array.from(
      menuRef.current?.querySelectorAll<HTMLButtonElement>('[role="option"]') ?? [],
    );
    if (options.length === 0) return;
    event.preventDefault();
    const currentIndex = options.indexOf(event.currentTarget as HTMLButtonElement);
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? options.length - 1
        : event.key === "ArrowDown"
          ? Math.min(options.length - 1, currentIndex + 1)
          : Math.max(0, currentIndex < 0 ? 0 : currentIndex - 1);
    options[nextIndex]?.focus();
  };

  const list: Mode[] = modesLoaded
    ? modes
    : ([{ id: currentMode }] as Mode[]);
  const activeCfg = MODE_CONFIG[currentMode] || {
    icon: Sparkles,
    label: currentMode,
    color: "text-nexus-accent bg-nexus-accent/10 border-nexus-accent/40",
  };
  const ActiveIcon = activeCfg.icon;

  return (
    <div ref={containerRef} className="relative">
      <motion.button
        ref={triggerRef}
        type="button"
        whileTap={{ scale: 0.97 }}
        onClick={() => {
          if (open) {
            setOpen(false);
            triggerRef.current?.focus();
          } else {
            setOpen(true);
          }
        }}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Escolher modo. Atual: ${activeCfg.label}`}
        title="Escolher modo"
        className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs font-medium shadow-sm transition-all duration-200 ${
          open
            ? activeCfg.color
            : `${activeCfg.color} border-opacity-60 hover:border-opacity-100`
        }`}
      >
        <ActiveIcon className="h-3.5 w-3.5" />
        <span className="hidden sm:inline">{activeCfg.label}</span>
        <ChevronDown
          className={`h-3 w-3 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
        />
      </motion.button>

      <motion.div
        ref={menuRef}
        initial={false}
        animate={open
          ? { opacity: 1, y: 0, scale: 1 }
          : { opacity: 0, y: -6, scale: 0.98 }}
        transition={{ duration: 0.16, ease: "easeOut" }}
        role={open ? "listbox" : undefined}
        aria-label="Modos disponíveis"
        aria-hidden={!open}
        inert={!open}
        data-testid="mode-dropdown-menu"
        style={{ pointerEvents: open ? "auto" : "none", visibility: open ? "visible" : "hidden" }}
        className="absolute right-0 top-full z-50 mt-1.5 max-h-80 w-64 overflow-y-auto thin-scrollbar rounded-xl border border-nexus-border bg-nexus-panel/95 p-1 shadow-xl backdrop-blur-md"
      >
          <div aria-hidden="true" className="px-2.5 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
              Modo de raciocínio
            </div>
            {list.map((mode) => {
              const cfg = MODE_CONFIG[mode.id] || {
                icon: Sparkles,
                label: mode.id,
                color: "text-nexus-muted bg-transparent border-transparent",
              };
              const Icon = cfg.icon;
              const active = mode.id === currentMode;
              return (
                <button
                  key={mode.id}
                  type="button"
                  role="option"
                  aria-selected={active}
                  onKeyDown={handleMenuKeys}
                  onClick={() => {
                    setMode(mode.id);
                    setOpen(false);
                    triggerRef.current?.focus();
                  }}
                  className={`flex w-full items-start gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors ${
                    active ? "bg-nexus-accent/15" : "hover:bg-nexus-bg/60"
                  }`}
                >
                  <span
                    className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border ${cfg.color}`}
                  >
                    <Icon className="h-3.5 w-3.5" />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className={`block text-xs font-medium ${active ? "text-nexus-accent" : "text-nexus-text"}`}>
                      {cfg.label}
                    </span>
                    {mode.description && (
                      <span className="mt-0.5 block truncate text-[10px] text-nexus-muted" title={mode.description}>
                        {mode.description}
                      </span>
                    )}
                  </span>
                  {active && <Check className="mt-1 h-3.5 w-3.5 shrink-0 text-nexus-accent" />}
                </button>
              );
            })}
      </motion.div>
    </div>
  );
}

export default function ChatPanel({
  rightOpen = true,
  setRightOpen,
}: ChatPanelProps) {
  const [sessionId, setSessionId] = useState<string>("");
  const sessions = useChatSessions();
  const currentChatSessionId = sessions.currentId;
  const sessionsInitialized = sessions.initialized;
  const ensureCurrentChatSession = sessions.ensureCurrentSession;
  const toast = useToast();
  const { currentMode, modes, modesLoaded, loadModes, setMode } = useModeStore();
  const { activeModel, activeProvider, modelsLoaded, loadModels } = useModelStore();
  const { currentProject } = useProjectStore();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  // Model picker selections are concrete catalog ids. The explicit flag
  // distinguishes an id such as "coder" from the router tier with that name;
  // an empty id still means auto-route.

  const {
    events,
    streaming,
    busyOtherSession,
    error: streamError,
    send,
    resume,
    cancel,
    reset,
    getActiveRunId,
    getActiveRunSessionId,
  } = useAgentStream(sessionId);
  const streamResetBySessionRef = useRef(new Map<string, typeof reset>());
  if (sessionId) streamResetBySessionRef.current.set(sessionId, reset);
  const orderedEvents = useMemo(
    () => dedupeAndOrder(events as unknown as RuntimeEventLike[]) as unknown as StreamEvent[],
    [events],
  );
  const [input, setInput] = useState("");
  const { draft: sharedChatDraft, clear: clearSharedChatDraft } = useChatInput();
  const [historyPages, setHistoryPages] = useState<ChatMessage[][]>([]);
  const [historySnapshotRevision, setHistorySnapshotRevision] = useState(0);
  const [historySessionId, setHistorySessionId] = useState("");
  const historySessionIdRef = useRef("");
  const historyRequestedSessionIdRef = useRef("");
  const historyLoadGenerationRef = useRef(0);
  const selectedSessionIdRef = useRef(currentChatSessionId);
  selectedSessionIdRef.current = currentChatSessionId;
  const [olderHistoryCursor, setOlderHistoryCursor] = useState<string | null>(null);
  const seenHistoryCursorsRef = useRef<Set<string>>(new Set());
  const [hasOlderHistory, setHasOlderHistory] = useState(false);
  const [loadingOlderHistory, setLoadingOlderHistory] = useState(false);
  const historyScrollAnchorRef = useRef<{ height: number; top: number } | null>(null);
  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const [pendingUsersBySession, setPendingUsersBySession] = useState<Record<string, ChatMessage[]>>({});
  const pendingMessageSequenceRef = useRef(0);
  const pendingUser = useMemo(
    () => pendingUsersBySession[sessionId] ?? [],
    [pendingUsersBySession, sessionId],
  );
  const setPendingUser = useCallback(
    (update: ChatMessage[] | ((current: ChatMessage[]) => ChatMessage[])) => {
      setPendingUsersBySession((current) => {
        const previous = current[sessionId] ?? [];
        const next = typeof update === "function" ? update(previous) : update;
        return { ...current, [sessionId]: next };
      });
    },
    [sessionId],
  );
  const streamingRef = useRef(streaming);
  streamingRef.current = streaming;
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [olderHistoryError, setOlderHistoryError] = useState<string | null>(null);
  const [shared, setShared] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  // Drag & drop state
  const [isDraggingOver, setIsDraggingOver] = useState(false);
  // Voice input state
  const [isListening, setIsListening] = useState(false);
  const recognitionRef = useRef<any>(null);
  // @mentions state
  const [showMentions, setShowMentions] = useState(false);
  const [mentionQuery, setMentionQuery] = useState("");
  const [mentionStart, setMentionStart] = useState(-1);
  const [showCommands, setShowCommands] = useState(false);
  const [commandQuery, setCommandQuery] = useState("");
  const [commandStart, setCommandStart] = useState(-1);
  const [selectedCommandIndex, setSelectedCommandIndex] = useState(0);
  // Search state
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<MessageSearchResult[]>([]);
  const [activeSearchResultId, setActiveSearchResultId] = useState<string | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [searchScannedPages, setSearchScannedPages] = useState(0);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searchNavigationError, setSearchNavigationError] = useState<string | null>(null);
  const [searchNavigation, setSearchNavigation] = useState<SearchNavigationTarget | null>(null);
  const [searchHighlightMessageId, setSearchHighlightMessageId] = useState<string | null>(null);
  const searchHighlightTimerRef = useRef<number | null>(null);
  const searchGenerationRef = useRef(0);
  const searchPagesByMessageIdRef = useRef<Map<string, SearchHistoryPage>>(new Map());
  // Open/close state now lives inside <ModelSelector />.
  // Sessions are useful on demand, but should not compete with the chat for
  // horizontal space while the user is reading or writing.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [thinkingStrength, setThinkingStrength] = useState<ThinkingStrength>(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("nexus.thinkingStrength");
      if (stored === "low" || stored === "medium" || stored === "high") return stored;
    }
    return "low";
  });
  // Conversation-first workspace state (visual only — no send/history logic here).
  const [density, setDensity] = useState<ChatDensity>(() => readDensity());
  const [focusMode, setFocusMode] = useState(false);
  const [headerMenuOpen, setHeaderMenuOpen] = useState(false);
  const [attachOpen, setAttachOpen] = useState(false);
  const headerMenuRef = useRef<HTMLDivElement>(null);
  const attachMenuRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const historyPagesForSession = useMemo(
    () =>
      historySessionId === sessionId && sessionId === currentChatSessionId
        ? historyPages
        : [],
    [historyPages, historySessionId, sessionId, currentChatSessionId],
  );
  const historyMessages = useMemo(() => historyPagesForSession.flat(), [historyPagesForSession]);
  const historyLoadedForSession =
    historyLoaded && historySessionId === sessionId && sessionId === currentChatSessionId;
  const [activePlan, setActivePlan] = useState<PlanCreateResult | null>(null);
  const [planStatus, setPlanStatus] = useState<PlanStatusType | null>(null);
  const [planExecuting, setPlanExecuting] = useState(false);
  const [planCreating, setPlanCreating] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [activePlanSessionId, setActivePlanSessionId] = useState<string | null>(null);
  const [backendOffline, setBackendOffline] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const errorLoggedRef = useRef(false);
  const planPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const planPollGenerationRef = useRef(0);
  const planActionGenerationRef = useRef(0);
  const lastUserMessageRef = useRef<string>("");
  // Do not let the startup recovery poll resume the run that this tab has
  // just submitted. The initial poll can overlap the POST /chat request and
  // abort the legitimate stream as if it were a stale run.
  const submittedTurnRef = useRef(false);
  // Sessions we already tried to auto-title from their first message.
  const autoTitledSessionsRef = useRef<Set<string>>(new Set());

  // Auto-title a generic ("Chat <date>" / "Nova sessão") session from its
  // first real message — the pattern every modern chat UI uses. Fire-and-
  // forget: titling must never delay or fail the send itself.
  function autoTitleSession(firstMessage: string) {
    const record = sessions.sessions.find((s) => s.id === sessionId);
    if (!record) return;
    if (autoTitledSessionsRef.current.has(sessionId)) return;
    const isGenericTitle =
      record.title === "Nova sessão" ||
      /^Chat\s\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}/.test(record.title);
    if (!isGenericTitle) {
      autoTitledSessionsRef.current.add(sessionId);
      return;
    }
    autoTitledSessionsRef.current.add(sessionId);
    const compact = firstMessage.replace(/\s+/g, " ").trim();
    const title = compact.length > 60 ? `${compact.slice(0, 60)}…` : compact;
    void sessions.rename(sessionId, title);
  }

  // Consume mode and draft together so one URL replacement cannot discard
  // the other. Selecting a skill or a plan never sends a message automatically.
  const handoffRef = useRef<string | null>(null);
  useEffect(() => {
    const prompt = searchParams.get("prompt")?.trim();
    const requestedMode = searchParams.get("mode")?.trim();
    if (!prompt && !requestedMode) { handoffRef.current = null; return; }
    if (requestedMode && !modesLoaded) return;
    const handoff = JSON.stringify([prompt, requestedMode]);
    if (handoffRef.current === handoff) return;
    handoffRef.current = handoff;
    if (requestedMode && modes.some((mode) => mode.id === requestedMode)) setMode(requestedMode);
    if (prompt) setInput((current) => current || prompt);
    const remainingParams = new URLSearchParams(searchParams.toString());
    remainingParams.delete("prompt");
    remainingParams.delete("mode");
    const query = remainingParams.toString();
    router.replace((query ? `${pathname}?${query}` : pathname) as Route, { scroll: false });
  }, [pathname, router, searchParams, modes, modesLoaded, setMode]);

  // Results handed off from SWARM survive route changes in the shared draft.
  // Load them only into an empty composer so existing typing stays intact.
  useEffect(() => {
    if (!sharedChatDraft.trim()) return;
    setInput((current) => current || sharedChatDraft);
    clearSharedChatDraft();
  }, [clearSharedChatDraft, sharedChatDraft]);

  useEffect(() => {
    const handleChatDraft = (event: Event) => {
      const value = (event as CustomEvent<string>).detail;
      if (typeof value !== "string" || !value.trim()) return;
      setInput(value);
      requestAnimationFrame(() => inputRef.current?.focus());
      clearSharedChatDraft();
    };
    window.addEventListener("nexus:chat-input", handleChatDraft);
    return () => window.removeEventListener("nexus:chat-input", handleChatDraft);
  }, [clearSharedChatDraft]);

  // Resolve a real or explicitly-created offline session after the session
  // list has loaded. This keeps history and the stream off the "default"
  // sentinel, which is not a backend session id.
  useEffect(() => {
    if (!sessionsInitialized || currentChatSessionId) return;
    void ensureCurrentChatSession();
  }, [currentChatSessionId, ensureCurrentChatSession, sessionsInitialized]);

  // Sync the session list's currentId with local sessionId state
  useEffect(() => {
    const nextSessionId = currentChatSessionId ?? "";
    if (nextSessionId !== sessionId) {
      submittedTurnRef.current = false;
      setSessionId(nextSessionId);
    }
  }, [currentChatSessionId, sessionId]);

  // Each reset callback is bound to the session captured by useAgentStream.
  // Keep that callback while another session is streaming, then release the
  // old session's event/token buffers once it is safe to do so.
  useEffect(() => {
    if (busyOtherSession) return;
    for (const [ownerSessionId, clearSessionEvents] of streamResetBySessionRef.current) {
      if (ownerSessionId === sessionId) continue;
      clearSessionEvents();
      streamResetBySessionRef.current.delete(ownerSessionId);
    }
  }, [busyOtherSession, reset, sessionId]);

  // The Infinity panel lives outside ChatPanel. Let its "Usar /comando"
  // action place a real command in this input, so every mode is reachable
  // without relying on remembering aliases or copying text manually.
  useEffect(() => {
    const handleInsertCommand = (event: Event) => {
      const customEvent = event as CustomEvent<{ command?: string }>;
      const command = customEvent.detail?.command?.trim();
      if (!command) return;
      setInput(`${command} `);
      requestAnimationFrame(() => inputRef.current?.focus());
    };
    window.addEventListener("nexus:insert-command", handleInsertCommand);
    return () => window.removeEventListener("nexus:insert-command", handleInsertCommand);
  }, []);

  // Push stream / history errors to the global toast so they don't disappear
  useEffect(() => {
    if (streamError) {
      toast.error("Falha no chat", streamError, undefined);
    }
  }, [streamError, toast]);
  useEffect(() => {
    if (historyError) {
      toast.error("Não foi possível carregar o histórico", historyError, undefined);
    }
  }, [historyError, toast]);

  // Proactively detect demo mode: no LLM provider/API key configured.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = (await getProvidersStatus()) as {
          providers?: unknown[];
          active_provider?: string;
          llm_available?: boolean;
          demo_mode?: boolean;
        };
        if (cancelled) return;
        if (data.demo_mode === true || data.llm_available === false) {
          setDemoMode(true);
        }
      } catch {
        // Ignore — don't crash if the status endpoint is unavailable.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // Reactively detect the demo stub: backend streams text beginning with "MODO DEMO".
  useEffect(() => {
    if (
      orderedEvents.some(
        (e) =>
          e.type === "token" &&
          typeof e.content === "string" &&
          e.content.includes("MODO DEMO"),
      )
    ) {
      setDemoMode(true);
    }
  }, [orderedEvents]);


  useEffect(() => {
    localStorage.setItem("nexus.thinkingStrength", thinkingStrength);
  }, [thinkingStrength]);

  useEffect(() => {
    try {
      localStorage.setItem("nexus.density", density);
    } catch {
      // localStorage indisponível (SSR/privado) — densidade fica só em memória.
    }
  }, [density]);

  // Focus Mode: Ctrl+Shift+F alterna `nexus-focus` no <body> e avisa o resto
  // da shell via CustomEvent `nexus:focus-toggle` (sidebars escondem-se).
  useEffect(() => {
    const syncFromBody = () => {
      setFocusMode(document.body.classList.contains("nexus-focus"));
    };
    const onToggle = (event: Event) => {
      const detail = (event as CustomEvent<{ focus?: boolean }>).detail;
      if (typeof detail?.focus === "boolean") setFocusMode(detail.focus);
      else syncFromBody();
    };
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.shiftKey && (event.key === "F" || event.key === "f")) {
        event.preventDefault();
        toggleFocusMode();
        syncFromBody();
      }
    };
    syncFromBody();
    window.addEventListener("nexus:focus-toggle", onToggle);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("nexus:focus-toggle", onToggle);
      window.removeEventListener("keydown", onKey);
    };
  }, []);

  // Fecha os menus flutuantes (••• / +) ao clicar fora ou com Escape.
  useEffect(() => {
    if (!headerMenuOpen && !attachOpen) return;
    const onPointerDown = (event: MouseEvent) => {
      const t = event.target as Node;
      if (headerMenuRef.current && !headerMenuRef.current.contains(t)) setHeaderMenuOpen(false);
      if (attachMenuRef.current && !attachMenuRef.current.contains(t)) setAttachOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setHeaderMenuOpen(false);
        setAttachOpen(false);
      }
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [headerMenuOpen, attachOpen]);

  // Textarea auto-resize (primeira linha do composer cresce sem layout-shift).
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  const loadHistory = useCallback(async () => {
    const requestedSessionId = sessionId;
    const generation = ++historyLoadGenerationRef.current;
    if (historyRequestedSessionIdRef.current !== requestedSessionId) {
      historyRequestedSessionIdRef.current = requestedSessionId;
      setHistoryPages([]);
      seenHistoryCursorsRef.current.clear();
      setOlderHistoryCursor(null);
      setHasOlderHistory(false);
      setLoadingOlderHistory(false);
      setOlderHistoryError(null);
      historyScrollAnchorRef.current = null;
    }
    if (!sessionId || sessionId === "default") {
      setHistoryPages([]);
      setHistoryLoaded(false);
      setHistorySessionId("");
      historySessionIdRef.current = "";
      seenHistoryCursorsRef.current.clear();
      setOlderHistoryCursor(null);
      setHasOlderHistory(false);
      setHistoryError(null);
      setOlderHistoryError(null);
      setBackendOffline(false);
      return;
    }
    try {
      setHistoryLoaded(false);
      setHistoryError(null);
      setOlderHistoryError(null);
      const page = await getSessionHistoryPage(sessionId, 100);
      if (
        generation !== historyLoadGenerationRef.current ||
        selectedSessionIdRef.current !== requestedSessionId
      ) return;
      const normalized = page.messages.map((msg, index) => ({
        ...msg,
        id: msg.id || `${msg.role}-${index}-${msg.timestamp}`,
        content:
          msg.role === "assistant"
            ? sanitizeAssistantContent(stripAnsiCodes(msg.content))
            : stripAnsiCodes(msg.content),
      }));
      const firstPage = normalized;
      setHistoryPages(firstPage.length ? [firstPage] : []);
      const firstCursor = page.has_more ? page.next_cursor : null;
      seenHistoryCursorsRef.current = new Set(firstCursor ? [firstCursor] : []);
      setOlderHistoryCursor(firstCursor);
      setHasOlderHistory(Boolean(firstCursor));
      setOlderHistoryError(
        page.has_more && !firstCursor
          ? "A paginação do histórico não recebeu um cursor válido. Reabre a conversa para tentar novamente."
          : null,
      );
      setHistorySnapshotRevision((revision) => revision + 1);
      setHistorySessionId(sessionId);
      historySessionIdRef.current = sessionId;
      if (!streamingRef.current) setPendingUser([]);
      reset();
      setHistoryLoaded(true);
      setBackendOffline(false);
      // authenticatedFetch may have refreshed the token while loading the
      // history. This successful boundary is the reliable point to start
      // dashboard metrics after a cold production reload.
      initMetricsStream();
      errorLoggedRef.current = false;

      // The persisted message text is the critical path. Rebuilding optional
      // run timelines can require several journal requests, so enrich this
      // page after it is already visible instead of holding the conversation
      // behind that recovery work.
      void restoreRunTimelines(firstPage, requestedSessionId)
        .then((restored) => {
          if (
            restored === firstPage ||
            generation !== historyLoadGenerationRef.current ||
            selectedSessionIdRef.current !== requestedSessionId
          ) return;
          setHistoryPages((pages) =>
            pages.map((pageMessages) => pageMessages === firstPage ? restored : pageMessages),
          );
        })
        .catch((reason) => {
          log.warn("Optional run timeline recovery failed", reason);
        });
    } catch (error) {
      if (
        generation !== historyLoadGenerationRef.current ||
        selectedSessionIdRef.current !== requestedSessionId
      ) return;
      const isNetworkFailure =
        error instanceof ApiError && error.status === 0;
      setBackendOffline(isNetworkFailure);
      if (!isNetworkFailure && !errorLoggedRef.current) {
        log.warn("Chat history unavailable", error);
        errorLoggedRef.current = true;
        setHistoryError(
          error instanceof Error ? error.message : "Failed to load chat history",
        );
      }
      setHistorySessionId(requestedSessionId);
      historySessionIdRef.current = requestedSessionId;
      setHistoryLoaded(true);
    }
  }, [sessionId, reset, setPendingUser]);

  const loadOlderHistory = useCallback(async () => {
    const cursor = olderHistoryCursor;
    const requestedSessionId = sessionId;
    const generation = historyLoadGenerationRef.current;
    if (!cursor || !hasOlderHistory || loadingOlderHistory || !requestedSessionId) return;
    setLoadingOlderHistory(true);
    setOlderHistoryError(null);
    try {
      const page = await getSessionHistoryPage(requestedSessionId, 100, cursor);
      if (
        generation !== historyLoadGenerationRef.current ||
        selectedSessionIdRef.current !== requestedSessionId ||
        historySessionIdRef.current !== requestedSessionId
      ) return;
      const normalized = page.messages.map((msg, index) => ({
        ...msg,
        id: msg.id || `${msg.role}-older-${index}-${msg.timestamp}`,
        content:
          msg.role === "assistant"
            ? sanitizeAssistantContent(stripAnsiCodes(msg.content))
            : stripAnsiCodes(msg.content),
      }));
      const loadedMessageIds = new Set(
        historyPagesForSessionRef.current.flatMap((loadedPage) => loadedPage.map((message) => message.id)),
      );
      const olderPage = normalized.filter((message) => !loadedMessageIds.has(message.id));
      const nextCursor = page.has_more ? page.next_cursor : null;
      const cursorCycles = Boolean(nextCursor && seenHistoryCursorsRef.current.has(nextCursor));
      const canContinue = Boolean(nextCursor && !cursorCycles);
      if (canContinue && nextCursor) seenHistoryCursorsRef.current.add(nextCursor);
      setOlderHistoryCursor(canContinue ? nextCursor : null);
      setHasOlderHistory(canContinue);
      if (page.has_more && !canContinue) {
        setOlderHistoryError(
          "A paginação do histórico deixou de avançar; parei para evitar repetir mensagens. Reabre a conversa para tentar novamente.",
        );
      }
      if (olderPage.length > 0) {
        const container = messagesContainerRef.current;
        if (container) {
          historyScrollAnchorRef.current = {
            height: container.scrollHeight,
            top: container.scrollTop,
          };
        }
        setHistoryPages((pages) => (olderPage.length ? [olderPage, ...pages] : pages));
      }
      if (olderPage.length > 0) void restoreRunTimelines(olderPage, requestedSessionId)
        .then((restored) => {
          if (
            restored === olderPage ||
            generation !== historyLoadGenerationRef.current ||
            selectedSessionIdRef.current !== requestedSessionId ||
            historySessionIdRef.current !== requestedSessionId
          ) return;
          const currentContainer = messagesContainerRef.current;
          if (currentContainer) {
            historyScrollAnchorRef.current = {
              height: currentContainer.scrollHeight,
              top: currentContainer.scrollTop,
            };
          }
          setHistoryPages((pages) =>
            pages.map((pageMessages) => pageMessages === olderPage ? restored : pageMessages),
          );
        })
        .catch((reason) => {
          log.warn("Optional older run timeline recovery failed", reason);
        });
    } catch (reason) {
      if (
        generation === historyLoadGenerationRef.current &&
        selectedSessionIdRef.current === requestedSessionId
      ) {
        setOlderHistoryError(
          reason instanceof Error ? reason.message : "Não foi possível carregar mensagens anteriores.",
        );
      }
    } finally {
      if (
        generation === historyLoadGenerationRef.current &&
        selectedSessionIdRef.current === requestedSessionId
      ) {
        setLoadingOlderHistory(false);
      }
    }
  }, [hasOlderHistory, loadingOlderHistory, olderHistoryCursor, sessionId]);

  const advancedLoadCommands = useAdvancedModeStore((s) => s.loadCommands);
  const advancedLoadModes = useAdvancedModeStore((s) => s.loadModes);
  const commandsLoading = useAdvancedModeStore((s) => s.commandsLoading);
  const commandsError = useAdvancedModeStore((s) => s.commandsError);
  const advancedModes = useAdvancedModeStore((s) => s.modes);

  useEffect(() => {
    loadHistory();
    if (!modesLoaded) {
      void loadModes();
    }
    if (!modelsLoaded) {
      void loadModels();
    }
    void advancedLoadCommands();
    void advancedLoadModes();
  }, [
    advancedLoadCommands,
    advancedLoadModes,
    loadHistory,
    loadModes,
    modesLoaded,
    loadModels,
    modelsLoaded,
  ]);

  // A refresh must reconnect to an existing mission instead of creating a
  // second run or leaving the user with a stale history-only view.
  useEffect(() => {
    if (!sessionId) return;
    if (!historyLoadedForSession || streaming || busyOtherSession) return;
    if (submittedTurnRef.current) return;
    let cancelled = false;
    void getSessionRuns(sessionId)
      .then((runs) => {
        if (cancelled) return;
        const active = runs.find((run) =>
          ["running", "queued", "planning", "waiting_agent", "waiting_tool"].includes(run.status),
        );
        if (active) void resume(active.id);
      })
      .catch(() => {
        // History remains usable when the optional recovery endpoint is down.
      });
    return () => {
      cancelled = true;
    };
  }, [busyOtherSession, historyLoadedForSession, sessionId, resume, streaming]);

  const { toggleTheme } = useThemeStore();

  async function composeMessageWithAttachments(
    message: string,
    files: File[],
  ): Promise<string> {
    return composeChatMessageWithAttachments(message, files, stripAnsiCodes);
  }

  const doSendMessage = async (overrideText?: string, archivePreviousTurn = true) => {
    const trimmed = (overrideText ?? input).trim();
    if (!trimmed && attachedFiles.length === 0) return;
    if (!sessionId || sessionId === "default") {
      toast.info("A preparar conversa", "Espera um instante enquanto o NEXUS abre uma sessão.");
      return;
    }
    if (busyOtherSession) {
      toast.warning(
        "Outra conversa ainda está a gerar",
        "Espera que termine ou volta a essa conversa para acompanhar a execução.",
      );
      return;
    }
    if (planCreating) {
      toast.info("A preparar o plano", "Espera que o plano atual termine antes de enviar outro.");
      return;
    }
    if (streaming) {
      const runId = getActiveRunId();
      if (!runId) {
        const activeSessionId = getActiveRunSessionId();
        if (activeSessionId && activeSessionId !== sessionId) {
          toast.warning(
            "O run pertence a outra conversa",
            "Volta à conversa que iniciou esta execução para a orientar.",
          );
          return;
        }
        toast.warning(
          "Ainda não consigo orientar esta execução",
          "Espera pelo início do run e tenta enviar outra vez.",
        );
        return;
      }
      try {
        const result = await steerChatRun(runId, trimmed);
        if (!result.ok) {
          toast.warning("A orientação não foi aceite", result.reason);
          return;
        }
        setInput("");
        toast.info("Orientação enviada", "O NEXUS aplica-a no próximo ponto de decisão.");
      } catch (err) {
        toast.error(
          "Falha ao orientar o NEXUS",
          err instanceof Error ? err.message : String(err),
        );
      }
      return;
    }
    archiveCurrentTurn(archivePreviousTurn);
    autoTitleSession(trimmed || attachedFiles.map((file) => file.name).join(", "));
    const hasAttachments = attachedFiles.length > 0;
    const displayContent = hasAttachments
      ? `${trimmed}\n\n[${attachedFiles.length} ficheiro(s) anexado(s): ${attachedFiles.map(f => f.name).join(", ")}]`
      : trimmed;
    lastUserMessageRef.current = trimmed;
    submittedTurnRef.current = true;
    const pendingUserMessage: ChatMessage = {
      id: `u-${sessionId}-${Date.now()}-${pendingMessageSequenceRef.current++}`,
      role: "user",
      content: displayContent,
      timestamp: new Date().toISOString(),
    };
    const previousInput = input;
    const previousFiles = attachedFiles;
    setPendingUser((prev) => [...prev, pendingUserMessage]);
    setInput("");
    try {
      const messageToSend = stripAnsiCodes(
        hasAttachments
          ? await composeMessageWithAttachments(trimmed, attachedFiles)
          : trimmed,
      );
      setAttachedFiles([]);
      if (currentMode === "plan") {
        reset();
        const created = await handlePlanCreate(messageToSend);
        if (!created) {
          setPendingUser((prev) => prev.filter((m) => m.id !== pendingUserMessage.id));
          setInput(previousInput);
          setAttachedFiles(previousFiles);
        }
        return;
      }
      const projectPath = currentProject?.path || ".";
      const accepted = await send(
        messageToSend,
        currentMode,
        activeModel,
        projectPath,
        thinkingStrength,
        undefined,
        activeProvider,
        Boolean(activeModel),
      );
      if (!accepted) {
        setPendingUser((prev) => prev.filter((m) => m.id !== pendingUserMessage.id));
        setInput(previousInput);
        setAttachedFiles(previousFiles);
      }
    } catch (err) {
      setPendingUser((prev) => prev.filter((m) => m.id !== pendingUserMessage.id));
      setInput(previousInput);
      setAttachedFiles(previousFiles);
      toast.error("Falha ao enviar", err instanceof Error ? err.message : String(err));
      return;
    }
    // The SSE fold is the source of truth for the just-finished turn. Reloading
    // history here used to erase a terminal provider error before it could be
    // rendered when the backend had only persisted the run checkpoint. Full
    // history is still loaded on mount/session changes and remains available
    // after a refresh.
  };

  // -----------------------------------------------------------------------
  // Drag & Drop handlers
  // -----------------------------------------------------------------------
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (!isDraggingOver) setIsDraggingOver(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    // Only hide overlay if leaving the panel itself (not entering a child)
    if (e.currentTarget === e.target) {
      setIsDraggingOver(false);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDraggingOver(false);
    const files = Array.from(e.dataTransfer.files);
    if (!files.length) return;
    addChatFiles(files);
  };

  function addChatFiles(files: File[]) {
    const accepted: File[] = [];
    const rejected = new Set<string>();
    for (const file of files) {
      if (attachedFiles.length + accepted.length >= MAX_CHAT_ATTACHMENTS) {
        rejected.add("too_many");
        break;
      }
      const reason = getChatAttachmentRejection(file);
      if (reason) {
        rejected.add(reason);
        continue;
      }
      accepted.push(file);
    }
    if (accepted.length) setAttachedFiles((previous) => [...previous, ...accepted]);
    if (rejected.size) {
      const reasons = [
        rejected.has("sensitive") ? "Ficheiros com nomes de credenciais foram bloqueados." : "",
        rejected.has("too_large") ? "Cada ficheiro pode ter no máximo 50 KB." : "",
        rejected.has("unsupported") ? "Só ficheiros de texto são enviados; imagens e binários ainda não são suportados." : "",
        rejected.has("too_many") ? `O limite é ${MAX_CHAT_ATTACHMENTS} ficheiros por mensagem.` : "",
      ].filter(Boolean);
      toast.warning("Alguns ficheiros não foram anexados", reasons.join(" "));
    }
  }

  // -----------------------------------------------------------------------
  // Voice input handler
  // -----------------------------------------------------------------------
  const startListening = () => {
    const SpeechRecognition: any =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognition) {
      toast.error("Reconhecimento de voz não suportado neste browser");
      return;
    }
    if (isListening) {
      recognitionRef.current?.stop();
      setIsListening(false);
      return;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = "pt-PT";
    recognition.continuous = false;
    recognition.interimResults = false;
    recognition.onresult = (event: any) => {
      const transcript = event.results[0]?.[0]?.transcript ?? "";
      if (transcript) {
        setInput((prev) => (prev ? prev + " " + transcript : transcript));
      }
    };
    recognition.onend = () => setIsListening(false);
    recognition.onerror = () => setIsListening(false);
    recognitionRef.current = recognition;
    recognition.start();
    setIsListening(true);
  };

  // -----------------------------------------------------------------------
  // @mentions detection in input
  // -----------------------------------------------------------------------
  const handleInputChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const value = e.target.value;
    setInput(value);
    // Detect @-mention
    const cursorPos = e.target.selectionStart ?? value.length;
    const before = value.slice(0, cursorPos);
    const match = before.match(/(?:^|\s)@([a-zA-Z_]*)$/);
    if (match) {
      setMentionQuery(match[1]);
      setMentionStart(cursorPos - match[1].length - 1);
      setShowMentions(true);
      setShowCommands(false);
    } else {
      setShowMentions(false);
      setMentionQuery("");
      setMentionStart(-1);
    }
    // Detect /command
    // The backend only resolves a slash command when it is the first token.
    // Keeping the trigger aligned avoids offering commands in URLs or prose
    // where they would be sent as ordinary text.
    const cmdMatch = before.match(/^\s*\/([a-zA-Z0-9-]*)$/);
    if (cmdMatch) {
      setCommandQuery(cmdMatch[1]);
      setCommandStart(before.lastIndexOf("/"));
      setShowCommands(true);
      setShowMentions(false);
      setSelectedCommandIndex(0);
    } else {
      setShowCommands(false);
      setCommandQuery("");
      setCommandStart(-1);
    }
  };

  const insertMention = (agentName: string) => {
    if (mentionStart < 0) return;
    const before = input.slice(0, mentionStart);
    const after = input.slice(mentionStart + 1 + mentionQuery.length);
    const newInput = `${before}@${agentName} ${after}`;
    setInput(newInput);
    setShowMentions(false);
    setMentionQuery("");
    setMentionStart(-1);
  };

  const insertCommand = (cmdAlias: string) => {
    if (commandStart < 0) return;
    const before = input.slice(0, commandStart);
    const after = input.slice(commandStart + 1 + commandQuery.length);
    const newInput = `${before}/${cmdAlias} ${after}`;
    setInput(newInput);
    setShowCommands(false);
    setCommandQuery("");
    setCommandStart(-1);
    setSelectedCommandIndex(0);
    requestAnimationFrame(() => {
      const cursor = before.length + cmdAlias.length + 2;
      inputRef.current?.focus();
      inputRef.current?.setSelectionRange(cursor, cursor);
    });
  };

  // Filter agents based on mention query (grouped: file/project/agent/db/memory/terminal)
  const filteredAgents = useMemo(() => {
    if (!showMentions) return [];
    const q = mentionQuery.toLowerCase();
    return MENTION_GROUPS.map((group) => ({
      ...group,
      items: group.items.filter((item) => item.name.startsWith(q)),
    })).filter((group) => group.items.length > 0);
  }, [showMentions, mentionQuery]);

  // Filter commands based on /command query
  const advancedCommands = useAdvancedModeStore((s) => s.commands);
  const filteredCommands = useMemo(() => {
    if (!showCommands) return [];
    const q = commandQuery.toLowerCase();
    return Object.entries(advancedCommands)
      .map(([modeId, info], order) => {
        const aliases = info.aliases.map((alias) =>
          alias.replace(/^\//, "").toLowerCase()
        );
        let rank = 4;
        if (!q) rank = 0;
        else if (aliases.some((alias) => alias === q)) rank = 0;
        else if (aliases.some((alias) => alias.startsWith(q))) rank = 1;
        else if (modeId.toLowerCase().startsWith(q)) rank = 2;
        else if (
          modeId.toLowerCase().includes(q) ||
          info.description.toLowerCase().includes(q)
        ) rank = 3;
        return { modeId, info, order, rank };
      })
      .filter((command) => command.rank < 4)
      .sort((left, right) => left.rank - right.rank || left.order - right.order)
      .map(({ modeId, info }) => [modeId, info] as const);
  }, [showCommands, commandQuery, advancedCommands]);

  // Grouped view for the glass /command menu (analyze/debug/plan/research/test/review/build).
  const groupedCommands = useMemo(() => {
    const byAlias = new Map<string, (typeof filteredCommands)[number]>();
    for (const entry of filteredCommands) {
      const [modeId, info] = entry;
      for (const a of info.aliases) byAlias.set(a.replace(/^\//, "").toLowerCase(), entry);
      byAlias.set(modeId.toLowerCase(), entry);
    }
    const seen = new Set<string>();
    const groups = SLASH_GROUPS.map((g) => ({
      ...g,
      items: g.aliases
        .map((a) => byAlias.get(a))
        .filter((e): e is (typeof filteredCommands)[number] => Boolean(e))
        .filter((e) => {
          const key = e[0];
          if (seen.has(key)) return false;
          seen.add(key);
          return true;
        }),
    })).filter((g) => g.items.length > 0);
    const rest = filteredCommands.filter(([modeId]) => !seen.has(modeId));
    if (rest.length > 0) groups.push({ group: "Outros", aliases: [], items: rest });
    return groups;
  }, [filteredCommands]);

  function handleAttachOption(id: string) {
    setAttachOpen(false);
    if (id === "contexto") {
      setInput((prev) => (prev ? `${prev} @project ` : "@project "));
      requestAnimationFrame(() => inputRef.current?.focus());
      return;
    }
    fileInputRef.current?.click();
  }

  // -----------------------------------------------------------------------
  // Ctrl/Cmd+K belongs to global search in the TopBar. Ctrl/Cmd+F is scoped
  // to this conversation so the two search surfaces never fight each other.
  // -----------------------------------------------------------------------
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === "f") {
        e.preventDefault();
        setSearchOpen(true);
      } else if (e.key === "Escape" && searchOpen) {
        setSearchOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [searchOpen]);

  // Cleanup voice recognition on unmount
  useEffect(() => {
    return () => {
      try { recognitionRef.current?.stop(); } catch {}
    };
  }, []);

  useKeyboardShortcuts([
    {
      key: "Enter",
      callback: () => {
        if (!streaming && input.trim()) {
          void doSendMessage();
        }
      },
      description: "Send message",
    },
    {
      key: "d",
      ctrlKey: true,
      callback: toggleTheme,
      description: "Toggle theme",
    },
  ]);

  const liveMessages = useMemo(
    () => foldRun(pendingUser, orderedEvents, lastUserMessageRef.current ?? "").messages,
    [pendingUser, orderedEvents],
  );
  const messages = useMemo(
    () => [...historyMessages, ...liveMessages],
    [historyMessages, liveMessages],
  );

  const historyPagesForSessionRef = useRef(historyPagesForSession);
  historyPagesForSessionRef.current = historyPagesForSession;
  const olderHistoryCursorRef = useRef(olderHistoryCursor);
  olderHistoryCursorRef.current = olderHistoryCursor;
  const searchSnapshotRef = useRef({
    messages,
    sessionId,
    historyLoaded: historyLoadedForSession,
    olderCursor: olderHistoryCursor,
    hasOlder: hasOlderHistory,
  });
  searchSnapshotRef.current = {
    messages,
    sessionId,
    historyLoaded: historyLoadedForSession,
    olderCursor: olderHistoryCursor,
    hasOlder: hasOlderHistory,
  };
  const liveMessagesRef = useRef(liveMessages);
  liveMessagesRef.current = liveMessages;
  const archiveCurrentTurn = (archiveMessages = true) => {
    const messagesToArchive = archiveMessages ? liveMessagesRef.current : [];
    if (messagesToArchive.length > 0) {
      const existingMessages = historyPagesForSessionRef.current.flat();
      const seenIds = new Set(existingMessages.map((message) => message.id));
      const newMessages = messagesToArchive.filter((message) => {
        if (seenIds.has(message.id)) return false;
        seenIds.add(message.id);
        return true;
      });
      if (newMessages.length > 0) {
        setHistoryPages(chunkHistory([...existingMessages, ...newMessages]));
      }
    }
    setPendingUser([]);
    reset();
  };
  const activeSearchResultIndex = searchResults.findIndex(
    (result) => result.message.id === activeSearchResultId,
  );
  const safeActiveSearchResultIndex = activeSearchResultIndex >= 0 ? activeSearchResultIndex : 0;
  const searchResultWindowSize = 12;
  const searchResultWindowStart = Math.max(
    0,
    Math.min(
      safeActiveSearchResultIndex - Math.floor(searchResultWindowSize / 2),
      searchResults.length - searchResultWindowSize,
    ),
  );
  const visibleSearchResults = searchResults.slice(
    searchResultWindowStart,
    searchResultWindowStart + searchResultWindowSize,
  );

  useEffect(() => () => {
    if (searchHighlightTimerRef.current !== null) {
      window.clearTimeout(searchHighlightTimerRef.current);
    }
  }, []);

  // Search the current page immediately, then walk the authenticated cursor
  // API from newest to oldest. Only matching pages are retained for jumping;
  // the rest of the scan keeps a small cursor chain instead of another full
  // copy of a potentially very large conversation.
  useEffect(() => {
    const generation = ++searchGenerationRef.current;
    if (!searchOpen) {
      setSearchLoading(false);
      return;
    }

    const query = searchQuery.trim();
    if (!query) {
      searchPagesByMessageIdRef.current = new Map();
      setSearchResults([]);
      setActiveSearchResultId(null);
      setSearchLoading(false);
      setSearchScannedPages(0);
      setSearchError(null);
      return;
    }

    setSearchResults([]);
    setActiveSearchResultId(null);
    setSearchLoading(true);
    setSearchError(null);
    const timer = window.setTimeout(() => {
      const snapshot = searchSnapshotRef.current;
      if (!snapshot.historyLoaded || snapshot.sessionId !== sessionId) {
        setSearchLoading(!snapshot.historyLoaded);
        return;
      }

      const requestedSessionId = snapshot.sessionId;
      const normalizedQuery = query.toLocaleLowerCase();
      const pagesByMessageId = new Map<string, SearchHistoryPage>();
      searchPagesByMessageIdRef.current = pagesByMessageId;
      setSearchError(null);
      setSearchNavigationError(null);
      setSearchScannedPages(0);
      setSearchLoading(Boolean(snapshot.hasOlder && snapshot.olderCursor));

      const localMatches = snapshot.messages
        .filter((message) => message.content?.toLocaleLowerCase().includes(normalizedQuery))
        .map((message) => ({ message }));
      setSearchResults(localMatches);
      setActiveSearchResultId((current) =>
        current && localMatches.some((result) => result.message.id === current)
          ? current
          : localMatches[0]?.message.id ?? null,
      );

      void (async () => {
        const olderMatchPages: MessageSearchResult[][] = [];
        let cursor = snapshot.olderCursor;
        let scannedPages = 0;
        let scanError: string | null = null;
        const visitedCursors = new Set<string>();
        const isCurrent = () =>
          searchGenerationRef.current === generation &&
          selectedSessionIdRef.current === requestedSessionId;

        while (cursor && isCurrent()) {
          const beforeCursor = cursor;
          if (visitedCursors.has(beforeCursor)) {
            scanError = "A paginação da pesquisa repetiu um cursor. Mantive os resultados encontrados; pesquisa novamente para atualizar o histórico.";
            break;
          }
          visitedCursors.add(beforeCursor);
          try {
            const page = await getSessionHistoryPage(requestedSessionId, 100, beforeCursor);
            if (!isCurrent()) return;

            const normalizedMessages = page.messages.map((message, index) => ({
              ...message,
              id: message.id || `${requestedSessionId}-search-${scannedPages}-${index}`,
              content:
                message.role === "assistant"
                  ? sanitizeAssistantContent(stripAnsiCodes(message.content))
                  : stripAnsiCodes(message.content),
            }));
            const pageKey = normalizedMessages[0]?.id ?? `${requestedSessionId}-search-${scannedPages}`;
            const pageMatches = normalizedMessages.filter((message) =>
              message.content?.toLocaleLowerCase().includes(normalizedQuery),
            );
            if (pageMatches.length) {
              const cachedPage: SearchHistoryPage = {
                beforeCursor,
                pageKey,
              };
              for (const message of pageMatches) pagesByMessageId.set(message.id, cachedPage);
              olderMatchPages.push(pageMatches.map((message) => ({ message })));
            }

            scannedPages += 1;
            setSearchScannedPages(scannedPages);
            // Publish in small batches so a common term in a very long chat
            // doesn't make each page re-flatten an ever-growing result list.
            if (scannedPages % 8 === 0 && olderMatchPages.length) {
              const olderMatches = [...olderMatchPages].reverse().flat();
              const nextResults = [...olderMatches, ...localMatches];
              setSearchResults(nextResults);
              setActiveSearchResultId((current) =>
                current && nextResults.some((result) => result.message.id === current)
                  ? current
                  : nextResults[0]?.message.id ?? null,
              );
            }

            if (!page.has_more) break;
            if (!page.next_cursor) {
              scanError = "O histórico indica mais mensagens, mas não forneceu um cursor válido. Mantive os resultados encontrados.";
              break;
            }
            if (visitedCursors.has(page.next_cursor)) {
              scanError = "A paginação da pesquisa repetiu um cursor. Mantive os resultados encontrados; pesquisa novamente para atualizar o histórico.";
              break;
            }
            cursor = page.next_cursor;
          } catch (error) {
            if (!isCurrent()) return;
            scanError = error instanceof Error ? error.message : String(error);
            break;
          }
        }

        if (!isCurrent()) return;
        const olderMatches = [...olderMatchPages].reverse().flat();
        const allResults = [...olderMatches, ...localMatches];
        setSearchResults(allResults);
        setActiveSearchResultId((current) =>
          current && allResults.some((result) => result.message.id === current)
            ? current
            : allResults[0]?.message.id ?? null,
        );
        setSearchError(scanError);
        setSearchLoading(false);
      })();
    }, 180);

    return () => {
      window.clearTimeout(timer);
      if (searchGenerationRef.current === generation) searchGenerationRef.current += 1;
    };
  }, [searchOpen, searchQuery, sessionId, historyLoadedForSession]);

  const navigateToSearchResult = useCallback(async (result: MessageSearchResult) => {
    const messageId = result.message.id;
    const requestedSessionId = sessionId;
    const historyGeneration = historyLoadGenerationRef.current;
    setSearchOpen(false);
    setSearchNavigationError(null);

    const scheduleLoadedTarget = () => {
      const loadedPages = historyPagesForSessionRef.current;
      const pageIndex = loadedPages.findIndex((page) => page.some((message) => message.id === messageId));
      if (pageIndex >= 0) {
        const page = loadedPages[pageIndex];
        setSearchNavigation({
          messageId,
          messageListId: `${requestedSessionId}-history-${page[0]?.id ?? pageIndex}`,
        });
        return true;
      }
      if (liveMessagesRef.current.some((message) => message.id === messageId)) {
        setSearchNavigation({ messageId, messageListId: `${requestedSessionId}-live` });
        return true;
      }
      return false;
    };

    if (scheduleLoadedTarget()) return;
    const targetPage = searchPagesByMessageIdRef.current.get(messageId);
    if (!targetPage) {
      setSearchNavigationError("Este resultado já não está disponível. Faz novamente a pesquisa.");
      setSearchOpen(true);
      return;
    }

    const startingCursor = olderHistoryCursorRef.current;
    let cursor = startingCursor;
    const bridgePages: ChatMessage[][] = [];
    let pageNumber = 0;
    try {
      while (cursor && cursor !== targetPage.beforeCursor) {
        if (
          selectedSessionIdRef.current !== requestedSessionId ||
          historyLoadGenerationRef.current !== historyGeneration
        ) return;
        const page = await getSessionHistoryPage(requestedSessionId, 100, cursor);
        if (
          selectedSessionIdRef.current !== requestedSessionId ||
          historyLoadGenerationRef.current !== historyGeneration
        ) return;
        const normalized = page.messages.map((message, index) => ({
          ...message,
          id: message.id || `${requestedSessionId}-search-jump-${pageNumber}-${index}`,
          content:
            message.role === "assistant"
              ? sanitizeAssistantContent(stripAnsiCodes(message.content))
              : stripAnsiCodes(message.content),
        }));
        bridgePages.push(normalized);
        pageNumber += 1;
        if (!page.next_cursor || page.next_cursor === cursor) break;
        cursor = page.next_cursor;
      }

      if (
        selectedSessionIdRef.current !== requestedSessionId ||
        historyLoadGenerationRef.current !== historyGeneration
      ) return;
      if (scheduleLoadedTarget()) return;
      if (
        olderHistoryCursorRef.current !== startingCursor ||
        cursor !== targetPage.beforeCursor
      ) {
        setSearchNavigationError("O histórico mudou durante a navegação. Pesquisa novamente para atualizar os resultados.");
        setSearchOpen(true);
        return;
      }

      const targetResponse = await getSessionHistoryPage(
        requestedSessionId,
        100,
        targetPage.beforeCursor,
      );
      if (
        selectedSessionIdRef.current !== requestedSessionId ||
        historyLoadGenerationRef.current !== historyGeneration
      ) return;
      if (olderHistoryCursorRef.current !== startingCursor) {
        if (scheduleLoadedTarget()) return;
        setSearchNavigationError("O histórico mudou durante a navegação. Pesquisa novamente para atualizar os resultados.");
        setSearchOpen(true);
        return;
      }
      const targetMessages = targetResponse.messages.map((message, index) => ({
        ...message,
        id: message.id || `${requestedSessionId}-search-target-${index}`,
        content:
          message.role === "assistant"
            ? sanitizeAssistantContent(stripAnsiCodes(message.content))
            : stripAnsiCodes(message.content),
      }));
      if (!targetMessages.some((message) => message.id === messageId)) {
        setSearchNavigationError("A mensagem já não está nessa página. Pesquisa novamente para atualizar os resultados.");
        setSearchOpen(true);
        return;
      }

      // Cursor pages are fetched newest-to-oldest, while ChatPanel stores them
      // oldest-to-newest. Include every bridge page so the result stays in its
      // true chronological position among the already-rendered messages.
      const pagesToPrepend = [targetMessages, ...bridgePages.reverse()];
      const existingIds = new Set(historyPagesForSessionRef.current.flatMap((page) => page.map((message) => message.id)));
      const uniquePages = pagesToPrepend
        .map((page) => page.filter((message) => !existingIds.has(message.id)))
        .filter((page) => page.length > 0);
      historyScrollAnchorRef.current = null;
      setHistoryPages((pages) => [...uniquePages, ...pages]);
      setHistorySessionId(requestedSessionId);
      historySessionIdRef.current = requestedSessionId;
      setOlderHistoryCursor(targetResponse.next_cursor);
      setHasOlderHistory(targetResponse.has_more);
      olderHistoryCursorRef.current = targetResponse.next_cursor;
      setSearchNavigation({
        messageId,
        messageListId: `${requestedSessionId}-history-${targetPage.pageKey}`,
      });
    } catch (error) {
      setSearchNavigationError(
        error instanceof Error ? error.message : "Não foi possível carregar o resultado da pesquisa.",
      );
      setSearchOpen(true);
    }
  }, [sessionId]);

  // Results can be in a page hidden by the progressive message list. Expand
  // just that page, then scroll the stable message id into view and briefly
  // highlight it so the jump is easy to spot.
  useEffect(() => {
    if (!searchNavigation) return;
    let cancelled = false;
    let attempts = 0;
    let timer: number | null = null;
    const container = messagesContainerRef.current;

    const attemptNavigation = () => {
      if (cancelled || !container) return;
      const target = Array.from(container.querySelectorAll<HTMLElement>("[data-chat-message-id]"))
        .find((element) => element.dataset.chatMessageId === searchNavigation.messageId);
      if (target) {
        target.scrollIntoView?.({ behavior: "smooth", block: "center" });
        setSearchHighlightMessageId(searchNavigation.messageId);
        if (searchHighlightTimerRef.current !== null) {
          window.clearTimeout(searchHighlightTimerRef.current);
        }
        searchHighlightTimerRef.current = window.setTimeout(() => {
          setSearchHighlightMessageId((current) =>
            current === searchNavigation.messageId ? null : current,
          );
        }, 1_800);
        setSearchNavigation(null);
        return;
      }

      const messageList = Array.from(
        container.querySelectorAll<HTMLElement>("[data-chat-message-list-id]"),
      ).find((element) => element.dataset.chatMessageListId === searchNavigation.messageListId);
      const loadMore = messageList
        ? Array.from(messageList.querySelectorAll("button")).find((button) =>
            /^Carregar mais\s+\d+\s+mensagens/i.test(button.textContent?.trim() ?? ""),
          )
        : undefined;
      if (loadMore) loadMore.click();
      attempts += 1;
      if (attempts >= 50) {
        setSearchNavigationError("A mensagem foi carregada, mas não apareceu na lista. Tenta novamente.");
        setSearchNavigation(null);
        return;
      }
      timer = window.setTimeout(attemptNavigation, loadMore ? 0 : 20);
    };

    const frame = window.requestAnimationFrame(attemptNavigation);
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frame);
      if (timer) window.clearTimeout(timer);
    };
  }, [searchNavigation, historyMessages]);

  // True while streaming but before the first token/thinking event arrives.
  const waitingForFirstToken =
    streaming &&
    !orderedEvents.some(
      (e) => (e.type === "token" || e.type === "thinking") && e.content,
    );

  // Most recent meaningful streaming status, scanned from the end of the event list.
  // Kept for the compact fallback pill; the temporal line below is the primary UI.
  const streamStatus = useMemo<string | null>(() => {
    if (!streaming) return null;
    for (let i = orderedEvents.length - 1; i >= 0; i--) {
      const e = orderedEvents[i];
      switch (e.type) {
        case "agent_started":
          return `${e.agent ?? "IA"} a pensar…`;
        case "thinking":
          return `${e.agent ?? "IA"} a raciocinar…`;
        case "tool_call":
          return `A usar ferramenta: ${e.tool_name ?? ""}`;
        case "tool_result":
          return "Ferramenta concluída";
        case "routing":
          return "A encaminhar…";
        default:
          break;
      }
    }
    return "A pensar…";
  }, [streaming, orderedEvents]);

  // Temporal live line derived from the whole run: understand → plan → explore → agents.
  const livePhase = useMemo<LivePhase | null>(() => {
    if (!streaming) return null;
    return deriveLivePhases(orderedEvents);
  }, [streaming, orderedEvents]);
  const liveAgentCount = livePhase?.agents.length ?? 0;

  const previousMessagesLength = useRef(messages.length);
  const initialScrollSessionRef = useRef<string | null>(null);
  const userScrolledUp = useRef(false);
  const [showScrollDown, setShowScrollDown] = useState(false);

  const scrollToBottom = useCallback(() => {
    const container = messagesContainerRef.current;
    if (!container) return;
    container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }, []);

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    if (
      historyLoadedForSession &&
      sessionId &&
      initialScrollSessionRef.current !== sessionId
    ) {
      initialScrollSessionRef.current = sessionId;
      previousMessagesLength.current = messages.length;
      userScrolledUp.current = false;
      setShowScrollDown(false);
      requestAnimationFrame(() => {
        container.scrollTop = container.scrollHeight;
      });
      return;
    }

    const historyAnchor = historyScrollAnchorRef.current;
    if (historyAnchor) {
      historyScrollAnchorRef.current = null;
      previousMessagesLength.current = messages.length;
      requestAnimationFrame(() => {
        const nextHeight = container.scrollHeight;
        container.scrollTop = historyAnchor.top + (nextHeight - historyAnchor.height);
      });
      return;
    }

    const isNewMessageAdded = messages.length > previousMessagesLength.current;
    previousMessagesLength.current = messages.length;

    // Anti layout-shift: never yank the viewport while the user reads history.
    // Only auto-follow when already near the bottom. New turns scroll smoothly;
    // token updates within the same assistant message follow immediately.
    const isNearBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight < 120;

    if (userScrolledUp.current || !isNearBottom) return;
    setShowScrollDown(false);
    if (!isNewMessageAdded) {
      container.scrollTop = container.scrollHeight;
      return;
    }
    const reduced = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduced) {
      container.scrollTop = container.scrollHeight;
      return;
    }
    container.scrollTo({ top: container.scrollHeight, behavior: "smooth" });
  }, [historyLoadedForSession, messages, sessionId, streaming]);

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    const handleScroll = () => {
      const isNearBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight < 100;
      userScrolledUp.current = !isNearBottom;
      setShowScrollDown(!isNearBottom);
    };

    container.addEventListener("scroll", handleScroll);
    return () => container.removeEventListener("scroll", handleScroll);
  }, []);

  const lastUserMessage =
    [...historyMessages, ...pendingUser]
      .reverse()
      .find((message) => message.role === "user")?.content ?? "";

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    await doSendMessage();
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (showCommands) {
      if (e.key === "Escape") {
        e.preventDefault();
        setShowCommands(false);
        return;
      }
      if (e.key === "ArrowDown" && filteredCommands.length > 0) {
        e.preventDefault();
        setSelectedCommandIndex((index) => (index + 1) % filteredCommands.length);
        return;
      }
      if (e.key === "ArrowUp" && filteredCommands.length > 0) {
        e.preventDefault();
        setSelectedCommandIndex(
          (index) => (index - 1 + filteredCommands.length) % filteredCommands.length,
        );
        return;
      }
      if ((e.key === "Enter" || e.key === "Tab") && filteredCommands.length > 0) {
        e.preventDefault();
        const [modeId, info] = filteredCommands[selectedCommandIndex] ?? filteredCommands[0];
        insertCommand(info.aliases[0]?.replace(/^\//, "") || modeId);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const form = e.currentTarget.closest("form");
      if (form) form.requestSubmit();
    }
  }

  function handleCancel() {
    cancel();
  }

  // Edit a user message: update its content and immediately regenerate the
  // assistant response (modern chat UX — no second "Send" click). Everything
  // after the edited turn is dropped from the local view; the resent prompt
  // appears once as a fresh pending bubble.
  function handleEditMessage(messageId: string, newContent: string) {
    if (streaming) return;
    const idx = historyMessages.findIndex((m) => m.id === messageId);
    if (idx < 0) return;
    setHistoryPages(chunkHistory(historyMessages.slice(0, idx)));
    setPendingUser([]);
    reset();
    void doSendMessage(newContent, false);
  }

  // Regenerate the assistant response for a given message: drop the reply and
  // everything after it, then resend the original prompt right away.
  function handleRegenerateMessage(messageId: string) {
    if (streaming) return;
    const idx = historyMessages.findIndex((m) => m.id === messageId);
    if (idx < 0) {
      toast.error("Não foi possível regenerar");
      return;
    }
    // Walk back to the user prompt that produced this assistant message.
    let userIdx = idx - 1;
    while (userIdx >= 0 && historyMessages[userIdx].role !== "user") userIdx -= 1;
    if (userIdx < 0) {
      toast.error("Apenas é possível regenerar a partir de uma mensagem do utilizador");
      return;
    }
    const prompt = historyMessages[userIdx].content;
    setHistoryPages(chunkHistory(historyMessages.slice(0, userIdx)));
    setPendingUser([]);
    reset();
    void doSendMessage(prompt, false);
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    if (files.length > 0) addChatFiles(files);
    e.target.value = "";
  }

  function handleRemoveFile(index: number) {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
  }

  function handleRegenerate() {
    if (streaming) return;
    const last = lastUserMessage || lastUserMessageRef.current;
    if (!last) return;
    const projectPath = currentProject?.path || ".";
    archiveCurrentTurn();
    void send(
      last,
      currentMode,
      activeModel,
      projectPath,
      thinkingStrength,
      undefined,
      activeProvider,
      Boolean(activeModel),
    ).then(() => loadHistory());
  }

  // Retry the prompt from an error bubble (passed to MessageBubble):
  // resend immediately instead of asking for a second "Send" click.
  function handleRetryFromError(prompt: string) {
    if (streaming || !prompt.trim()) return;
    void doSendMessage(prompt);
  }

  async function handleNewChat() {
    const title = `Chat ${new Date().toLocaleString("pt-PT")}`;
    const created = await sessions.create(title, currentMode);
    if (!created) {
      toast.error("Não foi possível criar a sessão", sessions.error ?? "Confirma a ligação ao backend e tenta novamente.");
      return;
    }
    setPendingUsersBySession((current) => ({ ...current, [created.id]: [] }));
    sessions.setCurrentId(created.id);
    setSessionId(created.id);
    setHistoryPages([]);
    setHistoryLoaded(true);
    setHistoryError(null);
    setHistorySessionId(created.id);
    historySessionIdRef.current = created.id;
    historyLoadGenerationRef.current += 1;
    setOlderHistoryCursor(null);
    setHasOlderHistory(false);
    reset();
    toast.info("Nova sessão criada", created.title);
  }

  function handleShare() {
    const allMessages = [
      ...historyMessages,
      ...foldRun(pendingUser, orderedEvents).messages,
    ];
    if (allMessages.length === 0) return;
    const text = allMessages
      .map((m) => `[${m.role}] ${m.content}`)
      .join("\n\n");
    navigator.clipboard.writeText(text);
    setShared(true);
    setTimeout(() => setShared(false), 2000);
  }

  const stopPlanPolling = useCallback(() => {
    planPollGenerationRef.current += 1;
    if (planPollRef.current !== null) {
      clearInterval(planPollRef.current);
      planPollRef.current = null;
    }
  }, []);

  const startPlanPolling = useCallback((planId: string, planSessionId: string, actionGeneration: number) => {
    stopPlanPolling();
    const pollGeneration = planPollGenerationRef.current;
    let requestInFlight = false;
    const poll = async () => {
      if (
        requestInFlight ||
        pollGeneration !== planPollGenerationRef.current ||
        selectedSessionIdRef.current !== planSessionId
      ) return;
      requestInFlight = true;
      try {
        const status = await getPlanStatus(planId);
        if (
          pollGeneration !== planPollGenerationRef.current ||
          selectedSessionIdRef.current !== planSessionId
        ) return;
        setPlanStatus(status);
        if (["completed", "failed", "cancelled"].includes(status.status)) {
          stopPlanPolling();
          if (actionGeneration === planActionGenerationRef.current) {
            setPlanExecuting(false);
          }
        }
      } catch (error) {
        if (
          pollGeneration !== planPollGenerationRef.current ||
          selectedSessionIdRef.current !== planSessionId
        ) return;
        if (error instanceof ApiError && error.status === 404) {
          setPlanError(getPlanErrorMessage(error, "Não foi possível ler o estado do plano."));
          stopPlanPolling();
          if (actionGeneration === planActionGenerationRef.current) {
            setPlanExecuting(false);
          }
        }
      } finally {
        requestInFlight = false;
      }
    };

    // Read once immediately, then keep the UI current while the action request
    // is still running inline on the backend.
    void poll();
    planPollRef.current = setInterval(() => void poll(), 2000);
  }, [stopPlanPolling]);

  const startPlanExecution = useCallback(async (planId: string) => {
    if (planExecuting) return;
    const planSessionId = sessionId;
    const actionGeneration = ++planActionGenerationRef.current;
    setPlanError(null);
    setPlanExecuting(true);
    startPlanPolling(planId, planSessionId, actionGeneration);
    try {
      await executePlan(planId, sessionId, currentProject?.path || ".");
      const status = await getPlanStatus(planId);
      if (
        actionGeneration === planActionGenerationRef.current &&
        selectedSessionIdRef.current === planSessionId
      ) setPlanStatus(status);
    } catch (err) {
      if (actionGeneration === planActionGenerationRef.current) {
        setPlanError(getPlanErrorMessage(err, "Falha ao executar o plano."));
        log.error("Failed to execute plan:", err);
      }
    } finally {
      if (actionGeneration === planActionGenerationRef.current) {
        stopPlanPolling();
        setPlanExecuting(false);
      }
    }
  }, [currentProject?.path, planExecuting, sessionId, startPlanPolling, stopPlanPolling]);

  const handlePlanCreate = useCallback(async (objective: string): Promise<boolean> => {
    setPlanError(null);
    setPlanCreating(true);
    try {
      const planning = await createPlan(objective, sessionId, "", false, true);
      const plan = planning.plan;
      if (!plan) {
        const proposal = planning.deterministic_proposal;
        setActivePlan(proposal);
        setActivePlanSessionId(proposal ? sessionId : null);
        if (proposal) {
          setPlanStatus({
            plan_id: proposal.plan_id,
            status: "planning_blocked",
            title: proposal.title,
            total_steps: proposal.total_steps,
            steps: proposal.steps,
            requires_approval: true,
            approved: false,
          });
        }
        setPlanError(
          planning.error || "O planeamento foi bloqueado; existe uma proposta segura para revisão.",
        );
        await loadHistory();
        return true;
      }
      setActivePlan(plan);
      setActivePlanSessionId(sessionId);
      try {
        setPlanStatus(await getPlanStatus(plan.plan_id));
      } catch (statusError) {
        setPlanStatus(null);
        setPlanError(
          statusError instanceof Error
            ? `Plano criado, mas não consegui carregar o estado: ${getPlanErrorMessage(statusError, "erro desconhecido")}`
            : "Plano criado, mas não consegui carregar o estado.",
        );
      }
      await loadHistory();
      return true;
    } catch (err) {
      setPlanError(getPlanErrorMessage(err, "Falha ao criar o plano."));
      log.error("Failed to create plan:", err);
      return false;
    } finally {
      setPlanCreating(false);
    }
  }, [loadHistory, sessionId]);

  const handlePlanContinue = useCallback(async () => {
    setPlanError(null);
    try {
      const planning = await continuePlan(sessionId);
      if (!planning.plan) throw new Error("A proposta segura já não está disponível");
      setActivePlan(planning.plan);
      setActivePlanSessionId(sessionId);
      setPlanStatus(await getPlanStatus(planning.plan.plan_id));
    } catch (err) {
      setPlanError(getPlanErrorMessage(err, "Falha ao continuar o plano."));
    }
  }, [sessionId]);

  const handlePlanApprove = useCallback(async () => {
    if (!activePlan || planExecuting) return;
    const planSessionId = sessionId;
    const actionGeneration = ++planActionGenerationRef.current;
    setPlanError(null);
    setPlanExecuting(true);
    startPlanPolling(activePlan.plan_id, planSessionId, actionGeneration);
    try {
      await approvePlan(activePlan.plan_id, sessionId);
      const status = await getPlanStatus(activePlan.plan_id);
      if (
        actionGeneration === planActionGenerationRef.current &&
        selectedSessionIdRef.current === planSessionId
      ) setPlanStatus(status);
    } catch (err) {
      if (actionGeneration === planActionGenerationRef.current) {
        setPlanError(getPlanErrorMessage(err, "Falha ao aprovar o plano."));
        log.error("Failed to approve plan:", err);
      }
    } finally {
      if (actionGeneration === planActionGenerationRef.current) {
        stopPlanPolling();
        setPlanExecuting(false);
      }
    }
  }, [activePlan, planExecuting, sessionId, startPlanPolling, stopPlanPolling]);

  const handlePlanExecute = useCallback(async () => {
    if (!activePlan || planExecuting) return;
    await startPlanExecution(activePlan.plan_id);
  }, [activePlan, planExecuting, startPlanExecution]);

  const handlePlanCancel = useCallback(async () => {
    try {
      await cancelPlan(sessionId);
      setActivePlan(null);
      setActivePlanSessionId(null);
      setPlanStatus(null);
      setPlanExecuting(false);
      planActionGenerationRef.current += 1;
      stopPlanPolling();
    } catch (err) {
      setPlanError(getPlanErrorMessage(err, "Falha ao cancelar o plano."));
      log.error("Failed to cancel plan:", err);
    }
  }, [sessionId, stopPlanPolling]);

  useEffect(() => {
    return () => {
      planActionGenerationRef.current += 1;
      stopPlanPolling();
    };
  }, [stopPlanPolling]);

  useEffect(() => {
    if (activePlanSessionId === sessionId || planPollRef.current === null) return;
    planActionGenerationRef.current += 1;
    stopPlanPolling();
    setPlanExecuting(false);
  }, [activePlanSessionId, sessionId, stopPlanPolling]);

  const suggestions: { label: string; prompt: string; icon: ReactNode }[] = [
    {
      label: "Analisar projeto",
      prompt: "Analisa a estrutura deste projeto e explica a arquitetura",
      icon: <Search className="h-3.5 w-3.5" />,
    },
    {
      label: "Corrigir erros",
      prompt: "Procura erros e código problemático neste projeto e propõe correções",
      icon: <Bug className="h-3.5 w-3.5" />,
    },
    {
      label: "Executar testes",
      prompt: "Executa os testes do projeto e resume os resultados",
      icon: <Zap className="h-3.5 w-3.5" />,
    },
    {
      label: "Gerar código",
      prompt: "Ajuda-me a escrever código novo para este projeto",
      icon: <Code className="h-3.5 w-3.5" />,
    },
  ];

  return (
    <ChatDensityContext.Provider value={density}>
    <div className="relative flex h-full min-w-0 bg-nexus-bg" data-testid="ai-cockpit" data-density={density}>
      {!sidebarCollapsed && (
        <button
          type="button"
          aria-label="Fechar sessões"
          onClick={() => setSidebarCollapsed(true)}
          className="absolute inset-0 z-40 bg-black/25 backdrop-blur-[1px]"
        />
      )}
      <SessionList
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((c) => !c)}
      />
      <div className="flex h-full min-w-0 flex-1 flex-col">
      {/* Chat header — minimal conversation-first: NEXUS/projeto · Auto/Modelo/agentes · ••• */}
      <div className="flex shrink-0 items-center justify-between gap-2 border-b border-nexus-border/60 bg-nexus-panel/70 px-3 py-3 sm:px-5" data-testid="chat-header">
        <div className="flex min-w-0 items-center gap-2">
          <motion.button
            type="button"
            whileTap={{ scale: 0.95 }}
            onClick={() => setSidebarCollapsed(false)}
            className="flex items-center gap-1.5 rounded-lg border border-nexus-border bg-nexus-card px-2 py-1.5 text-xs font-medium text-nexus-muted transition-colors hover:border-nexus-accent/30 hover:text-nexus-text"
            title="Abrir sessões"
            aria-label="Abrir sessões"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            <span className="rounded-full bg-nexus-bg/70 px-1.5 py-0.5 font-mono text-[10px] tabular-nums">
              {sessions.sessions.length}
            </span>
          </motion.button>
          <div className="min-w-0 leading-tight">
            <h1 className="truncate text-sm font-semibold tracking-tight text-nexus-text">
              NEXUS <span className="font-normal text-nexus-faint">/</span>{" "}
              <span className="font-medium text-nexus-muted">{currentProject?.name ?? "sem projeto"}</span>
            </h1>
          </div>
        </div>

        <div className="chat-header-center hidden min-w-0 items-center gap-1.5 md:flex" aria-label="Modo, modelo e agentes">
          {/* Mode selector — compact dropdown instead of one button per mode */}
          <ModeDropdown />
          {/* Model selector — search, provider grouping, price/context */}
          <ModelSelector />
          <span
            className="ml-1 hidden items-center gap-1.5 rounded-full border border-nexus-border bg-nexus-card px-2 py-1 text-[11px] text-nexus-muted lg:inline-flex"
            title={streaming ? livePhase?.line ?? "A executar" : "Nenhuma execução ativa"}
            aria-live={streaming ? "polite" : undefined}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${streaming ? "bg-emerald-400 animate-pulse-subtle" : "bg-nexus-faint"}`} />
            {streaming ? `●${Math.max(1, liveAgentCount)} agentes` : "○ em espera"}
          </span>
        </div>

        <div className="flex shrink-0 items-center gap-1.5">
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.9 }}
            onClick={handleShare}
            className="rounded-lg border border-nexus-border bg-nexus-card p-1.5 text-nexus-muted hover:text-nexus-text transition-all duration-200 hover:border-nexus-accent/30"
            title="Partilhar (copiar conversação)"
            aria-label="Partilhar conversa"
          >
            <AnimatePresence mode="wait">
              {shared ? (
                <motion.div
                  key="check"
                  initial={{ scale: 0.5, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0.5, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <Check className="h-3.5 w-3.5 text-green-400" />
                </motion.div>
              ) : (
                <motion.div
                  key="share"
                  initial={{ scale: 0.5, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0.5, opacity: 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <Share2 className="h-3.5 w-3.5" />
                </motion.div>
              )}
            </AnimatePresence>
          </motion.button>
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.9 }}
            onClick={() => {
              toggleFocusMode();
              setFocusMode(document.body.classList.contains("nexus-focus"));
            }}
            className={`rounded-lg border p-1.5 transition-all duration-200 hover:border-nexus-accent/30 hover:text-nexus-text ${focusMode ? "border-nexus-accent/50 bg-nexus-accent/15 text-nexus-accent" : "border-nexus-border bg-nexus-card text-nexus-muted"}`}
            title="Focus Mode (Ctrl+Shift+F)"
            aria-label="Alternar Focus Mode"
            aria-pressed={focusMode}
          >
            <Crosshair className="h-3.5 w-3.5" />
          </motion.button>
          <div ref={headerMenuRef} className="relative">
            <motion.button
              whileHover={{ scale: 1.05 }}
              whileTap={{ scale: 0.9 }}
              onClick={() => setHeaderMenuOpen((v) => !v)}
              className="rounded-lg border border-nexus-border bg-nexus-card p-1.5 text-nexus-muted hover:text-nexus-text transition-all duration-200 hover:border-nexus-accent/30"
              title="Mais opções"
              aria-label="Mais opções"
              aria-haspopup="menu"
              aria-expanded={headerMenuOpen}
            >
              <MoreHorizontal className="h-3.5 w-3.5" />
            </motion.button>
            {headerMenuOpen && (
              <div
                role="menu"
                aria-label="Opções do chat"
                className="nx-glass absolute right-0 top-full z-50 mt-1.5 w-64 rounded-xl p-1.5 shadow-xl"
              >
                <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
                  Força de raciocínio
                </div>
                {THINKING_STRENGTH_OPTIONS.map((option) => {
                  const Icon = option.icon;
                  const isActive = thinkingStrength === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      role="menuitemradio"
                      aria-checked={isActive}
                      onClick={() => setThinkingStrength(option.value)}
                      className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors ${isActive ? "bg-nexus-accent/15 text-nexus-accent" : "text-nexus-text hover:bg-nexus-bg/60"}`}
                    >
                      <Icon className="h-3.5 w-3.5" />
                      <span className="flex-1 font-medium">{option.label}</span>
                      <span className="text-[10px] text-nexus-muted">{option.description}</span>
                      {isActive && <Check className="h-3.5 w-3.5" />}
                    </button>
                  );
                })}
                <div className="mx-2 my-1 border-t border-nexus-border/60" />
                <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
                  Densidade
                </div>
                {DENSITY_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    role="menuitemradio"
                    aria-checked={density === option.value}
                    onClick={() => {
                      setDensity(option.value);
                      setHeaderMenuOpen(false);
                    }}
                    className={`flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs transition-colors ${density === option.value ? "bg-nexus-accent/15 text-nexus-accent" : "text-nexus-text hover:bg-nexus-bg/60"}`}
                    title={option.hint}
                  >
                    <span className="flex-1 font-medium">{option.label}</span>
                    <span className="truncate text-[10px] text-nexus-muted">{option.hint}</span>
                    {density === option.value && <Check className="h-3.5 w-3.5" />}
                  </button>
                ))}
                <div className="mx-2 my-1 border-t border-nexus-border/60" />
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setHeaderMenuOpen(false);
                    void handleNewChat();
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-nexus-text transition-colors hover:bg-nexus-bg/60"
                >
                  <Plus className="h-3.5 w-3.5" />
                  <span className="font-medium">Novo Chat</span>
                </button>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setHeaderMenuOpen(false);
                    setRightOpen?.(!rightOpen);
                  }}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-nexus-text transition-colors hover:bg-nexus-bg/60"
                >
                  {rightOpen ? <PanelRightClose className="h-3.5 w-3.5" /> : <PanelRightOpen className="h-3.5 w-3.5" />}
                  <span className="font-medium">Painel direito</span>
                </button>
                <div className="mx-2 my-1 border-t border-nexus-border/60" />
                <div className="flex items-center justify-between px-2.5 py-1.5">
                  <span className="text-[11px] text-nexus-muted">Modo avançado</span>
                  <AdvancedModeHeaderIndicator />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Messages area — central conversation column */}
      <div
        ref={messagesContainerRef}
        data-testid="messages"
        aria-label="Histórico da conversa"
        className="min-h-0 flex-1 overflow-y-auto thin-scrollbar py-5 sm:py-7"
        style={{
          background: "radial-gradient(ellipse at 50% 0%, color-mix(in srgb, var(--nx-accent) 5%, transparent), transparent 55%)",
        }}
      >
      <div className="mx-auto w-full max-w-[960px] px-4 sm:px-7">
        {/* Live temporal status — above the list, not just a spinner */}
        {livePhase && (
          <div className="mb-3 flex justify-start" aria-live="polite" role="status" data-testid="live-phase-pill">
            <span
              className="nx-glass inline-flex max-w-full items-center gap-2 rounded-full px-3 py-1.5 text-[11px] text-nexus-text"
              title={streamStatus ?? undefined}
            >              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-400 animate-pulse-subtle" aria-hidden="true" />
              <span className="truncate">● {livePhase.line}…</span>
            </span>
          </div>
        )}
        {/* Stream error banner */}
        {streamError && (
          <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2">
            <div className="flex items-center gap-2 text-xs text-red-400">
              <AlertTriangle className="h-3.5 w-3.5" />
              <span>{streamError}</span>
            </div>
          </div>
        )}

        {!historyLoadedForSession && (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3 text-sm text-nexus-muted">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
              <span>A carregar conversação...</span>
            </div>
          </div>
        )}

        {historyError && historyLoadedForSession && (
          <div className="flex h-full items-center justify-center">
            <div className="max-w-md rounded-lg border border-red-500/50 bg-red-500/10 p-4">
              <div className="mb-2 flex items-center gap-2 text-sm font-medium text-red-400">
                <svg
                  className="h-4 w-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                  />
                </svg>
                Erro ao carregar histórico
              </div>
              <p className="text-xs text-red-300">{historyError}</p>
              <button
                onClick={() => loadHistory()}
                className="mt-3 rounded bg-red-500/20 px-3 py-1.5 text-xs font-medium text-red-300 hover:bg-red-500/30 transition-colors"
              >
                Tentar novamente
              </button>
            </div>
          </div>
        )}

        {messages.length === 0 && historyLoadedForSession && !historyError && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="mx-auto flex h-full min-h-[360px] max-w-2xl flex-col items-center justify-center px-1 py-10 text-center"
          >
            <div className="relative mb-6">
              <div className="absolute -inset-5 rounded-full bg-nexus-accent/10 blur-2xl" />
              <motion.div
                animate={{
                  scale: [1, 1.06, 1],
                }}
                transition={{
                  duration: 3,
                  repeat: Infinity,
                  ease: "easeInOut",
                }}
                className="relative flex h-14 w-14 items-center justify-center rounded-2xl border border-nexus-accent/20 bg-gradient-to-br from-nexus-accent/15 to-nexus-card text-nexus-accent shadow-sm"
              >
                <Sparkles className="h-8 w-8" />
              </motion.div>
            </div>
            <h2 className="mb-3 text-[26px] font-semibold leading-tight tracking-tight text-nexus-text sm:text-[32px]">
              {currentProject?.name ? (
                <>
                  Vamos trabalhar em{" "}
                  <span className="bg-gradient-to-r from-nexus-accent to-nexus-accent-bright bg-clip-text text-transparent">
                    {currentProject.name}
                  </span>
                  ?
                </>
              ) : (
                "Como posso ajudar?"
              )}
            </h2>
            <p className="mb-8 max-w-sm text-sm leading-relaxed text-nexus-muted">
              Uma ideia, um erro ou o próximo passo. Acompanha a execução, as ferramentas e os ficheiros numa só conversa.
            </p>
            <div className="grid w-full max-w-lg grid-cols-1 gap-2.5 min-[420px]:grid-cols-2">
              {suggestions.map((s) => (
                <motion.button
                  key={s.label}
                  onClick={() => setInput(s.prompt)}
                  whileHover={{ scale: 1.03, y: -2 }}
                  whileTap={{ scale: 0.97 }}
                  transition={{ duration: 0.15 }}
                  className="group flex items-center gap-3 rounded-2xl border border-nexus-border/70 bg-nexus-card/50 px-4 py-4 text-left text-xs text-nexus-muted transition-all duration-150 hover:border-nexus-accent/35 hover:bg-nexus-accent/5 hover:text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/50"
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-nexus-accent/10 text-nexus-accent/70 transition-colors duration-150 group-hover:bg-nexus-accent/20 group-hover:text-nexus-accent">
                    {s.icon}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-medium">{s.label}</span>
                  <span aria-hidden="true" className="shrink-0 text-nexus-faint opacity-0 transition-opacity duration-150 group-hover:opacity-100">→</span>
                </motion.button>
              ))}
            </div>
            {sessions.sessions.length > 0 && (
              <div className="mt-6 w-full max-w-md text-left">
                <div className="mb-1.5 px-1 text-[11px] font-medium text-nexus-faint">Recentes:</div>
                <div className="flex flex-col gap-1">
                  {sessions.sessions.slice(0, 3).map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      onClick={() => sessions.setCurrentId(s.id)}
                      className="group flex min-w-0 items-center gap-2 rounded-lg border border-transparent px-2.5 py-1.5 text-left text-xs text-nexus-muted transition-colors duration-150 hover:border-nexus-border hover:bg-nexus-card/60 hover:text-nexus-text"
                      title={s.title}
                    >
                      <MessageSquare className="h-3.5 w-3.5 shrink-0 text-nexus-faint" />
                      <span className="min-w-0 flex-1 truncate font-medium">{s.title || "Sem título"}</span>
                      <span className="shrink-0 text-[10px] text-nexus-faint">{formatRecente(s.last_active_at)}</span>
                      <span aria-hidden="true" className="shrink-0 text-nexus-faint opacity-0 transition-opacity duration-150 group-hover:opacity-100">→</span>
                    </button>
                  ))}
                </div>
              </div>
            )}
            <div className="mt-8 flex flex-wrap items-center justify-center gap-2 text-[11px] text-nexus-faint">
              <button
                type="button"
                onClick={() => setShowCommands(true)}
                className="rounded-full border border-nexus-border/70 px-2.5 py-1 transition-colors hover:border-nexus-accent/40 hover:text-nexus-text"
              >
                <span className="font-mono text-nexus-muted">/</span> comandos
              </button>
              <button
                type="button"
                onClick={() => {
                  setInput("@");
                  requestAnimationFrame(() => inputRef.current?.focus());
                }}
                className="rounded-full border border-nexus-border/70 px-2.5 py-1 transition-colors hover:border-nexus-accent/40 hover:text-nexus-text"
              >
                <span className="font-mono text-nexus-muted">@</span> agentes
              </button>
              <button
                type="button"
              onClick={() => setSearchOpen(true)}
                className="rounded-full border border-nexus-border/70 px-2.5 py-1 transition-colors hover:border-nexus-accent/40 hover:text-nexus-text"
              >
                <span className="font-mono text-nexus-muted">Ctrl/Cmd+F</span> procurar nesta conversa
              </button>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="rounded-full border border-nexus-border/70 px-2.5 py-1 transition-colors hover:border-nexus-accent/40 hover:text-nexus-text"
              >
                anexar ficheiros
              </button>
            </div>
          </motion.div>
        )}

        {currentMode === "plan" && planCreating && (
          <div
            className="mb-4 flex items-center gap-2 rounded-xl border border-nexus-accent/20 bg-nexus-accent/5 px-4 py-3 text-sm text-nexus-muted"
            role="status"
            aria-live="polite"
          >
            <Loader2 className="h-4 w-4 animate-spin text-nexus-accent" />
            A preparar um plano para esta mensagem…
          </div>
        )}

        {currentMode === "plan" && planError && !activePlan && (
          <div
            className="mb-4 rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-300"
            role="alert"
          >
            {planError}
          </div>
        )}

        {activePlan && activePlanSessionId === sessionId && (
          <PlanExecutionPanel
            plan={activePlan}
            status={planStatus}
            executing={planExecuting}
            error={planError}
            onContinue={() => void handlePlanContinue()}
            onApprove={() => void handlePlanApprove()}
            onExecute={() => void handlePlanExecute()}
            onCancel={() => void handlePlanCancel()}
          />
        )}

        {historyLoadedForSession && (hasOlderHistory || olderHistoryError) && (
          <>
            {olderHistoryError && (
              <div
                role="alert"
                className="mb-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
              >
                <span>Não foi possível carregar mensagens anteriores: {olderHistoryError}</span>
              </div>
            )}
            {hasOlderHistory && (
              <button
                type="button"
                onClick={() => void loadOlderHistory()}
                disabled={loadingOlderHistory}
                className="mb-4 flex w-full items-center justify-center gap-2 rounded-lg border border-nexus-border/60 px-3 py-2 text-xs text-nexus-muted transition-colors hover:border-nexus-accent/40 hover:text-nexus-text disabled:opacity-60"
              >
                {loadingOlderHistory && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                {loadingOlderHistory
                  ? "A carregar mensagens…"
                  : olderHistoryError
                    ? "Tentar carregar novamente"
                    : "Carregar mensagens anteriores"}
              </button>
            )}
          </>
        )}
        {historyPagesForSession.map((page, pageIndex) => {
          const pageOffset = historyPagesForSession
            .slice(0, pageIndex)
            .reduce((count, previousPage) => count + previousPage.length, 0);
          const pageKey = page[0]?.id ?? pageIndex;
          return (
            <div
              key={`${sessionId}-history-${page[0]?.id ?? pageIndex}`}
              data-chat-message-list-id={`${sessionId}-history-${pageKey}`}
            >
              <VirtualMessageList
                messages={page}
                resetKey={`${sessionId}:${historySnapshotRevision}:${pageKey}`}
                renderItem={(message, pageIndex) => {
                  const messageIndex = pageOffset + pageIndex;
                  return (
                    <div
                      key={message.id}
                      data-chat-message-id={message.id}
                      className={`nx-msg-enter rounded-xl transition-shadow ${searchHighlightMessageId === message.id ? "ring-2 ring-nexus-accent/70 shadow-lg shadow-nexus-accent/10" : ""}`}
                    >
                      <MessageBubble
                        message={message}
                        sessionId={sessionId}
                        isStreaming={streaming && messageIndex === messages.length - 1}
                        onRetry={handleRetryFromError}
                        onEdit={handleEditMessage}
                        onRegenerate={handleRegenerateMessage}
                      />
                    </div>
                  );
                }}
                initialLimit={50}
                className="mb-4 space-y-4"
              />
            </div>
          );
        })}
        {liveMessages.length > 0 && (
          <div
            key={`${sessionId}-live`}
            data-chat-message-list-id={`${sessionId}-live`}
          >
            <VirtualMessageList
              messages={liveMessages}
              resetKey={`${sessionId}:${liveMessages[0]?.id ?? "empty"}`}
              renderItem={(message, liveIndex) => {
                const messageIndex = historyMessages.length + liveIndex;
                return (
                  <div
                    key={message.id}
                    data-chat-message-id={message.id}
                    className={`nx-msg-enter rounded-xl transition-shadow ${searchHighlightMessageId === message.id ? "ring-2 ring-nexus-accent/70 shadow-lg shadow-nexus-accent/10" : ""}`}
                  >
                    <MessageBubble
                      message={message}
                      sessionId={sessionId}
                      isStreaming={streaming && messageIndex === messages.length - 1}
                      onRetry={handleRetryFromError}
                      onEdit={handleEditMessage}
                      onRegenerate={handleRegenerateMessage}
                    />
                  </div>
                );
              }}
              initialLimit={50}
              className="space-y-4"
            />
          </div>
        )}
        <div ref={messagesEndRef} />

        {/* Reserved min-height while streaming — anti layout-shift: the list
            never collapses to zero height mid-run. */}
        {streaming && (
          <div aria-hidden="true" className="min-h-[72px]" data-testid="streaming-reserve" />
        )}

        {/* "Thinking / typing" placeholder shown while awaiting the first token */}
        {waitingForFirstToken && (
          <div className="mb-4 flex justify-start">
            <div className="rounded-2xl border border-nexus-border bg-nexus-card px-4 py-3">
              <div className="flex items-center gap-1.5">
                {[0, 1, 2].map((i) => (
                  <motion.span
                    key={i}
                    className="h-2 w-2 rounded-full bg-nexus-muted"
                    animate={{ y: [0, -5, 0] }}
                    transition={{
                      duration: 0.6,
                      repeat: Infinity,
                      ease: "easeInOut",
                      delay: i * 0.15,
                    }}
                  />
                ))}
              </div>
              <div className="mt-1 text-[10px] text-nexus-muted">a pensar…</div>
            </div>
          </div>
        )}
      </div>
      </div>

      {/* Input area — fixed at bottom, mesma coluna central */}
      <div className="relative shrink-0 bg-gradient-to-t from-nexus-bg via-nexus-bg to-nexus-bg/90 pb-3 pt-3">
        {showScrollDown && messages.length > 3 && (
          <button
            type="button"
            onClick={scrollToBottom}
            aria-label="Ir para o fim"
            title="Ir para o fim"
            className="absolute -top-12 right-6 z-20 flex h-9 w-9 items-center justify-center rounded-full border border-nexus-border bg-nexus-panel/95 text-nexus-muted shadow-lg backdrop-blur-sm transition-all duration-150 hover:border-nexus-accent/40 hover:text-nexus-text hover:-translate-y-0.5"
            style={{ opacity: showScrollDown ? 1 : 0 }}
          >
            <span aria-hidden="true" className="text-base leading-none">↓</span>
          </button>
        )}
      <div className="mx-auto w-full max-w-[960px] px-3 sm:px-7">
        {sessionId && <BackgroundAgentsPanel sessionId={sessionId} onCompleted={loadHistory} />}
        {sessions.initialized && !sessionId && (
          <div
            className="mb-2 flex items-center justify-between gap-3 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-200"
            role="status"
            aria-live="polite"
          >
            <span className="min-w-0 truncate">
              Não há uma sessão ativa.{sessions.error ? ` ${sessions.error}` : " Cria ou recupera uma sessão para começar."}
            </span>
            <button
              type="button"
              onClick={() => void sessions.refresh().then(() => sessions.ensureCurrentSession())}
              className="shrink-0 rounded border border-amber-400/30 px-2 py-1 font-medium hover:bg-amber-400/10"
            >
              Tentar novamente
            </button>
          </div>
        )}
        <div className="mb-2"><RuntimeReadinessBanner /></div>

        {/* History connectivity is not a readiness verdict. */}
        {backendOffline && (
          <div role="alert" className="mb-2 flex flex-wrap items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
            <WifiOff className="h-3.5 w-3.5 shrink-0" />
            <span className="font-medium">Ligação ao histórico indisponível</span>
            <span className="text-red-300">— Tenta atualizar a conversa para recuperar a ligação.</span>
            <button type="button" onClick={() => void loadHistory()} disabled={!sessionId || streaming}
              className="ml-auto rounded-lg border border-red-400/25 px-2.5 py-1.5 font-medium text-red-200 hover:bg-red-500/10 focus-visible:ring-2 focus-visible:ring-nexus-accent disabled:opacity-40">Recuperar ligação</button>
          </div>
        )}

        {/* DEMO-MODE warning banner (no LLM provider configured) */}
        {demoMode && (
          <div className="mb-2 flex items-center gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-300">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span>
              ⚠️ MODO DEMO — nenhum provedor LLM configurado. A IA não gera respostas reais.{" "}
              <Link href="/settings" className="text-amber-200 underline font-medium">
                Definições
              </Link>
            </span>
          </div>
        )}

        {/* Persistent error banner — stays until user dismisses or sends a new message */}
        {streamError && !streaming && (
          <div className="mb-2 flex items-start gap-2 rounded-lg border border-red-500/40 bg-red-500/15 px-3 py-2 text-xs text-red-300 shadow-sm">
            <AlertCircle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <div className="min-w-0 flex-1">
              <div className="font-semibold text-red-200">Erro no chat</div>
              <div className="mt-0.5 break-words leading-relaxed text-red-300/90">{streamError}</div>
            </div>
            <button
              type="button"
              onClick={reset}
              className="rounded p-0.5 text-red-300/70 hover:bg-red-500/20 hover:text-red-200"
              title="Fechar erro"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-2 flex flex-col gap-2">
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept="text/*,.md,.py,.js,.ts,.tsx,.jsx,.json,.yaml,.yml,.toml,.css,.scss,.html,.xml,.csv,.sql,.sh,.bat,.ps1,.ini,.cfg,.gitignore,.java,.go,.rs,.php,.rb,.c,.cpp,.h,.vue,.svelte"
            onChange={handleFileSelect}
            className="hidden"
          />

          {/* Context chips acima do textarea — Cursor file pills */}
          <AnimatePresence>
          {attachedFiles.length > 0 && (
            <motion.div
              role="list"
              aria-label="Ficheiros anexados"
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              transition={{ duration: 0.15 }}
              className="mb-2 flex flex-wrap gap-1.5"
            >
              {attachedFiles.map((file, idx) => (
                <AttachmentChip key={`${file.name}-${idx}`} file={file} index={idx} onRemove={handleRemoveFile} />
              ))}
            </motion.div>
          )}
          </AnimatePresence>

          {/* Composer novo — rounded-2xl nx-elev-2, duas linhas */}
          <motion.div
            className={`nx-elev-2 relative flex flex-col gap-2 rounded-[22px] border border-nexus-border/80 bg-nexus-elevated px-3 pb-2.5 pt-3 shadow-[0_8px_32px_rgba(0,0,0,0.18)] transition-all focus-within:border-nexus-accent/45 focus-within:ring-2 focus-within:ring-nexus-accent/10 sm:px-4 ${
              isDraggingOver ? "border-nexus-accent" : ""
            }`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            {isDraggingOver && (
              <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-2xl border-2 border-dashed border-nexus-accent bg-nexus-panel/80 backdrop-blur-sm">
                <div className="flex items-center gap-2.5 rounded-xl border border-nexus-accent/40 bg-nexus-accent/10 px-4 py-2.5 text-sm font-medium text-nexus-accent">
                  <Paperclip className="h-4 w-4 shrink-0" />
                  Larga ficheiros de texto (máx. 5 · 50 KB cada)
                </div>
              </div>
            )}
            {/* Linha 1 — textarea auto-resize */}
            <textarea
              ref={inputRef}
              className="max-h-[160px] min-h-[52px] w-full resize-none bg-transparent px-1 py-1 text-[14px] leading-relaxed text-nexus-text placeholder:text-nexus-muted/70 outline-none"
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder={getChatComposerPlaceholder({ busyOtherSession, streaming })}
              aria-autocomplete="list"
              aria-controls={showCommands ? "slash-command-menu" : undefined}
              aria-haspopup={showCommands ? "listbox" : undefined}
              rows={1}
            />
            {streaming && (
              <div aria-live="polite" className="px-1 text-[11px] text-nexus-faint">
                A executar… Enter põe em fila como orientação
              </div>
            )}

            {/* @mentions autocomplete — glass, grouped */}
            {showMentions && filteredAgents.length > 0 && (
              <div className="nx-glass absolute bottom-full left-2 z-50 mb-2 max-h-64 w-64 overflow-y-auto thin-scrollbar rounded-xl p-1.5 shadow-xl">
                <div className="px-2 py-1 text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
                  Mencionar — @ficheiro @projeto @agente @db @memória @terminal
                </div>
                {filteredAgents.map((group) => (
                  <div key={group.group}>
                    <div className="px-2 pt-1.5 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
                      {group.group}
                    </div>
                    {group.items.map((item) => (
                      <button
                        key={item.name}
                        type="button"
                        onClick={() => insertMention(item.name)}
                        className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-xs text-nexus-text transition-colors hover:bg-nexus-accent/15"
                      >
                        <span className="font-mono font-medium text-nexus-accent">@{item.name}</span>
                        <span className="truncate text-[11px] text-nexus-muted">{item.hint}</span>
                      </button>
                    ))}
                  </div>
                ))}
              </div>
            )}

            {/* /command autocomplete — glass, grouped */}
            {showCommands && (
              <div
                id="slash-command-menu"
                data-testid="slash-command-menu"
                role="listbox"
                aria-label="Comandos de IA"
                className="nx-glass absolute bottom-full left-2 z-50 mb-2 max-h-72 w-[min(26rem,calc(100%-1rem))] overflow-y-auto thin-scrollbar rounded-xl p-1.5 shadow-xl"
              >
                <div className="flex items-center justify-between border-b border-nexus-border/60 px-2 py-1.5">
                  <span className="text-[10px] font-semibold uppercase tracking-wider text-nexus-muted">
                    Comandos de IA
                  </span>
                  <span className="text-[10px] text-nexus-muted">↑↓ navegar · Tab/Enter escolher · Esc fechar</span>
                </div>
                {commandsLoading && filteredCommands.length === 0 && (
                  <div className="px-3 py-3 text-xs text-nexus-muted">A carregar comandos…</div>
                )}
                {!commandsLoading && commandsError && filteredCommands.length === 0 && (
                  <div className="flex items-center justify-between gap-3 px-3 py-3">
                    <span className="text-xs text-amber-300">{commandsError}</span>
                    <button
                      type="button"
                      onClick={() => void advancedLoadCommands()}
                      className="shrink-0 rounded-md border border-nexus-border px-2 py-1 text-[10px] text-nexus-text hover:border-nexus-accent/50"
                    >
                      Tentar novamente
                    </button>
                  </div>
                )}
                {!commandsLoading && !commandsError && filteredCommands.length === 0 && (
                  <div className="px-3 py-3 text-xs text-nexus-muted">
                    Nenhum comando corresponde a “/{commandQuery}”.
                  </div>
                )}
                {(() => {
                  let globalIndex = -1;
                  return groupedCommands.map((group) => (
                    <div key={group.group}>
                      <div className="px-2 pt-2 pb-0.5 text-[10px] font-semibold uppercase tracking-wider text-nexus-faint">
                        {group.group}
                      </div>
                      {group.items.map(([modeId, info]) => {
                        globalIndex += 1;
                        const gi = globalIndex;
                        const mode = advancedModes[modeId];
                        const selected = gi === selectedCommandIndex;
                        return (
                          <button
                            key={modeId}
                            type="button"
                            role="option"
                            aria-selected={selected}
                            onMouseEnter={() => setSelectedCommandIndex(gi)}
                            onClick={() => insertCommand(info.aliases[0]?.replace(/^\//, "") || modeId)}
                            className={`mt-0.5 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-xs text-nexus-text transition-colors ${
                              selected ? "bg-nexus-accent/20" : "hover:bg-nexus-accent/10"
                            }`}
                          >
                            <span
                              className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-[10px] font-bold text-white"
                              style={{ backgroundColor: mode?.color || "#8B5CF6" }}
                            >
                              {mode?.icon === "infinity" ? "∞" : mode?.icon === "shield" ? "🛡" : mode?.icon === "hammer" ? "⚒" : mode?.icon === "layers" ? "◈" : mode?.icon === "git-branch" ? "↗" : mode?.icon === "check-circle" ? "✓" : mode?.icon === "flask" ? "⚗" : mode?.icon === "search" ? "🔍" : mode?.icon === "brain" ? "🧠" : mode?.icon === "eye" ? "👁" : mode?.icon?.[0]?.toUpperCase() || "∞"}
                            </span>
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-1.5">
                                <span className="font-medium text-nexus-accent">{info.aliases[0]}</span>
                                <span className="truncate text-nexus-muted">— {info.description}</span>
                              </div>
                              {info.aliases.length > 1 && (
                                <div className="mt-0.5 truncate text-[10px] text-nexus-faint">
                                  Também: {info.aliases.slice(1).join(", ")}
                                </div>
                              )}
                            </div>
                          </button>
                        );
                      })}
                    </div>
                  ));
                })()}
              </div>
            )}

            {/* Linha 2 — [+][@][/][Auto▾][Modelo▾] · [🎙][↑] */}
            <div className="flex items-center justify-between gap-2 border-t border-nexus-border/40 pt-2">
              <div className="flex min-w-0 items-center gap-1">
                <div ref={attachMenuRef} className="relative">
                  <button
                    type="button"
                    onClick={() => setAttachOpen((v) => !v)}
                    className="rounded-lg p-1.5 text-nexus-muted transition-colors hover:bg-nexus-bg/60 hover:text-nexus-text"
                    title="Anexar texto e contexto do projeto"
                    aria-label="Anexar"
                    aria-haspopup="menu"
                    aria-expanded={attachOpen}
                  >
                    <Plus className="h-4 w-4" />
                  </button>
                  {attachOpen && (
                    <div role="menu" aria-label="Anexar" className="nx-glass absolute bottom-full left-0 z-50 mb-2 w-56 rounded-xl p-1.5 shadow-xl">
                      {ATTACH_OPTIONS.map((opt) => {
                        const Icon = opt.icon;
                        return (
                          <button
                            key={opt.id}
                            type="button"
                            role="menuitem"
                            onClick={() => handleAttachOption(opt.id)}
                            className="flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left transition-colors hover:bg-nexus-accent/15"
                          >
                            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-nexus-accent/10 text-nexus-accent">
                              <Icon className="h-3.5 w-3.5" />
                            </span>
                            <span className="min-w-0 flex-1">
                              <span className="block text-xs font-medium text-nexus-text">{opt.label}</span>
                              <span className="block truncate text-[10px] text-nexus-muted">{opt.hint}</span>
                            </span>
                          </button>
                        );
                      })}
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setInput((prev) => (prev ? `${prev}@` : "@"));
                    requestAnimationFrame(() => inputRef.current?.focus());
                  }}
                  className="rounded-lg p-1.5 text-nexus-muted transition-colors hover:bg-nexus-bg/60 hover:text-nexus-text"
                  title="Mencionar (@ficheiro @projeto @agente @db @memória @terminal)"
                  aria-label="Mencionar"
                >
                  <AtSign className="h-4 w-4" />
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setInput((prev) => (prev ? prev : "/"));
                    setShowCommands(true);
                    requestAnimationFrame(() => inputRef.current?.focus());
                  }}
                  className="rounded-lg px-1.5 py-1 font-mono text-sm text-nexus-muted transition-colors hover:bg-nexus-bg/60 hover:text-nexus-text"
                  title="Comandos (/analyze /debug /plan /research /test /review /build)"
                  aria-label="Comandos"
                >
                  /
                </button>
                <span className="mx-0.5 h-4 w-px bg-nexus-border/70" aria-hidden="true" />
                <ModeDropdown />
                <ModelSelector />
                <span className="ml-1 hidden truncate text-[11px] text-nexus-faint xl:inline">/ para comandos · @ para ficheiros</span>
                <button
                  type="button"
                  onClick={() => {
                    const value = input.trim();
                    if (value) {
                      router.push(("/search?q=" + encodeURIComponent(value)) as any);
                    }
                  }}
                  disabled={!input.trim() || busyOtherSession}
                  className="rounded-lg p-1.5 text-nexus-muted transition-colors hover:bg-nexus-bg/60 hover:text-nexus-text disabled:cursor-not-allowed disabled:opacity-40"
                  title="Pesquisar na web"
                  aria-label="Web Search"
                >
                  <Search className="h-4 w-4" />
                </button>
              </div>
              <div className="flex shrink-0 items-center gap-1.5">
                <button
                  type="button"
                  onClick={startListening}
                  className={`rounded-lg p-2 transition-colors ${
                    isListening
                      ? "bg-red-500/10 text-red-400 animate-pulse"
                      : "text-nexus-muted hover:bg-nexus-bg/60 hover:text-nexus-text"
                  }`}
                  title={isListening ? "A ouvir... clica para parar" : "Input de voz (Web Speech API)"}
                  aria-label="Voice input"
                >
                  <Mic className="h-4 w-4" />
                </button>
                {streaming && (
                  <motion.button
                    type="button"
                    onClick={handleCancel}
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    className="shrink-0 rounded-xl bg-gradient-to-br from-red-500/20 to-red-500/10 p-2 text-red-400 hover:from-red-500/30 hover:to-red-500/20 transition-all duration-200 shadow-sm hover:shadow-red-500/20"
                    aria-label="Parar execução"
                    title="Parar execução"
                  >
                    <StopCircle className="h-4 w-4" />
                  </motion.button>
                )}
                <motion.button
                  type={streaming ? "button" : "submit"}
                  onClick={streaming ? () => void doSendMessage() : undefined}
                  disabled={isChatComposerSendDisabled({
                    input,
                    sessionId,
                    busyOtherSession,
                    planCreating,
                    streaming,
                  })}
                  whileHover={{ scale: input.trim() ? 1.05 : 1 }}
                  whileTap={{ scale: 0.92 }}
                  className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl text-white transition-all duration-200 shadow-sm ${
                    input.trim()
                      ? "bg-gradient-to-br from-nexus-accent to-nexus-accent/80 hover:shadow-nexus-accent/40 hover:from-nexus-accent hover:to-nexus-accent/90"
                      : "bg-nexus-accent/50 cursor-not-allowed opacity-40"
                  }`}
                  aria-label={streaming ? "Enviar orientação" : "Enviar mensagem"}
                  title={streaming ? "Enviar orientação ao run ativo (Enter)" : "Enviar mensagem (Enter · Shift+Enter newline)"}
                >
                  <ArrowUp className="h-4 w-4 pointer-events-none" />
                </motion.button>
              </div>
            </div>
          </motion.div>
        </form>

        <div className="mt-2 flex items-center justify-between gap-2 px-1 text-[10px] text-nexus-faint">
          <span>
            NEXUS IDE — Modo {currentMode} · {thinkingStrength === "low" ? "Rápido" : thinkingStrength === "medium" ? "Médio" : "Alto"} · {density}
          </span>
          <span className="hidden lg:inline">Enter envia · Shift+Enter nova linha</span>
          <motion.button
            type="button"
            onClick={handleRegenerate}
            disabled={!lastUserMessage || streaming}
            whileHover={{ scale: lastUserMessage && !streaming ? 1.03 : 1 }}
            whileTap={{ scale: 0.95 }}
            className="flex items-center gap-1 hover:text-nexus-text disabled:opacity-40 transition-all duration-200"
          >
            <RotateCcw className="h-3 w-3" />
            Regenerar
          </motion.button>
        </div>
      </div>
      </div>
      </div>

      {/* Search overlay (Ctrl/Cmd+F, scoped to this conversation) */}
      <AnimatePresence>
        {searchOpen && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            role="dialog"
            aria-modal="false"
            aria-label="Procurar nesta conversa"
            className="absolute left-3 right-3 top-20 z-50 rounded-xl border border-nexus-border bg-nexus-panel/95 p-3 shadow-2xl backdrop-blur-md sm:left-auto sm:right-4 sm:w-80"
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-nexus-muted">
                Procurar nas mensagens
              </span>
              <button
                type="button"
                onClick={() => setSearchOpen(false)}
                className="text-nexus-muted hover:text-nexus-text"
                title="Fechar (Esc)"
                aria-label="Fechar pesquisa na conversa"
              >
                <XCircle className="h-3.5 w-3.5" />
              </button>
            </div>
            <input
              aria-label="Procurar nas mensagens desta conversa"
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(event) => {
                if (!searchResults.length) return;
                if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                  event.preventDefault();
                  const direction = event.key === "ArrowDown" ? 1 : -1;
                  const nextIndex =
                    (safeActiveSearchResultIndex + direction + searchResults.length) % searchResults.length;
                  setActiveSearchResultId(searchResults[nextIndex]?.message.id ?? null);
                } else if (event.key === "Enter") {
                  event.preventDefault();
                  const activeResult = searchResults[safeActiveSearchResultIndex];
                  if (activeResult) void navigateToSearchResult(activeResult);
                }
              }}
              placeholder="Procurar neste histórico..."
              autoFocus
              aria-keyshortcuts="ArrowDown ArrowUp Enter Escape"
              className="w-full rounded border border-nexus-border bg-nexus-bg/40 px-2 py-1 text-sm text-nexus-text placeholder-nexus-muted outline-none focus:border-nexus-accent"
            />
            <div className="mt-2 flex items-center justify-between text-[11px] text-nexus-muted" role="status" aria-live="polite">
              {searchLoading ? (
                <span>
                  A pesquisar no histórico…{searchScannedPages > 0 ? ` ${searchScannedPages} páginas lidas` : ""}
                </span>
              ) : searchQuery.trim() ? (
                <span>{searchResults.length} resultado(s){searchError ? " · pesquisa parcial" : ""}</span>
              ) : (
                <span>Pesquisa todas as mensagens desta conversa</span>
              )}
              {searchResults.length > 0 && (
                <span aria-label={`Resultado ${safeActiveSearchResultIndex + 1} de ${searchResults.length}`}>
                  {safeActiveSearchResultIndex + 1}/{searchResults.length}
                </span>
              )}
            </div>
            {searchError && (
              <div role="alert" className="mt-2 rounded-md border border-amber-400/30 bg-amber-400/10 px-2 py-1.5 text-[11px] text-amber-200">
                A pesquisa ficou incompleta: {searchError}
              </div>
            )}
            {searchNavigationError && (
              <div role="alert" className="mt-2 rounded-md border border-rose-400/30 bg-rose-400/10 px-2 py-1.5 text-[11px] text-rose-200">
                {searchNavigationError}
              </div>
            )}
            {searchResults.length > 0 && (
              <div className="mt-2 max-h-56 space-y-1 overflow-y-auto" aria-label="Resultados da pesquisa">
                {visibleSearchResults.map((result, visibleIndex) => {
                  const m = result.message;
                  const q = searchQuery.trim().toLocaleLowerCase();
                  const pos = m.content?.toLocaleLowerCase().indexOf(q) ?? -1;
                  const rawSnippet = m.content?.slice(Math.max(0, pos - 32), pos + q.length + 52) ?? "";
                  const snippet = `${pos > 32 ? "…" : ""}${rawSnippet}${pos >= 0 && pos + q.length + 52 < (m.content?.length ?? 0) ? "…" : ""}`;
                  const resultIndex = searchResultWindowStart + visibleIndex;
                  const active = m.id === activeSearchResultId;
                  return (
                    <button
                      type="button"
                      key={m.id}
                      onMouseEnter={() => setActiveSearchResultId(m.id)}
                      onClick={() => void navigateToSearchResult(result)}
                      aria-label={`${m.role === "user" ? "Tu" : "NEXUS"}: ${snippet || "mensagem sem texto"}`}
                      aria-pressed={active}
                      className={`block w-full rounded-md border px-2 py-1.5 text-left text-[11px] transition-colors ${
                        active
                          ? "border-nexus-accent/30 bg-nexus-accent/15 text-nexus-accent"
                          : "border-transparent text-nexus-text hover:border-nexus-border hover:bg-nexus-bg/40"
                      }`}
                    >
                      <span className="mb-0.5 flex items-center justify-between gap-2 text-[9px] uppercase tracking-wide text-nexus-muted">
                        <span>{m.role === "user" ? "Tu" : "NEXUS"}</span>
                        <span>{resultIndex + 1}</span>
                      </span>
                      <span className="block line-clamp-2">{snippet || "(sem preview)"}</span>
                    </button>
                  );
                })}
              </div>
            )}
            {searchQuery.trim() && !searchLoading && !searchError && searchResults.length === 0 && (
              <div className="mt-3 rounded-md border border-nexus-border/60 px-2 py-3 text-center text-xs text-nexus-muted">
                Sem resultados nesta conversa.
              </div>
            )}
            <p className="mt-2 text-[10px] text-nexus-muted/80">
              Enter abre · ↑/↓ percorre resultados · Esc fecha · Ctrl/Cmd+K pesquisa global
            </p>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
    </ChatDensityContext.Provider>
  );
}
