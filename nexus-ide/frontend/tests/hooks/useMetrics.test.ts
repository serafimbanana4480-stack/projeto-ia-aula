import { describe, expect, it, vi, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useMetrics } from "../../hooks/useMetrics";

class MockEventSource {
  url: string;
  onmessage: ((e: MessageEvent) => void) | null = null;
  static instances: MockEventSource[] = [];

  constructor(url: string) {
    this.url = url;
    MockEventSource.instances.push(this);
  }

  close() {}

  _emitMessage(data: string) {
    this.onmessage?.(new MessageEvent("message", { data }) as any);
  }
}

describe("useMetrics", () => {
  afterEach(() => {
    MockEventSource.instances = [];
    vi.restoreAllMocks();
  });

  it("starts with null metrics", () => {
    (global as any).EventSource = MockEventSource;
    const { result } = renderHook(() => useMetrics());
    expect(result.current).toBeNull();
  });

  it("creates EventSource with correct URL", () => {
    (global as any).EventSource = MockEventSource;
    renderHook(() => useMetrics());
    expect(MockEventSource.instances[0].url).toContain("/api/system/metrics/stream");
  });

  it("updates metrics on message event", () => {
    (global as any).EventSource = MockEventSource;
    const { result } = renderHook(() => useMetrics());
    act(() => {
      MockEventSource.instances[0]._emitMessage('{"tokens_per_second": 42, "active_model": "gpt-4"}');
    });
    expect(result.current).toEqual({ tokens_per_second: 42, active_model: "gpt-4" });
  });

  it("ignores invalid JSON data", () => {
    (global as any).EventSource = MockEventSource;
    const { result } = renderHook(() => useMetrics());
    act(() => {
      MockEventSource.instances[0]._emitMessage("not json");
    });
    expect(result.current).toBeNull();
  });

  it("closes EventSource on unmount", () => {
    (global as any).EventSource = MockEventSource;
    const { unmount } = renderHook(() => useMetrics());
    const closeSpy = vi.spyOn(MockEventSource.prototype, "close");
    unmount();
    expect(closeSpy).toHaveBeenCalled();
  });
});
