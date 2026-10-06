import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import type { StreamEvent } from "../../lib/types";
import { foldRun } from "../../lib/foldRun";
import { replayRunEvents, useAgentStream } from "../../hooks/useAgentStream";

const { mockRefreshAuth, mockClearAuth } = vi.hoisted(() => ({
  mockRefreshAuth: vi.fn(),
  mockClearAuth: vi.fn(),
}));

vi.mock("../../lib/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/auth")>();
  return { ...actual, refreshAuth: mockRefreshAuth, clearAuth: mockClearAuth };
});

vi.mock("../../stores/chatTelemetryStore", () => ({
  useChatTelemetryStore: (
    selector: (state: { setStream: () => void }) => () => void,
  ) => selector({ setStream: () => undefined }),
}));

let tsCounter = 0;

function evt(partial: Partial<StreamEvent> & { type: StreamEvent["type"] }): StreamEvent {
  tsCounter += 1;
  return { timestamp: `2026-01-01T00:00:${String(tsCounter).padStart(2, "0")}Z`, ...partial };
}

/** Frame carrying the runtime ordering envelope (run_id, seq, event_id). */
function stamped(runId: string, seq: number, eventId = `e${seq}`): StreamEvent {
  return evt({ type: "progress", content: `step-${seq}`, run_id: runId, seq, event_id: eventId });
}

function terminal(runId: string, seq: number): StreamEvent {
  return evt({ type: "done", run_id: runId, seq, event_id: `${runId}-done-${seq}` });
}

function token(content: string): StreamEvent {
  return evt({ type: "token", content });
}

function done(): StreamEvent {
  return evt({ type: "done" });
}

function sseBody(frames: StreamEvent[]): string {
  return frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
}

function sseResponse(frames: StreamEvent[]): Response {
  const encoder = new TextEncoder();
  const payload = sseBody(frames);
  return {
    ok: true,
    status: 200,
    body: new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(payload));
        controller.close();
      },
    }),
    text: async () => payload,
    headers: new Headers(),
  } as unknown as Response;
}

function interruptedSseResponse(frames: StreamEvent[]): Response {
  const encoder = new TextEncoder();
  const payload = sseBody(frames);
  let delivered = false;
  return {
    ok: true,
    status: 200,
    body: new ReadableStream<Uint8Array>({
      start(controller) {
        if (payload) controller.enqueue(encoder.encode(payload));
      },
      pull(controller) {
        if (delivered) return;
        delivered = true;
        controller.error(new Error("connection reset"));
      },
    }),
    text: async () => payload,
    headers: new Headers(),
  } as unknown as Response;
}

/** A stream that delivers one chunk and then stays open (never completes). */
function hangingSseResponse(frame?: StreamEvent): Response {
  const encoder = new TextEncoder();
  return {
    ok: true,
    status: 200,
    body: new ReadableStream<Uint8Array>({
      start(controller) {
        if (frame) controller.enqueue(encoder.encode(sseBody([frame])));
      },
    }),
    text: async () => "",
    headers: new Headers(),
  } as unknown as Response;
}

function controllableSseResponse(): {
  response: Response;
  send: (frames: StreamEvent[]) => void;
  close: () => void;
} {
  const encoder = new TextEncoder();
  let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
  const response = {
    ok: true,
    status: 200,
    body: new ReadableStream<Uint8Array>({
      start(controller) {
        streamController = controller;
      },
    }),
    text: async () => "",
    headers: new Headers(),
  } as unknown as Response;
  return {
    response,
    send: (frames) => streamController?.enqueue(encoder.encode(sseBody(frames))),
    close: () => streamController?.close(),
  };
}

