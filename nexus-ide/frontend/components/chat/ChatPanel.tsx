"use client";
import { useMemo, useState, useEffect, useRef } from "react";
import { useAgentStream } from "../../hooks/useAgentStream";
import { getSessionHistory } from "../../lib/api";
import { useModeStore } from "../../stores/modeStore";
import { useThemeStore } from "../../stores/themeStore";
import { useKeyboardShortcuts } from "../../hooks/useKeyboardShortcuts";
import MessageBubble from "./MessageBubble";
import type { AgentName, ChatMessage, StreamEvent } from "../../lib/types";

/** Fold the raw SSE event stream into an ordered list of ChatMessages.
 *
 * Rules:
 *  - every user message the panel sent is already pushed via `pendingUser`.
 *  - `agent_started` opens a new assistant bubble we keep appending to.
 *  - each `token` event appends to that bubble's content.
 *  - `error` replaces the current assistant bubble with an error message.
 *  - `done` / `agent_finished` just close the current bubble.
 */
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
      default: // routing, etc. — ignored in the message list.
        break;
    }
  }
  return out;
}

export default function ChatPanel() {
  const sessionId = "default";
  const { currentMode } = useModeStore();
  const { events, streaming, send, cancel, reset } = useAgentStream(sessionId);
  const [input, setInput] = useState("");
  const [historyMessages, setHistoryMessages] = useState<ChatMessage[]>([]);
  const [pendingUser, setPendingUser] = useState<ChatMessage[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const loadHistory = async () => {
    try {
      console.log("Loading chat history for session:", sessionId);
      const history = await getSessionHistory(sessionId);
      console.log("Loaded history:", history);
      const normalized = history.map((msg, index) => ({
        ...msg,
        id: `${msg.role}-${index}-${msg.timestamp}`,
      }));
      setHistoryMessages(normalized);
      setPendingUser([]);
      reset();
      setHistoryLoaded(true);
    } catch (error) {
      console.error("Failed to load chat history:", error);
      setHistoryLoaded(true);
    }
  };

  // Load chat history from backend on mount
  useEffect(() => {
    loadHistory();
  }, []); // Remove sessionId from deps to prevent re-renders

  // Keyboard shortcuts
  const { toggleTheme } = useThemeStore();
  useKeyboardShortcuts([
    {
      key: "Enter",
      callback: () => {
        if (!streaming && input.trim()) {
          handleSubmit(new Event("submit") as any);
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

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  const lastUserMessage = [...historyMessages, ...pendingUser].reverse().find((message) => message.role === "user")?.content ?? "";

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || streaming) return;
    setPendingUser((prev) => [
      ...prev,
      {
        id: `u-${prev.length}-${Date.now()}`,
        role: "user",
        content: trimmed,
        timestamp: new Date().toISOString(),
      },
    ]);
    // Send the message and wait for streaming to complete
    await send(trimmed, currentMode);
    // Wait a bit to ensure backend has persisted the message
    await new Promise(resolve => setTimeout(resolve, 500));
    // Then reload history
    await loadHistory();
    setInput("");
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

  function handleRegenerate() {
    if (streaming) return;
    if (!lastUserMessage) return;
    void send(lastUserMessage, currentMode).then(() => loadHistory());
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 space-y-1.5 overflow-y-auto px-2 pb-1.5 pt-0">
        {!historyLoaded && (
          <div className="flex h-full items-center justify-center">
            <div className="flex items-center gap-3 text-sm text-gray-500">
              <span className="animate-spin">⏳</span>
              <span>Loading conversation...</span>
            </div>
          </div>
        )}
        {messages.length === 0 && historyLoaded && (
          <div className="flex h-full items-center justify-center text-center">
            <div className="space-y-2">
              <div className="text-3xl">💬</div>
              <div className="text-sm text-gray-500">Start a conversation</div>
              <div className="text-xs text-gray-600">Ask anything about your code</div>
              <div className="flex flex-wrap justify-center gap-1.5 pt-1">
                <button
                  type="button"
                  onClick={() => setInput("Explain this code")}
                  className="rounded-full bg-nexus-border/50 px-2.5 py-1 text-[10px] text-gray-400 hover:bg-nexus-border hover:text-gray-200 transition-colors"
                >
                  Explain code
                </button>
                <button
                  type="button"
                  onClick={() => setInput("Find bugs in this code")}
                  className="rounded-full bg-nexus-border/50 px-2.5 py-1 text-[10px] text-gray-400 hover:bg-nexus-border hover:text-gray-200 transition-colors"
                >
                  Find bugs
                </button>
                <button
                  type="button"
                  onClick={() => setInput("Refactor this for better performance")}
                  className="rounded-full bg-nexus-border/50 px-2.5 py-1 text-[10px] text-gray-400 hover:bg-nexus-border hover:text-gray-200 transition-colors"
                >
                  Refactor
                </button>
              </div>
            </div>
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} message={m} />
        ))}
        <div ref={messagesEndRef} />
      </div>
      <form className="border-t border-nexus-border bg-nexus-panel/50 p-1.5" onSubmit={handleSubmit}>
        <div className="mb-0.5 flex items-center justify-between text-[10px] text-gray-500">
          <span>{sessionId}</span>
          <div className="flex gap-2">
            <button type="button" onClick={handleRegenerate} className="hover:text-gray-300 disabled:opacity-50" disabled={!lastUserMessage || streaming}>
              Regenerate
            </button>
            <button type="button" onClick={handleCancel} className="hover:text-gray-300 disabled:opacity-50" disabled={!streaming}>
              Cancel
            </button>
          </div>
        </div>
        <div className="flex gap-2">
          <textarea
            className="flex-1 min-h-[34px] max-h-[72px] resize-none rounded-lg border border-nexus-border bg-black/30 px-3 py-1 text-sm text-gray-200 placeholder-gray-500 focus:border-nexus-accent focus:outline-none focus:ring-1 focus:ring-nexus-accent/50 transition-all"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your code... (Enter to send, Shift+Enter for newline)"
            disabled={streaming}
            rows={1}
            style={{ fieldSizing: "content" }}
          />
          <button
            className="rounded-lg bg-nexus-accent px-3 py-1 text-sm font-semibold text-black hover:bg-nexus-accent/90 disabled:opacity-50 disabled:cursor-not-allowed transition-all shadow-lg shadow-nexus-accent/20"
            type="submit"
            disabled={streaming || !input.trim()}
          >
            {streaming ? (
              <span className="flex items-center gap-1">
                <span className="animate-spin">⏳</span>
              </span>
            ) : (
              "Send"
            )}
          </button>
        </div>
      </form>
    </div>
  );
}
