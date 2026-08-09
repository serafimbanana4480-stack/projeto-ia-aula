"use client";
import { useMemo, useState, useEffect, useRef, useCallback, type ReactNode } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import { useAgentStream } from "../../hooks/useAgentStream";
import { useChatSessions } from "../../hooks/useChatSessions";
import { useToast } from "./Toast";
import { ApiError, getSessionHistory, getSessionRuns, createPlan, approvePlan, executePlan, getPlanStatus, cancelPlan, getProvidersStatus } from "../../lib/api";
import type { PlanCreateResult, PlanStatus as PlanStatusType } from "../../lib/api";
import { useModeStore, type Mode } from "../../stores/modeStore";
import { useModelStore } from "../../stores/modelStore";
import { useProjectStore } from "../../stores/projectStore";
import { useThemeStore } from "../../stores/themeStore";
import { useKeyboardShortcuts } from "../../hooks/useKeyboardShortcuts";
import MessageBubble from "./MessageBubble";
import BackgroundAgentsPanel from "./BackgroundAgentsPanel";
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
  Send,
  StopCircle,
  RotateCcw,
  Check,
  Play,
  CheckCircle2,
  XCircle,
  Clock,
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
} from "lucide-react";
import type { AgentName, ChatMessage, StreamEvent } from "../../lib/types";
import { log } from "../../lib/log";
import { stripAnsiCodes } from "../../lib/utils";
import {
  activityFromProgress,
  activityFromMissionEvent,
  agentActivity,
  sanitizeAssistantContent,
} from "../../lib/chatPresentation";

