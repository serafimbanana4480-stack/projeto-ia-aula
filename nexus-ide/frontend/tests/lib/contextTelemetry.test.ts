import { describe, expect, it } from "vitest";
import { deriveContextUsage, loadedSkillsFromEvents } from "../../lib/contextTelemetry";
import type { UsageSnapshot } from "../../stores/chatTelemetryStore";
import type { StreamEvent } from "../../lib/types";

function usage(context?: Record<string, unknown>): UsageSnapshot {
  return { input_tokens: 100, output_tokens: 25, reasoning_tokens: 0, total_tokens: 125, source: "provider", context };
}

describe("session context telemetry", () => {
  it("leaves empty conversations unknown instead of inventing a context total", () => {
    expect(deriveContextUsage(null, 8192)).toMatchObject({ used: null, percent: null, source: "unknown", segments: [] });
  });

  it("does not add billed output tokens to the provider's input snapshot", () => {
    expect(deriveContextUsage(usage(), 1000)).toMatchObject({ used: 100, percent: 10, source: "provider" });
  });

  it("counts MCP once because it is a subset of the legacy tool total", () => {
    const result = deriveContextUsage(usage({ prompt: 50, tools: 100, mcp: 30, total: 180, source: "estimated", context_window: 1000 }));
    expect(result.used).toBe(180);
    expect(result.segments.find((part) => part.key === "tools")?.value).toBe(70);
    expect(result.segments.find((part) => part.key === "mcp")?.value).toBe(30);
    expect(result.segments.find((part) => part.key === "other")?.value).toBe(30);
    expect(result.segments.reduce((sum, part) => sum + part.value, 0)).toBe(180);
    expect(result.source).toBe("estimated");
  });

  it("keeps provider billing separate from an estimated context breakdown", () => {
    expect(deriveContextUsage(usage({ prompt: 25, response: 5 }), 100)).toMatchObject({ used: 30, source: "estimated" });
  });

  it("rejects invalid token values and uses a selected model window when the runtime reports zero", () => {
    const result = deriveContextUsage(usage({ context_window: 0, prompt: -2, memory: NaN, total: Infinity }), 1000);
    expect(result.used).toBe(100);
    expect(result.percent).toBe(10);
    expect(result.segments.every((part) => Number.isFinite(part.value) && part.value >= 0)).toBe(true);
    expect(deriveContextUsage(usage(), Infinity).percent).toBeNull();
  });

  it("records a skill only after a successful load result", () => {
    const event = (type: StreamEvent["type"], tool_result: unknown, tool_error?: string): StreamEvent =>
      ({ type, tool_name: "load_skill", tool_result, tool_error, timestamp: "now" });
    expect(loadedSkillsFromEvents([
      event("tool_call", { name: "not-yet" }),
      event("tool_result", { ok: false, name: "failed" }),
      event("tool_result", { error: "missing", name: "missing" }),
      event("tool_result", { result: { name: "frontend", ok: true } }),
      event("tool_result", { name: "frontend" }),
      event("tool_result", { name: "bad" }, "failed"),
    ])).toEqual(["frontend"]);
  });
});
