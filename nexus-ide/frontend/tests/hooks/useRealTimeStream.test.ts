import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";
import { useRealTimeStore } from "../../stores/realTimeStore";

describe("useRealTimeStore", () => {
  beforeEach(() => {
    useRealTimeStore.setState({
      events: [],
      lastEvent: null,
    });
  });

  it("starts with empty events", () => {
    const { events } = useRealTimeStore.getState();
    expect(events).toEqual([]);
  });

  it("starts with null lastEvent", () => {
    expect(useRealTimeStore.getState().lastEvent).toBeNull();
  });

  it("addEvent appends to events", () => {
    const evt = { type: "token", content: "hello", timestamp: "t1" };
    useRealTimeStore.getState().addEvent(evt as any);
    expect(useRealTimeStore.getState().events).toHaveLength(1);
    expect(useRealTimeStore.getState().lastEvent).toEqual(evt);
  });

  it("addEvent trims to MAX_EVENTS (200)", () => {
    const store = useRealTimeStore.getState();
    for (let i = 0; i < 250; i++) {
      store.addEvent({ type: "token", content: `msg-${i}`, timestamp: `t${i}` } as any);
    }
    expect(useRealTimeStore.getState().events).toHaveLength(200);
    // Should keep the LAST 200 events
    const events = useRealTimeStore.getState().events;
    expect(events[0].content).toBe("msg-50");
    expect(events[199].content).toBe("msg-249");
  });

  it("addEvent updates lastEvent", () => {
    useRealTimeStore.getState().addEvent({ type: "token", content: "a", timestamp: "t1" } as any);
    useRealTimeStore.getState().addEvent({ type: "token", content: "b", timestamp: "t2" } as any);
    expect(useRealTimeStore.getState().lastEvent?.content).toBe("b");
  });

  it("clearEvents empties the store", () => {
    useRealTimeStore.getState().addEvent({ type: "token", content: "hello", timestamp: "t1" } as any);
    expect(useRealTimeStore.getState().events).toHaveLength(1);
    useRealTimeStore.getState().clearEvents();
    expect(useRealTimeStore.getState().events).toEqual([]);
    expect(useRealTimeStore.getState().lastEvent).toBeNull();
  });

  it("getEventsByType filters by type", () => {
    const store = useRealTimeStore.getState();
    store.addEvent({ type: "token", content: "a", timestamp: "t1" } as any);
    store.addEvent({ type: "progress", content: "b", timestamp: "t2" } as any);
    store.addEvent({ type: "token", content: "c", timestamp: "t3" } as any);
    const tokens = useRealTimeStore.getState().getEventsByType("token");
    expect(tokens).toHaveLength(2);
    expect(tokens[0].content).toBe("a");
    expect(tokens[1].content).toBe("c");
  });

  it("getEventsByAgent filters by agent", () => {
    const store = useRealTimeStore.getState();
    store.addEvent({ type: "token", agent: "CODER", content: "a", timestamp: "t1" } as any);
    store.addEvent({ type: "token", agent: "DEBUGGER", content: "b", timestamp: "t2" } as any);
    store.addEvent({ type: "token", agent: "CODER", content: "c", timestamp: "t3" } as any);
    const coderEvents = useRealTimeStore.getState().getEventsByAgent("CODER");
    expect(coderEvents).toHaveLength(2);
  });

  it("getEventsByType returns empty for unmatched type", () => {
    const store = useRealTimeStore.getState();
    store.addEvent({ type: "token", content: "a", timestamp: "t1" } as any);
    expect(useRealTimeStore.getState().getEventsByType("nonexistent")).toEqual([]);
  });
});
