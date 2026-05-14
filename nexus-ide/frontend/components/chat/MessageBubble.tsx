"use client";

import { memo } from "react";
import type { ChatMessage } from "../../lib/types";
import AgentBadge from "./AgentBadge";

function MessageBubbleComponent({ message }: { message: ChatMessage }) {
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
            <span className="font-medium">{isUser ? "Você" : "LUSO AI"}</span>
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
