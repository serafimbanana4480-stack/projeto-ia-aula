"use client";
import { useMemo, useState, useEffect, useRef, useCallback } from "react";
import { motion } from "framer-motion";
import { useAgentStream } from "../../hooks/useAgentStream";
import { getSessionHistory, createPlan, approvePlan, executePlan, getPlanStatus, cancelPlan } from "../../lib/api";
import { apiUrl } from "../../lib/api";
import type { PlanCreateResult, PlanStatus as PlanStatusType } from "../../lib/api";
import { useModeStore } from "../../stores/modeStore";
import { useModelStore } from "../../stores/modelStore";
import { useProjectStore } from "../../stores/projectStore";
import { useThemeStore } from "../../stores/themeStore";
import { useKeyboardShortcuts } from "../../hooks/useKeyboardShortcuts";
import MessageBubble from "./MessageBubble";
import VirtualMessageList from "./VirtualMessageList";
import {
  Sparkles,
  Plus,
  Share2,
  PanelRightClose,
  PanelRightOpen,
  Wand2,
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
  AlertTriangle,
  X,
  WifiOff,
} from "lucide-react";
import type { AgentName, ChatMessage, StreamEvent } from "../../lib/types";
import { log } from "../../lib/log";

interface ChatPanelProps {
  rightOpen?: boolean;
  setRightOpen?: (open: boolean) => void;
}

