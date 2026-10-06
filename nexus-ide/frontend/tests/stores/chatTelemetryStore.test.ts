import { describe, expect, it, vi, beforeEach } from "vitest";
import { act } from "@testing-library/react";
import { useChatTelemetryStore } from "../../stores/chatTelemetryStore";
import type { StreamEvent } from "../../lib/types";

function makeEvent(overrides: Partial<StreamEvent> = {}): StreamEvent {
  return {
    type: "token",
    timestamp: "2025-01-01T00:00:00.000Z",
    ...overrides,
  } as StreamEvent;
}

describe("chatTelemetryStore", () => {
  beforeEach(() => {
    act(() => {
      useChatTelemetryStore.setState({
        sessionId: "",
        streaming: false,
        events: [],
        usage: null,
        startedAt: null,
        completedAt: null,
      });
    });
  });

  it("starts with empty session id", () => {
    expect(useChatTelemetryStore.getState().sessionId).toBe("");
  });

  it("starts not streaming", () => {
    expect(useChatTelemetryStore.getState().streaming).toBe(false);
  });

  it("starts with empty events", () => {
    expect(useChatTelemetryStore.getState().events).toEqual([]);
  });

  it("starts with null usage", () => {
    expect(useChatTelemetryStore.getState().usage).toBeNull();
  });

  it("starts with null startedAt", () => {
    expect(useChatTelemetryStore.getState().startedAt).toBeNull();
  });

  it("starts with null completedAt", () => {
    expect(useChatTelemetryStore.getState().completedAt).toBeNull();
  });

  it("setStream with streaming=true sets startedAt", () => {
    const now = Date.now();
    act(() => {
      useChatTelemetryStore.getState().setStream("sess-1", true, []);
    });
    const state = useChatTelemetryStore.getState();
    expect(state.sessionId).toBe("sess-1");
    expect(state.streaming).toBe(true);
    expect(state.startedAt).not.toBeNull();
    expect(state.startedAt!).toBeGreaterThanOrEqual(now);
    expect(state.completedAt).toBeNull();
  });

  it("setStream with streaming=false sets completedAt", () => {
    act(() => {
      useChatTelemetryStore.getState().setStream("sess-1", true, []);
      useChatTelemetryStore.getState().setStream("sess-1", false, []);
    });
    const state = useChatTelemetryStore.getState();
    expect(state.streaming).toBe(false);
    expect(state.completedAt).not.toBeNull();
  });

  it("setStream sets events", () => {
    const events = [makeEvent({ type: "token", content: "hello" })];
    act(() => {
      useChatTelemetryStore.getState().setStream("sess-1", true, events);
    });
    expect(useChatTelemetryStore.getState().events).toEqual(events);
  });

  it("setStream extracts usage from event data", () => {
    const events = [
      makeEvent({ type: "metric", data: { usage: { input_tokens: 100, output_tokens: 200 } } }),
    ];
    act(() => {
      useChatTelemetryStore.getState().setStream("sess-1", true, events);
    });
    const usage = useChatTelemetryStore.getState().usage;
    expect(usage).toMatchObject({ input_tokens: 100, output_tokens: 200 });
  });

  it("readUsage finds usage in reversed event order", () => {
    const events: StreamEvent[] = [
      makeEvent({ type: "metric", data: { usage: { input_tokens: 10, output_tokens: 20 } } }),
      makeEvent({ type: "token", content: "hello" }),
      makeEvent({ type: "metric", data: { usage: { input_tokens: 100, output_tokens: 200 } } }),
    ];
    act(() => {
      useChatTelemetryStore.getState().setStream("sess-1", true, events);
    });
    // readUsage scans from the end, so should find the last usage
    const usage = useChatTelemetryStore.getState().usage;
    expect(usage).toMatchObject({ input_tokens: 100, output_tokens: 200 });
  });

  it("setStream with no usage events returns null usage", () => {
    const events = [makeEvent({ type: "token", content: "hello" })];
    act(() => {
      useChatTelemetryStore.getState().setStream("sess-1", true, events);
    });
    expect(useChatTelemetryStore.getState().usage).toBeNull();
  });

  it("setStream reuses startedAt for same session", () => {
    vi.useFakeTimers();
    try {
      let firstStarted: number | null = null;
      act(() => {
        useChatTelemetryStore.getState().setStream("sess-1", true, []);
        firstStarted = useChatTelemetryStore.getState().startedAt;
      });
      vi.advanceTimersByTime(2000);
      act(() => {
        useChatTelemetryStore.getState().setStream("sess-1", true, []);
      });
      expect(useChatTelemetryStore.getState().startedAt).toBe(firstStarted);
    } finally {
      vi.useRealTimers();
    }
  });

  it("setStream sets new startedAt for new session", () => {
    vi.useFakeTimers();
    try {
      let firstStarted: number | null = null;
      act(() => {
        useChatTelemetryStore.getState().setStream("sess-1", true, []);
        firstStarted = useChatTelemetryStore.getState().startedAt;
      });
      vi.advanceTimersByTime(2000);
      act(() => {
        useChatTelemetryStore.getState().setStream("sess-2", true, []);
      });
      expect(useChatTelemetryStore.getState().startedAt).not.toBe(firstStarted);
      expect(useChatTelemetryStore.getState().sessionId).toBe("sess-2");
    } finally {
      vi.useRealTimers();
    }
  });

  it("clear resets all state", () => {
    const events = [
      makeEvent({ type: "metric", data: { usage: { input_tokens: 100 } } }),
    ];
    act(() => {
      useChatTelemetryStore.getState().setStream("sess-1", true, events);
      useChatTelemetryStore.getState().clear();
    });
    const state = useChatTelemetryStore.getState();
    expect(state.sessionId).toBe("");
    expect(state.streaming).toBe(false);
    expect(state.events).toEqual([]);
    expect(state.usage).toBeNull();
    expect(state.startedAt).toBeNull();
    expect(state.completedAt).toBeNull();
  });

  it("does not move completion time on repeated idle updates or leak timing to another session", () => {
    vi.useFakeTimers();
    try {
      const store = useChatTelemetryStore.getState();
      store.setStream("a", true, []);
      vi.advanceTimersByTime(1000);
      store.setStream("a", false, []);
      const completed = useChatTelemetryStore.getState().completedAt;
      vi.advanceTimersByTime(5000);
      store.setStream("a", false, []);
      expect(useChatTelemetryStore.getState().completedAt).toBe(completed);
      store.setStream("b", false, []);
      expect(useChatTelemetryStore.getState()).toMatchObject({ startedAt: null, completedAt: null, usage: null });
    } finally { vi.useRealTimers(); }
  });

  it("ignores malformed usage and normalises negative or non-finite token values", () => {
    const store = useChatTelemetryStore.getState();
    store.setStream("a", false, [makeEvent({ data: { usage: [] } })]);
    expect(useChatTelemetryStore.getState().usage).toBeNull();
    store.setStream("a", false, [makeEvent({ data: { usage: { input_tokens: 42, output_tokens: -1, total_tokens: Infinity } } })]);
    expect(useChatTelemetryStore.getState().usage).toMatchObject({ input_tokens: 42, output_tokens: 0, total_tokens: 42 });
  });
});