interface ChatPanelProps {
  rightOpen?: boolean;
  setRightOpen?: (open: boolean) => void;
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

/** Fold the raw SSE event stream into an ordered list of ChatMessages. */
  function foldEvents(
    pendingUser: ChatMessage[],
    events: StreamEvent[],
    lastUserMessage: string = "",
  ): ChatMessage[] {
    const out: ChatMessage[] = [...pendingUser];
    let current: ChatMessage | null = null;
    // Track the latest agent_started so we can attach tool calls
    // that arrive without a fresh agent_started (e.g. legacy events).
    let currentAgent: AgentName = "CODER";
    let lastThinkingIteration = 0;

    const ensureCurrent = (event: StreamEvent) => {
      if (current) return current;
      current = {
        id: `a-${out.length}-${event.timestamp}`,
        role: "assistant",
        agent: currentAgent,
        content: "",
        timestamp: event.timestamp,
        toolCalls: [],
        activities: [],
      };
      out.push(current);
      return current;
    };

    const upsertActivity = (activity: NonNullable<ChatMessage["activities"]>[number]) => {
      const message = ensureCurrent({ type: "progress", timestamp: activity.timestamp });
      message.activities = message.activities || [];
      const existing = message.activities.findIndex((item) => item.id === activity.id);
      if (existing >= 0) {
        const previous = message.activities[existing];
        message.activities[existing] = {
          ...previous,
          ...activity,
          detail: activity.detail ?? previous.detail,
        };
      } else {
        message.activities.push(activity);
      }
    };

    const findRunningTool = (name?: string) => {
      if (!current?.toolCalls) return -1;
      const calls = current.toolCalls;
      for (let i = calls.length - 1; i >= 0; i--) {
        if (calls[i].status !== "running") continue;
        if (!name || calls[i].name === name) return i;
      }
      return -1;
    };

    for (const e of events) {
      switch (e.type) {
        case "agent_started": {
          currentAgent = (e.agent ?? "CODER") as AgentName;
          const message = ensureCurrent(e);
          if (!message.agent || message.agent === "CODER") message.agent = currentAgent;
          upsertActivity(agentActivity(e, out.length, "running"));
          break;
        }
        case "token": {
          // Skip if this is an embedded thinking iteration marker
          if (e.content && e.content.startsWith("<event>thinking|iteration:")) {
            break;
          }
          ensureCurrent(e).content += e.content ?? "";
          break;
        }
        case "thinking": {
          // Parse iteration number to detect and skip duplicates
          const iterMatch = (e.content ?? "").match(/thinking\|iteration:(\d+)/);
          if (iterMatch) {
            const iteration = parseInt(iterMatch[1], 10);
            if (iteration <= lastThinkingIteration) {
              break; // Skip duplicate thinking iteration marker
            }
            lastThinkingIteration = iteration;
          }
          const message = ensureCurrent(e);
          const separator = message.thinking && e.content ? "\n" : "";
          message.thinking = (message.thinking ?? "") + separator + (e.content ?? "");
          break;
        }
        case "tool_call": {
          current = ensureCurrent(e);
          current.toolCalls = current.toolCalls || [];
          current.toolCalls.push({
            id: `tc-${current.toolCalls.length}-${e.timestamp}`,
            name: e.tool_name || "tool",
            args: e.tool_args || {},
            status: "running",
            timestamp: e.timestamp,
          });
          break;
        }
        case "progress": {
          upsertActivity(activityFromProgress(e, out.length));
          break;
        }
        case "mission_brief":
        case "mission_plan":
        case "mission_wave":
        case "mission_agent":
        case "mission_decision":
        case "mission_verification":
        case "mission_completed": {
          upsertActivity(activityFromMissionEvent(e, out.length));
          break;
        }
        case "tool_result": {
          const idx = findRunningTool(e.tool_name);
          if (idx >= 0 && current) {
            current.toolCalls![idx].status = "success";
            current.toolCalls![idx].result = e.tool_result;
            const duration = e.data?.duration_ms;
            if (typeof duration === "number") current.toolCalls![idx].durationMs = duration;
          }
          break;
        }
        case "tool_error": {
          const idx = findRunningTool(e.tool_name);
          if (idx >= 0 && current) {
            current.toolCalls![idx].status = "error";
            current.toolCalls![idx].error = e.tool_error;
          }
          break;
        }
        case "tool_confirmation": {
          const idx = findRunningTool(e.tool_name);
          if (idx >= 0 && current) {
            const confirmation = e.data ?? {};
            current.toolCalls![idx].status = "awaiting_confirmation";
            current.toolCalls![idx].confirmationId = String(confirmation.confirmation_id ?? "");
            current.toolCalls![idx].suggestion = String(confirmation.suggestion ?? "");
            current.toolCalls![idx].riskLevel = String(confirmation.risk_level ?? "medium");
          }
          break;
        }
        case "metric": {
          current = ensureCurrent(e);
          const usage = e.data?.usage;
          if (usage && typeof usage === "object") {
            const u = usage as Record<string, unknown>;
            current.metrics = {
              "Input": String(u.input_tokens ?? 0),
              "Output": String(u.output_tokens ?? 0),
              "Raciocínio": String(u.reasoning_tokens ?? 0),
              "Total": String(u.total_tokens ?? 0),
            };
          }
          break;
        }
        case "error": {
          out.push({
            id: `err-${out.length}-${e.timestamp}`,
            role: "assistant",
            agent: "CODER",
            content: `⚠ ${e.content || "Erro desconhecido (sem mensagem do servidor)"}`,
            timestamp: e.timestamp,
            metadata: { kind: "error", canRetry: true, prompt: lastUserMessage },
          });
          current = null;
          break;
        }
        case "routing": {
          // Routing decisions are metadata; ignore null content. The user
          // will see the agent badge on the first token event.
          break;
        }
        case "agent_finished": {
          upsertActivity(agentActivity(e, out.length, "success"));
          break;
        }
        case "done": {
          current = null;
          break;
        }
        default:
          break;
      }
    }

  const extractThinking = (text: string) => {
    const thinkingParts: string[] = [];
    const cleaned = text.replace(/<thinking>([\s\S]*?)<\/thinking>/g, (_, inner) => {
      thinkingParts.push(inner.trim());
      return "";
    });
    return {
      content: cleaned.trim(),
      thinking: thinkingParts.length > 0 ? thinkingParts.join("\n\n---\n\n") : undefined,
    };
  };

  for (const m of out) {
    if (m.content) {
      m.content = sanitizeAssistantContent(stripAnsiCodes(m.content));
      const { content, thinking } = extractThinking(m.content);
      m.content = content;
      if (thinking) m.thinking = thinking;
    }
  }

  return out;
}

export default function ChatPanel({
  rightOpen = true,
  setRightOpen,
}: ChatPanelProps) {
  const [sessionId, setSessionId] = useState<string>("default");
  const sessions = useChatSessions();
  const toast = useToast();
  const { currentMode, modes, modesLoaded, loadModes } = useModeStore();
  const { activeModel, activeProvider, modelsLoaded, loadModels } = useModelStore();
  const { currentProject } = useProjectStore();
  const router = useRouter();
  const searchParams = useSearchParams();
  // The chosen model id is sent to /api/chat as-is. A hardcoded
  // MODEL_TO_TIER map used to translate it to a router tier first, so the
  // backend resolved that tier through config/models.yaml and ran a
  // *different* model than the one shown in the UI. `/api/chat` now accepts
  // concrete provider model ids; "" still means auto-route.

  const { events, streaming, error: streamError, send, resume, cancel, reset } = useAgentStream(sessionId);
  const [input, setInput] = useState("");
  const [historyMessages, setHistoryMessages] = useState<ChatMessage[]>([]);
  const [pendingUser, setPendingUser] = useState<ChatMessage[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
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
  const [searchResults, setSearchResults] = useState<number[]>([]);
  const [searchIdx, setSearchIdx] = useState(0);
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
  const fileInputRef = useRef<HTMLInputElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [activePlan, setActivePlan] = useState<PlanCreateResult | null>(null);
  const [planStatus, setPlanStatus] = useState<PlanStatusType | null>(null);
  const [planExecuting, setPlanExecuting] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [backendOffline, setBackendOffline] = useState(false);
  const [demoMode, setDemoMode] = useState(false);
  const errorLoggedRef = useRef(false);
  const planPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastUserMessageRef = useRef<string>("");

  // The dashboard can hand off a prompt through the URL. Pre-fill it without
  // replacing anything the user has already started typing.
  useEffect(() => {
    const prompt = searchParams.get("prompt")?.trim();
    if (prompt) setInput((current) => current || prompt);
  }, [searchParams]);

  // Sync the session list's currentId with local sessionId state
  useEffect(() => {
    if (sessions.currentId && sessions.currentId !== sessionId) {
      setSessionId(sessions.currentId);
    }
  }, [sessions.currentId]);

  // Push stream / history errors to the global toast so they don't disappear
  useEffect(() => {
    if (streamError) {
      toast.error("Falha no chat", streamError, undefined);
    }
  }, [streamError]);
  useEffect(() => {
    if (historyError) {
      toast.error("Não foi possível carregar o histórico", historyError, undefined);
    }
  }, [historyError]);

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
      events.some(
        (e) =>
          e.type === "token" &&
          typeof e.content === "string" &&
          e.content.includes("MODO DEMO"),
      )
    ) {
      setDemoMode(true);
    }
  }, [events]);


  useEffect(() => {
    localStorage.setItem("nexus.thinkingStrength", thinkingStrength);
  }, [thinkingStrength]);

  const loadHistory = useCallback(async () => {
    try {
      setHistoryError(null);
      const history = await getSessionHistory(sessionId);
      const normalized = history.map((msg, index) => ({
        ...msg,
        id: `${msg.role}-${index}-${msg.timestamp}`,
        content:
          msg.role === "assistant"
            ? sanitizeAssistantContent(stripAnsiCodes(msg.content))
            : stripAnsiCodes(msg.content),
      }));
      setHistoryMessages(normalized);
      setPendingUser([]);
      reset();
      setHistoryLoaded(true);
      setBackendOffline(false);
      errorLoggedRef.current = false;
    } catch (error) {
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
      setHistoryLoaded(true);
    }
  }, [sessionId, reset]);

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
    if (!historyLoaded || streaming) return;
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
  }, [historyLoaded, sessionId, resume, streaming]);

  const { toggleTheme } = useThemeStore();

  async function composeMessageWithAttachments(
    message: string,
    files: File[],
  ): Promise<string> {
    if (files.length === 0) return message;
    const parts: string[] = [];
    for (const file of files) {
      if (file.size > 50 * 1024) {
        parts.push(`\n---\n[Anexo: ${file.name} — ${(file.size / 1024).toFixed(0)}KB (ficheiro demasiado grande para incluir)]\n---\n`);
        continue;
      }
      const isText = file.type.startsWith("text/") ||
        file.name.match(/\.(txt|md|py|js|ts|tsx|jsx|json|yaml|yml|toml|css|scss|html|xml|csv|sql|sh|bat|ps1|ini|cfg|env|gitignore|dockerfile)$/i);
      if (!isText) {
        parts.push(`\n---\n[Anexo: ${file.name} — ${(file.size / 1024).toFixed(0)}KB (tipo ${file.type || "binário"})]\n---\n`);
        continue;
      }
      try {
        const text = await file.text();
        parts.push(`\n---\n[Anexo: ${file.name}]\n\n\`\`\`\n${stripAnsiCodes(text)}\n\`\`\`\n---\n`);
      } catch {
        parts.push(`\n---\n[Anexo: ${file.name} — erro ao ler conteúdo]\n---\n`);
      }
    }
    return `${message}\n${parts.join("\n")}`;
  }

  const doSendMessage = async () => {
    const trimmed = input.trim();
    if (!trimmed || streaming) return;
    const hasAttachments = attachedFiles.length > 0;
    const displayContent = hasAttachments
      ? `${trimmed}\n\n[${attachedFiles.length} ficheiro(s) anexado(s): ${attachedFiles.map(f => f.name).join(", ")}]`
      : trimmed;
    lastUserMessageRef.current = trimmed;
    const pendingUserMessage: ChatMessage = {
      id: `u-${pendingUser.length}-${Date.now()}`,
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
      const projectPath = currentProject?.path || ".";
      await send(messageToSend, currentMode, activeModel, projectPath, thinkingStrength, undefined, activeProvider);
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
    // Reuse same validation as picker: max 5, 50KB each
    const valid: File[] = [];
    for (const f of files) {
      if (attachedFiles.length + valid.length >= 5) break;
      if (f.size > 50_000) continue; // skip oversized
      valid.push(f);
    }
    if (valid.length) setAttachedFiles((prev) => [...prev, ...valid]);
  };

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

  // Filter agents based on mention query
  const filteredAgents = useMemo(() => {
    if (!showMentions) return [];
    const agents = ["auto", "coder", "analyzer", "architect", "reviewer", "debugger", "researcher", "optimizer"];
    const q = mentionQuery.toLowerCase();
    return agents.filter((a) => a.startsWith(q));
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

  // -----------------------------------------------------------------------
  // Search within messages (Ctrl+K)
  // -----------------------------------------------------------------------
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      } else if (e.key === "Escape" && searchOpen) {
        setSearchOpen(false);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [searchOpen]);

  useEffect(() => {
    if (!searchQuery) {
      setSearchResults([]);
      return;
    }
    const q = searchQuery.toLowerCase();
    const results: number[] = [];
    (historyMessages || []).forEach((m, i) => {
      if (m.content?.toLowerCase().includes(q)) results.push(i);
    });
    setSearchResults(results);
    setSearchIdx(0);
  }, [searchQuery, historyMessages]);

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

  const messages = useMemo(
    () => [
      ...historyMessages,
      ...foldEvents(pendingUser, events, lastUserMessageRef.current),
    ],
    [historyMessages, pendingUser, events],
  );

  // True while streaming but before the first token/thinking event arrives.
  const waitingForFirstToken =
    streaming &&
    !events.some(
      (e) => (e.type === "token" || e.type === "thinking") && e.content,
    );

  // Most recent meaningful streaming status, scanned from the end of the event list.
  const streamStatus = useMemo<string | null>(() => {
    if (!streaming) return null;
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i];
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
  }, [streaming, events]);

  const messagesContainerRef = useRef<HTMLDivElement>(null);
  const previousMessagesLength = useRef(messages.length);
  const userScrolledUp = useRef(false);

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    const isNewMessageAdded = messages.length > previousMessagesLength.current;
    previousMessagesLength.current = messages.length;

    if (!isNewMessageAdded) return;

    const isNearBottom =
      container.scrollHeight - container.scrollTop - container.clientHeight < 100;

    if (!userScrolledUp.current || isNearBottom) {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages]);

  useEffect(() => {
    const container = messagesContainerRef.current;
    if (!container) return;

    const handleScroll = () => {
      const isNearBottom =
        container.scrollHeight - container.scrollTop - container.clientHeight < 100;
      userScrolledUp.current = !isNearBottom;
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

  // Edit a user message: replace its content and regenerate the assistant response
  function handleEditMessage(messageId: string, newContent: string) {
    setHistoryMessages((prev) => prev.map((m) => (m.id === messageId ? { ...m, content: newContent } : m)));
    setInput(newContent);
    toast.info("Mensagem editada. Reenvia para regenerar a resposta.");
  }

  // Regenerate the assistant response for a given message
  async function handleRegenerateMessage(messageId: string) {
    // Find the previous user message
    const idx = historyMessages.findIndex((m) => m.id === messageId);
    if (idx < 1) {
      toast.error("Não foi possível regenerar");
      return;
    }
    const prev = historyMessages[idx - 1];
    if (prev.role !== "user") {
      toast.error("Apenas é possível regenerar a partir de uma mensagem do utilizador");
      return;
    }
    // Remove everything after the user message
    const newHistory = historyMessages.slice(0, idx - 1);
    setHistoryMessages(newHistory);
    setInput(prev.content);
    toast.info("Pronto. Envia para regenerar a resposta.");
  }

  function handleFileSelect(e: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files || []);
    if (files.length > 0) {
      setAttachedFiles((prev) => [...prev, ...files].slice(0, 5));
    }
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
    void send(last, currentMode, activeModel, projectPath, thinkingStrength, undefined, activeProvider).then(() => loadHistory());
  }

  // Retry the prompt from an error bubble (passed to MessageBubble)
  const handleRetryFromError = useCallback(
    (prompt: string) => {
      if (streaming || !prompt.trim()) return;
      setInput(prompt);
      toast.info("Mensagem pronta para reenvio", "Clique em Enviar para tentar novamente");
    },
    [streaming, toast],
  );

  async function handleNewChat() {
    const title = `Chat ${new Date().toLocaleString("pt-PT")}`;
    const created = await sessions.create(title, currentMode);
    if (created) {
      sessions.setCurrentId(created.id);
      setSessionId(created.id);
    }
    setHistoryMessages([]);
    setPendingUser([]);
    setHistoryLoaded(true);
    setHistoryError(null);
    reset();
    toast.info("Nova sessão criada", created?.title);
  }

  function handleShare() {
    const allMessages = [
      ...historyMessages,
      ...foldEvents(pendingUser, events),
    ];
    if (allMessages.length === 0) return;
    const text = allMessages
      .map((m) => `[${m.role}] ${m.content}`)
      .join("\n\n");
    navigator.clipboard.writeText(text);
    setShared(true);
    setTimeout(() => setShared(false), 2000);
  }

  const startPlanExecution = useCallback(async (planId: string) => {
    if (planExecuting) return;
    setPlanError(null);
    setPlanExecuting(true);
    try {
      await executePlan(planId, sessionId, currentProject?.path || ".");
      planPollRef.current = setInterval(async () => {
        try {
          const status = await getPlanStatus(planId);
          setPlanStatus(status);
          if (["completed", "failed", "cancelled"].includes(status.status)) {
            if (planPollRef.current) clearInterval(planPollRef.current);
            setPlanExecuting(false);
          }
        } catch {
          if (planPollRef.current) clearInterval(planPollRef.current);
          setPlanExecuting(false);
        }
      }, 2000);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to execute plan";
      setPlanError(msg);
      setPlanExecuting(false);
      log.error("Failed to execute plan:", err);
    }
  }, [currentProject?.path, planExecuting, sessionId]);

  const handlePlanCreate = useCallback(async (objective: string) => {
    setPlanError(null);
    try {
      const plan = await createPlan(objective, sessionId);
      setActivePlan(plan);
      const status = await getPlanStatus(plan.plan_id);
      setPlanStatus(status);
      // Plan mode is an autonomous workflow by default. The legacy approve
      // endpoint remains available for callers that explicitly request
      // manual approval, but the UI must not strand a plan waiting for a click.
      if (status.approved && !["completed", "failed", "cancelled"].includes(status.status)) {
        void startPlanExecution(plan.plan_id);
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to create plan";
      setPlanError(msg);
      log.error("Failed to create plan:", err);
    }
  }, [sessionId, startPlanExecution]);

  const handlePlanApprove = useCallback(async () => {
    if (!activePlan) return;
    setPlanError(null);
    try {
      await approvePlan(activePlan.plan_id, sessionId);
      const status = await getPlanStatus(activePlan.plan_id);
      setPlanStatus(status);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to approve plan";
      setPlanError(msg);
      log.error("Failed to approve plan:", err);
    }
  }, [activePlan, sessionId]);

  const handlePlanExecute = useCallback(async () => {
    if (!activePlan || planExecuting) return;
    await startPlanExecution(activePlan.plan_id);
  }, [activePlan, planExecuting, startPlanExecution]);

  const handlePlanCancel = useCallback(async () => {
    try {
      await cancelPlan(sessionId);
      setActivePlan(null);
      setPlanStatus(null);
      setPlanExecuting(false);
      if (planPollRef.current) clearInterval(planPollRef.current);
    } catch (err) {
      log.error("Failed to cancel plan:", err);
    }
  }, [sessionId]);

  useEffect(() => {
    return () => {
      if (planPollRef.current) clearInterval(planPollRef.current);
    };
  }, []);

  useEffect(() => {
    if (currentMode === "plan" && activePlan === null && messages.length > 0) {
      const lastUser = [...messages].reverse().find((m) => m.role === "user");
      if (lastUser) {
        handlePlanCreate(lastUser.content);
      }
    }
  }, [currentMode, messages, activePlan, handlePlanCreate]);

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
    <div className="relative flex h-full" data-testid="ai-cockpit">
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
      {/* Chat header */}
      <div className="flex shrink-0 items-center justify-between border-b border-nexus-border px-5 py-2.5">
        <div className="flex items-center gap-2.5">
          <motion.button
            type="button"
            whileTap={{ scale: 0.95 }}
            onClick={() => setSidebarCollapsed(false)}
            className="flex items-center gap-1.5 rounded-lg border border-nexus-border bg-nexus-card px-2.5 py-1.5 text-xs font-medium text-nexus-muted transition-colors hover:border-nexus-accent/30 hover:text-nexus-text"
            title="Abrir sessões"
            aria-label="Abrir sessões"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Conversas</span>
            <span className="rounded-full bg-nexus-bg/70 px-1.5 py-0.5 font-mono text-[10px] tabular-nums">
              {sessions.sessions.length}
            </span>
          </motion.button>
          <motion.div
            whileHover={{ scale: 1.05, rotate: -3 }}
            whileTap={{ scale: 0.95 }}
            className="flex h-6 w-6 items-center justify-center rounded-md bg-nexus-accent/15 text-nexus-accent cursor-default"
          >
            <Sparkles className="h-3.5 w-3.5" />
          </motion.div>
          <div className="min-w-0 leading-tight">
            <h1 className="text-sm font-semibold text-nexus-text">Chat</h1>
            {/* This line was hardcoded to the "no project" warning, so it
                showed even with a project open. Reflect the real state. */}
            <div className="truncate text-[11px] text-nexus-muted">
              {currentProject?.name
                ? currentProject.name
                : "Sem projeto ativo — seleciona um projeto para usar ferramentas"}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Mode selector */}
          <motion.div
            whileTap={{ scale: 0.97 }}
            className="flex items-center rounded-lg border border-nexus-border bg-nexus-card p-0.5"
          >
            {(modesLoaded ? modes : ([{ id: currentMode }] as Mode[])).map((mode) => {
              const cfg = MODE_CONFIG[mode.id] || {
                icon: Sparkles,
                label: mode.id,
                color: "text-nexus-muted bg-transparent border-transparent",
              };
              const Icon = cfg.icon;
              const active = mode.id === currentMode;
              return (
                <motion.button
                  key={mode.id}
                  type="button"
                  onClick={() => useModeStore.getState().setMode(mode.id)}
                  title={mode.description || cfg.label}
                  whileTap={{ scale: 0.9 }}
                  className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-all duration-200 ${
                    active
                      ? `${cfg.color} border shadow-sm`
                      : "text-nexus-muted hover:text-nexus-text hover:bg-nexus-bg border border-transparent"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  <span className="hidden sm:inline">{cfg.label}</span>
                </motion.button>
              );
            })}
          </motion.div>

          {/* Advanced mode indicator + toggle */}
          <AdvancedModeHeaderIndicator />

          {/* Model selector — search, provider grouping, price/context */}
          <ModelSelector />

          {/* Thinking strength selector */}
          <motion.div
            whileTap={{ scale: 0.97 }}
            className="flex items-center rounded-lg border border-nexus-border bg-nexus-card p-0.5"
          >
            {THINKING_STRENGTH_OPTIONS.map((option) => {
              const Icon = option.icon;
              const isActive = thinkingStrength === option.value;
              return (
                <motion.button
                  key={option.value}
                  type="button"
                  onClick={() => setThinkingStrength(option.value)}
                  title={option.description}
                  whileTap={{ scale: 0.9 }}
                  className={`flex items-center gap-1 rounded-md px-2 py-1.5 text-[11px] font-medium transition-all duration-200 ${
                    isActive
                      ? "bg-nexus-accent/15 text-nexus-accent border border-nexus-accent/30 shadow-sm shadow-nexus-accent/10"
                      : "text-nexus-muted hover:text-nexus-text border border-transparent"
                  }`}
                >
                  <Icon className="h-3 w-3" />
                  <span className="hidden sm:inline">{option.label}</span>
                </motion.button>
              );
            })}
          </motion.div>

          <motion.button
            whileHover={{ scale: 1.03 }}
            whileTap={{ scale: 0.95 }}
            onClick={handleNewChat}
            className="flex items-center gap-1.5 rounded-lg border border-nexus-border bg-nexus-card px-3 py-1.5 text-xs text-nexus-muted hover:text-nexus-text transition-all duration-200 hover:border-nexus-accent/30"
          >
            <Plus className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Novo Chat</span>
          </motion.button>
          <motion.button
            whileHover={{ scale: 1.05 }}
            whileTap={{ scale: 0.9 }}
            onClick={handleShare}
            className="rounded-lg border border-nexus-border bg-nexus-card p-1.5 text-nexus-muted hover:text-nexus-text transition-all duration-200 hover:border-nexus-accent/30"
            title="Copiar conversação"
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
            onClick={() => setRightOpen?.(!rightOpen)}
            className="rounded-lg border border-nexus-border bg-nexus-card p-1.5 text-nexus-muted hover:text-nexus-text transition-all duration-200 hover:border-nexus-accent/30"
            title="Toggle painel direito"
          >
            {rightOpen ? (
              <PanelRightClose className="h-3.5 w-3.5" />
            ) : (
              <PanelRightOpen className="h-3.5 w-3.5" />
            )}
          </motion.button>
        </div>
      </div>

      {/* Messages area */}
      <div
        ref={messagesContainerRef}
        data-testid="messages"
        aria-label="Histórico da conversa"
        className="min-h-0 flex-1 overflow-y-auto thin-scrollbar px-5 py-3"
        style={{
          background: "linear-gradient(180deg, rgba(13,17,28,0) 0%, rgba(13,17,28,0.4) 50%, rgba(13,17,28,0) 100%)",
        }}
      >
        {/* Stream error banner */}
        {streamError && (
          <div className="mb-3 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2">
            <div className="flex items-center gap-2 text-xs text-red-400">
              <AlertTriangle className="h-3.5 w-3.5" />
              <span>{streamError}</span>
            </div>
          </div>
        )}

        {!historyLoaded && (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3 text-sm text-nexus-muted">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-nexus-accent border-t-transparent" />
              <span>A carregar conversação...</span>
            </div>
          </div>
        )}

        {historyError && historyLoaded && (
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

        {messages.length === 0 && historyLoaded && !historyError && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="flex h-full flex-col items-center justify-center text-center"
          >
            <motion.div
              animate={{
                scale: [1, 1.08, 1],
                opacity: [0.7, 1, 0.7],
              }}
              transition={{
                duration: 3,
                repeat: Infinity,
                ease: "easeInOut",
              }}
              className="mb-6 flex h-16 w-16 items-center justify-center rounded-2xl bg-gradient-to-br from-nexus-accent/15 to-nexus-accent/5 text-nexus-accent shadow-lg shadow-nexus-accent/10"
            >
              <Sparkles className="h-8 w-8" />
            </motion.div>
            <h2 className="mb-2 text-xl font-bold tracking-tight text-nexus-text">NEXUS IDE</h2>
            <p className="mb-8 max-w-xs text-sm text-nexus-muted leading-relaxed">
              Pergunte, analise, crie. A sua IA, os seus dados.
            </p>
            <div className="grid w-full max-w-md grid-cols-2 gap-2.5">
              {suggestions.map((s) => (
                <motion.button
                  key={s.label}
                  onClick={() => setInput(s.prompt)}
                  whileHover={{ scale: 1.03, y: -2 }}
                  whileTap={{ scale: 0.97 }}
                  className="group flex items-center gap-2.5 rounded-xl border border-nexus-border bg-nexus-card/80 px-4 py-3 text-left text-xs text-nexus-muted transition-all duration-200 hover:border-nexus-accent/40 hover:text-nexus-text hover:shadow-md hover:shadow-nexus-accent/10"
                >
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-nexus-accent/10 text-nexus-accent/70 transition-colors group-hover:bg-nexus-accent/20 group-hover:text-nexus-accent">
                    {s.icon}
                  </span>
                  <span className="font-medium">{s.label}</span>
                </motion.button>
              ))}
            </div>
          </motion.div>
        )}

        {/* Plan Execution Panel */}
        {currentMode === "plan" && activePlan && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className="mb-4 rounded-xl border border-nexus-accent/30 bg-nexus-accent/5 p-4"
          >
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ListChecks className="h-4 w-4 text-nexus-accent" />
                <span className="text-sm font-semibold text-nexus-accent">
                  Plano autónomo
                </span>
                {planStatus && (
                  <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${
                    planStatus.status === "completed" ? "bg-green-500/20 text-green-400" :
                    planStatus.status === "failed" ? "bg-red-500/20 text-red-400" :
                    planStatus.status === "executing" ? "bg-blue-500/20 text-blue-400" :
                    planStatus.status === "awaiting_approval" ? "bg-yellow-500/20 text-yellow-400" :
                    "bg-nexus-border text-nexus-muted"
                  }`}>
                    {planStatus.status.replace("_", " ")}
                  </span>
                )}
              </div>
              {planError && (
                <div className="rounded-lg bg-red-500/10 px-3 py-2 text-xs text-red-400">
                  {planError}
                </div>
              )}
              <div className="flex items-center gap-2">
                {planStatus?.status === "awaiting_approval" && (
                  <button
                    onClick={handlePlanApprove}
                    className="flex items-center gap-1 rounded-lg bg-green-500/20 px-3 py-1.5 text-xs font-medium text-green-400 hover:bg-green-500/30 transition-colors"
                  >
                    <CheckCircle2 className="h-3.5 w-3.5" />
                    Approve
                  </button>
                )}
                {(planStatus?.status === "awaiting_approval" || planStatus?.approved) && !planExecuting && planStatus?.status !== "completed" && planStatus?.status !== "failed" && (
                  <button
                    onClick={handlePlanExecute}
                    className="flex items-center gap-1 rounded-lg bg-nexus-accent/20 px-3 py-1.5 text-xs font-medium text-nexus-accent hover:bg-nexus-accent/30 transition-colors"
                  >
                    <Play className="h-3.5 w-3.5" />
                    Execute
                  </button>
                )}
                {planExecuting && (
                  <button
                    onClick={handlePlanCancel}
                    className="flex items-center gap-1 rounded-lg bg-red-500/20 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-500/30 transition-colors"
                  >
                    <XCircle className="h-3.5 w-3.5" />
                    Cancel
                  </button>
                )}
              </div>
            </div>

            <div className="space-y-2">
              {activePlan.steps?.map((step, idx) => {
                const stepStatus = planStatus?.steps?.find(s => s.task_id === step.task_id)?.status || "pending";
                return (
                  <div
                    key={step.task_id || idx}
                    className="flex items-start gap-3 rounded-lg border border-nexus-border/50 bg-nexus-card/50 p-2.5"
                  >
                    <div className="mt-0.5">
                      {stepStatus === "completed" ? (
                        <CheckCircle2 className="h-4 w-4 text-green-400" />
                      ) : stepStatus === "running" ? (
                        <Loader2 className="h-4 w-4 animate-spin text-blue-400" />
                      ) : stepStatus === "failed" ? (
                        <XCircle className="h-4 w-4 text-red-400" />
                      ) : (
                        <Clock className="h-4 w-4 text-nexus-muted" />
                      )}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="text-xs font-medium text-nexus-text">
                          Step {idx + 1}: {step.name}
                        </span>
                        <span className="rounded bg-nexus-border/50 px-1.5 py-0.5 text-[10px] text-nexus-muted">
                          {step.agent}
                        </span>
                      </div>
                      {step.description && (
                        <p className="mt-0.5 text-[11px] text-nexus-muted line-clamp-2">
                          {step.description}
                        </p>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {planStatus && planStatus.total_steps > 0 && (
              <div className="mt-3 flex items-center gap-4 text-[11px] text-nexus-muted">
                <span>Total: {planStatus.total_steps} steps</span>
                <span>Completed: {planStatus.steps?.filter(s => s.status === "completed").length || 0}</span>
                <span>Failed: {planStatus.steps?.filter(s => s.status === "failed").length || 0}</span>
              </div>
            )}
          </motion.div>
        )}

        <VirtualMessageList
          messages={messages}
          renderItem={(m, idx) => (
            <MessageBubble
              key={m.id}
              message={m}
              sessionId={sessionId}
              isStreaming={streaming && idx === messages.length - 1}
              onRetry={handleRetryFromError}
              onEdit={handleEditMessage}
              onRegenerate={handleRegenerateMessage}
            />
          )}
          initialLimit={50}
          className="space-y-4"
        />
        <div ref={messagesEndRef} />

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

      {/* Input area — fixed at bottom */}
      <div className="shrink-0 border-t border-nexus-border bg-nexus-panel px-5 pt-3 pb-2">
        <BackgroundAgentsPanel sessionId={sessionId} onCompleted={loadHistory} />
        {/* Live streaming-status pill */}
        {streamStatus && (
          <div className="mb-2 flex justify-start">
            <span className="rounded-full border border-nexus-border bg-nexus-card px-2 py-0.5 text-[10px] text-nexus-muted">
              {streamStatus}
            </span>
          </div>
        )}

        {/* Backend offline indicator */}
        {backendOffline && (
          <div className="mb-2 flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs text-red-400">
            <WifiOff className="h-3.5 w-3.5 shrink-0" />
            <span className="font-medium">Backend offline</span>
            <span className="text-red-300">— Aguardando reconexão para enviar mensagens.</span>
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
            onChange={handleFileSelect}
            className="hidden"
          />

          {/* Attached files preview */}
          <AnimatePresence>
          {attachedFiles.length > 0 && (
            <motion.div
              initial={{ opacity: 0, height: 0 }}
              animate={{ opacity: 1, height: "auto" }}
              exit={{ opacity: 0, height: 0 }}
              className="mb-2 flex flex-wrap gap-2"
            >
              {attachedFiles.map((file, idx) => (
                <motion.div
                  key={`${file.name}-${idx}`}
                  initial={{ scale: 0.9, opacity: 0 }}
                  animate={{ scale: 1, opacity: 1 }}
                  exit={{ scale: 0.9, opacity: 0 }}
                  className="flex items-center gap-1.5 rounded-lg border border-nexus-accent/20 bg-nexus-accent/5 px-2.5 py-1.5 text-[11px] text-nexus-text shadow-sm"
                >
                  <Paperclip className="h-3 w-3 text-nexus-accent/70" />
                  <span className="max-w-[140px] truncate font-medium">{file.name}</span>
                  <span className="text-nexus-muted">({(file.size / 1024).toFixed(0)} KB)</span>
                  <button
                    type="button"
                    onClick={() => handleRemoveFile(idx)}
                    className="ml-1 rounded-full p-0.5 text-nexus-muted hover:bg-nexus-border/50 hover:text-nexus-text"
                    aria-label={`Remover ${file.name}`}
                  >
                    <XCircle className="h-3 w-3" />
                  </button>
                </motion.div>
              ))}
            </motion.div>
          )}
          </AnimatePresence>

          <motion.div
            className={`relative flex items-end gap-2 rounded-xl border bg-nexus-bg/60 px-2 py-2 shadow-inner transition-colors ${
              isDraggingOver ? "border-nexus-accent bg-nexus-accent/5" : "border-nexus-border"
            }`}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            {isDraggingOver && (
              <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center rounded-xl border-2 border-dashed border-nexus-accent bg-nexus-accent/10">
                <div className="flex items-center gap-2 text-sm font-medium text-nexus-accent">
                  <Paperclip className="h-4 w-4" />
                  Larga os ficheiros aqui
                </div>
              </div>
            )}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="shrink-0 rounded-lg border border-nexus-border/70 p-2 text-nexus-muted transition-colors hover:border-nexus-accent/40 hover:text-nexus-text"
              title="Anexar ficheiros"
            >
              <Paperclip className="h-4 w-4" />
            </button>

            <textarea
              ref={inputRef}
              className="min-h-[40px] max-h-[160px] flex-1 resize-none bg-transparent px-2 py-2 text-sm text-nexus-text placeholder-nexus-muted outline-none"
              value={input}
              onChange={handleInputChange}
              onKeyDown={handleKeyDown}
              placeholder="Pergunte qualquer coisa... (use @ para agents, / para comandos, Ctrl+K para procurar)"
              aria-autocomplete="list"
              aria-controls={showCommands ? "slash-command-menu" : undefined}
              aria-expanded={showCommands}
              disabled={streaming}
              rows={1}
              style={{ fieldSizing: "content" }}
            />

            {/* Voice input button */}
            <button
              type="button"
              onClick={startListening}
              className={`shrink-0 rounded-lg border p-2 transition-colors ${
                isListening
                  ? "border-red-500/50 bg-red-500/10 text-red-400 animate-pulse"
                  : "border-nexus-border/70 text-nexus-muted hover:border-nexus-accent/40 hover:text-nexus-text"
              }`}
              title={isListening ? "A ouvir... clica para parar" : "Input de voz (Web Speech API)"}
              aria-label="Voice input"
            >
              <Mic className="h-4 w-4" />
            </button>

            {/* Web Search button */}
            <button
              type="button"
              onClick={() => {
                const value = input.trim();
                if (value) {
                  router.push(("/search?q=" + encodeURIComponent(value)) as any);
                }
              }}
              disabled={!input.trim()}
              className="shrink-0 rounded-lg border border-nexus-border/70 p-2 text-nexus-muted transition-colors hover:border-nexus-accent/40 hover:text-nexus-text disabled:cursor-not-allowed disabled:opacity-40"
              title="Pesquisar na web"
              aria-label="Web Search"
            >
              <Search className="h-4 w-4" />
            </button>

            {/* @mentions autocomplete */}
            {showMentions && filteredAgents.length > 0 && (
              <div className="absolute bottom-full left-12 mb-1 max-h-40 w-48 overflow-y-auto rounded-lg border border-nexus-border bg-nexus-panel/95 shadow-lg backdrop-blur-md">
                {filteredAgents.map((a) => (
                  <button
                    key={a}
                    type="button"
                    onClick={() => insertMention(a)}
                    className="block w-full px-3 py-1.5 text-left text-xs text-nexus-text hover:bg-nexus-accent/20"
                  >
                    <span className="text-nexus-accent">@{a}</span>
                  </button>
                ))}
              </div>
            )}

            {/* /command autocomplete */}
            {showCommands && (
              <div
                id="slash-command-menu"
                data-testid="slash-command-menu"
                role="listbox"
                aria-label="Comandos de IA"
                className="absolute bottom-full left-12 z-50 mb-1 max-h-64 w-[min(24rem,calc(100%-3rem))] overflow-y-auto rounded-lg border border-nexus-border bg-nexus-panel/95 p-1 shadow-xl backdrop-blur-md"
              >
                <div className="flex items-center justify-between border-b border-nexus-border/70 px-2 py-1.5">
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
                {filteredCommands.map(([modeId, info], index) => {
                  const mode = advancedModes[modeId];
                  const selected = index === selectedCommandIndex;
                  return (
                    <button
                      key={modeId}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      onMouseEnter={() => setSelectedCommandIndex(index)}
                      onClick={() => insertCommand(info.aliases[0]?.replace(/^\//, "") || modeId)}
                      className={`mt-0.5 flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-xs text-nexus-text ${
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
            )}

            {streaming ? (
              <motion.button
                type="button"
                onClick={handleCancel}
                whileHover={{ scale: 1.05 }}
                whileTap={{ scale: 0.95 }}
                className="shrink-0 rounded-lg bg-gradient-to-br from-red-500/20 to-red-500/10 p-2 text-red-400 hover:from-red-500/30 hover:to-red-500/20 transition-all duration-200 shadow-sm hover:shadow-red-500/20"
              >
                <StopCircle className="h-4 w-4" />
              </motion.button>
            ) : (
              <motion.button
                type="submit"
                disabled={!input.trim()}
                whileHover={{ scale: input.trim() ? 1.05 : 1 }}
                whileTap={{ scale: 0.92 }}
                className={`shrink-0 rounded-lg p-2 text-white transition-all duration-200 shadow-md ${
                  input.trim()
                    ? "bg-gradient-to-br from-nexus-accent to-nexus-accent/80 hover:shadow-nexus-accent/40 hover:from-nexus-accent hover:to-nexus-accent/90"
                    : "bg-nexus-accent/50 cursor-not-allowed opacity-40"
                }`}
              >
                <Send className="h-4 w-4 pointer-events-none" />
              </motion.button>
            )}
          </motion.div>
        </form>

        <div className="mt-1.5 flex items-center justify-between text-[10px] text-nexus-muted">
          <span>
            NEXUS IDE — Modo {currentMode} · Força: {thinkingStrength === "low" ? "Rápido" : thinkingStrength === "medium" ? "Médio" : "Alto"}
          </span>
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

      {/* Search overlay (Ctrl+K) */}
      <AnimatePresence>
        {searchOpen && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="absolute right-4 top-20 z-50 w-80 rounded-lg border border-nexus-border bg-nexus-panel/95 p-3 shadow-2xl backdrop-blur-md"
          >
            <div className="mb-2 flex items-center justify-between">
              <span className="text-xs font-semibold uppercase tracking-wider text-nexus-muted">
                Procurar nas mensagens
              </span>
              <button
                onClick={() => setSearchOpen(false)}
                className="text-nexus-muted hover:text-nexus-text"
                title="Fechar (Esc)"
              >
                <XCircle className="h-3.5 w-3.5" />
              </button>
            </div>
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Escreve para procurar..."
              autoFocus
              className="w-full rounded border border-nexus-border bg-nexus-bg/40 px-2 py-1 text-sm text-nexus-text placeholder-nexus-muted outline-none focus:border-nexus-accent"
            />
            {searchQuery && (
              <div className="mt-2 text-[11px] text-nexus-muted">
                {searchResults.length} resultado(s) &mdash;{" "}
                {searchIdx + 1}/{Math.max(1, searchResults.length)}
              </div>
            )}
            {searchResults.length > 0 && (
              <div className="mt-2 max-h-40 overflow-y-auto">
                {searchResults.slice(0, 5).map((idx, i) => {
                  const m = messages[idx];
                  if (!m) return null;
                  const q = searchQuery.toLowerCase();
                  const pos = m.content?.toLowerCase().indexOf(q) ?? -1;
                  const snippet = m.content?.slice(Math.max(0, pos - 20), pos + 60) ?? "";
                  return (
                    <button
                      key={idx}
                      onClick={() => setSearchIdx(i)}
                      className={`block w-full rounded px-2 py-1 text-left text-[11px] ${
                        i === searchIdx
                          ? "bg-nexus-accent/20 text-nexus-accent"
                          : "text-nexus-text hover:bg-nexus-bg/40"
                      }`}
                    >
                      {snippet || "(sem preview)"}
                    </button>
                  );
                })}
              </div>
            )}
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
