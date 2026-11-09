import { beforeEach, describe, expect, it } from "vitest";
import { useChatTelemetryStore } from "../../stores/chatTelemetryStore";
import type { StreamEvent } from "../../lib/types";

function metricFrame(usage: Record<string, unknown>): StreamEvent {
  return {
    type: "metric",
    agent: "NEXUS",
    content: "",
    timestamp: "2026-01-01T00:00:00Z",
    data: { usage },
  } as unknown as StreamEvent;
}

describe("chatTelemetryStore resolved model", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useChatTelemetryStore.setState({
      sessionId: "",
      streaming: false,
      events: [],
      usage: null,
      startedAt: null,
      completedAt: null,
      resolvedModel: null,
      resolvedProvider: null,
    });
  });

  it("records the concrete model reported by the runtime", () => {
    useChatTelemetryStore
      .getState()
      .setStream("s1", true, [
        metricFrame({
          input_tokens: 10,
          output_tokens: 20,
          provider: { name: "lmstudio", model: "kimi-k2.7-code" },
        }),
      ]);

    const state = useChatTelemetryStore.getState();
    expect(state.resolvedModel).toBe("kimi-k2.7-code");
    expect(state.resolvedProvider).toBe("lmstudio");
  });

  it("remembers the model across a reload of the same session", () => {
    useChatTelemetryStore
      .getState()
      .setStream("s1", true, [
        metricFrame({
          input_tokens: 10,
          output_tokens: 20,
          provider: { name: "lmstudio", model: "kimi-k2.7-code" },
        }),
      ]);

    // A refresh: the store starts empty, then the session is re-opened with
    // no live usage block.
    useChatTelemetryStore.setState({
      sessionId: "",
      streaming: false,
      events: [],
      usage: null,
      startedAt: null,
      completedAt: null,
      resolvedModel: null,
      resolvedProvider: null,
    });
    useChatTelemetryStore.getState().setStream("s1", false, []);

    expect(useChatTelemetryStore.getState().resolvedModel).toBe("kimi-k2.7-code");
    expect(useChatTelemetryStore.getState().resolvedProvider).toBe("lmstudio");
  });

  it("does not leak the model between sessions", () => {
    useChatTelemetryStore
      .getState()
      .setStream("s1", true, [
        metricFrame({
          input_tokens: 1,
          output_tokens: 1,
          provider: { name: "lmstudio", model: "model-a" },
        }),
      ]);
    useChatTelemetryStore.getState().setStream("s2", false, []);

    expect(useChatTelemetryStore.getState().resolvedModel).toBeNull();
  });
});
