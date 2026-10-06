"use client";

import ReactMarkdown from "react-markdown";
import Link from "next/link";
import { lazy, memo, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Copy, Check, RefreshCw, AlertCircle, Pencil, RotateCw, Save, X, ExternalLink, ThumbsUp, ThumbsDown, FileCode2 } from "lucide-react";
import type { ChatMessage } from "../../lib/types";
import { stripAnsiCodes } from "../../lib/utils";
import { useThemeStore } from "../../stores/themeStore";
import RunTimeline from "./RunTimeline";
import { sanitizeAssistantContent } from "../../lib/chatPresentation";
import { agentColor } from "../../lib/foldRun";

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
      <span className="text-nexus-muted">A pensar...</span>
    </span>
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

  useEffect(() => {
    const interval = setInterval(() => {
      setRelativeTime(getRelativeTime(new Date(message.timestamp)));
    }, 30000);
    return () => clearInterval(interval);
  }, [message.timestamp]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 4 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.16, ease: "easeOut" }}
      className={`group flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`min-w-0 text-[15px] transition-all duration-200 ${
          isUser
            ? "max-w-[92%] rounded-[20px] rounded-br-md border border-nexus-border/70 bg-nexus-elevated px-4 py-3 text-nexus-text shadow-sm sm:max-w-[80%]"
            : "w-full max-w-[900px] py-2"
        }`}
      >
        {/* Meta row: editorial label + time. Activity lives in RunTimeline; this is Result. */}
        <div className={`mb-2 flex items-center gap-2 text-[11px] ${isUser ? "justify-end" : ""}`}>
          {!isUser && (
            <>
              <span aria-hidden="true" className="flex h-5 w-5 items-center justify-center rounded-md bg-nexus-accent/10 text-[9px] leading-none" style={{ color }}>
                ●
              </span>
              <span className="text-[12px] font-semibold tracking-wide" style={{ color }}>
                {message.agent === "NEXUS" ? "NEXUS" : message.agent || "NEXUS"}
              </span>
              {isStreaming && (
                <span className="inline-flex items-center gap-1 rounded-full bg-nexus-accent/10 px-1.5 py-px text-[9px] font-medium text-nexus-accent">
                  <span className="h-1 w-1 animate-pulse rounded-full bg-nexus-accent" />
                  ao vivo
                </span>
              )}
            </>
          )}
          {isUser && <span className="font-medium text-nexus-muted">Você</span>}
          <span className="text-[10px] tabular-nums text-nexus-faint">
            {relativeTime}
          </span>
        </div>

        <div
          className="min-w-0 break-words [&_pre]:max-w-full"
          data-testid={!isUser ? "assistant-response" : undefined}
        >
          {visibleContent.trim() && typeof ReactMarkdown !== "undefined" ? (
            <ReactMarkdown
              className="prose prose-base max-w-[900px] text-[15px] leading-[1.65] text-nexus-text prose-headings:font-semibold prose-headings:text-nexus-text prose-h1:text-[24px] prose-h2:text-[20px] prose-h2:mt-5 prose-h1:mt-5 prose-p:my-2.5 prose-p:leading-[1.65] prose-li:leading-[1.65] prose-table:w-full prose-table:overflow-hidden prose-table:rounded-lg prose-pre:rounded-lg prose-pre:border prose-pre:border-nexus-border/60 [&_table]:w-full [&_table]:rounded-lg [&_table]:border [&_table]:border-nexus-border/40"
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
                    <th className="bg-nexus-bg/60 px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-nexus-muted" {...props}>
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
                        style={{ accentColor: "var(--color-nexus-accent, #8b7cf6)" }}
                        {...props}
                      />
                    );
                  }
                  return <input type={type} {...props} />;
                },
                code({ inline, className, children, ...props }: any) {
                  const match = /language-(\w+)/.exec(className || "");
                  const lang = match ? match[1] : "";
                  const codeString = String(children).replace(/\n$/, "");

                  if (!inline && lang) {
                    return <FencedCodeBlock lang={lang} code={codeString} theme={theme} />;
                  }

                  const mergedClassName = `${className ?? ""} ${inline ? "rounded bg-nexus-bg/80 px-1 py-0.5 text-[11px]" : "rounded-lg bg-nexus-bg/80 p-3 text-xs overflow-x-auto border border-nexus-border/60 block"}`.trim();
                  return (
                    <code className={mergedClassName} {...props}>
                      {children}
                    </code>
                  );
                },
              }}
            >
              {stripAnsiCodes(visibleContent)}
            </ReactMarkdown>
          ) : visibleContent.trim() ? (
            <div className="whitespace-pre-wrap text-[15px] leading-[1.65]">{visibleContent}</div>
          ) : null}
          {/* Soft streaming caret: a 2px pulse appended to the prose, not a full re-render. */}
          {!isUser && isStreaming && visibleContent.trim() && (
            <span
              aria-hidden="true"
              className="ml-1 inline-block h-4 w-[2px] animate-pulse rounded-full bg-nexus-accent align-[-2px]"
            />
          )}

          {!isUser && isStreaming && !visibleContent.trim() && !message.thinking && (!message.toolCalls || message.toolCalls.length === 0) && (!message.activities || message.activities.length === 0) && (
            <div className="mt-2 flex items-center gap-2 text-xs text-nexus-muted">
              <TypingDots />
            </div>
          )}

          {/* Error retry + copy actions (only for error messages) */}
          {!isUser && message.metadata?.kind === "error" && (
            <div className="mt-3 flex items-center gap-2 border-t border-rose-500/20 pt-2">
              <AlertCircle className="h-3.5 w-3.5 text-rose-400" />
              <span className="text-[10px] uppercase tracking-wider text-rose-400/80">
                {message.metadata?.outcome === "interrupted" ? "Interrompido" : "Erro"}
              </span>
              {message.metadata?.canRetry && onRetry && message.metadata?.prompt && (
                <button
                  onClick={() => onRetry(message.metadata!.prompt as string)}
                  className="ml-auto flex items-center gap-1 rounded-md border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 text-[11px] font-medium text-rose-300 transition-colors hover:bg-rose-500/20"
                  title="Reenviar a mesma mensagem"
                >
                  <RefreshCw className="h-3 w-3" />
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

            <RunTimeline
              message={message}
              isStreaming={isStreaming}
              sessionId={sessionId}
            />

            {changedFiles.length > 0 && <CheckpointArtifact files={changedFiles} />}
          </div>
        )}

        {/* Edit mode for user messages */}
        {isUser && isEditing && (
          <div className="mt-2 space-y-2">
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="w-full resize-none rounded-lg border border-nexus-border bg-nexus-bg/40 p-2 text-sm text-nexus-text focus:border-nexus-accent focus:outline-none"
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

        {/* Action buttons (edit, regenerate, copy) — hover-only, 100ms fade */}
        {!isStreaming && visibleContent.trim() && !isEditing && (
          <div className={`mt-2 flex items-center gap-1 opacity-70 transition-opacity duration-100 sm:opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 ${isUser ? "justify-end" : ""}`}>
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
    </motion.div>
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
          aria-label="Aplicar bloco de código"
          title="Copia para aplicar no editor"
        >
          {applied ? "Copiado" : "Aplicar"}
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
          <Check className="h-3 w-3 text-emerald-400" />
          <span className="text-emerald-400">Copiado</span>
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

function CheckpointArtifact({ files }: { files: string[] }) {
  const [copiedList, setCopiedList] = useState(false);
  const [copiedPath, setCopiedPath] = useState<string | null>(null);
  const scheduleListReset = useResetTimer();
  const schedulePathReset = useResetTimer();
  return (
    <details
      data-testid="changed-files-artifact"
      className="overflow-hidden rounded-xl border border-nexus-border/30 bg-nexus-card/20"
    >
      <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2 text-xs [&::-webkit-details-marker]:hidden">
        <span className="font-medium text-nexus-text">Checkpoint</span>
        <span className="tabular-nums text-nexus-muted">({files.length}) ficheiros</span>
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
            <FileCode2 className="h-3.5 w-3.5 shrink-0 text-nexus-muted" aria-hidden="true" />
            <span className="break-all font-mono text-[11px] leading-5 text-nexus-text/80">{path}</span>
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
      {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
    </button>
  );
}

export default memo(MessageBubbleComponent);
