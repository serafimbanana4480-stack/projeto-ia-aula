import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useWebSocket } from "../../hooks/useWebSocket";

class MockWebSocket {
  url: string;
  readyState: number = 0;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;
  onclose: ((e: Event) => void) | null = null;

  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;

  constructor(url: string) {
    this.url = url;
    MockWebSocket.instances.push(this);
  }

  static instances: MockWebSocket[] = [];

  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new Event("close"));
  }

  send(data: string) {
    this._lastData = data;
  }
  _lastData: string = "";

  // Helpers
  _emitOpen() {
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.(new Event("open"));
  }

  _emitMessage(data: string) {
    this.onmessage?.(
      new MessageEvent("message", { data }) as any,
    );
  }

  _emitError() {
    this.onerror?.(new Event("error"));
  }

  _emitClose() {
    this.readyState = MockWebSocket.CLOSED;
    this.onclose?.(new Event("close"));
  }
}

describe("useWebSocket", () => {
  beforeEach(() => {
    MockWebSocket.instances = [];
    (global as any).WebSocket = MockWebSocket;
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts with disconnected state", () => {
    const { result } = renderHook(() => useWebSocket("ws://localhost:8000/stream"));
    expect(result.current.isConnected).toBe(false);
    expect(result.current.data).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it("creates WebSocket with ws:// for http:// input", () => {
    renderHook(() => useWebSocket("http://localhost:8000/stream"));
    expect(MockWebSocket.instances[0].url).toBe("ws://localhost:8000/stream");
  });

  it("creates WebSocket with wss:// for https:// input", () => {
    renderHook(() => useWebSocket("https://localhost:8000/stream"));
    expect(MockWebSocket.instances[0].url).toBe("wss://localhost:8000/stream");
  });

  it("creates WebSocket with ws:// for ws:// input", () => {
    renderHook(() => useWebSocket("ws://localhost:8000/stream"));
    expect(MockWebSocket.instances[0].url).toBe("ws://localhost:8000/stream");
  });

  it("sets connected on open", () => {
    const { result } = renderHook(() => useWebSocket("ws://localhost:8000/stream"));
    act(() => {
      MockWebSocket.instances[0]._emitOpen();
    });
    expect(result.current.isConnected).toBe(true);
    expect(result.current.error).toBeNull();
  });

  it("parses incoming JSON message", () => {
    const { result } = renderHook(() => useWebSocket<{ type: string }>("ws://localhost:8000/stream"));
    act(() => {
      MockWebSocket.instances[0]._emitOpen();
      MockWebSocket.instances[0]._emitMessage('{"type":"token","content":"hello"}');
    });
    expect(result.current.data).toEqual({ type: "token", content: "hello" });
  });

  it("sets error on invalid JSON", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const { result } = renderHook(() => useWebSocket("ws://localhost:8000/stream"));
    act(() => {
      MockWebSocket.instances[0]._emitOpen();
      MockWebSocket.instances[0]._emitMessage("not json");
    });
    expect(result.current.error).instanceof(Error);
    consoleSpy.mockRestore();
  });

  it("sets error on WebSocket error", () => {
    const { result } = renderHook(() => useWebSocket("ws://localhost:8000/stream"));
    act(() => {
      MockWebSocket.instances[0]._emitError();
    });
    expect(result.current.isConnected).toBe(false);
    expect(result.current.error).instanceof(Error);
  });

  it("sets disconnected on close", () => {
    const { result } = renderHook(() => useWebSocket("ws://localhost:8000/stream"));
    act(() => {
      MockWebSocket.instances[0]._emitOpen();
      MockWebSocket.instances[0]._emitClose();
    });
    expect(result.current.isConnected).toBe(false);
  });

  it("closes WebSocket on unmount", () => {
    const { unmount } = renderHook(() => useWebSocket("ws://localhost:8000/stream"));
    const closeSpy = vi.spyOn(MockWebSocket.prototype, "close");
    unmount();
    expect(closeSpy).toHaveBeenCalledTimes(1);
  });

  it("recreates WebSocket when url changes", () => {
    const { rerender } = renderHook(
      ({ url }) => useWebSocket(url),
      { initialProps: { url: "ws://localhost:8000/a" } },
    );
    expect(MockWebSocket.instances).toHaveLength(1);
    rerender({ url: "ws://localhost:8000/b" });
    expect(MockWebSocket.instances).toHaveLength(2);
    expect(MockWebSocket.instances[1].url).toBe("ws://localhost:8000/b");
  });
});