/** Fold the raw SSE event stream into an ordered list of ChatMessages. */
function foldEvents(
  pendingUser: ChatMessage[],
  events: StreamEvent[],
): ChatMessage[] {
  const out: ChatMessage[] = [...pendingUser];
  let current: ChatMessage | null = null;

  for (const e of events) {
    switch (e.type) {
      case "agent_started": {
        current = {
          id: `a-${out.length}-${e.timestamp}`,
          role: "assistant",
          agent: (e.agent ?? "CODER") as AgentName,
          content: "",
          timestamp: e.timestamp,
        };
        out.push(current);
        break;
      }
      case "token": {
        if (current) current.content += e.content ?? "";
        break;
      }
      case "error": {
        out.push({
          id: `err-${out.length}-${e.timestamp}`,
          role: "assistant",
          agent: "CODER",
          content: `⚠ ${e.content ?? "unknown error"}`,
          timestamp: e.timestamp,
        });
        current = null;
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
  return out;
}

export default function ChatPanel({
  rightOpen = true,
  setRightOpen,
}: ChatPanelProps) {
  const [sessionId, setSessionId] = useState("default");
  const { currentMode, modes, modesLoaded, loadModes } = useModeStore();
  const { activeModel } = useModelStore();
  const { currentProject } = useProjectStore();
  const { events, streaming, error: streamError, send, cancel, reset } = useAgentStream(sessionId);
  const [input, setInput] = useState("");
  const [historyMessages, setHistoryMessages] = useState<ChatMessage[]>([]);
  const [pendingUser, setPendingUser] = useState<ChatMessage[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [shared, setShared] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState<File[]>([]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [activePlan, setActivePlan] = useState<PlanCreateResult | null>(null);
  const [planStatus, setPlanStatus] = useState<PlanStatusType | null>(null);
  const [planExecuting, setPlanExecuting] = useState(false);
  const [backendOffline, setBackendOffline] = useState(false);
  const errorLoggedRef = useRef(false);
  const planPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const loadHistory = async () => {
    try {
      setHistoryError(null);
      const history = await getSessionHistory(sessionId);
      const normalized = history.map((msg, index) => ({
        ...msg,
        id: `${msg.role}-${index}-${msg.timestamp}`,
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
      // Keep local pendingUser and events visible so messages don't disappear
      setHistoryLoaded(true);
    }
  };

  useEffect(() => {
    loadHistory();
    // DataInitProvider already triggers mode loading, but keep a lightweight
    // guard here in case this component is rendered outside that context.
    if (!modesLoaded) {
      void loadModes();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const { toggleTheme } = useThemeStore();

  // Read file contents and compose message with attachments
  async function composeMessageWithAttachments(
    message: string,
    files: File[],
  ): Promise<string> {
    if (files.length === 0) return message;
    const parts: string[] = [];
    for (const file of files) {
      // Skip files larger than 50KB to avoid hitting backend limits
      if (file.size > 50 * 1024) {
        parts.push(`\n---\n[Anexo: ${file.name} — ${(file.size / 1024).toFixed(0)}KB (ficheiro demasiado grande para incluir)]\n---\n`);
        continue;
      }
      // Only include text-like files; skip binary/image files
      const isText = file.type.startsWith("text/") ||
        file.name.match(/\.(txt|md|py|js|ts|tsx|jsx|json|yaml|yml|toml|css|scss|html|xml|csv|sql|sh|bat|ps1|ini|cfg|env|gitignore|dockerfile)$/i);
      if (!isText) {
        parts.push(`\n---\n[Anexo: ${file.name} — ${(file.size / 1024).toFixed(0)}KB (tipo ${file.type || "binário"})]\n---\n`);
        continue;
      }
      try {
        const text = await file.text();
        parts.push(`\n---\n[Anexo: ${file.name}]\n\n\`\`\`\n${text}\n\`\`\`\n---\n`);
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
    setPendingUser((prev) => [
      ...prev,
      {
        id: `u-${prev.length}-${Date.now()}`,
        role: "user",
        content: displayContent,
        timestamp: new Date().toISOString(),
      },
    ]);
    setInput("");
    const messageToSend = hasAttachments
      ? await composeMessageWithAttachments(trimmed, attachedFiles)
      : trimmed;
    setAttachedFiles([]); // Clear attachments after reading
    await send(messageToSend, currentMode, activeModel, currentProject?.path ?? "");
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
    () => [...historyMessages, ...foldEvents(pendingUser, events)],
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
      setAttachedFiles((prev) => [...prev, ...files].slice(0, 5)); // Max 5 files
    }
    e.target.value = ""; // Reset input
  }

  function handleRemoveFile(index: number) {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index));
  }

  function handleRegenerate() {
    if (streaming) return;
    if (!lastUserMessage) return;
    void send(lastUserMessage, currentMode, activeModel, currentProject?.path ?? "").then(() => loadHistory());
  }

  async function handleNewChat() {
    try {
      const response = await fetch(
        apiUrl(`/api/sessions?title=Novo Chat&mode=${currentMode}`),
        { method: "POST" },
      );
      if (response.ok) {
        const data = await response.json();
        setSessionId(data.id);
      } else {
        // Fallback: generate a random session ID
        setSessionId(`session-${Date.now()}`);
      }
    } catch {
      setSessionId(`session-${Date.now()}`);
    }
    setHistoryMessages([]);
    setPendingUser([]);
    setHistoryLoaded(true);
    setHistoryError(null);
    reset();
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

  // Plan execution handlers
  const handlePlanCreate = useCallback(async (objective: string) => {
    try {
      const plan = await createPlan(objective, sessionId);
      setActivePlan(plan);
      // Immediately fetch status
      const status = await getPlanStatus(plan.plan_id);
      setPlanStatus(status);
    } catch (err) {
      log.error("Failed to create plan:", err);
    }
  }, [sessionId]);

  const handlePlanApprove = useCallback(async () => {
    if (!activePlan) return;
    try {
      await approvePlan(activePlan.plan_id, sessionId);
      const status = await getPlanStatus(activePlan.plan_id);
      setPlanStatus(status);
    } catch (err) {
      log.error("Failed to approve plan:", err);
    }
  }, [activePlan, sessionId]);

  const handlePlanExecute = useCallback(async () => {
    if (!activePlan) return;
    try {
      setPlanExecuting(true);
      await executePlan(activePlan.plan_id, sessionId);
      // Start polling for status
      planPollRef.current = setInterval(async () => {
        try {
          const status = await getPlanStatus(activePlan.plan_id);
          setPlanStatus(status);
          if (["completed", "failed", "cancelled"].includes(status.status)) {
            if (planPollRef.current) clearInterval(planPollRef.current);
            setPlanExecuting(false);
          }
        } catch {
          // Stop polling on error
          if (planPollRef.current) clearInterval(planPollRef.current);
          setPlanExecuting(false);
        }
      }, 2000);
    } catch (err) {
      log.error("Failed to execute plan:", err);
      setPlanExecuting(false);
    }
  }, [activePlan, sessionId]);

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

  // Clean up polling on unmount
  useEffect(() => {
    return () => {
      if (planPollRef.current) clearInterval(planPollRef.current);
    };
  }, []);

  // When in plan mode and user sends a message, also create a plan
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
    <div className="flex h-full flex-col">
      {/* Chat header */}
      <div className="flex shrink-0 items-center justify-between border-b border-nexus-border px-5 py-2.5">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-nexus-accent/15 text-nexus-accent">
            <Sparkles className="h-3.5 w-3.5" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold">Chat com IA</div>
            <div className="text-[11px] text-nexus-muted">
              {currentProject ? (
                <span className="flex items-center gap-1">
                  <span className="text-nexus-accent">●</span>
                  {currentProject.name}
                </span>
              ) : (
                "Sem projeto ativo — seleciona um projeto para usar ferramentas"
              )}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* Mode selector */}
          <select
            value={currentMode}
            onChange={(e) => useModeStore.getState().setMode(e.target.value)}
            className="rounded-lg border border-nexus-border bg-nexus-card px-2 py-1.5 text-xs text-nexus-muted outline-none focus:border-nexus-accent/50"
            title={modes.find((m) => m.id === currentMode)?.description || ""}
          >
            {modes.map((mode) => (
              <option key={mode.id} value={mode.id}>
                {mode.id}
              </option>
            ))}
            {!modesLoaded && <option value={currentMode}>{currentMode}</option>}
          </select>

          <button
            onClick={handleNewChat}
            className="flex items-center gap-1.5 rounded-lg border border-nexus-border bg-nexus-card px-3 py-1.5 text-xs text-nexus-muted hover:text-nexus-text transition-colors"
          >
            <Plus className="h-3.5 w-3.5" />
            Novo Chat
          </button>
          <button
            onClick={handleShare}
            className="rounded-lg border border-nexus-border bg-nexus-card p-1.5 text-nexus-muted hover:text-nexus-text transition-colors"
            title="Copiar conversação"
          >
            {shared ? (
              <Check className="h-3.5 w-3.5 text-green-400" />
            ) : (
              <Share2 className="h-3.5 w-3.5" />
            )}
          </button>
          <button
            onClick={() => setRightOpen?.(!rightOpen)}
            className="rounded-lg border border-nexus-border bg-nexus-card p-1.5 text-nexus-muted hover:text-nexus-text transition-colors"
            title="Toggle painel direito"
          >
            {rightOpen ? (
              <PanelRightClose className="h-3.5 w-3.5" />
            ) : (
              <PanelRightOpen className="h-3.5 w-3.5" />
            )}
          </button>
        </div>
      </div>

      {/* Messages area */}
      <div ref={messagesContainerRef} className="min-h-0 flex-1 overflow-y-auto thin-scrollbar px-5 py-3">
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
                Error loading chat history
              </div>
              <p className="text-xs text-red-300">{historyError}</p>
              <button
                onClick={() => loadHistory()}
                className="mt-3 rounded bg-red-500/20 px-3 py-1.5 text-xs font-medium text-red-300 hover:bg-red-500/30 transition-colors"
              >
                Try again
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
            <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-2xl bg-nexus-accent/10 text-nexus-accent">
              <Sparkles className="h-7 w-7" />
            </div>
            <h2 className="mb-1 text-lg font-semibold">NEXUS IDE</h2>
            <p className="mb-6 max-w-sm text-sm text-nexus-muted">
              Pergunte, analise, crie. A sua IA, os seus dados.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
              {suggestions.map((s) => (
                <button
                  key={s}
                  onClick={() => setInput(s)}
                  className="rounded-full border border-nexus-border bg-nexus-card px-3 py-1.5 text-xs text-nexus-muted hover:border-nexus-accent/30 hover:text-nexus-text transition-colors"
                >
                  {s}
                </button>
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
          renderItem={(m) => <MessageBubble key={m.id} message={m} />}
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
        {/* Attached files preview */}
        {attachedFiles.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {attachedFiles.map((file, idx) => (
              <div
                key={`${file.name}-${idx}`}
                className="flex items-center gap-1.5 rounded-lg border border-nexus-border bg-nexus-bg px-2 py-1 text-[11px] text-nexus-muted"
              >
                <Paperclip className="h-3 w-3" />
                <span className="max-w-[120px] truncate">{file.name}</span>
                <span className="text-gray-600">({(file.size / 1024).toFixed(0)} KB)</span>
                <button
                  type="button"
                  onClick={() => handleRemoveFile(idx)}
                  className="ml-1 text-gray-500 hover:text-red-400"
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Quick suggestion chips above input */}
        <div className="mb-2 flex flex-wrap gap-2">
          {suggestions.map((s) => (
            <button
              key={s}
              onClick={() => setInput(s)}
              className="flex items-center gap-1.5 rounded-full border border-nexus-border bg-nexus-bg px-3 py-1 text-[11px] text-nexus-muted hover:border-nexus-accent/30 hover:text-nexus-text transition-colors"
            >
              <Wand2 className="h-3 w-3" />
              {s}
            </button>
          ))}
        </div>

        <form onSubmit={handleSubmit}>
          <div className="flex items-end gap-1.5 rounded-xl border border-nexus-border bg-nexus-card p-2 focus-within:border-nexus-accent/50 transition-colors">
            <input
              type="file"
              ref={fileInputRef}
              onChange={handleFileSelect}
              className="hidden"
              multiple
              accept=".txt,.md,.py,.js,.ts,.tsx,.json,.yaml,.yml,.csv,.html,.css,.sql,.log"
            />
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="shrink-0 rounded-lg p-2 text-nexus-muted hover:text-nexus-text transition-colors"
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

            <button
              type="button"
              disabled
              title="Em breve"
              className="shrink-0 rounded-lg p-2 text-nexus-muted opacity-50 cursor-not-allowed transition-colors"
            >
              <Mic className="h-4 w-4" />
            </button>

            {streaming ? (
              <button
                type="button"
                onClick={handleCancel}
                className="shrink-0 rounded-lg bg-red-500/15 p-2 text-red-400 hover:bg-red-500/25 transition-colors"
              >
                <StopCircle className="h-4 w-4" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                className="shrink-0 rounded-lg bg-nexus-accent p-2 text-white hover:bg-nexus-accent/90 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                <Send className="h-4 w-4 pointer-events-none" />
              </button>
            )}
          </div>
        </form>

        <div className="mt-1.5 flex items-center justify-between text-[10px] text-nexus-muted">
          <span>
            NEXUS IDE — Modo {currentMode}
          </span>
          <button
            type="button"
            onClick={handleRegenerate}
            disabled={!lastUserMessage || streaming}
            className="flex items-center gap-1 hover:text-nexus-text disabled:opacity-40 transition-colors"
          >
            <RotateCcw className="h-3 w-3" />
            Regenerar
          </button>
        </div>
      </div>
    </div>
  );
}
