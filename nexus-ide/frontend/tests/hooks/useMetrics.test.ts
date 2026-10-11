import { describe, expect, it, vi, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useMetrics } from "../../hooks/useMetrics";
import { clearAuth, setAccessToken } from "../../lib/auth";

class MockStream {
  body: ReadableStream<Uint8Array>;
  private controller!: ReadableStreamDefaultController<Uint8Array>;

  constructor() {
    this.body = new ReadableStream<Uint8Array>({
      start: (c) => {
        this.controller = c;
      },
    });
  }

  emit(data: string) {
    this.controller.enqueue(new TextEncoder().encode(`data: ${data}\n\n`));
  }

  emitRaw(chunk: string) {
    this.controller.enqueue(new TextEncoder().encode(chunk));
  }

  close() {
    this.controller.close();
  }
}

function streamResponse(stream: MockStream): Response {
  return {
    ok: true,
    status: 200,
    body: stream.body,
    headers: new Headers(),
  } as unknown as Response;
}

describe("useMetrics", () => {
  const originalFetch = globalThis.fetch;

  afterEach(() => {
    vi.unstubAllGlobals();
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
    clearAuth();
  });

  it("starts with null metrics", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, _init?: RequestInit) => new Promise<Response>(() => undefined)),
    );
    const { result } = renderHook(() => useMetrics());
    expect(result.current).toBeNull();
  });

  it("opens the stream with the access token", () => {
    setAccessToken("metrics-token");
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) => new Promise<Response>(() => undefined));
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useMetrics());

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toContain("/api/system/metrics/stream");
    expect((init.headers as Record<string, string>).Authorization).toBe("Bearer metrics-token");
    expect((init.headers as Record<string, string>).Accept).toBe("text/event-stream");
  });

  it("sends no Authorization header when there is no token", () => {
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) => new Promise<Response>(() => undefined));
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useMetrics());

    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.headers as Record<string, string>).Authorization).toBeUndefined();
  });

  it("updates metrics on a stream frame", async () => {
    const stream = new MockStream();
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(streamResponse(stream))));

    const { result } = renderHook(() => useMetrics());
    await act(async () => {
      stream.emit('{"tokens_per_second": 42, "active_model": "gpt-4"}');
      await Promise.resolve();
    });

    expect(result.current).toEqual({ tokens_per_second: 42, active_model: "gpt-4" });
  });

  it("ignores invalid JSON data", async () => {
    const stream = new MockStream();
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(streamResponse(stream))));

    const { result } = renderHook(() => useMetrics());
    await act(async () => {
      stream.emit("not json");
      await Promise.resolve();
    });

    expect(result.current).toBeNull();
  });

  it("ignores frames without a data payload", async () => {
    const stream = new MockStream();
    vi.stubGlobal("fetch", vi.fn(() => Promise.resolve(streamResponse(stream))));

    const { result } = renderHook(() => useMetrics());
    await act(async () => {
      stream.emitRaw(": keepalive\n\n");
      await Promise.resolve();
    });

    expect(result.current).toBeNull();
  });

  it("aborts the stream on unmount", async () => {
    const stream = new MockStream();
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) => Promise.resolve(streamResponse(stream)));
    vi.stubGlobal("fetch", fetchMock);

    const { unmount } = renderHook(() => useMetrics());
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect((init.signal as AbortSignal).aborted).toBe(false);

    unmount();

    expect((init.signal as AbortSignal).aborted).toBe(true);
  });
});