describe("useAgentStream", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    mockRefreshAuth.mockReset();
    mockClearAuth.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    globalThis.fetch = originalFetch;
  });

  it("keeps the ordered runtime terminal event before the synthetic replay terminator", async () => {
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        stamped("r-terminal-history", 1),
        terminal("r-terminal-history", 2),
        done(),
      ]),
    );

    const events = await replayRunEvents("s1", "r-terminal-history");

    expect(events.map((event) => event.type)).toEqual(["progress", "done"]);
    expect(events[1]).toMatchObject({
      run_id: "r-terminal-history",
      seq: 2,
      event_id: "r-terminal-history-done-2",
    });
  });

  it("parses multiple SSE frames into ordered events", async () => {
    fetchMock.mockResolvedValueOnce(sseResponse([token("ol"), token("á"), done()]));
    const { result } = renderHook(() => useAgentStream("s1"));

    await act(async () => {
      await result.current.send("oi");
    });

    expect(result.current.error).toBeNull();
    expect(result.current.streaming).toBe(false);
    expect(result.current.events.map((e) => e.type)).toEqual(["token", "token", "done"]);
    expect(result.current.events.map((e) => e.content)).toEqual(["ol", "á", undefined]);
  });

  it("reports a rejected chat request so the composer can restore its draft", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));
    const { result } = renderHook(() => useAgentStream("s1"));
    let accepted = true;

    await act(async () => {
      accepted = await result.current.send("mensagem com anexo");
    });

    expect(accepted).toBe(false);
    expect(result.current.streaming).toBe(false);
    expect(result.current.error).toContain("backend");
  });

  it("batches token deltas for 20ms and flushes them before a status event", async () => {
    vi.useFakeTimers();
    const stream = controllableSseResponse();
    fetchMock.mockResolvedValueOnce(stream.response);
    const { result } = renderHook(() => useAgentStream("s1"));
    let activeSend: Promise<boolean> | undefined;

    await act(async () => {
      activeSend = result.current.send("oi");
      stream.send([token("primeiro "), token("segundo")]);
      for (let i = 0; i < 12; i += 1) await Promise.resolve();
    });

    expect(result.current.events).toEqual([]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(19);
    });
    expect(result.current.events).toEqual([]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
      await Promise.resolve();
    });
    expect(result.current.events.map((event) => event.content)).toEqual([
      "primeiro ",
      "segundo",
    ]);

    await act(async () => {
      stream.send([evt({ type: "progress", content: "a validar" }), done()]);
      stream.close();
      for (let i = 0; i < 12; i += 1) await Promise.resolve();
      await activeSend;
    });
    expect(result.current.events.map((event) => event.content)).toEqual([
      "primeiro ",
      "segundo",
      "a validar",
      undefined,
    ]);
    expect(result.current.streaming).toBe(false);
  });

  it("deduplicates a duplicated runtime event by event_id", async () => {
    const first = stamped("r-dup", 1, "dup-id");
    fetchMock.mockResolvedValueOnce(
      sseResponse([first, stamped("r-dup", 2, "other-id"), { ...first }]),
    );
    const { result } = renderHook(() => useAgentStream("s1"));

    await act(async () => {
      await result.current.send("oi");
    });

    expect(result.current.events).toHaveLength(2);
    expect(result.current.events.filter((e) => e.event_id === "dup-id")).toHaveLength(1);
  });

  it("recovers an unexpected EOF from the same run cursor without reposting the prompt", async () => {
    vi.useFakeTimers();
    fetchMock
      .mockResolvedValueOnce(sseResponse([stamped("r-eof", 1)]))
      .mockResolvedValueOnce(
        sseResponse([stamped("r-eof", 2), terminal("r-eof", 3), done()]),
      );
    const { result } = renderHook(() => useAgentStream("s1"));
    let activeSend: Promise<boolean> | undefined;

    await act(async () => {
      activeSend = result.current.send("continua");
      for (let i = 0; i < 12; i += 1) await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
      await activeSend;
    });

    const chatPosts = fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/chat"));
    const replayCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/api/sessions/s1/events"),
    );
    expect(chatPosts).toHaveLength(1);
    expect(replayCalls).toHaveLength(1);
    expect(String(replayCalls[0][0])).toContain("run_id=r-eof");
    expect(String(replayCalls[0][0])).toContain("after_seq=1");
    expect(
      result.current.events
        .map((event) => event.seq)
        .filter((seq): seq is number => typeof seq === "number"),
    ).toEqual([1, 2, 3]);
    expect(result.current.events.at(-1)).toMatchObject({
      type: "done",
      seq: 3,
      event_id: "r-eof-done-3",
    });
    expect(result.current.error).toBeNull();
    expect(result.current.streaming).toBe(false);
  });

  it("ignores a duplicate submit while this session already has an active run", async () => {
    fetchMock
      .mockResolvedValueOnce(hangingSseResponse(stamped("r-single-submit", 1)))
      .mockResolvedValue({ ok: true, status: 200 } as Response);
    const { result } = renderHook(() => useAgentStream("s1"));
    let activeSend: Promise<boolean> | undefined;

    await act(async () => {
      activeSend = result.current.send("pedido original");
      for (let i = 0; i < 12; i += 1) await Promise.resolve();
    });
    expect(result.current.streaming).toBe(true);

    let duplicateAccepted = true;
    await act(async () => {
      duplicateAccepted = await result.current.send("pedido duplicado");
    });

    expect(duplicateAccepted).toBe(false);
    expect(result.current.streaming).toBe(true);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/chat"))).toHaveLength(1);
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/cancel"))).toBe(false);

    act(() => result.current.cancel());
    await act(async () => {
      await activeSend;
    });
  });

  it("recovers a dropped connection from before the earliest missing sequence", async () => {
    vi.useFakeTimers();
    fetchMock
      // Seq 2 is missing when the first connection drops, even though seq 3
      // was already received. Resuming after seq 3 would lose the missing event.
      .mockResolvedValueOnce(
        sseResponse([stamped("r-gap-reconnect", 1), stamped("r-gap-reconnect", 3)]),
      )
      .mockResolvedValueOnce(
        sseResponse([stamped("r-gap-reconnect", 2), stamped("r-gap-reconnect", 3), done()]),
      );
    const { result } = renderHook(() => useAgentStream("s1"));
    let activeSend: Promise<boolean> | undefined;

    await act(async () => {
      activeSend = result.current.send("continua");
      for (let i = 0; i < 12; i += 1) await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
      await activeSend;
    });

    const replayCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/api/sessions/s1/events"),
    );
    expect(replayCall).toBeDefined();
    expect(String(replayCall![0])).toContain("run_id=r-gap-reconnect");
    expect(String(replayCall![0])).toContain("after_seq=1");
    const seqs = result.current.events
      .map((event) => event.seq)
      .filter((seq): seq is number => typeof seq === "number")
      .sort((a, b) => a - b);
    expect(seqs).toEqual([1, 2, 3]);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/chat"))).toHaveLength(1);
  });

  it("recovers a reader error through the durable run replay endpoint", async () => {
    vi.useFakeTimers();
    fetchMock
      .mockResolvedValueOnce(interruptedSseResponse([stamped("r-reset", 1)]))
      .mockResolvedValueOnce(sseResponse([stamped("r-reset", 2), done()]));
    const { result } = renderHook(() => useAgentStream("s1"));
    let activeSend: Promise<boolean> | undefined;

    await act(async () => {
      activeSend = result.current.send("continua");
      for (let i = 0; i < 12; i += 1) await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(250);
      await activeSend;
    });

    expect(
      result.current.events
        .map((event) => event.seq)
        .filter((seq): seq is number => typeof seq === "number"),
    ).toEqual([1, 2]);
    expect(result.current.events.at(-1)?.type).toBe("done");
    expect(result.current.error).toBeNull();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/chat"))).toHaveLength(1);
  });

  it("bounds reconnection attempts and does not retry the chat POST", async () => {
    vi.useFakeTimers();
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/chat")) {
        return sseResponse([stamped("r-exhaust", 1)]);
      }
      return sseResponse([]);
    });
    const { result } = renderHook(() => useAgentStream("s1"));
    let activeSend: Promise<boolean> | undefined;

    await act(async () => {
      activeSend = result.current.send("continua");
      for (let i = 0; i < 12; i += 1) await Promise.resolve();
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
      await activeSend;
    });

    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/chat"))).toHaveLength(1);
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/sessions/s1/events")),
    ).toHaveLength(3);
    expect(result.current.streaming).toBe(false);
    expect(result.current.error).toContain("interrompida antes de terminar");
  });

  it("keeps a live run and its events attached to the originating chat", async () => {
    fetchMock
      .mockResolvedValueOnce(hangingSseResponse(stamped("r-session-a", 1)))
      .mockResolvedValue({ ok: true, status: 200 } as Response);
    const { result, rerender } = renderHook(
      ({ sessionId }: { sessionId: string }) => useAgentStream(sessionId),
      { initialProps: { sessionId: "session-a" } },
    );
    let activeSend: Promise<boolean> | undefined;

    await act(async () => {
      activeSend = result.current.send("continua a trabalhar");
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(result.current.streaming).toBe(true);
    expect(result.current.getActiveRunId()).toBe("r-session-a");
    expect(result.current.events).toHaveLength(1);

    rerender({ sessionId: "session-b" });
    expect(result.current.streaming).toBe(false);
    expect(result.current.busyOtherSession).toBe(true);
    expect(result.current.getActiveRunId()).toBeNull();
    expect(result.current.events).toEqual([]);

    await act(async () => {
      await result.current.send("esta mensagem não pode ir para o run A");
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(result.current.error).toContain("Outra conversa");

    act(() => result.current.reset());
    rerender({ sessionId: "session-a" });
    expect(result.current.streaming).toBe(true);
    expect(result.current.busyOtherSession).toBe(false);
    expect(result.current.getActiveRunId()).toBe("r-session-a");
    expect(result.current.events).toHaveLength(1);

    act(() => result.current.cancel());
    await act(async () => {
      await activeSend;
    });
    expect(result.current.streaming).toBe(false);
  });

  it("detects a sequence gap and replays once from the contiguous prefix", async () => {
    vi.useFakeTimers();
    // Live stream loses seq 3 and 4: client sees 1, 2, 5.
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        stamped("r-gap", 1),
        stamped("r-gap", 2),
        stamped("r-gap", 5),
        done(),
      ]),
    );
    // Gap replay resends 3, 4, the duplicate of 5, and the terminal event.
    fetchMock.mockResolvedValueOnce(
      sseResponse([
        stamped("r-gap", 3),
        stamped("r-gap", 4),
        stamped("r-gap", 5),
        terminal("r-gap", 6),
        done(),
      ]),
    );
    const { result } = renderHook(() => useAgentStream("s1"));

    await act(async () => {
      await result.current.send("oi");
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500);
    });

    const replayCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/api/sessions/s1/events"),
    );
    expect(replayCalls).toHaveLength(1);
    expect(String(replayCalls[0][0])).toContain("run_id=r-gap");
    expect(String(replayCalls[0][0])).toContain("after_seq=2");

    // The missing events were inserted; the replayed duplicate was dropped.
    const seqs = result.current.events
      .map((e) => e.seq)
      .filter((s): s is number => typeof s === "number");
    expect(seqs.sort((a, b) => a - b)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(result.current.events).toContainEqual(
      expect.objectContaining({
        type: "done",
        run_id: "r-gap",
        seq: 6,
        event_id: "r-gap-done-6",
      }),
    );
  });

  it("does not re-request a replay the server cannot satisfy", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValueOnce(
      sseResponse([stamped("r-lost", 1), stamped("r-lost", 4), done()]),
    );
    fetchMock.mockResolvedValueOnce(sseResponse([])); // server has nothing after seq 1
    const { result } = renderHook(() => useAgentStream("s1"));

    await act(async () => {
      await result.current.send("oi");
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_500);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });

    const replayCalls = fetchMock.mock.calls.filter(([url]) =>
      String(url).includes("/api/sessions/s1/events"),
    );
    expect(replayCalls).toHaveLength(1);
    expect(result.current.events).toHaveLength(3); // seq1, seq4, done
    expect(result.current.error).toContain("timeline ficou incompleta");
  });

  it("cancel posts to the cancel endpoint", async () => {
    fetchMock.mockResolvedValueOnce(hangingSseResponse(token("parcial")));
    const { result } = renderHook(() => useAgentStream("s1"));

    await act(async () => {
      result.current.send("oi").catch(() => {});
      await Promise.resolve();
    });

    act(() => {
      result.current.cancel();
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.streaming).toBe(false);
    const cancelCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/api/chat/cancel/"),
    );
    expect(cancelCall).toBeDefined();
    expect(cancelCall![1]?.method).toBe("POST");
  });

  it("records the user's cancellation locally and leaves no tool call spinning", async () => {
    // The user pressed "Parar execução". The reader is aborted, so the
    // backend's RUN_CANCELLED frame can never arrive: without a local marker
    // the cancellation left no trace at all and every in-flight tool call kept
    // showing a spinner forever.
    const stream = controllableSseResponse();
    fetchMock.mockResolvedValueOnce(stream.response);
    const { result } = renderHook(() => useAgentStream("s1"));
    let activeSend: Promise<boolean> | undefined;

    await act(async () => {
      activeSend = result.current.send("compila o projeto");
      stream.send([
        stamped("r-user-cancel", 1),
        { type: "tool_call", run_id: "r-user-cancel", seq: 2, event_id: "u-2", tool_name: "execute_terminal", tool_args: {}, timestamp: "t2" },
      ]);
      for (let i = 0; i < 12; i += 1) await Promise.resolve();
    });

    expect(result.current.getActiveRunId()).toBe("r-user-cancel");

    await act(async () => {
      result.current.cancel();
      for (let i = 0; i < 12; i += 1) await Promise.resolve();
    });
    await act(async () => {
      await activeSend;
    });

    // One marker, ordered after the run's own frames, and explicitly labelled
    // as a request made by the user — observed locally, not a server
    // confirmation.
    const markers = result.current.events.filter(
      (event) => event.data?.kind === "run_cancelled",
    );
    expect(markers).toHaveLength(1);
    expect(markers[0].type).toBe("progress");
    expect(markers[0].data).toMatchObject({ requested_by: "user", local: true });
    expect(markers[0].content).toContain("a pedido do utilizador");
    expect(markers[0].run_id).toBe("r-user-cancel");
    expect(markers[0].seq).toBe(3);
    expect(result.current.events.at(-1)).toBe(markers[0]);

    // Folding what the user actually sees: the cancellation is in the timeline
    // and nothing is left in a running/spinner state.
    const timeline = foldRun([], result.current.events).messages.find(
      (message) => message.role === "assistant" && message.toolCalls?.length,
    );
    expect(timeline?.toolCalls?.some((call) => call.status === "running")).toBe(false);
    expect(timeline?.steps?.some((step) => step.status === "running")).toBe(false);
    expect(timeline?.steps?.some((step) => step.kind === "run_cancelled")).toBe(true);

    // A single fire-and-forget cancel POST, and never the prompt again.
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/api/chat/cancel/"))).toHaveLength(1);
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/chat"))).toHaveLength(1);
    expect(result.current.streaming).toBe(false);
  });

  it("watchdog reports an error after the inactivity timeout", async () => {
    vi.useFakeTimers();
    fetchMock.mockResolvedValueOnce(hangingSseResponse());
    const { result } = renderHook(() => useAgentStream("s1"));

    await act(async () => {
      result.current.send("oi").catch(() => {});
      await Promise.resolve();
    });
    expect(result.current.error).toBeNull();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_800_000);
    });

    expect(result.current.error).toContain("Sem dados do servidor");
    expect(result.current.streaming).toBe(false);
    const errorEvents = result.current.events.filter((e) => e.type === "error");
    expect(errorEvents).toHaveLength(1);
    expect(errorEvents[0].content).toContain("Timeout de inatividade");
    // The watchdog also cancels the server-side work.
    const cancelCall = fetchMock.mock.calls.find(([url]) =>
      String(url).includes("/api/chat/cancel/"),
    );
    expect(cancelCall).toBeDefined();
  }, 20_000);

  it("on 401 refreshes auth once and retries the chat request", async () => {
    mockRefreshAuth.mockResolvedValue(true);
    let chatCalls = 0;
    fetchMock.mockImplementation(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/chat")) {
        chatCalls += 1;
        if (chatCalls === 1) {
          return {
            ok: false,
            status: 401,
            text: async () => "expired",
          } as unknown as Response;
        }
        return sseResponse([token("depois do refresh"), done()]);
      }
      throw new Error(`unexpected fetch: ${String(input)}`);
    });
    const { result } = renderHook(() => useAgentStream("s1"));

    await act(async () => {
      await result.current.send("oi");
    });

    expect(mockRefreshAuth).toHaveBeenCalledTimes(1);
    expect(chatCalls).toBe(2);
    expect(result.current.error).toBeNull();
    expect(result.current.events.map((e) => e.content)).toEqual([
      "depois do refresh",
      undefined,
    ]);
  });
});
