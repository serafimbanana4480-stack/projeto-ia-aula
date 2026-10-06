/**
 * This file is named for `useRealTimeStream` but used to contain a second copy
 * of the `useRealTimeStore` tests (in `tests/stores/realTimeStore.test.ts`),
 * with `vi` and `renderHook` imported and never used. The hook itself had zero
 * coverage, so these are real tests of the hook: the SSE connection lifecycle
 * and the filter that decides which frames reach the store.
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useRealTimeStore } from "../../stores/realTimeStore";
import { useRealTimeStream } from "../../hooks/useRealTimeStream";

const encoder = new TextEncoder();

function sseFrame(payload: unknown): Uint8Array {
  return encoder.encode(`data: ${JSON.stringify(payload)}\n\n`);
}

/** A body the test feeds frames into. */
function controllableBody() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    body,
    push: (payload: unknown) => controller.enqueue(sseFrame(payload)),
    close: () => controller.close(),
    error: (reason: Error) => controller.error(reason),
  };
}

describe("useRealTimeStream", () => {
  const originalFetch = globalThis.fetch;
  let fetchMock: ReturnType<typeof vi.fn>;
  let streams: Array<ReturnType<typeof controllableBody>>;

  beforeEach(() => {
    useRealTimeStore.setState({ events: [], lastEvent: null });
    streams = [];
    // The abort signal is honoured the way a real `fetch` honours it, so the
    // unmount/disconnect tests can observe the request being torn down.
    fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      const signal = init?.signal;
      if (signal?.aborted) return Promise.reject(new DOMException("Aborted", "AbortError"));
      // A fresh body per call: re-connecting to an already-locked
      // ReadableStream is a harness artefact, not a real behaviour.
      const body = controllableBody();
      streams.push(body);
      return Promise.resolve({
        ok: true,
        status: 200,
        body: body.body,
        headers: new Headers(),
      } as unknown as Response);
    });
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("não abre ligação quando o URL é null", () => {
    renderHook(() => useRealTimeStream(null));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("não abre ligação quando está desativado", () => {
    renderHook(() => useRealTimeStream("http://api/stream", { enabled: false }));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("abre a ligação ao URL pedido", async () => {
    renderHook(() => useRealTimeStream("http://api/stream"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0][0])).toBe("http://api/stream");
  });

  it("entrega ao store os frames que trazem type e timestamp", async () => {
    renderHook(() => useRealTimeStream("http://api/stream"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      streams[0].push({ type: "token", timestamp: "2026-01-01T00:00:00Z", content: "olá" });
      await Promise.resolve();
    });

    await waitFor(() => expect(useRealTimeStore.getState().events).toHaveLength(1));
    expect(useRealTimeStore.getState().lastEvent?.content).toBe("olá");
  });

  it("descarta frames sem type ou sem timestamp", async () => {
    renderHook(() => useRealTimeStream("http://api/stream"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      streams[0].push({ content: "sem type" });
      streams[0].push({ type: "token", content: "sem timestamp" });
      streams[0].push({ type: "token", timestamp: "2026-01-01T00:00:00Z", content: "válido" });
      await Promise.resolve();
    });

    await waitFor(() => expect(useRealTimeStore.getState().events).toHaveLength(1));
    // The malformed frames are dropped instead of poisoning the store.
    expect(useRealTimeStore.getState().events[0].content).toBe("válido");
  });

  it("reporta o estado da ligação", async () => {
    const { result } = renderHook(() => useRealTimeStream("http://api/stream"));
    expect(result.current.isConnected).toBe(false);

    await waitFor(() => expect(result.current.isConnected).toBe(true));
    expect(result.current.connectionStatus).toBe("connected");
    expect(result.current.error).toBeNull();
  });

  it("reporta um erro de HTTP sem partir a ligação", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 503,
      body: null,
      headers: new Headers(),
    } as unknown as Response);
    vi.spyOn(console, "error").mockImplementation(() => {});

    const { result } = renderHook(() => useRealTimeStream("http://api/stream"));

    await waitFor(() => expect(result.current.connectionStatus).toBe("error"));
    expect(result.current.error?.message).toContain("503");
    expect(result.current.isConnected).toBe(false);
  });

  it("aborta a ligação ao desmontar", async () => {
    const { unmount } = renderHook(() => useRealTimeStream("http://api/stream"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const signal = (fetchMock.mock.calls[0][1] as RequestInit).signal as AbortSignal;
    expect(signal.aborted).toBe(false);

    unmount();

    // The contract is "the request is aborted": the reader is owned by
    // `useSSE`, so a locked body cannot be cancelled from here.
    expect(signal.aborted).toBe(true);
  });

  it("volta a ligar quando o caller pede um reconnect manual", async () => {
    const { result } = renderHook(() => useRealTimeStream("http://api/stream"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    await act(async () => {
      result.current.manualReconnect();
      await Promise.resolve();
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("desliga a ligação a pedido", async () => {
    const { result } = renderHook(() => useRealTimeStream("http://api/stream"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const signal = (fetchMock.mock.calls[0][1] as RequestInit).signal as AbortSignal;

    await act(async () => {
      result.current.disconnect();
      await Promise.resolve();
    });

    expect(result.current.isConnected).toBe(false);
    expect(result.current.connectionStatus).toBe("disconnected");
    expect(signal.aborted).toBe(true);
  });
});
