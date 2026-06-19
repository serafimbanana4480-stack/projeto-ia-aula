"use client";

import ReactMarkdown from "react-markdown";
import { memo, useEffect, useState } from "react";
import { motion } from "framer-motion";
import { Copy, Check, RefreshCw, AlertCircle } from "lucide-react";
import type { ChatMessage, AgentName } from "../../lib/types";
import { stripAnsiCodes } from "../../lib/utils";
import AgentBadge from "./AgentBadge";
import ToolCallTimeline from "./ToolCallTimeline";
import ThinkingBlock from "./ThinkingBlock";

const AGENT_HEX_COLORS: Record<AgentName, string> = {
  ROUTER: "#4b5563",
  ARCHITECT: "#4f46e5",
  RESEARCHER: "#2563eb",
  CODER: "#059669",
  ANALYZER: "#d97706",
  DEBUGGER: "#dc2626",
  DOCUMENTER: "#0284c7",
  OPTIMIZER: "#9333ea",
  DASHBOARD: "#0d9488",
  ORCHESTRATOR: "#7c3aed",
  SWARM: "#db2777",
  MICRO: "#6b7280",
};

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
  isStreaming = false,
  onRetry,
}: {
  message: ChatMessage;
  isStreaming?: boolean;
  onRetry?: (prompt: string) => void;
}) {
  const isUser = message.role === "user";
  const [relativeTime, setRelativeTime] = useState(() =>
    getRelativeTime(new Date(message.timestamp)),
  );

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
      className={`flex ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`group max-w-[85%] rounded-2xl p-4 text-sm shadow-lg transition-all duration-200 hover:shadow-xl ${
          isUser
            ? "bg-gradient-to-br from-nexus-accent/90 to-nexus-accent/70 text-white hover:scale-[1.01]"
            : "bg-nexus-card text-nexus-text border border-nexus-border/60 hover:border-nexus-accent/30 hover:shadow-nexus-accent/5"
        }`}
      >
        <div className="mb-2 flex items-center justify-between gap-3 text-[11px] text-nexus-muted">
          <div className="flex items-center gap-2.5">
            {!isUser && (
              <motion.div
                initial={{ scale: 0.8, opacity: 0 }}
                animate={{ scale: 1, opacity: 1 }}
                transition={{ delay: 0.1 }}
                className="flex items-center gap-2"
              >
                <AgentBadge agent={message.agent || "ROUTER"} />
                  <div
                    className="flex h-7 w-7 items-center justify-center rounded-full text-[10px] font-bold text-white shadow-md"
                    style={{
                      background: `linear-gradient(135deg, ${AGENT_HEX_COLORS[message.agent || "ROUTER"]}, ${AGENT_HEX_COLORS[message.agent || "ROUTER"]}dd)`,
                    }}
                  >
                    {(message.agent || "N").charAt(0).toUpperCase()}
                  </div>
              </motion.div>
            )}
            <span className="font-medium">{isUser ? "Você" : message.agent || "NEXUS IDE"}</span>
          </div>
          <span className="tabular-nums opacity-70">{relativeTime}</span>
        </div>

        {typeof ReactMarkdown !== "undefined" ? (
          <ReactMarkdown
            className="prose prose-sm max-w-none"
            components={{
              code({ inline, className, children, ...props }: any) {
                const mergedClassName = `${className ?? ""} ${inline ? "rounded bg-nexus-bg/80 px-1 py-0.5 text-[11px]" : "rounded-lg bg-nexus-bg/80 p-3 text-xs overflow-x-auto border border-nexus-border/60 block"}`.trim();
                if (inline) {
                  return (
                    <code className={mergedClassName} {...props}>
                      {children}
                    </code>
                  );
                }
                return (
                  <code className={mergedClassName} {...props}>
                    {children}
                  </code>
                );
              },
            }}
          >
            {stripAnsiCodes(message.content)}
          </ReactMarkdown>
        ) : (
          <div className="whitespace-pre-wrap leading-relaxed">{message.content}</div>
        )}

        {!isUser && isStreaming && !message.content.trim() && (!message.toolCalls || message.toolCalls.length === 0) && (
          <div className="mt-2 flex items-center gap-2 text-xs text-nexus-muted">
            <TypingDots />
          </div>
        )}

        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <ToolCallTimeline calls={message.toolCalls} />
        )}

        {!isUser && message.thinking && (
          <ThinkingBlock content={message.thinking} />
        )}

        {message.metrics && (
          <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-nexus-muted">
            {Object.entries(message.metrics).map(([k, v], idx) => (
              <span
                key={`${idx}-${k}`}
                className="rounded-lg bg-nexus-bg/80 px-2.5 py-1 backdrop-blur-sm"
              >
                {k}: {v}
              </span>
            ))}
          </div>
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
            <CopyMessageButton text={message.content} />
          </div>
        )}

        {/* Copy button for regular assistant messages */}
        {!isUser && message.metadata?.kind !== "error" && message.content.trim() && (
          <CopyMessageButton text={message.content} className="absolute -top-1 right-2 opacity-0 transition-opacity group-hover:opacity-100" />
        )}
      </div>
    </motion.div>
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
