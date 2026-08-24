"use client";

import ReactMarkdown from "react-markdown";
import { memo, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Copy, Check, RefreshCw, AlertCircle, Pencil, RotateCw, Save, X } from "lucide-react";
import { Prism as SyntaxHighlighter } from "react-syntax-highlighter";
import {
  oneDark,
  oneLight,
} from "react-syntax-highlighter/dist/esm/styles/prism";
import type { ChatMessage, AgentName } from "../../lib/types";
import { stripAnsiCodes } from "../../lib/utils";
import { useThemeStore } from "../../stores/themeStore";
import RunTimeline from "./RunTimeline";
import { sanitizeAssistantContent } from "../../lib/chatPresentation";
import { agentColor } from "../../lib/foldRun";

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
  const color = agentColor(message.agent || "");

  useEffect(() => {
    const interval = setInterval(() => {
      setRelativeTime(getRelativeTime(new Date(message.timestamp)));
    }, 30000);
    return () => clearInterval(interval);
  }, [message.timestamp]);

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3, ease: "easeOut" }}
      className={`group flex gap-3 ${isUser ? "justify-end" : "justify-start"}`}
    >
      {/* Assistant avatar */}
      {!isUser && (
        <div
          className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-[10px] font-bold text-white shadow-md"
          style={{
            background: `linear-gradient(135deg, ${color}, ${color}cc)`,
            boxShadow: `0 2px 8px -2px ${color}66`,
          }}
          title={message.agent || "NEXUS"}
        >
          {(message.agent || "N").charAt(0).toUpperCase()}
        </div>
      )}

      <div
        className={`min-w-0 text-[15px] leading-7 transition-all duration-200 ${
          isUser
            ? "max-w-[78%] rounded-2xl rounded-br-md bg-gradient-to-br from-nexus-accent to-nexus-accent-deep p-4 text-white shadow-lg shadow-nexus-accent/20 hover:scale-[1.01]"
            : "w-full max-w-[880px]"
        }`}
      >
        {/* Meta row: name + time */}
        <div className={`mb-1 flex items-center gap-2 text-[11px] ${isUser ? "justify-end" : ""}`}>
          {!isUser && (
            <>
              <span className="font-semibold" style={{ color }}>
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
          {isUser && <span className="font-medium text-white/70">Você</span>}
          <span className={`tabular-nums opacity-60 ${isUser ? "text-white/60" : "text-nexus-muted"}`}>
            {relativeTime}
          </span>
        </div>

        <div
          className={
            !isUser
              ? "rounded-2xl rounded-tl-md border border-nexus-border/40 bg-nexus-card/50 px-4 py-3 shadow-sm backdrop-blur-sm"
              : ""
          }
        >
          {visibleContent.trim() && typeof ReactMarkdown !== "undefined" ? (
            <ReactMarkdown
              className="prose prose-base max-w-none leading-7"
              components={{
                code({ inline, className, children, ...props }: any) {
                  const match = /language-(\w+)/.exec(className || "");
                  const lang = match ? match[1] : "";
                  const codeString = String(children).replace(/\n$/, "");

                  if (!inline && lang) {
                    const style = theme === "light" ? oneLight : oneDark;
                    return (
                      <div className="relative group/code">
                        <div className="absolute right-2 top-2 z-10 flex items-center gap-1.5">
                          <span className="rounded bg-nexus-bg/60 px-1.5 py-0.5 text-[9px] uppercase tracking-wider text-nexus-muted font-mono border border-nexus-border/40">
                            {lang}
                          </span>
                          <CopyCodeButton code={codeString} />
                        </div>
                        <SyntaxHighlighter
                          language={lang}
                          style={style}
                          customStyle={{
                            margin: 0,
                            borderRadius: "0.5rem",
                            fontSize: "0.75rem",
                            lineHeight: "1.4",
                            padding: "1rem",
                            background: "rgba(11, 11, 20, 0.8)",
                          }}
                          PreTag="div"
                          showLineNumbers={codeString.split("\n").length > 3}
                        >
                          {codeString}
                        </SyntaxHighlighter>
                      </div>
                    );
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
            <div className="whitespace-pre-wrap leading-relaxed">{visibleContent}</div>
          ) : null}

          {!isUser && isStreaming && !visibleContent.trim() && !message.thinking && (!message.toolCalls || message.toolCalls.length === 0) && (!message.activities || message.activities.length === 0) && (
            <div className="mt-2 flex items-center gap-2 text-xs text-nexus-muted">
              <TypingDots />
            </div>
          )}

          {!isUser && (
            <RunTimeline
              message={message}
              isStreaming={isStreaming}
              sessionId={sessionId}
            />
          )}

          {/* Error retry + copy actions (only for error messages) */}
          {!isUser && message.metadata?.kind === "error" && (
            <div className="mt-3 flex items-center gap-2 border-t border-rose-500/20 pt-2">
              <AlertCircle className="h-3.5 w-3.5 text-rose-400" />
              <span className="text-[10px] uppercase tracking-wider text-rose-400/80">
                Erro
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

        {/* Action buttons (edit, regenerate, copy) */}
        {!isStreaming && visibleContent.trim() && !isEditing && (
          <div className={`mt-1 flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100 ${isUser ? "justify-end" : ""}`}>
            {/* Edit button (user messages only) */}
            {isUser && onEdit && (
              <button
                onClick={() => setIsEditing(true)}
                className="flex items-center gap-1 rounded p-1 text-[10px] text-nexus-muted hover:bg-nexus-bg/40 hover:text-nexus-text"
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

      {/* User avatar */}
      {isUser && (
        <div className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-nexus-border/60 bg-nexus-elevated text-[10px] font-bold text-nexus-muted shadow-sm">
          TU
        </div>
      )}
    </motion.div>
  );
}

function CopyCodeButton({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async (e) => {
        e.stopPropagation();
        try {
          await navigator.clipboard.writeText(code);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        } catch {}
      }}
      className="flex items-center gap-1 rounded border border-nexus-border/40 bg-nexus-bg/60 px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wider text-nexus-muted opacity-0 transition-all hover:text-nexus-text group-hover/code:opacity-100"
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

function CopyMessageButton({ text, className = "" }: { text: string; className?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={async (e) => {
        e.stopPropagation();
        try {
          await navigator.clipboard.writeText(text);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        } catch {}
      }}
      className={`flex items-center gap-1 rounded p-1 text-[10px] text-nexus-muted hover:bg-nexus-bg/40 hover:text-nexus-text ${className}`}
      title="Copiar mensagem"
    >
      {copied ? <Check className="h-3 w-3 text-emerald-400" /> : <Copy className="h-3 w-3" />}
    </button>
  );
}

export default memo(MessageBubbleComponent);
