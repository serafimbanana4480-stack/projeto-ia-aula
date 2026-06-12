"use client";

import { memo } from "react";
import { Loader2 } from "lucide-react";
import type { ChatMessage } from "../../lib/types";
import AgentBadge from "./AgentBadge";
import ToolCallTimeline from "./ToolCallTimeline";

function MessageBubbleComponent({
  message,
  isStreaming = false,
}: {
  message: ChatMessage;
  isStreaming?: boolean;
}) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded-xl p-3 text-sm ${
          isUser
            ? "bg-nexus-accent/10 text-nexus-text"
            : "bg-nexus-card text-nexus-text border border-nexus-border"
        }`}
      >
        <div className="mb-2 flex items-center justify-between gap-3 text-[11px] text-nexus-muted">
          <div className="flex items-center gap-2">
            {!isUser && message.agent && <AgentBadge agent={message.agent} />}
            <span className="font-medium">{isUser ? "Você" : "NEXUS IDE"}</span>
          </div>
          <span>
            {new Date(message.timestamp).toLocaleTimeString("pt-PT", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>

        <div className="whitespace-pre-wrap leading-relaxed">
          {message.content}
        </div>

        {!isUser && isStreaming && !message.content.trim() && (!message.toolCalls || message.toolCalls.length === 0) && (
          <div className="flex items-center gap-2 text-xs text-nexus-muted">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            <span>A pensar...</span>
          </div>
        )}

        {!isUser && message.toolCalls && message.toolCalls.length > 0 && (
          <ToolCallTimeline calls={message.toolCalls} />
        )}

        {!isUser && message.thinking && (
          <details className="mt-3 rounded border border-nexus-border/50 bg-nexus-bg/50">
            <summary className="cursor-pointer px-3 py-1.5 text-[11px] font-medium text-nexus-muted hover:text-nexus-text">
              💭 Pensamento da IA
            </summary>
            <div className="max-h-48 overflow-y-auto px-3 py-2 text-[11px] text-nexus-muted whitespace-pre-wrap">
              {message.thinking}
            </div>
          </details>
        )}

        {message.metrics && (
          <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-nexus-muted">
            {Object.entries(message.metrics).map(([k, v]) => (
              <span key={k} className="rounded bg-nexus-bg px-2 py-1">
                {k}: {v}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(MessageBubbleComponent);
