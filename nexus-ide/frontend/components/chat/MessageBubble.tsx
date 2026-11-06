"use client";

import ReactMarkdown from "react-markdown";
import Link from "next/link";
import {
  lazy,
  memo,
  Suspense,
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { motion } from "framer-motion";
import { Copy, Check, RefreshCw, AlertCircle, Pencil, RotateCw, Save, X, ExternalLink, ThumbsUp, ThumbsDown, FileCode2, Sparkles } from "lucide-react";
import type { ChatMessage } from "../../lib/types";
import { stripAnsiCodes } from "../../lib/utils";
import { useThemeStore } from "../../stores/themeStore";
import RunTimeline from "./RunTimeline";
import AgentTranscript from "./AgentTranscript";
import { RunDeliveryNote } from "./WorkNarration";
import { sanitizeAssistantContent } from "../../lib/chatPresentation";
import { agentColor } from "../../lib/foldRun";
import { parseRichBlock, promoteMarkdownTables } from "../../lib/richBlocks";
import RichDataBlock from "./RichDataBlock";

const MessageCodeBlock = lazy(() => import("./MessageCodeBlock"));

function useResetTimer(delayMs = 1200) {
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clearTimer = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  useEffect(() => clearTimer, [clearTimer]);

  return useCallback(
    (callback: () => void) => {
      clearTimer();
      timeoutRef.current = setTimeout(() => {
        timeoutRef.current = null;
        callback();
      }, delayMs);
    },
    [clearTimer, delayMs],
  );
}

function getRelativeTime(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);
  const diffMin = Math.floor(diffSec / 60);
  const diffHr = Math.floor(diffMin / 60);

  if (diffSec < 10) return "agora";
  if (diffSec < 60) return `há ${diffSec}s`;
  if (diffMin === 1) return "há 1 min";
  if (diffMin < 60) return `há ${diffMin} min`;
  if (diffHr === 1) return "há 1 h";
  if (diffHr < 24) return `há ${diffHr} h`;
  return date.toLocaleDateString("pt-PT", { day: "2-digit", month: "short" });
}

function TypingDots() {
  return (
    <span className="inline-flex items-center gap-1">
      <span className="flex gap-0.5">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="inline-block h-1 w-1 rounded-full bg-nexus-accent"
            animate={{ opacity: [0.3, 1, 0.3], y: [0, -3, 0] }}
            transition={{
              duration: 1.2,
              repeat: Infinity,
              delay: i * 0.2,
              ease: "easeInOut",
            }}
          />
        ))}
      </span>
      <span className="text-nexus-muted">A pensar…</span>
    </span>
  );
}

/** Assistant meta row — dimensional agent chip (replaces flat ● + label). */
function AssistantAgentMeta({
  agent,
  color,
  isStreaming,
  relativeTime,
  timestamp,
}: {
  agent: string;
  color: string;
  isStreaming: boolean;
  relativeTime: string;
  timestamp: string | number | Date;
}) {
  const label = agent === "NEXUS" ? "NEXUS" : agent || "NEXUS";

  return (
    <div
      className="mb-2.5 flex flex-wrap items-center gap-2"
    >
      <span
        className="nx-conversation-agent inline-flex items-center gap-2.5"
        data-live={isStreaming ? "true" : undefined}
        style={{ "--nx-agent": color } as CSSProperties}
      >
        <span className="nx-conversation-avatar flex h-8 w-8 shrink-0 items-center justify-center rounded-xl" aria-hidden="true">
          <Sparkles className="h-[15px] w-[15px]" />
        </span>
        <span className="text-[12px] font-semibold tracking-wide text-nexus-text">
          {label}
        </span>
        {isStreaming ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-black/20 px-1.5 py-px text-[9px] font-semibold uppercase tracking-wide text-nexus-text/90">
            <motion.span
              className="h-1.5 w-1.5 rounded-full"
              style={{ background: color }}
              animate={{ opacity: [0.35, 1, 0.35], scale: [0.85, 1.15, 0.85] }}
              transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
            />
            ao vivo
          </span>
        ) : null}
      </span>
      <time
        className="nx-agent-meta-time text-[10px] tabular-nums text-nexus-faint"
        dateTime={new Date(timestamp).toISOString()}
      >
        {relativeTime}
      </time>
    </div>
  );
}

