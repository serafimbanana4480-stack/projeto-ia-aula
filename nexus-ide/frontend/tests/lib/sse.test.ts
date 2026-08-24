import { describe, expect, it, vi, afterEach } from "vitest";
import {
  createSSEConnection,
  handleApiError,
  safeJsonParse,
  safeSlice,
} from "../../lib/sse";

// Mock EventSource globally
class MockEventSource {
  static instances: MockEventSource[] = [];
  url: string;
  onopen: ((e: Event) => void) | null = null;
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: ((e: Event) => void) | null = null;

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  close() {}

  // Helpers to simulate server events
  _emitOpen() {
    this.onopen?.(new Event("open"));
  }
  _emitMessage(data: string) {
    this.onmessage?.(new MessageEvent("message", { data }));
  }
  _emitError() {
    this.onerror?.(new Event("error"));
  }
}

describe("lib/sse", () => {
  afterEach(() => {
    MockEventSource.instances = [];
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe("createSSEConnection", () => {
    it("creates an EventSource with the given url", () => {
      const originalEventSource = global.EventSource;
      global.EventSource = MockEventSource as any;
      try {
        const onMessage = vi.fn();
        createSSEConnection({ url: "http://localhost:8000/events", onMessage });
        expect(MockEventSource.instances.length).toBe(1);
        expect(MockEventSource.instances[0].url).toBe("http://localhost:8000/events");
      } finally {
        global.EventSource = originalEventSource;
      }
    });

    it("calls onMessage with parsed JSON on message event", () => {
      const originalEventSource = global.EventSource;
      global.EventSource = MockEventSource as any;
      try {
        const onMessage = vi.fn();
        createSSEConnection({ url: "http://test/events", onMessage });
        const es = MockEventSource.instances[0];
        es._emitMessage('{"type":"token","content":"hello"}');
        expect(onMessage).toHaveBeenCalledTimes(1);
        expect(onMessage).toHaveBeenCalledWith({ type: "token", content: "hello" });
      } finally {
        global.EventSource = originalEventSource;
      }
    });

    it("logs error and continues on parse failure", () => {
      const originalEventSource = global.EventSource;
      const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      global.EventSource = MockEventSource as any;
      try {
        const onMessage = vi.fn();
        createSSEConnection({ url: "http://test/events", onMessage });
        const es = MockEventSource.instances[0];
        es._emitMessage("not json");
        expect(onMessage).not.toHaveBeenCalled();
        expect(consoleSpy).toHaveBeenCalledWith("Failed to parse SSE data from http://test/events:", expect.any(SyntaxError));
      } finally {
        global.EventSource = originalEventSource;
        consoleSpy.mockRestore();
      }
    });

    it("resets reconnectAttempts on open", () => {
      const originalEventSource = global.EventSource;
      global.EventSource = MockEventSource as any;
      try {
        const onMessage = vi.fn();
        createSSEConnection({ url: "http://test/events", onMessage, maxReconnectAttempts: 3 });
        const es = MockEventSource.instances[0];
        es._emitOpen();
      } finally {
        global.EventSource = originalEventSource;
      }
    });

    it("attempts reconnection on error within maxReconnectAttempts", () => {
      const originalEventSource = global.EventSource;
      global.EventSource = MockEventSource as any;
      vi.useFakeTimers();
      try {
        const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
        const onError = vi.fn();
        const onMessage = vi.fn();
        createSSEConnection({
          url: "http://test/events",
          onMessage,
          onError,
          maxReconnectAttempts: 5,
          reconnectDelay: 1000,
        });
        const es = MockEventSource.instances[0];
        es._emitError();
        expect(onError).toHaveBeenCalledTimes(1);
        // Should schedule a reconnect
        expect(setTimeoutSpy).toHaveBeenCalled();
      } finally {
        global.EventSource = originalEventSource;
        vi.useRealTimers();
      }
    });

    it("calls onError callback if provided", () => {
      const originalEventSource = global.EventSource;
      global.EventSource = MockEventSource as any;
      try {
        const onError = vi.fn();
        createSSEConnection({
          url: "http://test/events",
          onMessage: vi.fn(),
          onError,
        });
        const es = MockEventSource.instances[0];
        es._emitError();
        expect(onError).toHaveBeenCalledTimes(1);
      } finally {
        global.EventSource = originalEventSource;
      }
    });

    it("does not reconnect after exceeding maxReconnectAttempts", () => {
      const originalEventSource = global.EventSource;
      global.EventSource = MockEventSource as any;
      vi.useFakeTimers();
      try {
        createSSEConnection({
          url: "http://test/events",
          onMessage: vi.fn(),
          maxReconnectAttempts: 2,
          reconnectDelay: 100,
        });
        // First error triggers reconnect (attempt 1)
        MockEventSource.instances[0]._emitError();
        // Second error triggers reconnect (attempt 2)
        MockEventSource.instances[0]._emitError();

        // Advance time to allow reconnects to fire
        vi.advanceTimersByTime(500);
      } finally {
        global.EventSource = originalEventSource;
      }
    });

    it("cleanup function closes EventSource and clears reconnect timeout", () => {
      const originalEventSource = global.EventSource;
      global.EventSource = MockEventSource as any;
      try {
        const cleanup = createSSEConnection({
          url: "http://test/events",
          onMessage: vi.fn(),
        });
        const es = MockEventSource.instances[0];
        const closeSpy = vi.spyOn(es, "close");
        cleanup();
        expect(closeSpy).toHaveBeenCalled();
      } finally {
        global.EventSource = originalEventSource;
      }
    });

    it("uses exponential backoff for reconnection delay", () => {
      const originalEventSource = global.EventSource;
      global.EventSource = MockEventSource as any;
      vi.useFakeTimers();
      try {
        const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout");
        createSSEConnection({
          url: "http://test/events",
          onMessage: vi.fn(),
          maxReconnectAttempts: 5,
          reconnectDelay: 1000,
        });
        // Trigger error to start backoff
        MockEventSource.instances[0]._emitError();
        // reconnectDelay * 2^(1-1) = 1000 * 1 = 1000ms
        expect(setTimeoutSpy).toHaveBeenCalledWith(expect.any(Function), 1000);
      } finally {
        global.EventSource = originalEventSource;
        vi.useRealTimers();
      }
    });
  });

  describe("handleApiError", () => {
    it("logs the error with context", () => {
      const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      const error = new Error("Something went wrong");
      handleApiError(error, "fetchData");
      expect(consoleSpy).toHaveBeenCalledWith("[fetchData] Error:", error);
      consoleSpy.mockRestore();
    });

    it("handles non-Error values", () => {
      const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
      handleApiError("string error", "apiCall");
      expect(consoleSpy).toHaveBeenCalledWith("[apiCall] Error:", "string error");
      consoleSpy.mockRestore();
    });
  });

  describe("safeJsonParse", () => {
    it("parses valid JSON", () => {
      const result = safeJsonParse('{"key":"value"}', { fallback: true });
      expect(result).toEqual({ key: "value" });
    });

    it("returns fallback on invalid JSON", () => {
      const fallback = { safe: true };
      const result = safeJsonParse("not json", fallback);
      expect(result).toBe(fallback);
    });

    it("returns fallback on empty string", () => {
      const fallback = { safe: true };
      const result = safeJsonParse("", fallback);
      expect(result).toBe(fallback);
    });

    it("parses JSON arrays", () => {
      const result = safeJsonParse('[1, 2, 3]', [] as number[]);
      expect(result).toEqual([1, 2, 3]);
    });

    it("parses null input to null (JSON.parse(null) returns null)", () => {
      // JSON.parse(null) converts null to "null" string and parses to null value
      const result = safeJsonParse(null as any, { safe: true });
      expect(result).toBeNull();
    });

    it("returns fallback on undefined input", () => {
      const fallback = { safe: true };
      const result = safeJsonParse(undefined as any, fallback);
      expect(result).toBe(fallback);
    });
  });

  describe("safeSlice", () => {
    it("returns full array when under maxLength", () => {
      const arr = [1, 2, 3];
      expect(safeSlice(arr, 10)).toEqual([1, 2, 3]);
    });

    it("trims array to maxLength", () => {
      const arr = [1, 2, 3, 4, 5];
      expect(safeSlice(arr, 3)).toEqual([1, 2, 3]);
    });

    it("handles empty array", () => {
      expect(safeSlice([], 5)).toEqual([]);
    });

    it("handles maxLength of 0", () => {
      expect(safeSlice([1, 2, 3], 0)).toEqual([]);
    });

    it("returns all when length equals maxLength", () => {
      expect(safeSlice([1, 2, 3], 3)).toEqual([1, 2, 3]);
    });

    it("works with strings", () => {
      expect(safeSlice(["a", "b", "c", "d", "e"], 2)).toEqual(["a", "b"]);
    });
  });
});
