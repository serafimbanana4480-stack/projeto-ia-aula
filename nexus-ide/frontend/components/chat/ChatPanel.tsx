"use client";
import { useMemo, useState, useEffect, useRef, useCallback } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { useAgentStream } from "../../hooks/useAgentStream";
import { useChatSessions } from "../../hooks/useChatSessions";
import { useToast } from "./Toast";
import { getSessionHistory, createPlan, approvePlan, executePlan, getPlanStatus, cancelPlan } from "../../lib/api";
import type { PlanCreateResult, PlanStatus as PlanStatusType } from "../../lib/api";
import { useModeStore, type Mode } from "../../stores/modeStore";
import { useModelStore } from "../../stores/modelStore";
import { useThemeStore } from "../../stores/themeStore";
import { useKeyboardShortcuts } from "../../hooks/useKeyboardShortcuts";
import MessageBubble from "./MessageBubble";
import VirtualMessageList from "./VirtualMessageList";
import SessionList from "./SessionList";
import {
  Sparkles,
  Plus,
  Share2,
  PanelRightClose,
  PanelRightOpen,
  Wand2,
  Paperclip,
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
} from "lucide-react";
import type { AgentName, ChatMessage, StreamEvent } from "../../lib/types";
import { log } from "../../lib/log";
import { stripAnsiCodes } from "../../lib/utils";

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
          current = {
            id: `a-${out.length}-${e.timestamp}`,
            role: "assistant",
            agent: currentAgent,
            content: "",
            timestamp: e.timestamp,
            toolCalls: [],
          };
          out.push(current);
          break;
        }
        case "token": {
          // Skip if this is an embedded thinking iteration marker
          if (e.content && e.content.startsWith("<event>thinking|iteration:")) {
            break;
          }
          if (!current) {
            current = {
              id: `a-${out.length}-${e.timestamp}`,
              role: "assistant",
              agent: currentAgent,
              content: "",
              timestamp: e.timestamp,
              toolCalls: [],
            };
            out.push(current);
          }
          current.content += e.content ?? "";
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
          if (!current) {
            current = {
              id: `a-${out.length}-${e.timestamp}`,
              role: "assistant",
              agent: currentAgent,
              content: "",
              timestamp: e.timestamp,
              toolCalls: [],
            };
            out.push(current);
          }
          current.thinking = (current.thinking ?? "") + (e.content ?? "");
          break;
        }
        case "tool_call": {
          if (!current) {
            current = {
              id: `a-${out.length}-${e.timestamp}`,
              role: "assistant",
              agent: currentAgent,
              content: "",
              timestamp: e.timestamp,
              toolCalls: [],
            };
            out.push(current);
          }
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
        case "tool_result": {
          const idx = findRunningTool(e.tool_name);
          if (idx >= 0 && current) {
            current.toolCalls![idx].status = "success";
            current.toolCalls![idx].result = e.tool_result;
          }
          break;
        }
        case "tool_error": {
          const idx = findRunningTool();
          if (idx >= 0 && current) {
            current.toolCalls![idx].status = "error";
            current.toolCalls![idx].error = e.tool_error;
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
        case "agent_finished":
        case "done": {
          current = null;
          break;
        }
        default:
          break;
      }
    }

    const normalizeCodeBlocks = (text: string) =>
      text
        .replace(/```(\w*)\s*\n([\s\S]*?)```/g, (_, lang, body) => {
          const trimmed = body.replace(/^\s+|\s+$/g, "");
          return trimmed ? `\`\`\`${lang}\n${trimmed}\n\`\`\`` : "";
        })
        .replace(/```(\w*)(?:\n|$)/g, "")
        .replace(/``+/g, "");

    const stripToolMarkup = (text: string) =>
      normalizeCodeBlocks(
        stripAnsiCodes(
          text
          .replace(/<event>[^]*?<\/event>/g, "")
          .replace(/```tool\s*[\s\S]*?```/g, "")
          .split("\n")
          .filter((line) => !/^```tool\s*$/.test(line.trim()))
          .join("\n"),
        )
      )

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
      m.content = stripToolMarkup(m.content);
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
  const { activeModel, models, modelsLoaded, loadModels, setActiveModel } = useModelStore();
  // Map an OpenCode Go model id to a tier name that the backend accepts.
  // The chat route validates the model field against ALLOWED_MODEL_TIERS,
  // so we cannot send raw OpenCode Go model ids (e.g. "minimax-m3").
  const MODEL_TO_TIER: Record<string, string> = {
    "minimax-m3": "fast",
    "deepseek-v4-flash": "fast",
    "deepseek-v4-pro": "deep",
    "glm-5.2": "reasoning",
    "kimi-k2.7-code": "coder",
    "qwen3.7-max": "large",
    "mimo-v2-pro": "medium",
  };
  const resolveActiveTier = (): string => {
    if (!activeModel) return "";
    return MODEL_TO_TIER[activeModel] || "";
  };

  const { events, streaming, error: streamError, send, cancel, reset } = useAgentStream(sessionId);
  const [input, setInput] = useState("");
  const [historyMessages, setHistoryMessages] = useState<ChatMessage[]>([]);
  const [pendingUser, setPendingUser] = useState<ChatMessage[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [shared, setShared] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const [modelSelectorOpen, setModelSelectorOpen] = useState(false);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [thinkingStrength, setThinkingStrength] = useState<ThinkingStrength>(() => {
    if (typeof window !== "undefined") {
      const stored = localStorage.getItem("nexus.thinkingStrength");
      if (stored === "low" || stored === "medium" || stored === "high") return stored;
    }
    return "medium";
  });
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [activePlan, setActivePlan] = useState<PlanCreateResult | null>(null);
  const [planStatus, setPlanStatus] = useState<PlanStatusType | null>(null);
  const [planExecuting, setPlanExecuting] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [backendOffline, setBackendOffline] = useState(false);
  const errorLoggedRef = useRef(false);
  const planPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastUserMessageRef = useRef<string>("");

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


  useEffect(() => {
    localStorage.setItem("nexus.thinkingStrength", thinkingStrength);
  }, [thinkingStrength]);

  const loadHistory = useCallback(async () => {
    try {
      setHistoryError(null);
      const history = await getSessionHistory(sessionId);
      const stripToolMarkup = (text: string) =>
        text
          .replace(/<event>[^]*?<\/event>/g, "")
          .replace(/```tool\s*\n[\s\S]*?```/g, "");
      const normalized = history.map((msg, index) => ({
        ...msg,
        id: `${msg.role}-${index}-${msg.timestamp}`,
        content: stripAnsiCodes(stripToolMarkup(msg.content)),
      }));
      setHistoryMessages(normalized);
      setPendingUser([]);
      reset();
      setHistoryLoaded(true);
      setBackendOffline(false);
      errorLoggedRef.current = false;
    } catch (error) {
      setBackendOffline(true);
      if (!errorLoggedRef.current) {
        log.warn("Backend offline — chat history unavailable");
        errorLoggedRef.current = true;
      }
      setHistoryError(
        error instanceof Error ? error.message : "Failed to load chat history",
      );
      setHistoryLoaded(true);
    }
  }, [sessionId, reset]);

  useEffect(() => {
    loadHistory();
    if (!modesLoaded) {
      void loadModes();
    }
    if (!modelsLoaded) {
      void loadModels();
    }
  }, [loadHistory, loadModes, modesLoaded, loadModels, modelsLoaded]);

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
      await send(messageToSend, currentMode, resolveActiveTier(), "", thinkingStrength);
    } catch (err) {
      setPendingUser((prev) => prev.filter((m) => m.id !== pendingUserMessage.id));
      setInput(previousInput);
      setAttachedFiles(previousFiles);
      toast.error("Falha ao enviar", err instanceof Error ? err.message : String(err));
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
    await loadHistory();
  };

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
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const form = e.currentTarget.closest("form");
      if (form) form.requestSubmit();
    }
  }

  function handleCancel() {
    cancel();
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
    void send(last, currentMode, resolveActiveTier(), "", thinkingStrength).then(() => loadHistory());
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

  const handlePlanCreate = useCallback(async (objective: string) => {
    setPlanError(null);
    try {
      const plan = await createPlan(objective, sessionId);
      setActivePlan(plan);
      const status = await getPlanStatus(plan.plan_id);
      setPlanStatus(status);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to create plan";
      setPlanError(msg);
      log.error("Failed to create plan:", err);
    }
  }, [sessionId]);

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
    setPlanError(null);
    setPlanExecuting(true);
    try {
      await executePlan(activePlan.plan_id, sessionId);
      planPollRef.current = setInterval(async () => {
        try {
          const status = await getPlanStatus(activePlan.plan_id);
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
      log.error("Failed to execute plan:", err);
      setPlanExecuting(false);
    }
  }, [activePlan, planExecuting, sessionId]);

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

  const suggestions = [
    "Análise de mercado",
    "Comparar zonas",
    "Gerar relatório",
    "Encontrar leads",
  ];

  return (
    <div className="flex h-full">
      <SessionList
        collapsed={sidebarCollapsed}
        onToggle={() => setSidebarCollapsed((c) => !c)}
      />
      <div className="flex h-full min-w-0 flex-1 flex-col">
      {/* Chat header */}
      <div className="flex shrink-0 items-center justify-between border-b border-nexus-border px-5 py-2.5">
        <div className="flex items-center gap-2.5">
          <motion.div
            whileHover={{ scale: 1.05, rotate: -3 }}
            whileTap={{ scale: 0.95 }}
            className="flex h-6 w-6 items-center justify-center rounded-md bg-nexus-accent/15 text-nexus-accent cursor-default"
          >
            <Sparkles className="h-3.5 w-3.5" />
          </motion.div>
          <div className="leading-tight">
            <div className="text-sm font-semibold text-nexus-text">Chat com IA</div>
              <div className="text-[11px] text-nexus-muted">
                {"Sem projeto ativo — seleciona um projeto para usar ferramentas"}
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

          {/* Model selector */}
          <div className="relative">
            <motion.button
              type="button"
              onClick={() => setModelSelectorOpen((open) => !open)}
              whileTap={{ scale: 0.97 }}
              className="flex items-center gap-1.5 rounded-lg border border-nexus-border bg-nexus-card px-2.5 py-1.5 text-[11px] font-medium text-nexus-muted hover:text-nexus-text transition-all duration-200"
            >
              <Sparkles className="h-3.5 w-3.5 text-nexus-accent/70" />
              <span className="hidden sm:inline max-w-[120px] truncate">{modelsLoaded ? models.find((m) => m.id === activeModel)?.name || activeModel : activeModel}</span>
              <ChevronDown className="h-3 w-3 text-nexus-muted" />
            </motion.button>
            {modelSelectorOpen && (
              <div className="absolute right-0 top-full z-50 mt-1 w-64 rounded-lg border border-nexus-border bg-nexus-card shadow-xl">
                <div className="max-h-72 overflow-y-auto py-1 thin-scrollbar">
                  {(modelsLoaded ? models : []).length === 0 && (
                    <div className="px-3 py-2 text-[11px] text-nexus-muted">No models available</div>
                  )}
                  {(modelsLoaded ? models : []).map((model) => {
                    const active = model.id === activeModel;
                    const label = model.name || model.id;
                    return (
                      <button
                        key={model.id}
                        type="button"
                        onClick={() => {
                          setActiveModel(model.id);
                          setModelSelectorOpen(false);
                        }}
                        className={`flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left transition-colors ${
                          active ? "bg-nexus-accent/10 text-nexus-text" : "text-nexus-muted hover:bg-nexus-bg hover:text-nexus-text"
                        }`}
                      >
                        <span className="truncate text-xs">{label}</span>
                        <span className="flex items-center gap-2">
                          {model.pricing === "free" && (
                            <span className="rounded bg-green-500/15 px-1.5 py-0.5 text-[10px] font-medium text-green-400">FREE</span>
                          )}
                          {typeof model.estimated_tokens_per_sec === "number" && model.estimated_tokens_per_sec > 0 && (
                            <span className="text-[10px] text-nexus-muted">{model.estimated_tokens_per_sec} t/s</span>
                          )}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

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
            <div className="flex flex-wrap justify-center gap-2.5">
              {suggestions.map((s) => (
                <motion.button
                  key={s}
                  onClick={() => setInput(s)}
                  whileHover={{ scale: 1.03, y: -1 }}
                  whileTap={{ scale: 0.97 }}
                  className="group rounded-full border border-nexus-border bg-nexus-card/80 px-4 py-2 text-xs text-nexus-muted hover:border-nexus-accent/40 hover:text-nexus-text transition-all duration-200 hover:shadow-md hover:shadow-nexus-accent/5"
                >
                  <span className="flex items-center gap-1.5">
                    <Wand2 className="h-3 w-3 text-nexus-accent/60 group-hover:text-nexus-accent transition-colors" />
                    {s}
                  </span>
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
                  Execution Plan
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
              isStreaming={streaming && idx === messages.length - 1}
              onRetry={handleRetryFromError}
            />
          )}
          initialLimit={50}
          className="space-y-4"
        />
        <div ref={messagesEndRef} />
      </div>

      {/* Input area — fixed at bottom */}
      <div className="shrink-0 border-t border-nexus-border bg-nexus-panel px-5 pt-3 pb-2">
        {/* Backend offline indicator */}
        {backendOffline && (
          <div className="mb-2 flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs text-red-400">
            <WifiOff className="h-3.5 w-3.5 shrink-0" />
            <span className="font-medium">Backend offline</span>
            <span className="text-red-300">— Aguardando reconexão para enviar mensagens.</span>
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

          <motion.div className="flex items-end gap-2 rounded-xl border border-nexus-border bg-nexus-bg/60 px-2 py-2 shadow-inner">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="shrink-0 rounded-lg border border-nexus-border/70 p-2 text-nexus-muted transition-colors hover:border-nexus-accent/40 hover:text-nexus-text"
              title="Anexar ficheiros"
            >
              <Paperclip className="h-4 w-4" />
            </button>

            <textarea
              className="min-h-[40px] max-h-[160px] flex-1 resize-none bg-transparent px-2 py-2 text-sm text-nexus-text placeholder-nexus-muted outline-none"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Pergunte qualquer coisa..."
              disabled={streaming}
              rows={1}
              style={{ fieldSizing: "content" }}
            />

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
    </div>
  );
}
