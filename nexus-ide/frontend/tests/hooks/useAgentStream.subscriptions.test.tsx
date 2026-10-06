/**
 * Regression pin for the re-render loop in `useAgentStream`.
 *
 * `events` used to be `eventsBySession[sessionId] ?? []`, a fresh array literal
 * on every render, so the telemetry effect below it re-ran on *every* render.
 * Two things came out of that and both are asserted here:
 *
 *  1. `chatTelemetryStore.setStream` was called once per render, so every
 *     subscriber of the store (ContextUsagePanel, RightPanel) was notified
 *     once per ChatPanel repaint.
 *  2. `setStream` stamps `completedAt: Date.now()` whenever it is called while
 *     not streaming, so the "completed at" figure was really "last render
 *     time" and any duration derived from it was wrong.
 *
 * The second file also pins the transport contract the warning was reported
 * against: a re-render mid-stream must not re-POST the chat request and must
 * not drop the tokens that arrive after it.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, cleanup } from "@testing-library/react";
import type { StreamEvent } from "../../lib/types";
import { useAgentStream } from "../../hooks/useAgentStream";
import { useChatTelemetryStore } from "../../stores/chatTelemetryStore";

const { mockRefreshAuth, mockClearAuth } = vi.hoisted(() => ({
  mockRefreshAuth: vi.fn(),
  mockClearAuth: vi.fn(),
}));

vi.mock("../../lib/auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../lib/auth")>();
  return { ...actual, refreshAuth: mockRefreshAuth, clearAuth: mockClearAuth };
});

let tsCounter = 0;

function evt(partial: Partial<StreamEvent> & { type: StreamEvent["type"] }): StreamEvent {
  tsCounter += 1;
  return {
    timestamp: `2026-01-01T00:00:${String(tsCounter).padStart(2, "0")}Z`,
    ...partial,
  };
}

function sseResponse(frames: StreamEvent[]): Response {
  const encoder = new TextEncoder();
  const payload = frames.map((f) => `data: ${JSON.stringify(f)}\n\n`).join("");
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

/**
 * A live stream the test drives by hand, plus a counter for how many times the
 * consumer tore it down.
 */
function controllableSse() {
  const encoder = new TextEncoder();
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  let cancels = 0;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
    cancel() {
      cancels += 1;
    },
  });
  return {
    cancels: () => cancels,
    response: {
      ok: true,
      status: 200,
      body,
      text: async () => "",
      headers: new Headers(),
    } as unknown as Response,
    push(frame: StreamEvent) {
      controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\n\n`));
    },
  };
}

describe("useAgentStream — telemetry identity across re-renders", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: ReturnType<typeof vi.fn>;
  let setStreamCalls = 0;
  const realSetStream = useChatTelemetryStore.getState().setStream;

  beforeEach(() => {
    tsCounter = 0;
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    mockRefreshAuth.mockReset();
    mockClearAuth.mockReset();
    setStreamCalls = 0;
    // Wrap — not replace — the real action, so the store keeps its real
    // semantics (usage snapshot, startedAt/completedAt bookkeeping) and the
    // test still counts the calls.
    useChatTelemetryStore.setState({
      setStream: (...args: Parameters<typeof realSetStream>) => {
        setStreamCalls += 1;
        return realSetStream(...args);
      },
    });
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    globalThis.fetch = originalFetch;
    useChatTelemetryStore.setState({
      setStream: realSetStream,
      sessionId: "",
      streaming: false,
      events: [],
      usage: null,
      startedAt: null,
      completedAt: null,
    });
  });

  it("publishes telemetry once for an empty session, not once per render", () => {
    const { rerender } = renderHook(() => useAgentStream("s1"));

    expect(setStreamCalls).toBe(1);

    // The bug: each of these re-renders produced a new `[]`, which re-ran the
    // effect and re-published.
    act(() => {
      rerender();
      rerender();
      rerender();
      rerender();
    });

    expect(setStreamCalls).toBe(1);
  });

  it("republishes exactly once per new events array and not again on re-render", async () => {
    fetchMock.mockResolvedValueOnce(
      sseResponse([evt({ type: "token", content: "olá" }), evt({ type: "done" })]),
    );
    const { result, rerender } = renderHook(() => useAgentStream("s1"));

    expect(setStreamCalls).toBe(1);

    await act(async () => {
      await result.current.send("oi");
    });

    // The two new events produce exactly two republishes (one per new array).
    expect(result.current.events).toHaveLength(2);
    const afterStream = setStreamCalls;
    expect(afterStream).toBeGreaterThan(1);

    act(() => {
      rerender();
      rerender();
    });
    expect(setStreamCalls).toBe(afterStream);
  });

  it("does not restamp completedAt on a re-render after the run finished", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T10:00:00.000Z"));
    fetchMock.mockResolvedValueOnce(
      sseResponse([evt({ type: "token", content: "fim" }), evt({ type: "done" })]),
    );
    const { result, rerender } = renderHook(() => useAgentStream("s1"));

    await act(async () => {
      await result.current.send("oi");
    });

    expect(useChatTelemetryStore.getState().streaming).toBe(false);
    const completedAt = useChatTelemetryStore.getState().completedAt;
    expect(completedAt).toBe(Date.parse("2026-01-01T10:00:00.000Z"));

    // Three minutes of unrelated repaints. `completedAt` is a property of the
    // run, not of the last frame the UI happened to draw.
    vi.setSystemTime(new Date("2026-01-01T10:03:00.000Z"));
    await act(async () => {
      rerender();
      rerender();
      rerender();
    });

    expect(useChatTelemetryStore.getState().completedAt).toBe(completedAt);
  });

  it("does not restamp completedAt for an idle session that has never streamed", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-01-01T09:00:00.000Z"));

    // A freshly opened chat: no run, no events — the state a session sits in
    // for most of its life, and the one where `?? []` allocated a new array on
    // every keystroke, hover and resize the composer caused.
    const { rerender } = renderHook(() => useAgentStream("s1"));

    const completedAt = useChatTelemetryStore.getState().completedAt;
    expect(completedAt).toBeNull(); // No run has completed in an empty conversation.

    vi.setSystemTime(new Date("2026-01-01T09:00:45.000Z"));
    for (let i = 0; i < 5; i += 1) {
      act(() => rerender());
    }

    expect(useChatTelemetryStore.getState().completedAt).toBe(completedAt);
  });
});

describe("useAgentStream — the chat stream is not torn down by a re-render", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    tsCounter = 0;
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

  it("keeps one request and one reader alive across re-renders mid-stream", async () => {
    vi.useFakeTimers();
    const sse = controllableSse();
    fetchMock.mockResolvedValueOnce(sse.response);
    const { result, rerender } = renderHook(() => useAgentStream("s1"));

    await act(async () => {
      void result.current.send("oi").catch(() => {});
      await Promise.resolve();
      await Promise.resolve();
    });

    await act(async () => {
      sse.push(evt({ type: "token", content: "a" }));
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(20);
    });
    expect(result.current.events.map((e) => e.content)).toEqual(["a"]);
    expect(result.current.streaming).toBe(true);

    // The render churn a token stream causes while the effect was unstable.
    act(() => {
      rerender();
      rerender();
      rerender();
    });

    await act(async () => {
      sse.push(evt({ type: "token", content: "b" }));
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(20);
    });

    // No re-POST, no dropped frame, no torn-down reader.
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(sse.cancels()).toBe(0);
    expect(result.current.events.map((e) => e.content)).toEqual(["a", "b"]);
    expect(result.current.streaming).toBe(true);
    expect(result.current.error).toBeNull();
  });
});
