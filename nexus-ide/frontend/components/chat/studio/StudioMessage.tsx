"use client";

import { memo, useCallback, useEffect, useState } from "react";
import { AlertCircle, Copy, Check, Pencil, RefreshCw, Reply, RotateCw, Save, X } from "lucide-react";
import type { ChatMessage } from "../../../lib/types";
import { useThemeStore } from "../../../stores/themeStore";
import { sanitizeAssistantContent } from "../../../lib/chatPresentation";
import { agentColor } from "../../../lib/foldRun";
import AgentTranscript from "../AgentTranscript";
import RunTimeline from "../RunTimeline";
import { AssistantMarkdown } from "../MessageBubble";
import IdentityMark from "./IdentityMark";

function timeValue(timestamp: string): Date | null {
  const date = new Date(timestamp);
  return Number.isNaN(date.getTime()) ? null : date;
}

function relativeTime(date: Date): string {
  const diffSec = Math.floor((Date.now() - date.getTime()) / 1000);
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

function StudioMessageComponent({
  message,
  sessionId = "default",
  isStreaming = false,
  onRetry,
  onEdit,
  onRegenerate,
  onReply,
}: {
  message: ChatMessage;
  sessionId?: string;
  isStreaming?: boolean;
  onRetry?: (prompt: string) => void;
  onEdit?: (messageId: string, newContent: string) => void;
  onRegenerate?: (messageId: string) => void;
  onReply?: (excerpt: string) => void;
}) {
  const theme = useThemeStore((s) => s.theme);
  const isUser = message.role === "user";
  const isError = !isUser && message.metadata?.kind === "error";
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(message.content);
  const [copied, setCopied] = useState(false);
  const stamp = timeValue(message.timestamp);
  const [when, setWhen] = useState(() => (stamp ? relativeTime(stamp) : ""));
  const visible = isUser ? message.content : sanitizeAssistantContent(message.content);
  const useTranscript = !isUser && !isError && (message.events?.length ?? 0) > 0;
  const color = agentColor(message.agent || "NEXUS");
  const name = message.agent || "NEXUS";
  const changedFiles = Array.isArray(message.metadata?.changedFiles)
    ? message.metadata.changedFiles.filter((path): path is string => typeof path === "string" && path.trim().length > 0)
    : [];

  useEffect(() => {
    const timer = setInterval(() => {
      const next = timeValue(message.timestamp);
      setWhen(next ? relativeTime(next) : "");
    }, 30_000);
    return () => clearInterval(timer);
  }, [message.timestamp]);

  const renderSegment = useCallback(
    (text: string) => {
      const clean = sanitizeAssistantContent(text);
      return clean.trim() ? <AssistantMarkdown text={clean} theme={theme} /> : null;
    },
    [theme],
  );

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(visible);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  };

  const actions = !isStreaming && visible.trim() && !editing ? (
    <div className="mt-2 flex items-center gap-0.5 opacity-100 sm:opacity-0 sm:group-hover:opacity-100 sm:group-focus-within:opacity-100 [@media(hover:none)]:opacity-100">
      {isUser && onEdit && (
        <button type="button" onClick={() => setEditing(true)} aria-label="Editar mensagem" className="rounded-md p-1.5 text-nexus-faint hover:bg-nexus-elevated hover:text-nexus-text">
          <Pencil className="h-3.5 w-3.5" />
        </button>
      )}
      {!isUser && onRegenerate && !isError && (
        <button type="button" onClick={() => onRegenerate(message.id)} aria-label="Regenerar resposta" className="rounded-md p-1.5 text-nexus-faint hover:bg-nexus-elevated hover:text-nexus-text">
          <RotateCw className="h-3.5 w-3.5" />
        </button>
      )}
      {onReply && !isError && (
        <button type="button" onClick={() => onReply(visible)} aria-label="Responder" className="rounded-md p-1.5 text-nexus-faint hover:bg-nexus-elevated hover:text-nexus-text">
          <Reply className="h-3.5 w-3.5" />
        </button>
      )}
      {!isError && (
        <button type="button" onClick={() => void copy()} aria-label="Copiar mensagem" className="rounded-md p-1.5 text-nexus-faint hover:bg-nexus-elevated hover:text-nexus-text">
          {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
        </button>
      )}
    </div>
  ) : null;

  if (isUser) {
    return (
      <article className="group flex justify-end" data-role="user">
        <div className="max-w-[min(100%,34rem)]">
          <div className="mb-1.5 flex items-center justify-end gap-2 text-[11px] text-nexus-faint">
            <span className="font-medium text-nexus-muted">Tu</span>
            <time dateTime={stamp?.toISOString()}>{when}</time>
          </div>
          <div className="rounded-2xl rounded-br-md border border-nexus-accent/25 bg-nexus-accent/[0.07] px-4 py-3 text-[15px] leading-relaxed text-nexus-text">
            {editing ? (
              <div className="space-y-2">
                <textarea
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  rows={Math.max(2, draft.split("\n").length)}
                  className="w-full resize-none rounded-lg border border-nexus-border bg-nexus-bg/50 p-2 text-sm text-nexus-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent/50"
                  autoFocus
                />
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      if (onEdit && draft.trim() && draft !== message.content) onEdit(message.id, draft.trim());
                      setEditing(false);
                    }}
                    className="inline-flex items-center gap-1 rounded-md bg-nexus-accent/20 px-2 py-1 text-[11px] font-medium text-nexus-accent"
                  >
                    <Save className="h-3 w-3" /> Guardar e regenerar
                  </button>
                  <button
                    type="button"
                    onClick={() => { setEditing(false); setDraft(message.content); }}
                    className="inline-flex items-center gap-1 rounded-md border border-nexus-border px-2 py-1 text-[11px] text-nexus-muted"
                  >
                    <X className="h-3 w-3" /> Cancelar
                  </button>
                </div>
              </div>
            ) : (
              <p className="whitespace-pre-wrap break-words">{visible}</p>
            )}
          </div>
          {actions}
        </div>
      </article>
    );
  }

  return (
    <article className="group grid grid-cols-[36px_minmax(0,1fr)] gap-x-3" data-role="assistant">
      <IdentityMark name={name} color={isError ? "#f0a0a8" : color} />
      <div className="min-w-0">
        <header className="mb-2 flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-[13px] font-semibold tracking-tight text-nexus-text">{name}</span>
          <span className="text-[11px] text-nexus-faint">{name === "NEXUS" ? "Assistente" : "Agente"}</span>
          {isStreaming && (
            <span className="inline-flex items-center gap-1.5 text-[11px] text-nexus-accent-bright">
              <span className="h-1.5 w-1.5 rounded-full bg-nexus-accent motion-safe:animate-pulse" />
              A escrever
            </span>
          )}
          {isError && (
            <span className="inline-flex items-center gap-1 text-[11px] font-medium text-red-300">
              <AlertCircle className="h-3 w-3" />
              {message.metadata?.outcome === "interrupted" ? "Interrompido" : "Erro"}
            </span>
          )}
          <time className="text-[11px] tabular-nums text-nexus-faint" dateTime={stamp?.toISOString()}>{when}</time>
        </header>
        <div
          className={isError
            ? "rounded-xl border border-red-400/30 bg-red-500/[0.06] px-3.5 py-3 text-[15px]"
            : "text-[15px] leading-relaxed"}
          data-testid="assistant-response"
        >
          {useTranscript ? (
            <AgentTranscript
              events={message.events ?? []}
              isStreaming={isStreaming}
              fallbackContent={visible}
              renderMarkdown={renderSegment}
            />
          ) : visible.trim() ? (
            <AssistantMarkdown text={visible} theme={theme} />
          ) : isStreaming ? (
            <p className="text-[13px] text-nexus-faint">A pensar…</p>
          ) : null}
          {!isUser && !useTranscript && isStreaming && visible.trim() && (
            <span aria-hidden="true" className="nx-caret" />
          )}
          {isError && message.metadata?.canRetry && onRetry && message.metadata.prompt && (
            <button
              type="button"
              onClick={() => onRetry(String(message.metadata?.prompt))}
              className="mt-3 inline-flex items-center gap-1 rounded-md border border-red-400/30 px-2 py-1 text-[11px] font-medium text-red-200 hover:bg-red-500/10"
            >
              <RefreshCw className="h-3 w-3" /> Tentar novamente
            </button>
          )}
        </div>
        {changedFiles.length > 0 && (
          <ul className="mt-3 space-y-1 text-[12px] text-nexus-muted">
            {changedFiles.map((file) => (
              <li key={file} className="truncate font-mono">{file}</li>
            ))}
          </ul>
        )}
        {!useTranscript && (
          <div className="mt-2">
            <RunTimeline message={message} isStreaming={isStreaming} sessionId={sessionId} />
          </div>
        )}
        {actions}
      </div>
    </article>
  );
}

const StudioMessage = memo(StudioMessageComponent);
export default StudioMessage;
