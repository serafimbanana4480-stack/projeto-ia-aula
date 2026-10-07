"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { StreamEvent } from "../lib/types";
import {
  RunEventBuffer,
  isOrderable,
  type RuntimeEventLike,
} from "../lib/eventOrdering";
import { postChat, cancelChatRequest, ApiError, apiUrl } from "../lib/api";
import { authHeaders } from "../lib/auth";
import { clearAuth, refreshAuth } from "../lib/auth";
import { log } from "../lib/log";
import { useChatTelemetryStore } from "../stores/chatTelemetryStore";

/**
 * Shared identity for "this session has no events yet".
 *
 * `eventsBySession[sessionId] ?? []` allocates a brand-new array on every
 * render, so `events` changed identity on every render and the telemetry
 * effect below re-ran on every render. React may also discard a `useMemo`
 * cache at any time, so the fallback has to be a module constant rather than
 * something a memo recomputes.
 */
const NO_EVENTS: StreamEvent[] = [];
const TOKEN_BATCH_WINDOW_MS = 20;
const STREAM_RECONNECT_DELAYS_MS = [250, 500, 1_000] as const;

function createCancellationRequestId(): string {
  if (typeof globalThis.crypto?.randomUUID === "function") {
    return globalThis.crypto.randomUUID();
  }
  return `chat-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function waitForReconnect(delayMs: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    let timer: ReturnType<typeof setTimeout> | null = null;
    const finish = () => {
      if (timer) clearTimeout(timer);
      signal.removeEventListener("abort", finish);
      resolve();
    };
    timer = setTimeout(finish, delayMs);
    signal.addEventListener("abort", finish, { once: true });
  });
}

/**
 * Read one persisted run journal as SSE frames and stop at its synthetic,
 * unsequenced `done` terminator.
 *
 * `GET /api/sessions/{id}/events?run_id=…` replays the durable run journal
 * (`data/runs/{run_id}.jsonl`) and then follows the live bus. For a *finished*
 * run it emits a synthetic unsequenced `done` frame after the journal events;
 * the runtime's sequenced terminal event is part of that journal and must be
 * retained. An expired journal emits only the synthetic terminator, while a
 * live run is bounded by the caller's abort signal.
 *
 * Returns `[]` when the journal no longer exists — history then renders as
 * plain text, which is the truth, rather than pretending a timeline exists.
 */
export async function replayRunEvents(
  sessionId: string,
  runId: string,
  signal?: AbortSignal,
): Promise<StreamEvent[]> {
  if (!runId) return [];
  let response: Response;
  try {
    response = await fetch(
      `${apiUrl(`/api/sessions/${encodeURIComponent(sessionId)}/events`)}?run_id=${encodeURIComponent(runId)}&after_seq=0`,
      { headers: { ...authHeaders(), Accept: "text/event-stream" }, signal },
    );
  } catch (reason) {
    if (!signal?.aborted) {
      log.warn(`Could not replay run ${runId}:`, reason);
    }
    return [];
  }
  if (!response.ok || !response.body) {
    log.warn(`Run ${runId} journal unavailable: ${response.status}`);
    return [];
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const events: StreamEvent[] = [];
  let buffer = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      if (signal?.aborted) {
        await reader.cancel().catch(() => {});
        return events;
      }
      buffer += decoder.decode(value, { stream: true });
      const chunks = buffer.split("\n\n");
      buffer = chunks.pop() || "";
      for (const chunk of chunks) {
        const line = chunk.split("\n").find((part) => part.startsWith("data:"));
        if (!line) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        let event: StreamEvent;
        try {
          event = JSON.parse(payload) as StreamEvent;
        } catch {
          continue;
        }
        // Preserve the runtime's ordered terminal event. The endpoint's
        // synthetic `done` has no sequence envelope and only closes the replay.
        if (
          event.type === "done" &&
          !isOrderable(event as unknown as RuntimeEventLike)
        ) {
          return events;
        }
        events.push(event);
      }
    }
  } catch (reason) {
    if (!signal?.aborted) {
      log.warn(`Run ${runId} replay interrupted:`, reason);
    }
  } finally {
    await reader.cancel().catch(() => {});
  }
  return events;
}

// Posts a chat message and consumes the SSE body stream incrementally.
export function useAgentStream(sessionId: string) {
  const [eventsBySession, setEventsBySession] = useState<Record<string, StreamEvent[]>>({});
  const [streamingBySession, setStreamingBySession] = useState<Record<string, boolean>>({});
  const [errorsBySession, setErrorsBySession] = useState<Record<string, string | null>>({});
  const events = useMemo(
    () => eventsBySession[sessionId] ?? NO_EVENTS,
    [eventsBySession, sessionId],
  );
  const streaming = streamingBySession[sessionId] ?? false;
  const error = errorsBySession[sessionId] ?? null;
  const abortRef = useRef<AbortController | null>(null);
  const pendingTokensBySessionRef = useRef(new Map<string, StreamEvent[]>());
  const tokenFlushTimersRef = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const activeRequestId = useRef(0);
  const activeStreamSessionRef = useRef<string | null>(null);
  const activeRunIdRef = useRef<string | null>(null);
  const streamingSessionsRef = useRef(new Set<string>());
  const activeCancellationRequestId = useRef<string | null>(null);
  const readerRef = useRef<ReadableStreamDefaultReader<Uint8Array> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const gapReplayTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const runEventBufferRef = useRef(new RunEventBuffer());
  const replayAttemptedRef = useRef(false);
  const completionObservedRef = useRef(false);
  const setTelemetry = useChatTelemetryStore((state) => state.setStream);

  const setSessionEvents = useCallback(
    (ownerSessionId: string, update: StreamEvent[] | ((current: StreamEvent[]) => StreamEvent[])) => {
      setEventsBySession((current) => {
        const previous = current[ownerSessionId] ?? [];
        const next = typeof update === "function" ? update(previous) : update;
        return { ...current, [ownerSessionId]: next };
      });
    },
    [],
  );
  const takePendingTokens = useCallback((ownerSessionId: string): StreamEvent[] => {
    const timer = tokenFlushTimersRef.current.get(ownerSessionId);
    if (timer) clearTimeout(timer);
    tokenFlushTimersRef.current.delete(ownerSessionId);
    const pending = pendingTokensBySessionRef.current.get(ownerSessionId) ?? [];
    pendingTokensBySessionRef.current.delete(ownerSessionId);
    return pending;
  }, []);
  const flushPendingTokens = useCallback(
    (ownerSessionId: string) => {
      const pending = takePendingTokens(ownerSessionId);
      if (pending.length === 0) return;
      setSessionEvents(ownerSessionId, (previous) => [...previous, ...pending]);
    },
    [setSessionEvents, takePendingTokens],
  );
  const appendSessionEvent = useCallback(
    (ownerSessionId: string, event: StreamEvent) => {
      if (event.type === "token") {
        const pending = pendingTokensBySessionRef.current.get(ownerSessionId) ?? [];
        pending.push(event);
        pendingTokensBySessionRef.current.set(ownerSessionId, pending);
        if (!tokenFlushTimersRef.current.has(ownerSessionId)) {
          const timer = setTimeout(() => {
            tokenFlushTimersRef.current.delete(ownerSessionId);
            const batch = pendingTokensBySessionRef.current.get(ownerSessionId) ?? [];
            pendingTokensBySessionRef.current.delete(ownerSessionId);
            if (batch.length > 0) {
              setSessionEvents(ownerSessionId, (previous) => [...previous, ...batch]);
            }
          }, TOKEN_BATCH_WINDOW_MS);
          tokenFlushTimersRef.current.set(ownerSessionId, timer);
        }
        return;
      }

      // Preserve stream order: queued text deltas are committed immediately
      // before the next non-token event, in one state update.
      const pending = takePendingTokens(ownerSessionId);
      setSessionEvents(ownerSessionId, (previous) => [...previous, ...pending, event]);
    },
    [setSessionEvents, takePendingTokens],
  );
  const setSessionStreaming = useCallback((ownerSessionId: string, value: boolean) => {
    if (value) streamingSessionsRef.current.add(ownerSessionId);
    else streamingSessionsRef.current.delete(ownerSessionId);
    setStreamingBySession((current) => ({ ...current, [ownerSessionId]: value }));
  }, []);
  const setSessionError = useCallback((ownerSessionId: string, value: string | null) => {
    setErrorsBySession((current) => ({ ...current, [ownerSessionId]: value }));
  }, []);
  const busyOtherSession = Object.keys(streamingBySession).some(
    (ownerSessionId) => ownerSessionId !== sessionId && streamingBySession[ownerSessionId],
  );

  // Publish the stream to the telemetry store (context gauge, phase, token
  // counters). `events` is memoised above so this fires once per *new* event
  // array instead of once per render: re-running it per render restamped
  // `chatTelemetryStore.completedAt` with `Date.now()` on every repaint, so
  // the "completed at" figure was really "last render time" and every
  // duration derived from it was wrong.
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
      const ownerSessionId = activeStreamSessionRef.current;
      cancelServerRequest();
      abortRef.current?.abort();
      if (ownerSessionId) setSessionStreaming(ownerSessionId, false);
      const timeoutMessage =
        `Sem dados do servidor há ${seconds}s. A execução pode ainda estar a decorrer no backend — verifica os logs do servidor ou tenta novamente.`;
      if (ownerSessionId) setSessionError(ownerSessionId, timeoutMessage);
      // Append, never replace: the progress streamed so far must stay visible.
      if (ownerSessionId) {
        appendSessionEvent(ownerSessionId, {
          type: "error",
          content: `Timeout de inatividade: o servidor não enviou dados durante ${seconds}s. Isto não é necessariamente um problema do modelo local — verifica o provider configurado e os logs do backend.`,
          timestamp: new Date().toISOString(),
        });
      }
    }, streamTimeoutMsRef.current);
  }, [appendSessionEvent, cancelServerRequest, setSessionError, setSessionStreaming]);

  const clearInactivityWatchdog = useCallback(() => {
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  const clearGapReplayTimer = useCallback(() => {
    if (gapReplayTimerRef.current) {
      clearTimeout(gapReplayTimerRef.current);
      gapReplayTimerRef.current = null;
    }
  }, []);

  const consumeReplay = useCallback(
    async (
      reader: ReadableStreamDefaultReader<Uint8Array>,
      requestId: number,
      signal: AbortSignal,
      ownerSessionId: string,
    ) => {
      const decoder = new TextDecoder();
      let buffer = "";

      const acceptFrame = (chunk: string) => {
        const line = chunk.split("\n").find((part) => part.startsWith("data:"));
        if (!line) return;
        try {
          const jsonStr = line.slice(5).trim();
          if (!jsonStr) return;
          const event = JSON.parse(jsonStr) as StreamEvent;
          // Keep the runtime `done` that carries the ordered event envelope;
          // ignore only the endpoint's synthetic unsequenced terminator.
          if (
            (event.type === "done" &&
              !isOrderable(event as unknown as RuntimeEventLike)) ||
            !runEventBufferRef.current.push(event as unknown as RuntimeEventLike)
          ) {
            return;
          }
          appendSessionEvent(ownerSessionId, event);
        } catch (reason) {
          log.warn("Failed to parse replayed SSE event:", reason);
        }
      };

      try {
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          if (requestId !== activeRequestId.current || signal.aborted) {
            await reader.cancel();
            return;
          }
          buffer += decoder.decode(value, { stream: true });
          const chunks = buffer.split("\n\n");
          buffer = chunks.pop() || "";
          for (const chunk of chunks) acceptFrame(chunk);
        }
        buffer += decoder.decode();
        if (buffer.trim()) acceptFrame(buffer);
      } finally {
        if (requestId !== activeRequestId.current || signal.aborted) {
          await reader.cancel().catch(() => {});
        }
      }
    },
    [appendSessionEvent],
  );

  const scheduleGapReplay = useCallback(
    (ownerSessionId: string, requestId: number, signal: AbortSignal) => {
      const eventBuffer = runEventBufferRef.current;
      if (
        replayAttemptedRef.current ||
        gapReplayTimerRef.current ||
        !eventBuffer.hasMissingSeqs()
      ) {
        return;
      }

      // Give the live stream a short window to deliver out-of-order frames
      // before asking the backend's durable event journal for the gap.
      gapReplayTimerRef.current = setTimeout(() => {
        gapReplayTimerRef.current = null;
        const firstMissingSeq = eventBuffer.firstMissingSeq();
        const runId = eventBuffer.currentRunId;
        if (
          requestId !== activeRequestId.current ||
          signal.aborted ||
          firstMissingSeq === null ||
          !runId
        ) {
          return;
        }

        replayAttemptedRef.current = true;
        const afterSeq = Math.max(0, firstMissingSeq - 1);
        const replayUrl = `${apiUrl(`/api/sessions/${encodeURIComponent(ownerSessionId)}/events`)}?run_id=${encodeURIComponent(runId)}&after_seq=${afterSeq}`;
        void (async () => {
          try {
            const response = await fetch(replayUrl, {
              headers: {
                ...authHeaders(),
                Accept: "text/event-stream",
              },
              signal,
            });
            if (!response.ok || !response.body) {
              log.warn("Could not replay missing runtime events:", response.status);
              const missingSeq = eventBuffer.firstMissingSeq();
              if (
                missingSeq !== null &&
                completionObservedRef.current &&
                requestId === activeRequestId.current &&
                !signal.aborted
              ) {
                setSessionError(
                  ownerSessionId,
                  `A resposta terminou, mas a timeline ficou incompleta: falta o evento ${missingSeq}. O texto recebido pode estar incompleto.`,
                );
              }
              return;
            }
            await consumeReplay(response.body.getReader(), requestId, signal, ownerSessionId);
            if (
              requestId === activeRequestId.current &&
              !runEventBufferRef.current.hasMissingSeqs()
            ) {
              replayAttemptedRef.current = false;
            } else if (
              completionObservedRef.current &&
              requestId === activeRequestId.current &&
              !signal.aborted
            ) {
              const missingSeq = eventBuffer.firstMissingSeq();
              if (missingSeq !== null) {
                setSessionError(
                  ownerSessionId,
                  `A resposta terminou, mas a timeline ficou incompleta: falta o evento ${missingSeq}. O texto recebido pode estar incompleto.`,
                );
              }
            }
          } catch (reason) {
            if (!signal.aborted) {
              log.warn("Runtime event replay failed:", reason);
              const missingSeq = eventBuffer.firstMissingSeq();
              if (
                missingSeq !== null &&
                completionObservedRef.current &&
                requestId === activeRequestId.current
              ) {
                setSessionError(
                  ownerSessionId,
                  `A resposta terminou, mas a timeline ficou incompleta: falta o evento ${missingSeq}. O texto recebido pode estar incompleto.`,
                );
              }
            }
          }
        })();
      }, 1_500);
    },
    [consumeReplay, setSessionError],
  );

  // Consume an SSE stream and recover transient disconnects from the same
  // durable run journal, without resending the user's message.
  const consumeStream = useCallback(
    async (
      reader: ReadableStreamDefaultReader<Uint8Array>,
      requestId: number,
      cancellationRequestId: string,
      signal: AbortSignal,
      ownerSessionId: string,
    ): Promise<void> => {
      let receivedEvent = false;
      let completed = false;
      let currentReader: ReadableStreamDefaultReader<Uint8Array> | null = reader;
      let reconnectAttempts = 0;
      let latestReadError: unknown = null;
      let recoveryFailure: string | null = null;
      let acceptedEventOnConnection = false;

      const acceptFrame = (chunk: string): void => {
        const line = chunk.split("\n").find((part) => part.startsWith("data:"));
        if (!line) return;
        try {
          const jsonStr = line.slice(5).trim();
          if (!jsonStr) return;
          const evt = JSON.parse(jsonStr) as StreamEvent;
          if (requestId !== activeRequestId.current) return;
          if (!runEventBufferRef.current.push(evt as unknown as RuntimeEventLike)) return;
          receivedEvent = true;
          acceptedEventOnConnection = true;
          if (typeof evt.run_id === "string") activeRunIdRef.current = evt.run_id;
          appendSessionEvent(ownerSessionId, evt);
          if (isOrderable(evt as unknown as RuntimeEventLike)) {
            scheduleGapReplay(ownerSessionId, requestId, signal);
          }

          if (evt.type === "error") {
            setSessionError(ownerSessionId, evt.content || "O provedor não conseguiu responder.");
          }

          if (evt.type === "done") {
            completed = true;
            completionObservedRef.current = true;
          }
        } catch (reason) {
          log.error("Failed to parse SSE event:", chunk, reason);
        }
      };

      try {
        while (!completed) {
          if (requestId !== activeRequestId.current || signal.aborted) break;

          if (currentReader) {
            const decoder = new TextDecoder();
            let buffer = "";
            try {
              while (true) {
                const { value, done } = await currentReader.read();
                if (done) break;
                if (requestId !== activeRequestId.current || signal.aborted) {
                  await currentReader.cancel().catch(() => {});
                  break;
                }

                // Any byte from the server is proof of life: reset the inactivity
                // watchdog so long autonomous runs are never killed mid-work.
                resetInactivityWatchdog();

                buffer += decoder.decode(value, { stream: true });
                const chunks = buffer.split("\n\n");
                buffer = chunks.pop() || "";
                for (const chunk of chunks) {
                  acceptFrame(chunk);
                  if (completed || requestId !== activeRequestId.current) break;
                }
                if (completed || requestId !== activeRequestId.current || signal.aborted) break;
              }
              buffer += decoder.decode();
              if (buffer.trim() && !signal.aborted && !completed) acceptFrame(buffer);
            } catch (reason) {
              latestReadError = reason;
            }
            if (acceptedEventOnConnection) reconnectAttempts = 0;
            acceptedEventOnConnection = false;
            currentReader = null;
          }

          if (completed || requestId !== activeRequestId.current || signal.aborted) break;

          const runId = activeRunIdRef.current || runEventBufferRef.current.currentRunId;
          if (!runId || reconnectAttempts >= STREAM_RECONNECT_DELAYS_MS.length) break;

          // The current connection ended without a terminal `done`. Reattach to
          // the same durable run journal; never POST the user's prompt again.
          const delayMs = STREAM_RECONNECT_DELAYS_MS[reconnectAttempts];
          reconnectAttempts += 1;
          await waitForReconnect(delayMs, signal);
          if (completed || requestId !== activeRequestId.current || signal.aborted) break;

          const firstMissingSeq = runEventBufferRef.current.firstMissingSeq();
          const afterSeq = firstMissingSeq !== null
            ? Math.max(0, firstMissingSeq - 1)
            : runEventBufferRef.current.lastSeq;
          const replayUrl = `${apiUrl(`/api/sessions/${encodeURIComponent(ownerSessionId)}/events`)}?run_id=${encodeURIComponent(runId)}&after_seq=${afterSeq}`;
          try {
            const response = await fetch(replayUrl, {
              headers: { ...authHeaders(), Accept: "text/event-stream" },
              signal,
            });
            if (requestId !== activeRequestId.current || signal.aborted) break;
            if (!response.ok || !response.body) {
              recoveryFailure = `HTTP ${response.status}: não foi possível recuperar a execução`;
              // Retry only server-side transient failures. Other statuses (for
              // example an expired session or missing run) need user attention.
              if (response.status < 500 || reconnectAttempts >= STREAM_RECONNECT_DELAYS_MS.length) {
                break;
              }
              continue;
            }
            currentReader = response.body.getReader();
            readerRef.current = currentReader;
            acceptedEventOnConnection = false;
            latestReadError = null;
            recoveryFailure = null;
            resetInactivityWatchdog();
          } catch (reason) {
            if (signal.aborted) break;
            latestReadError = reason;
          }
        }
      } finally {
        if (requestId === activeRequestId.current) {
          clearInactivityWatchdog();
          setSessionStreaming(ownerSessionId, false);
          if (completed && activeCancellationRequestId.current === cancellationRequestId) {
            activeCancellationRequestId.current = null;
          }
          if (signal.aborted) return;
          if (!receivedEvent) {
            setSessionError(ownerSessionId, "O servidor não devolveu dados. Verifica se o backend está a correr e se o provider configurado está acessível.");
            appendSessionEvent(ownerSessionId, {
                type: "error",
                content:
                  "O servidor não devolveu dados. Verifica se o backend está a correr e se o provider de modelos configurado está acessível.",
                timestamp: new Date().toISOString(),
              });
          } else if (!completed) {
            const message = recoveryFailure
              ? `A ligação ao servidor foi interrompida e a recuperação falhou (${recoveryFailure}). A execução pode ainda estar ativa; podes voltar a ligar ou cancelá-la.`
              : "A ligação ao servidor foi interrompida antes de terminar. A execução pode ainda estar ativa; podes voltar a ligar ou cancelá-la.";
            if (latestReadError) {
              log.warn("Chat stream ended before its terminal event:", latestReadError);
            }
            setSessionError(ownerSessionId, message);
          }
        }
      }
    },
    [
      appendSessionEvent,
      resetInactivityWatchdog,
      clearInactivityWatchdog,
      scheduleGapReplay,
      setSessionError,
      setSessionStreaming,
    ],
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
      modelIsConcrete = false,
    ): Promise<boolean> => {
      if ([...streamingSessionsRef.current].some((owner) => owner !== sessionId)) {
        setSessionError(sessionId, "Outra conversa ainda tem uma execução ativa. Espera que termine antes de enviar nesta sessão.");
        return false;
      }
      // ChatPanel steers the active run explicitly. A second send reaching
      // this hook for the same session is therefore a duplicate submit; never
      // cancel a healthy run and POST the same prompt again.
      if (streamingSessionsRef.current.has(sessionId)) return false;
      // Cancel any previous request
      cancelServerRequest();
      abortRef.current?.abort();
      flushPendingTokens(sessionId);
      clearInactivityWatchdog();
      clearGapReplayTimer();
      runEventBufferRef.current.reset();
      replayAttemptedRef.current = false;
      completionObservedRef.current = false;
      activeStreamSessionRef.current = sessionId;
      activeRunIdRef.current = null;
      const controller = new AbortController();
      abortRef.current = controller;
      const requestId = ++activeRequestId.current;
      const cancellationRequestId = createCancellationRequestId();
      activeCancellationRequestId.current = cancellationRequestId;

      setSessionStreaming(sessionId, true);
      setSessionError(sessionId, null);
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
          modelIsConcrete,
        );

        if (!res.ok) {
          const errorText = await res.text();
          if (requestId !== activeRequestId.current) return false;
          if (activeCancellationRequestId.current === cancellationRequestId) {
            activeCancellationRequestId.current = null;
          }
          setSessionError(sessionId, `Erro ${res.status}: ${errorText}`);
          appendSessionEvent(sessionId, {
              type: "error",
              content: `Pedido falhou: ${res.status} ${errorText}`,
              timestamp: new Date().toISOString(),
            });
          clearInactivityWatchdog();
          setSessionStreaming(sessionId, false);
          return false;
        }

        const reader = res.body?.getReader();
        readerRef.current = reader || null;
        if (!reader) {
          if (requestId !== activeRequestId.current) return false;
          if (activeCancellationRequestId.current === cancellationRequestId) {
            activeCancellationRequestId.current = null;
          }
          setSessionError(sessionId, "Sem resposta do servidor");
          appendSessionEvent(sessionId, {
              type: "error",
              content: "Não foi recebida resposta do servidor.",
              timestamp: new Date().toISOString(),
            });
          clearInactivityWatchdog();
          setSessionStreaming(sessionId, false);
          return false;
        }

        await consumeStream(reader, requestId, cancellationRequestId, controller.signal, sessionId);
        return true;
      } catch (error) {
        if (controller.signal.aborted || requestId !== activeRequestId.current)
          return false;
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
                modelIsConcrete,
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
                    sessionId,
                  );
                  return true;
                }
              }
              return false;
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
          return false;
        }
        if (activeCancellationRequestId.current === cancellationRequestId) {
          activeCancellationRequestId.current = null;
        }
        clearInactivityWatchdog();
        setSessionError(sessionId, msg);
        appendSessionEvent(sessionId, {
            type: "error",
            content: msg,
            timestamp: new Date().toISOString(),
          });
        setSessionStreaming(sessionId, false);
        return false;
      }
    },
    [
      sessionId,
      consumeStream,
      cancelServerRequest,
      resetInactivityWatchdog,
      clearInactivityWatchdog,
      clearGapReplayTimer,
      appendSessionEvent,
      flushPendingTokens,
      setSessionError,
      setSessionStreaming,
    ],
  );

  const resume = useCallback(
    async (runId: string) => {
      if ([...streamingSessionsRef.current].some((owner) => owner !== sessionId)) {
        setSessionError(sessionId, "Outra conversa ainda tem uma execução ativa. Espera que termine antes de recuperar esta sessão.");
        return;
      }
      cancelServerRequest();
      abortRef.current?.abort();
      clearInactivityWatchdog();
      clearGapReplayTimer();
      flushPendingTokens(sessionId);
      runEventBufferRef.current = new RunEventBuffer(runId);
      replayAttemptedRef.current = false;
      activeStreamSessionRef.current = sessionId;
      activeRunIdRef.current = runId;
      const controller = new AbortController();
      abortRef.current = controller;
      const requestId = ++activeRequestId.current;
      setSessionStreaming(sessionId, true);
      setSessionError(sessionId, null);
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
        await consumeStream(reader, requestId, "", controller.signal, sessionId);
      } catch (reason) {
        if (controller.signal.aborted || requestId !== activeRequestId.current) return;
        clearInactivityWatchdog();
        setSessionStreaming(sessionId, false);
        setSessionError(sessionId, reason instanceof Error ? reason.message : "Não foi possível recuperar a missão.");
      }
    },
    [
      sessionId,
      cancelServerRequest,
      clearInactivityWatchdog,
      resetInactivityWatchdog,
      consumeStream,
      clearGapReplayTimer,
      flushPendingTokens,
      setSessionError,
      setSessionStreaming,
    ],
  );

  const cancel = useCallback(() => {
    const ownerSessionId = activeStreamSessionRef.current;
    if (ownerSessionId !== sessionId) return;
    // The user asked for this run to stop, so record it as an ordered event
    // BEFORE the reader is killed. The backend does emit `RUN_CANCELLED`
    // (`progress`, `data.kind === "run_cancelled"`), but aborting first means
    // that frame can never arrive — the cancellation used to leave no trace at
    // all: no timeline row, no banner, and every in-flight tool call stuck
    // spinning because `foldRun.closeDanglingWork` only runs on done/error.
    // `data.requested_by`/`data.local` say the fact is the user's request
    // observed client-side, not a server confirmation; the wording matches the
    // server's own "a pedido do utilizador". `foldRun` de-duplicates this
    // against a server frame that arrives late, so the timeline shows one
    // cancellation line, not two.
    const seq = runEventBufferRef.current.lastSeq + 1;
    const runId = activeRunIdRef.current ?? runEventBufferRef.current.currentRunId ?? undefined;
    appendSessionEvent(ownerSessionId, {
      type: "progress",
      content: "execução parada a pedido do utilizador",
      data: {
        kind: "run_cancelled",
        runtime_type: "run_cancelled",
        requested_by: "user",
        local: true,
      },
      timestamp: new Date().toISOString(),
      ...(runId ? { run_id: runId } : {}),
      seq,
      event_id: `local-cancellation-${runId ?? "run"}-${seq}`,
    });
    cancelServerRequest();
    abortRef.current?.abort();
    readerRef.current?.cancel().catch(() => {});
    flushPendingTokens(sessionId);
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    setSessionStreaming(ownerSessionId, false);
  }, [
    appendSessionEvent,
    cancelServerRequest,
    flushPendingTokens,
    sessionId,
    setSessionStreaming,
  ]);

  const reset = useCallback(() => {
    if (!streamingSessionsRef.current.has(sessionId)) {
      setSessionEvents(sessionId, []);
      takePendingTokens(sessionId);
      if (streamingSessionsRef.current.size === 0) {
        clearGapReplayTimer();
        runEventBufferRef.current.reset();
        replayAttemptedRef.current = false;
      }
    }
    setSessionError(sessionId, null);
  }, [clearGapReplayTimer, sessionId, setSessionError, setSessionEvents, takePendingTokens]);

  const getActiveRunId = useCallback(
    () =>
      activeStreamSessionRef.current === sessionId &&
      streamingSessionsRef.current.has(sessionId)
        ? activeRunIdRef.current
        : null,
    [sessionId],
  );
  const getActiveRunSessionId = useCallback(
    () => {
      const ownerSessionId = activeStreamSessionRef.current;
      return ownerSessionId && streamingSessionsRef.current.has(ownerSessionId)
        ? ownerSessionId
        : null;
    },
    [],
  );

  // Cleanup on unmount
  useEffect(() => {
    const tokenFlushTimers = tokenFlushTimersRef.current;
    const pendingTokens = pendingTokensBySessionRef.current;
    return () => {
      cancelServerRequest();
      abortRef.current?.abort();
      readerRef.current?.cancel().catch(() => {});
      clearGapReplayTimer();
      for (const timer of tokenFlushTimers.values()) clearTimeout(timer);
      tokenFlushTimers.clear();
      pendingTokens.clear();
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
        timeoutRef.current = null;
      }
    };
  }, [cancelServerRequest, clearGapReplayTimer]);

  return {
    events,
    streaming,
    busyOtherSession,
    error,
    send,
    resume,
    cancel,
    reset,
    getActiveRunId,
    getActiveRunSessionId,
  };
}
