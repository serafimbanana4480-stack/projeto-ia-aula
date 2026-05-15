"use client";
import { useCallback, useRef, useState } from "react";
import type { StreamEvent } from "../lib/types";
import { postChat } from "../lib/api";

// Posts a chat message and consumes the SSE body stream incrementally.
// Returns the aggregated events and a send() function.
// TODO: handle backpressure, abort controllers, and reconnection.
export function useAgentStream(sessionId: string) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const activeRequestId = useRef(0);

  const send = useCallback(
    async (message: string, mode = "agent", model = "", projectPath = "") => {
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      const requestId = ++activeRequestId.current;

      setStreaming(true);
      setEvents([]); // Clear previous events for new message

      try {
        const res = await postChat(message, sessionId, mode, controller.signal, model, projectPath);

        // Check if response is ok
        if (!res.ok) {
          const errorText = await res.text();
          if (requestId !== activeRequestId.current) return;
          console.error("Chat request failed:", res.status, errorText);
          setEvents([
            {
              type: "error",
              content: `Request failed: ${res.status} ${errorText}`,
              timestamp: new Date().toISOString(),
            },
          ]);
          setStreaming(false);
          return;
        }

        const reader = res.body?.getReader();
        if (!reader) {
          if (requestId !== activeRequestId.current) return;
          setEvents([
            {
              type: "error",
              content: "No response body received",
              timestamp: new Date().toISOString(),
            },
          ]);
          setStreaming(false);
          return;
        }

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          if (requestId !== activeRequestId.current) return;

          buffer += decoder.decode(value, { stream: true });

          const chunks = buffer.split("\n\n");
          buffer = chunks.pop() || "";

          for (const chunk of chunks) {
            const line = chunk
              .split("\n")
              .find((part) => part.startsWith("data:"));
            if (!line) continue;
            try {
              const jsonStr = line.slice(5).trim();
              const evt = JSON.parse(jsonStr) as StreamEvent;
              if (requestId !== activeRequestId.current) return;
              setEvents((prev) => [...prev, evt]);

              if (evt.type === "done" || evt.type === "agent_finished") {
                return;
              }
            } catch (e) {
              console.error("Failed to parse SSE event:", chunk, e);
            }
          }
        }
      } catch (error) {
        if (controller.signal.aborted || requestId !== activeRequestId.current)
          return;
        console.error("Chat stream error:", error);
        setEvents([
          {
            type: "error",
            content: error instanceof Error ? error.message : "Unknown error",
            timestamp: new Date().toISOString(),
          },
        ]);
      } finally {
        if (requestId === activeRequestId.current) {
          setStreaming(false);
        }
      }
    },
    [sessionId],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, []);

  const reset = useCallback(() => {
    setEvents([]);
  }, []);

  return { events, streaming, send, cancel, reset };
}
