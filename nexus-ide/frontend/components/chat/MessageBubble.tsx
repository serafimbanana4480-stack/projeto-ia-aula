"use client";
import { memo } from "react";
import type { ChatMessage } from "../../lib/types";
import AgentBadge from "./AgentBadge";

function MessageBubbleComponent({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div className={`max-w-[85%] rounded-xl border p-3 text-sm shadow-sm ${isUser ? "border-blue-500/30 bg-blue-500/10" : "border-nexus-border bg-nexus-panel/90"}`}>
        <div className="mb-2 flex items-center justify-between gap-3 text-[11px] text-gray-400">
          <div className="flex items-center gap-2">
            {!isUser && message.agent && <AgentBadge agent={message.agent} />}
            <span>{isUser ? "You" : "Assistant"}</span>
          </div>
          <span>{new Date(message.timestamp).toLocaleTimeString()}</span>
        </div>

        <div className="whitespace-pre-wrap leading-6 text-gray-100">{message.content}</div>

        {message.metrics && (
          <div className="mt-3 flex flex-wrap gap-2 text-[11px] text-gray-400">
            {Object.entries(message.metrics).map(([k, v]) => (
              <span key={k} className="rounded bg-black/20 px-2 py-1">
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
