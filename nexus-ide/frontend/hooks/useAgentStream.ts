"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import type { StreamEvent } from "../lib/types";
import { postChat, cancelChatRequest, ApiError, apiUrl } from "../lib/api";
import { authHeaders } from "../lib/auth";
import { clearAuth, refreshAuth } from "../lib/auth";
import { log } from "../lib/log";
import { useChatTelemetryStore } from "../stores/chatTelemetryStore";

function createCancellationRequestId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

// Posts a chat message and consumes the SSE body stream incrementally.
export function useAgentStream(sessionId: string) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const activeRequestId = useRef(0);
  const activeCancellationRequestId = useRef<string | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const setTelemetry = useChatTelemetryStore((state) => state.setStream);

  useEffect(() => {
    setTelemetry(sessionId, streaming, events);
  }, [events, sessionId, setTelemetry, streaming]);

  const cancelServerRequest = useCallback(() => {
    const requestId = activeCancellationRequestId.current;
    if (!requestId) return;

    activeCancellationRequestId.current = null;
    void cancelChatRequest(requestId).catch((reason) => {
      // The browser abort remains a useful fallback if the server has already
      // finished or cannot be reached.  Do not replace the user's chat error
      // state with a best-effort cleanup failure.
      log.warn("Failed to cancel server-side chat request:", reason);
    });
  }, []);

  // Inactivity watchdog configuration. The effective limit is computed in
  // ``send`` and stored here so the watchdog callback can report the real
  // duration instead of a hard-coded (wrong) number.
  const streamTimeoutMsRef = useRef(1_800_000);

  // Arms (or re-arms) the inactivity watchdog. Any byte received from the
  // server resets it, so long autonomous runs that keep streaming are never
  // killed — only a genuinely silent connection is.
  const resetInactivityWatchdog = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }
    timeoutRef.current = setTimeout(() => {
      const seconds = Math.round(streamTimeoutMsRef.current / 1000);
      cancelServerRequest();
      abortRef.current?.abort();
      setStreaming(false);
      setError(
        `Sem dados do servidor há ${seconds}s. A execução pode ainda estar a decorrer no backend — verifica os logs do servidor ou tenta novamente.`,
      );
      // Append, never replace: the progress streamed so far must stay visible.
      setEvents((prev) => [
        ...prev,
        {
          type: "error",
          content: `Timeout de inatividade: o servidor não enviou dados durante ${seconds}s. Isto não é necessariamente um problema do modelo local — verifica o provider configurado e os logs do backend.`,
          timestamp: new Date().toISOString(),
        },
      ]);
    }, streamTimeoutMsRef.current);
  }, [cancelServerRequest]);

  const clearInactivityWatchdog = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  // Consume an SSE stream reader, appending events to state. Returns true if
  // the stream completed normally (or was superseded by a newer request).
  const consumeStream = useCallback(
    async (
      reader: ReadableStreamDefaultReader<Uint8Array>,
      requestId: number,
      cancellationRequestId: string,
      signal: AbortSignal,
    ): Promise<void> => {
      const decoder = new TextDecoder();
      let buffer = "";
      let receivedEvent = false;
      let completed = false;

      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          if (requestId !== activeRequestId.current) {
            reader.cancel().catch(() => {});
            return;
          }

          // Any byte from the server is proof of life: reset the inactivity
          // watchdog so long autonomous runs are never killed mid-work.
          resetInactivityWatchdog();

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
              receivedEvent = true;
              setEvents((prev) => [...prev, evt]);

              if (evt.type === "error") {
                setError(evt.content || "O provedor não conseguiu responder.");
              }

              if (evt.type === "done") {
                completed = true;
                setStreaming(false);
                return;
              }
            } catch (e) {
              log.error("Failed to parse SSE event:", chunk, e);
            }
          }
        }
      } finally {
        if (requestId === activeRequestId.current) {
          clearInactivityWatchdog();
          setStreaming(false);
          if (activeCancellationRequestId.current === cancellationRequestId) {
            activeCancellationRequestId.current = null;
          }
          if (signal.aborted) return;
          if (!receivedEvent) {
            setError("O servidor não devolveu dados. Verifica se o backend está a correr e se o provider configurado está acessível.");
            setEvents((prev) => [
              ...prev,
              {
                type: "error",
                content:
                  "O servidor não devolveu dados. Verifica se o backend está a correr e se o provider de modelos configurado está acessível.",
                timestamp: new Date().toISOString(),
              },
            ]);
          } else if (!completed) {
            setError("A ligação ao provedor foi interrompida antes de terminar. Podes tentar novamente.");
          }
        }
      }
    },
    [resetInactivityWatchdog, clearInactivityWatchdog],
  );

  const send = useCallback(
    async (
      message: string,
      mode = "auto",
      model = "",
      projectPath = "",
      thinkingStrength?: string,
      swarmOptions?: {
        agents?: string[];
        strategy?: string;
        operationalMode?: string;
      },
      provider = "",
    ) => {
      // Cancel any previous request
      cancelServerRequest();
      abortRef.current?.abort();
      clearInactivityWatchdog();
      const controller = new AbortController();
      abortRef.current = controller;
      const requestId = ++activeRequestId.current;
      const cancellationRequestId = createCancellationRequestId();
      activeCancellationRequestId.current = cancellationRequestId;

      setStreaming(true);
      setError(null);
      // Intentionally do NOT clear events here so previous errors stay
      // visible in the chat history. The new request will append tokens
      // on top of the existing events.

      // Long-running autonomous runs can spend several minutes inside a tool
      // or provider. The old hard-coded 6-minute watchdog closed the UI while
      // the backend was still working. Keep a bounded, configurable safety
      // limit instead — applied as an INACTIVITY timeout: it is reset every
      // time the server sends data, so healthy long runs are never killed.
      const configuredTimeout = Number(
        process.env.NEXT_PUBLIC_CHAT_STREAM_TIMEOUT_MS ?? 1_800_000,
      );
      streamTimeoutMsRef.current = Number.isFinite(configuredTimeout)
        ? Math.max(120_000, configuredTimeout)
        : 1_800_000;
      resetInactivityWatchdog();

      try {
        const res = await postChat(
          message,
          sessionId,
          mode,
          controller.signal,
          model,
          projectPath,
          thinkingStrength,
          swarmOptions,
          cancellationRequestId,
          provider,
        );

        if (!res.ok) {
          const errorText = await res.text();
          if (requestId !== activeRequestId.current) return;
          if (activeCancellationRequestId.current === cancellationRequestId) {
            activeCancellationRequestId.current = null;
          }
          setError(`Erro ${res.status}: ${errorText}`);
          setEvents((prev) => [
            ...prev,
            {
              type: "error",
              content: `Pedido falhou: ${res.status} ${errorText}`,
              timestamp: new Date().toISOString(),
            },
          ]);
          clearInactivityWatchdog();
          setStreaming(false);
          return;
        }

        const reader = res.body?.getReader();
        readerRef.current = reader || null;
        if (!reader) {
          if (requestId !== activeRequestId.current) return;
          if (activeCancellationRequestId.current === cancellationRequestId) {
            activeCancellationRequestId.current = null;
          }
          setError("Sem resposta do servidor");
          setEvents((prev) => [
            ...prev,
            {
              type: "error",
              content: "Não foi recebida resposta do servidor.",
              timestamp: new Date().toISOString(),
            },
          ]);
          clearInactivityWatchdog();
          setStreaming(false);
          return;
        }

        await consumeStream(reader, requestId, cancellationRequestId, controller.signal);
      } catch (error) {
        if (controller.signal.aborted || requestId !== activeRequestId.current)
          return;
        const msg = (() => {
          if (error instanceof ApiError) {
            if (error.status === 0)
              return "Não foi possível ligar ao backend.";
            return `${error.message}${error.responseText ? ` — ${error.responseText.slice(0, 240)}` : ""}`;
          }
          if (error instanceof Error) return error.message;
          return "Erro desconhecido";
        })();
        if (error instanceof ApiError && error.status === 401 && typeof window !== "undefined") {
          // Try to silently refresh the access token before giving up.
          const refreshed = await refreshAuth();
          if (refreshed) {
            // Retry the request once with the new token.
            try {
              const retryResponse = await postChat(
                message,
                sessionId,
                mode,
                controller.signal,
                model,
                projectPath,
                thinkingStrength,
                swarmOptions,
                cancellationRequestId,
                provider,
              );
              if (requestId === activeRequestId.current) {
                const retryReader = retryResponse.body?.getReader();
                readerRef.current = retryReader || null;
                if (retryReader) {
                  await consumeStream(
                    retryReader,
                    requestId,
                    cancellationRequestId,
                    controller.signal,
                  );
                }
              }
              return;
            } catch (retryErr) {
              if (
                retryErr instanceof ApiError &&
                retryErr.status === 401 &&
                typeof window !== "undefined"
              ) {
                // fall through to login redirect below
              } else {
                throw retryErr;
              }
            }
          }
          clearAuth();
          if (!window.location.pathname.startsWith("/login")) {
            window.location.href = "/login?expired=1";
          }
          return;
        }
        if (activeCancellationRequestId.current === cancellationRequestId) {
          activeCancellationRequestId.current = null;
        }
        clearInactivityWatchdog();
        setError(msg);
        setEvents((prev) => [
          ...prev,
          {
            type: "error",
            content: msg,
            timestamp: new Date().toISOString(),
          },
        ]);
        setStreaming(false);
      }
    },
    [sessionId, consumeStream, cancelServerRequest, resetInactivityWatchdog, clearInactivityWatchdog],
  );

  const resume = useCallback(
    async (runId: string) => {
      cancelServerRequest();
      abortRef.current?.abort();
      clearInactivityWatchdog();
      const controller = new AbortController();
      abortRef.current = controller;
      const requestId = ++activeRequestId.current;
      setStreaming(true);
      setError(null);
      streamTimeoutMsRef.current = 1_800_000;
      resetInactivityWatchdog();

      try {
        const response = await fetch(
          `${apiUrl(`/api/sessions/${encodeURIComponent(sessionId)}/events`)}?run_id=${encodeURIComponent(runId)}`,
          {
            headers: {
              ...authHeaders(),
              Accept: "text/event-stream",
            },
            signal: controller.signal,
          },
        );
        if (!response.ok || !response.body) {
          throw new ApiError(`HTTP ${response.status}: não foi possível recuperar a missão`, response.status);
        }
        const reader = response.body.getReader();
        readerRef.current = reader;
        await consumeStream(reader, requestId, "", controller.signal);
      } catch (reason) {
        if (controller.signal.aborted || requestId !== activeRequestId.current) return;
        clearInactivityWatchdog();
        setStreaming(false);
        setError(reason instanceof Error ? reason.message : "Não foi possível recuperar a missão.");
      }
    },
    [
      sessionId,
      cancelServerRequest,
      clearInactivityWatchdog,
      resetInactivityWatchdog,
      consumeStream,
    ],
  );

  const cancel = useCallback(() => {
    cancelServerRequest();
    abortRef.current?.abort();
    readerRef.current?.cancel().catch(() => {});
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    setStreaming(false);
  }, [cancelServerRequest]);

  const reset = useCallback(() => {
    setEvents([]);
    setError(null);
  }, []);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cancelServerRequest();
      abortRef.current?.abort();
      readerRef.current?.cancel().catch(() => {});
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
  }, [cancelServerRequest]);

  return { events, streaming, error, send, resume, cancel, reset };
}