function MessageBubbleComponent({
  message,
  sessionId = "default",
  isStreaming = false,
  onRetry,
  onEdit,
  onRegenerate,
}: {
  message: ChatMessage;
  sessionId?: string;
  isStreaming?: boolean;
  onRetry?: (prompt: string) => void;
  onEdit?: (messageId: string, newContent: string) => void;
  onRegenerate?: (messageId: string) => void;
}) {
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(message.content);
  const isUser = message.role === "user";
  const [relativeTime, setRelativeTime] = useState(() =>
    getRelativeTime(new Date(message.timestamp)),
  );
  const theme = useThemeStore((s) => s.theme);
  const visibleContent = isUser ? message.content : sanitizeAssistantContent(message.content);
  const changedFiles = Array.isArray(message.metadata?.changedFiles)
    ? message.metadata.changedFiles.filter(
        (path): path is string => typeof path === "string" && path.trim().length > 0,
      )
    : [];
  const color = agentColor(message.agent || "");
  // Runs that carry their ordered frames render as one chronological
  // transcript (text ↔ thinking ↔ tools ↔ subagents) instead of
  // "answer on top, activity log below".
  const useTranscript = !isUser && message.metadata?.kind !== "error" && (message.events?.length ?? 0) > 0;
  const renderSegment = useCallback(
    (text: string) => {
      const clean = sanitizeAssistantContent(text);
      return clean.trim() ? <AssistantMarkdown text={clean} theme={theme} /> : null;
    },
    [theme],
  );

  useEffect(() => {
    const interval = setInterval(() => {
      setRelativeTime(getRelativeTime(new Date(message.timestamp)));
    }, 30000);
    return () => clearInterval(interval);
  }, [message.timestamp]);

  return (
    <div className={`nx-chat-message group flex ${isUser ? "justify-end" : "justify-start"}`} data-role={message.role}>
      <div
        className={`min-w-0 text-[15px] transition-all duration-200 ${
          isUser
            ? "nx-chat-user-message max-w-[92%] rounded-[20px] rounded-br-md border border-nexus-border/70 bg-nexus-elevated px-4 py-3 text-nexus-text sm:max-w-[80%] sm:px-5"
            : "w-full max-w-[900px] py-2 sm:py-3"
        }`}
      >
        {/* Meta row: editorial label + time. Activity lives in RunTimeline; this is Result. */}
        {!isUser ? (
          <AssistantAgentMeta
            agent={message.agent || "NEXUS"}
            color={color}
            isStreaming={isStreaming}
            relativeTime={relativeTime}
            timestamp={message.timestamp}
          />
        ) : (
          <div className="mb-2 flex items-center justify-end gap-2 text-[11px]">
            <span className="font-medium text-nexus-muted">Você</span>
            <span className="text-[10px] tabular-nums text-nexus-faint">{relativeTime}</span>
          </div>
        )}

        <div
          className="min-w-0 break-words [&_pre]:max-w-full"
          data-testid={!isUser ? "assistant-response" : undefined}
        >
          {useTranscript ? (
            <AgentTranscript
              events={message.events ?? []}
              isStreaming={isStreaming}
              fallbackContent={visibleContent}
              renderMarkdown={renderSegment}
            />
          ) : visibleContent.trim() ? (
            <AssistantMarkdown text={visibleContent} theme={theme} />
          ) : visibleContent.trim() ? (
            <div className="nx-prose whitespace-pre-wrap">{visibleContent}</div>
          ) : null}
          {/* Soft streaming caret: the design-system block caret, reduced-motion aware. */}
          {!isUser && !useTranscript && isStreaming && visibleContent.trim() && (
            <span aria-hidden="true" className="nx-caret" />
          )}

          {!isUser && !useTranscript && isStreaming && !visibleContent.trim() && !message.thinking && (!message.toolCalls || message.toolCalls.length === 0) && (!message.activities || message.activities.length === 0) && (
            <div className="mt-2 flex items-center gap-2 text-xs text-nexus-muted">
              <TypingDots />
            </div>
          )}

          {/* Error retry + copy actions (only for error messages) */}
          {!isUser && message.metadata?.kind === "error" && (
            <div className="mt-3 flex items-center gap-2 border-t border-nexus-accent4/20 pt-2">
              <AlertCircle className="h-3.5 w-3.5 text-nexus-accent4" aria-hidden="true" />
              <span className="text-[10px] uppercase tracking-wider text-nexus-accent4">
                {message.metadata?.outcome === "interrupted" ? "Interrompido" : "Erro"}
              </span>
              {message.metadata?.canRetry && onRetry && message.metadata?.prompt && (
                <button
                  onClick={() => onRetry(message.metadata!.prompt as string)}
                  className="ml-auto flex items-center gap-1 rounded-md border border-nexus-accent4/30 bg-nexus-accent4/10 px-2 py-0.5 text-[11px] font-medium text-nexus-accent4 transition-colors hover:bg-nexus-accent4/20"
                  title="Reenviar a mesma mensagem"
                >
                  <RefreshCw className="h-3 w-3" aria-hidden="true" />
                  Tentar novamente
                </button>
              )}
              <CopyMessageButton text={visibleContent} />
            </div>
          )}
        </div>

        {!isUser && (
          <div className="mt-2 space-y-2">
            {!isStreaming && visibleContent.trim() && message.metadata?.kind !== "error" && (
              <RefinementBar messageId={message.id} onRegenerate={onRegenerate} />
            )}

            {!isStreaming && visibleContent.length > 80 && message.metadata?.kind !== "error" && (
              <FollowUpChips content={message.content} hasFiles={changedFiles.length > 0} />
            )}

            {!useTranscript && !isStreaming && <RunDeliveryNote message={message} />}

            {!useTranscript && (
              <RunTimeline
                message={message}
                isStreaming={isStreaming}
                sessionId={sessionId}
              />
            )}

            {changedFiles.length > 0 && <CheckpointArtifact files={changedFiles} />}
          </div>
        )}

        {/* Edit mode for user messages */}
        {isUser && isEditing && (
          <div className="mt-2 space-y-2">
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="w-full resize-none rounded-lg border border-nexus-border bg-nexus-bg/40 p-2 text-sm text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/50"
              rows={Math.max(2, editContent.split("\n").length)}
              autoFocus
            />
            <div className="flex items-center gap-2">
              <button
                onClick={() => {
                  if (onEdit && editContent.trim() && editContent !== message.content) {
                    onEdit(message.id, editContent.trim());
                  }
                  setIsEditing(false);
                }}
                className="flex items-center gap-1 rounded-md bg-nexus-accent/20 px-2 py-1 text-[11px] font-medium text-nexus-accent transition-colors hover:bg-nexus-accent/30"
              >
                <Save className="h-3 w-3" /> Guardar e regenerar
              </button>
              <button
                onClick={() => {
                  setIsEditing(false);
                  setEditContent(message.content);
                }}
                className="flex items-center gap-1 rounded-md border border-nexus-border px-2 py-1 text-[11px] font-medium text-nexus-muted transition-colors hover:bg-nexus-bg/40"
              >
                <X className="h-3 w-3" /> Cancelar
              </button>
            </div>
          </div>
        )}

        {/* Action buttons (edit, regenerate, copy). On pointer devices they
            fade in on hover/focus; on touch there is no hover, so they stay
            visible rather than becoming unreachable. */}
        {!isStreaming && visibleContent.trim() && !isEditing && (
          <div className={`mt-2 flex items-center gap-1 opacity-70 transition-opacity duration-100 sm:opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 [@media(hover:none)]:opacity-100 ${isUser ? "justify-end" : ""}`}>
            {/* Edit button (user messages only) */}
            {isUser && onEdit && (
              <button
                onClick={() => setIsEditing(true)}
                className="flex items-center gap-1 rounded p-1 text-[10px] text-nexus-muted hover:bg-nexus-bg/40 hover:text-nexus-text"
                aria-label="Editar mensagem"
                title="Editar mensagem"
              >
                <Pencil className="h-3 w-3" />
              </button>
            )}
            {/* Regenerate button (assistant messages only) */}
            {!isUser && onRegenerate && (
              <button
                onClick={() => onRegenerate(message.id)}
                className="flex items-center gap-1 rounded p-1 text-[10px] text-nexus-muted hover:bg-nexus-bg/40 hover:text-nexus-text"
                aria-label="Regenerar resposta"
                title="Regenerar resposta"
              >
                <RotateCw className="h-3 w-3" />
              </button>
            )}
            {/* Copy button */}
            {message.metadata?.kind !== "error" && (
              <CopyMessageButton text={visibleContent} />
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function dispatchInsertCommand(command: string) {
  window.dispatchEvent(new CustomEvent("nexus:insert-command", { detail: { command } }));
}

async function copyToClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

function FencedCodeBlock({
  lang,
  code,
  theme,
}: {
  lang: string;
  code: string;
  theme: "dark" | "light" | "system";
}) {
  const lineCount = code.split("\n").length;
  const collapsible = lineCount > 20;
  const [expanded, setExpanded] = useState(false);
  const [applied, setApplied] = useState(false);
  const scheduleReset = useResetTimer();
  const collapsed = collapsible && !expanded;
  const headerBtn =
    "rounded border border-nexus-border/40 bg-nexus-bg/60 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-nexus-muted opacity-80 transition-opacity duration-100 sm:opacity-0 hover:text-nexus-text group-hover/code:opacity-100 group-focus-within/code:opacity-100";

  return (
    <div className="relative group/code my-3 overflow-hidden rounded-xl border border-nexus-border/70">
      <div className="absolute right-2 top-2 z-10 flex items-center gap-1.5">
        <span className="rounded border border-nexus-border/40 bg-nexus-bg/60 px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wider text-nexus-muted">
          {lang}
        </span>
        <CopyCodeButton code={code} />
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            dispatchInsertCommand(`/ask Explica este bloco ${lang}`);
          }}
          className={headerBtn}
          aria-label="Explicar bloco de código"
          title="Explica este bloco no chat"
        >
          Explicar
        </button>
        <button
          type="button"
          onClick={async (event) => {
            event.stopPropagation();
            if (await copyToClipboard(code)) {
              setApplied(true);
              scheduleReset(() => setApplied(false));
            }
          }}
          className={headerBtn}
          aria-label="Copiar bloco de código"
          title="Copia o bloco para colares no editor"
        >
          {applied ? "Copiado" : "Copiar"}
        </button>
      </div>
      <Suspense
        fallback={
          <pre className="overflow-x-auto rounded-lg border border-nexus-border/60 bg-nexus-bg/80 px-4 pb-4 pt-10 text-xs leading-relaxed">
            <code>{code}</code>
          </pre>
        }
      >
        <MessageCodeBlock language={lang} code={code} theme={theme} maxLines={collapsed ? 12 : undefined} />
      </Suspense>
      {collapsible && (
        <div className="mt-1 flex justify-center">
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            title="Ver linhas"
            className="rounded px-2 py-0.5 text-[10px] text-nexus-muted transition-colors duration-100 hover:bg-nexus-bg/40 hover:text-nexus-text"
          >
            {expanded ? "Colapsar" : `Expandir ${lineCount - 12} linhas`}
          </button>
        </div>
      )}
    </div>
  );
}

const GHOST_ACTION =
  "rounded px-1.5 py-0.5 text-[11px] text-nexus-muted transition-colors duration-100 hover:bg-nexus-bg/40 hover:text-nexus-text";

function RefinementBar({
  messageId,
  onRegenerate,
}: {
  messageId: string;
  onRegenerate?: (messageId: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1 opacity-70 transition-opacity duration-100 sm:opacity-0 group-hover:opacity-100 group-focus-within:opacity-100">
      <button
        type="button"
        onClick={() => dispatchInsertCommand("/ask Resume em 3 bullets")}
        className={GHOST_ACTION}
        title="Resume a resposta em 3 bullets"
      >
        Mais curto
      </button>
      <button
        type="button"
        onClick={() => dispatchInsertCommand("/ask Detalha com exemplos")}
        className={GHOST_ACTION}
        title="Detalha a resposta com exemplos"
      >
        Detalhar
      </button>
      {onRegenerate && (
        <button
          type="button"
          onClick={() => onRegenerate(messageId)}
          className={GHOST_ACTION}
          aria-label="Tentar de novo"
          title="Gera outra versão desta resposta"
        >
          Tentar de novo
        </button>
      )}
      <span aria-hidden="true" className="mx-1 h-3 w-px bg-nexus-border/40" />
      <FeedbackButtons messageId={messageId} />
    </div>
  );
}

function FeedbackButtons({ messageId }: { messageId: string }) {
  const storageKey = `nexus:feedback:${messageId}`;
  const [value, setValue] = useState<"up" | "down" | null>(() => {
    try {
      if (typeof window === "undefined") return null;
      const stored = window.localStorage.getItem(storageKey);
      return stored === "up" || stored === "down" ? stored : null;
    } catch {
      return null;
    }
  });
  const toggle = (next: "up" | "down") => {
    setValue((prev) => {
      const resolved = prev === next ? null : next;
      try {
        if (resolved) window.localStorage.setItem(storageKey, resolved);
        else window.localStorage.removeItem(storageKey);
      } catch {
        // Feedback é só visual; falhar aqui não pode partir o chat.
      }
      return resolved;
    });
  };
  const base =
    "rounded p-1 text-nexus-muted transition-all duration-100 hover:bg-nexus-bg/40 hover:text-nexus-text";
  const selected = "bg-nexus-accent/10 text-nexus-accent ring-1 ring-nexus-accent/40";
  return (
    <span className="flex items-center gap-0.5">
      <button
        type="button"
        onClick={() => toggle("up")}
        aria-pressed={value === "up"}
        aria-label="Resposta útil"
        title="Resposta útil"
        className={`${base} ${value === "up" ? selected : ""}`}
      >
        <ThumbsUp className="h-3.5 w-3.5" />
      </button>
      <button
        type="button"
        onClick={() => toggle("down")}
        aria-pressed={value === "down"}
        aria-label="Resposta pouco útil"
        title="Resposta pouco útil"
        className={`${base} ${value === "down" ? selected : ""}`}
      >
        <ThumbsDown className="h-3.5 w-3.5" />
      </button>
    </span>
  );
}

function deriveFollowUps(content: string, hasFiles: boolean): string[] {
  const hasCode = /```/.test(content);
  if (hasCode && hasFiles) return ["Explica passo a passo", "Mostra diff", "Gera testes"];
  if (hasCode) return ["Explica passo a passo", "Gera testes"];
  if (hasFiles) return ["Mostra diff", "Aplica no projeto"];
  return ["Resume", "Próximos passos"];
}

function FollowUpChips({ content, hasFiles }: { content: string; hasFiles: boolean }) {
  const chips = deriveFollowUps(content, hasFiles);
  if (chips.length === 0) return null;
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {chips.map((chip) => (
        <button
          key={chip}
          type="button"
          onClick={() => dispatchInsertCommand(chip)}
          className="rounded-full border border-nexus-border/40 px-2.5 py-0.5 text-[11px] text-nexus-muted transition-all duration-100 hover:border-nexus-accent/40 hover:text-nexus-text"
        >
          {chip}
        </button>
      ))}
    </div>
  );
}

function CopyCodeButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const scheduleReset = useResetTimer();
  return (
    <button
      type="button"
      onClick={async (event) => {
        event.stopPropagation();
        try {
          await navigator.clipboard.writeText(code);
          setCopied(true);
          scheduleReset(() => setCopied(false));
        } catch {
          // Clipboard access can be unavailable outside a secure context.
        }
      }}
      className="flex items-center gap-1 rounded border border-nexus-border/40 bg-nexus-bg/60 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-nexus-muted opacity-80 transition-opacity sm:opacity-0 hover:text-nexus-text group-hover/code:opacity-100 group-focus-within/code:opacity-100"
      aria-label={copied ? "Código copiado" : "Copiar bloco de código"}
      title="Copiar código"
    >
      {copied ? (
        <>
          <Check className="h-3 w-3 text-nexus-accent2" />
          <span className="text-nexus-accent2">Copiado</span>
        </>
      ) : (
        <>
          <Copy className="h-3 w-3" />
          Copiar
        </>
      )}
    </button>
  );
}

function fileParts(path: string): { name: string; dir: string } {
  const normalized = path.replace(/\\/g, "/");
  const slash = normalized.lastIndexOf("/");
  if (slash < 0) return { name: path, dir: "" };
  return { name: normalized.slice(slash + 1), dir: normalized.slice(0, slash) };
}

function CheckpointArtifact({ files }: { files: string[] }) {
  const [copiedList, setCopiedList] = useState(false);
  const [copiedPath, setCopiedPath] = useState<string | null>(null);
  const scheduleListReset = useResetTimer();
  const schedulePathReset = useResetTimer();
  return (
    <details
      data-testid="changed-files-artifact"
      className="overflow-hidden rounded-xl border border-nexus-border/40 bg-nexus-card/25"
      open
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs [&::-webkit-details-marker]:hidden">
        <FileCode2 className="h-3.5 w-3.5 shrink-0 text-nexus-accent2" aria-hidden="true" />
        <span className="font-medium text-nexus-text">Ficheiros alterados</span>
        <span className="tabular-nums text-nexus-muted">({files.length})</span>
        <span className="ml-auto flex items-center gap-1.5">
          <button
            type="button"
            onClick={async (event) => {
              event.preventDefault();
              event.stopPropagation();
              if (await copyToClipboard(files.join("\n"))) {
                setCopiedList(true);
                scheduleListReset(() => setCopiedList(false));
              }
            }}
            className="rounded border border-nexus-border/40 px-1.5 py-0.5 text-[10px] text-nexus-muted transition-colors duration-100 hover:text-nexus-text"
            title="Copiar lista de ficheiros"
          >
            {copiedList ? "Copiado" : "Copiar lista"}
          </button>
          <Link
            href="/editor"
            onClick={(event) => event.stopPropagation()}
            className="rounded border border-nexus-border/40 px-1.5 py-0.5 text-[10px] text-nexus-muted transition-colors duration-100 hover:text-nexus-text"
          >
            Abrir no Editor
          </Link>
        </span>
      </summary>
      <ul className="max-h-48 space-y-0.5 overflow-y-auto border-t border-nexus-border/20 px-2 py-2">
        {files.map((path, index) => (
          <li
            key={`${path}-${index}`}
            className="group/file flex items-center gap-2 rounded px-1.5 py-1 transition-colors duration-100 hover:bg-nexus-bg/40"
          >
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-nexus-accent2" aria-hidden="true" />
            <span className="min-w-0 break-all font-mono text-[12px] leading-5">
              {fileParts(path).dir ? (
                <span className="text-nexus-faint">{fileParts(path).dir}/</span>
              ) : null}
              <span className="text-nexus-text">{fileParts(path).name}</span>
            </span>
            <button
              type="button"
              onClick={async (event) => {
                event.stopPropagation();
                if (await copyToClipboard(path)) {
                  setCopiedPath(path);
                  schedulePathReset(() => setCopiedPath(null));
                }
              }}
              className="ml-auto shrink-0 rounded px-1.5 py-0.5 text-[10px] text-nexus-muted opacity-0 transition-opacity duration-100 hover:text-nexus-text group-hover/file:opacity-100 group-focus-within/file:opacity-100"
              aria-label={`Copiar caminho ${path}`}
              title="Copiar path"
            >
              {copiedPath === path ? "Copiado" : "Copiar path"}
            </button>
          </li>
        ))}
      </ul>
    </details>
  );
}

function CopyMessageButton({ text, className = "" }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  const scheduleReset = useResetTimer();
  return (
    <button
      onClick={async (e) => {
        e.stopPropagation();
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          scheduleReset(() => setCopied(false));
        } catch {}
      }}
      className={`flex items-center gap-1 rounded p-1 text-[10px] text-nexus-muted hover:bg-nexus-bg/40 hover:text-nexus-text ${className}`}
      aria-label={copied ? "Mensagem copiada" : "Copiar mensagem"}
      title="Copiar mensagem"
    >
      {copied ? <Check className="h-3 w-3 text-nexus-accent2" /> : <Copy className="h-3 w-3" />}
    </button>
  );
}

export default memo(MessageBubbleComponent);

/** The assistant Markdown renderer (shared by the bubble and AgentTranscript segments). */
function AssistantMarkdown({ text, theme }: { text: string; theme: Parameters<typeof FencedCodeBlock>[0]["theme"] }) {
  return (
    <ReactMarkdown
      className="nx-prose text-nexus-text prose-headings:font-semibold prose-headings:text-nexus-text prose-h1:text-[24px] prose-h2:text-[20px] prose-h2:mt-5 prose-h1:mt-5 prose-p:my-2.5 prose-p:leading-[1.65] prose-li:leading-[1.65]"
      components={{
        ol({ children, className, ...props }: any) {
          return (
            <ol className={`my-2 list-decimal space-y-1 pl-6 ${className ?? ""}`.trim()} {...props}>
              {children}
            </ol>
          );
        },
        ul({ children, className, ...props }: any) {
          return (
            <ul className={`my-2 list-disc space-y-1 pl-6 ${className ?? ""}`.trim()} {...props}>
              {children}
            </ul>
          );
        },
        h1({ children, ...props }: any) {
          return (
            <h1 className="mb-2 mt-5 text-[20px] font-semibold tracking-tight text-nexus-text" {...props}>
              {children}
            </h1>
          );
        },
        h2({ children, ...props }: any) {
          return (
            <h2 className="mb-2 mt-5 text-[18px] font-semibold tracking-tight text-nexus-text" {...props}>
              {children}
            </h2>
          );
        },
        h3({ children, ...props }: any) {
          return (
            <h3 className="mb-1.5 mt-4 text-[16px] font-semibold tracking-tight text-nexus-text" {...props}>
              {children}
            </h3>
          );
        },
        blockquote({ children, ...props }: any) {
          return (
            <blockquote className="my-3 rounded-r-lg border-l-2 border-nexus-accent/60 bg-nexus-accent/5 px-3 py-2 text-[14px] text-nexus-text/90" {...props}>
              {children}
            </blockquote>
          );
        },
        table({ children, ...props }: any) {
          return (
            <div className="my-3 overflow-x-auto rounded-lg border border-nexus-border/40">
              <table className="w-full border-collapse text-[13px]" {...props}>
                {children}
              </table>
            </div>
          );
        },
        th({ children, ...props }: any) {
          return (
            <th className="bg-nexus-bg/60 px-3 py-2 text-left text-[12px] font-medium text-nexus-muted" {...props}>
              {children}
            </th>
          );
        },
        td({ children, ...props }: any) {
          return (
            <td className="border-t border-nexus-border/30 px-3 py-2 align-top text-[13px]" {...props}>
              {children}
            </td>
          );
        },
        a({ href, children, ...props }: any) {
          const url = typeof href === "string" ? href : "";
          if (!/^https?:\/\//i.test(url)) {
            return (
              <a href={url} {...props}>
                {children}
              </a>
            );
          }
          return (
            <a
              href={url}
              target="_blank"
              rel="noreferrer"
              title={url}
              className="underline decoration-nexus-accent/60 underline-offset-2 hover:decoration-nexus-accent"
              {...props}
            >
              {children}
              <ExternalLink className="mb-0.5 ml-0.5 inline h-2.5 w-2.5 opacity-60" aria-hidden="true" />
            </a>
          );
        },
        input({ type, checked, ...props }: any) {
          if (type === "checkbox") {
            return (
              <input
                type="checkbox"
                checked={!!checked}
                readOnly
                className="mr-1.5 h-3.5 w-3.5 align-[-2px]"
                style={{ accentColor: "var(--nx-accent)" }}
                {...props}
              />
            );
          }
          return <input type={type} {...props} />;
        },
        code({ inline: inlineProp, className, children, node: _node, ...props }: any) {
          const match = /language-([\w-]+)/.exec(className || "");
          const lang = match ? match[1] : "";
          const codeString = String(children).replace(/\n$/, "");
          // react-markdown 9 no longer passes `inline`: a span of code is
          // inline when it carries no language and no line break.
          const inline = typeof inlineProp === "boolean" ? inlineProp : !lang && !String(children).includes("\n");

          if (!inline && lang) {
            const rich = parseRichBlock(lang, codeString);
            if (rich) return <RichDataBlock block={rich} />;
            return <FencedCodeBlock lang={lang} code={codeString} theme={theme} />;
          }

          const mergedClassName = `${className ?? ""} ${inline ? "nx-inline-code rounded-[5px] border border-nexus-border/50 bg-white/[0.06] px-[5px] py-px font-mono text-[0.86em] text-nexus-text/95" : "rounded-lg bg-nexus-bg/80 p-3 text-xs overflow-x-auto border border-nexus-border/60 block"}`.trim();
          return (
            <code className={mergedClassName} {...props}>
              {children}
            </code>
          );
        },
      }}
    >
      {promoteMarkdownTables(stripAnsiCodes(text))}
    </ReactMarkdown>
  );
}
