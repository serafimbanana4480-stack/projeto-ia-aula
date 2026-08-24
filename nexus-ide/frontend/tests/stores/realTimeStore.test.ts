import { describe, expect, it, beforeEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useRealTimeStore } from "../../stores/realTimeStore";
import type { StreamEvent } from "../../lib/types";

function makeEvent(overrides: Partial<StreamEvent> = {}): StreamEvent {
  return {
    type: "token",
    timestamp: "2025-01-01T00:00:00.000Z",
    ...overrides,
  } as StreamEvent;
}

describe("realTimeStore", () => {
  beforeEach(() => {
    useRealTimeStore.setState({
      events: [],
      lastEvent: null,
    });
  });

  it("starts with empty events and null lastEvent", () => {
    const { events, lastEvent } = useRealTimeStore.getState();
    expect(events).toEqual([]);
    expect(lastEvent).toBeNull();
  });

  it("addEvent appends to events", () => {
    const evt = makeEvent({ type: "token", content: "hello" });
    act(() => {
      useRealTimeStore.getState().addEvent(evt);
    });
    expect(useRealTimeStore.getState().events).toHaveLength(1);
    expect(useRealTimeStore.getState().lastEvent).toEqual(evt);
  });

  it("addEvent trims to MAX_EVENTS (200)", () => {
    const store = useRealTimeStore.getState();
    for (let i = 0; i < 250; i++) {
      act(() => {
        store.addEvent(makeEvent({ type: "token", content: `msg-${i}` }));
      });
    }
    expect(useRealTimeStore.getState().events).toHaveLength(200);
    // Should keep the LAST 200 events
    const events = useRealTimeStore.getState().events;
    expect(events[0].content).toBe("msg-50");
    expect(events[199].content).toBe("msg-249");
  });

  it("addEvent updates lastEvent", () => {
    const evt1 = makeEvent({ type: "token", content: "first" });
    const evt2 = makeEvent({ type: "token", content: "second" });
    act(() => {
      useRealTimeStore.getState().addEvent(evt1);
      useRealTimeStore.getState().addEvent(evt2);
    });
    expect(useRealTimeStore.getState().lastEvent).toEqual(evt2);
  });

  it("clearEvents empties the store", () => {
    act(() => {
      useRealTimeStore.getState().addEvent(makeEvent({ type: "token", content: "hello" }));
    });
    expect(useRealTimeStore.getState().events).toHaveLength(1);
    act(() => {
      useRealTimeStore.getState().clearEvents();
    });
    expect(useRealTimeStore.getState().events).toEqual([]);
    expect(useRealTimeStore.getState().lastEvent).toBeNull();
  });

  it("getEventsByType filters by type", () => {
    const store = useRealTimeStore.getState();
    act(() => {
      store.addEvent(makeEvent({ type: "token", content: "a" }));
      store.addEvent(makeEvent({ type: "progress", content: "b" }));
      store.addEvent(makeEvent({ type: "token", content: "c" }));
    });
    const tokens = useRealTimeStore.getState().getEventsByType("token");
    expect(tokens).toHaveLength(2);
    expect(tokens[0].content).toBe("a");
    expect(tokens[1].content).toBe("c");
  });

  it("getEventsByAgent filters by agent", () => {
    const store = useRealTimeStore.getState();
    act(() => {
      store.addEvent(makeEvent({ type: "token", agent: "CODER", content: "a" }));
      store.addEvent(makeEvent({ type: "token", agent: "DEBUGGER", content: "b" }));
      store.addEvent(makeEvent({ type: "token", agent: "CODER", content: "c" }));
    });
    const coderEvents = useRealTimeStore.getState().getEventsByAgent("CODER");
    expect(coderEvents).toHaveLength(2);
  });

  it("getEventsByType returns empty for unmatched type", () => {
    const store = useRealTimeStore.getState();
    act(() => {
      store.addEvent(makeEvent({ type: "token", content: "a" }));
    });
    expect(useRealTimeStore.getState().getEventsByType("nonexistent")).toEqual([]);
  });
});
