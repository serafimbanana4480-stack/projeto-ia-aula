"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { StreamEvent } from "../lib/types";
import { postChat, ApiError } from "../lib/api";
import { clearAuth } from "../lib/auth";
import { log } from "../lib/log";

const STREAM_TIMEOUT_MS = 90000; // 90s timeout for the entire stream (Ollama may need time to load models)

// Posts a chat message and consumes the SSE body stream incrementally.
export function useAgentStream(sessionId: string) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeRequestId = useRef(0);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);

  const clearStreamTimeout = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const send = useCallback(
    async (message: string, mode = "auto", model = "", projectPath = "", thinkingStrength?: string) => {
      // Cancel any previous request
      abortRef.current?.abort();
      clearStreamTimeout();
      const controller = new AbortController();
      abortRef.current = controller;
      const requestId = ++activeRequestId.current;

      setStreaming(true);
      setError(null);
      setEvents([]);

      // Auto-timeout if stream takes too long
      timeoutRef.current = setTimeout(() => {
        if (requestId === activeRequestId.current) {
          controller.abort();
          setStreaming(false);
          setError("O modelo demorou demasiado tempo a responder. O Ollama pode estar a carregar o modelo na memória. Tenta novamente ou escolhe um modelo mais leve.");
          setEvents([
            {
              type: "error",
              content: "Timeout: O modelo não respondeu dentro do tempo esperado (90s). O Ollama pode estar a carregar o modelo na VRAM.",
              timestamp: new Date().toISOString(),
            },
          ]);
        }
      }, STREAM_TIMEOUT_MS);

      try {
        const res = await postChat(message, sessionId, mode, controller.signal, model, projectPath, thinkingStrength);

        if (!res.ok) {
          const errorText = await res.text();
          if (requestId !== activeRequestId.current) return;
          clearStreamTimeout();
          setError(`Erro ${res.status}: ${errorText}`);
          setEvents([
            {
              type: "error",
              content: `Pedido falhou: ${res.status} ${errorText}`,
              timestamp: new Date().toISOString(),
            },
          ]);
          setStreaming(false);
          return;
        }

        const reader = res.body?.getReader();
        readerRef.current = reader || null;
        if (!reader) {
          if (requestId !== activeRequestId.current) return;
          clearStreamTimeout();
          setError("Sem resposta do servidor");
          setEvents([
            {
              type: "error",
              content: "Não foi recebida resposta do servidor.",
              timestamp: new Date().toISOString(),
            },
          ]);
          setStreaming(false);
          return;
        }

        const decoder = new TextDecoder();
        let buffer = "";
        let receivedData = false;

        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          if (requestId !== activeRequestId.current) {
            reader.cancel().catch(() => {});
            return;
          }

          receivedData = true;
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
              if (!jsonStr) continue;
              const evt = JSON.parse(jsonStr) as StreamEvent;
              if (requestId !== activeRequestId.current) return;
              setEvents((prev) => [...prev, evt]);

              if (evt.type === "done" || evt.type === "agent_finished") {
                clearStreamTimeout();
                setStreaming(false);
                return;
              }
            } catch (e) {
              log.error("Failed to parse SSE event:", chunk, e);
            }
          }
        }

        // Stream ended without explicit done event
        if (requestId === activeRequestId.current) {
          clearStreamTimeout();
          setStreaming(false);
          if (!receivedData) {
            setError("O modelo não devolveu dados. Verifica se o Ollama está a correr.");
            setEvents([
              {
                type: "error",
                content: "O modelo não devolveu dados. Verifica se o Ollama está a correr com o modelo selecionado.",
                timestamp: new Date().toISOString(),
              },
            ]);
          }
        }
      } catch (error) {
        if (controller.signal.aborted || requestId !== activeRequestId.current)
          return;
        clearStreamTimeout();
        const msg = error instanceof Error ? error.message : "Erro desconhecido";
        if (error instanceof ApiError && error.status === 401 && typeof window !== "undefined") {
          clearAuth();
          window.location.href = "/login?expired=1";
          return;
        }
        setError(msg);
        setEvents([
          {
            type: "error",
            content: msg,
            timestamp: new Date().toISOString(),
          },
        ]);
        setStreaming(false);
      }
    },
    [sessionId, clearStreamTimeout],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    readerRef.current?.cancel().catch(() => {});
    clearStreamTimeout();
    setStreaming(false);
  }, [clearStreamTimeout]);

  const reset = useCallback(() => {
    setEvents([]);
    setError(null);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      readerRef.current?.cancel().catch(() => {});
      clearStreamTimeout();
    };
  }, [clearStreamTimeout]);

  return { events, streaming, error, send, cancel, reset };
}
