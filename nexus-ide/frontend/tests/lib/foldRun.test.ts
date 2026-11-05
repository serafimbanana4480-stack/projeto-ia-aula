import { describe, expect, it } from "vitest";
import { foldRun, agentColor, agentSeed, AGENT_DEFAULT, AGENT_COLORS } from "../../lib/foldRun";
import type { StreamEvent, ChatMessage } from "../../lib/types";

describe("lib/foldRun", () => {
  describe("agentColor", () => {
    it("returns color for known agents", () => {
      expect(agentColor("CODER")).toBe("#059669");
      expect(agentColor("DEBUGGER")).toBe("#dc2626");
      expect(agentColor("ARCHITECT")).toBe("#4f46e5");
    });

    it("returns default color for unknown agents", () => {
      expect(agentColor("unknown")).toBe(AGENT_DEFAULT);
      expect(agentColor("")).toBe(AGENT_DEFAULT);
    });
  });

  describe("agentSeed", () => {
    it("returns first letter uppercased", () => {
      expect(agentSeed("coder")).toBe("C");
      expect(agentSeed("Debugger")).toBe("D");
    });

    it("returns N for empty string", () => {
      expect(agentSeed("")).toBe("N");
    });
  });

  describe("foldRun", () => {
    it("returns pending user messages unchanged", () => {
      const pending: ChatMessage[] = [
        { id: "u1", role: "user", content: "Hello", timestamp: "2026-01-01T00:00:00Z" },
      ];
      const result = foldRun(pending, [], "Hello");
      expect(result.messages[0]).toEqual(pending[0]);
      expect(result.lastUserMessage).toBe("Hello");
    });

    it("creates assistant message on agent_started", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", agent: "CODER", timestamp: "2026-01-01T00:00:00Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg).toBeDefined();
      expect(assistantMsg!.agent).toBe("CODER");
      expect(assistantMsg!.steps).toHaveLength(1);
    });

    it("appends token content to assistant message", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", agent: "CODER", timestamp: "2026-01-01T00:00:00Z" },
        { type: "token", content: "Hello ", timestamp: "2026-01-01T00:00:01Z" },
        { type: "token", content: "world", timestamp: "2026-01-01T00:00:02Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg!.content).toContain("Hello world");
    });

    it("extracts thinking content from thinking events", () => {
      const events: StreamEvent[] = [
        { type: "thinking", content: "thinking|iteration:1 some reasoning here", timestamp: "2026-01-01T00:00:00Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg!.thinking).toContain("thinking|iteration:1 some reasoning here");
    });

    it("processes tool_call and tool_result events", () => {
      const events: StreamEvent[] = [
        { type: "tool_call", tool_name: "bash", tool_args: { cmd: "ls" }, timestamp: "2026-01-01T00:00:00Z" },
        { type: "tool_result", tool_name: "bash", tool_result: "done", timestamp: "2026-01-01T00:00:01Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg).toBeDefined();
      expect(assistantMsg!.toolCalls).toHaveLength(1);
      expect(assistantMsg!.toolCalls![0].name).toBe("bash");
      expect(assistantMsg!.toolCalls![0].status).toBe("success");
    });

    it("processes error events", () => {
      const events: StreamEvent[] = [
        { type: "error", content: "Something went wrong", timestamp: "2026-01-01T00:00:00Z" },
      ];
      const result = foldRun([], events, "user query");
      const errorMsg = result.messages.find((m) => m.metadata?.kind === "error");
      expect(errorMsg).toBeDefined();
      expect(errorMsg!.content).toContain("Something went wrong");
      expect(errorMsg!.metadata!.prompt).toBe("user query");
    });

    it("keeps a later run instead of dropping it", () => {
      const events: StreamEvent[] = [
        { type: "token", content: "primeiro", timestamp: "2026-01-01T00:00:00Z", run_id: "run-a", seq: 1, event_id: "a1" },
        { type: "done", timestamp: "2026-01-01T00:00:01Z", run_id: "run-a", seq: 2, event_id: "a2" },
        { type: "token", content: "segundo", timestamp: "2026-01-01T00:00:02Z", run_id: "run-b", seq: 1, event_id: "b1" },
        { type: "done", timestamp: "2026-01-01T00:00:03Z", run_id: "run-b", seq: 2, event_id: "b2" },
      ];
      const users: ChatMessage[] = [
        { id: "u1", role: "user", content: "um", timestamp: "2026-01-01T00:00:00Z" },
        { id: "u2", role: "user", content: "dois", timestamp: "2026-01-01T00:00:02Z" },
      ];
      const result = foldRun(users, events, "dois");
      expect(result.messages.map((message) => message.content)).toEqual(["um", "primeiro", "dois", "segundo"]);
    });

    it("drops a replayed event with the same id", () => {
      const events: StreamEvent[] = [
        { type: "token", content: "ola", timestamp: "2026-01-01T00:00:00Z", run_id: "run-a", seq: 1, event_id: "same" },
        { type: "token", content: "ola", timestamp: "2026-01-01T00:00:01Z", run_id: "run-a", seq: 1, event_id: "same" },
      ];
      const result = foldRun([], events, "");
      expect(result.messages.find((message) => message.role === "assistant")?.content).toBe("ola");
    });

    it("marks a cancelled run", () => {
      const events: StreamEvent[] = [
        { type: "tool_call", tool_name: "execute_terminal", tool_args: { command: "sleep 5" }, timestamp: "2026-01-01T00:00:00Z", run_id: "run-a", seq: 1, event_id: "t1" },
        { type: "done", timestamp: "2026-01-01T00:00:01Z", run_id: "run-a", seq: 2, event_id: "t2", data: { cancelled: true, status: "cancelled" } },
      ];
      const result = foldRun([], events, "");
      expect(result.messages[0].toolCalls?.[0].status).toBe("cancelled");
    });

    it("processes done event with telemetry", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", agent: "CODER", timestamp: "2026-01-01T00:00:00Z" },
        { type: "done", data: { elapsed: 5, telemetry: { input_tokens: 100, output_tokens: 50 } }, timestamp: "2026-01-01T00:00:01Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      const footer = assistantMsg!.metadata!.footer as
        | { elapsedMs?: number; telemetry?: Record<string, unknown> }
        | undefined;
      expect(footer).toBeDefined();
      expect(footer!.elapsedMs).toBe(5000);
      expect(footer!.telemetry).toBeDefined();
    });

    it("processes metric events with usage", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", agent: "CODER", timestamp: "2026-01-01T00:00:00Z" },
        { type: "metric", data: { usage: { input_tokens: 100, output_tokens: 50 } }, timestamp: "2026-01-01T00:00:01Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg!.metrics).toBeDefined();
      expect(assistantMsg!.metrics!.Input).toBe("100");
    });

    it("processes mission events as activities", () => {
      const events: StreamEvent[] = [
        { type: "mission_brief", agent: "CODER", content: "Starting mission", timestamp: "2026-01-01T00:00:00Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg!.activities).toBeDefined();
      expect(assistantMsg!.activities).toHaveLength(1);
    });

    it("sanitizes assistant content by stripping tags", () => {
      const events: StreamEvent[] = [
        { type: "agent_started", agent: "CODER", timestamp: "2026-01-01T00:00:00Z" },
        { type: "token", content: "<thinking>hidden</thinking>visible text", timestamp: "2026-01-01T00:00:01Z" },
      ];
      const result = foldRun([], events, "");
      const assistantMsg = result.messages.find((m) => m.role === "assistant");
      expect(assistantMsg!.content).not.toContain("<thinking>");
      expect(assistantMsg!.content).toContain("visible text");
    });

    it("handles empty events array", () => {
      const result = foldRun([], [], "");
      expect(result.messages).toEqual([]);
      expect(result.lastUserMessage).toBe("");
    });
  });

  describe("exports", () => {
    it("exports AGENT_COLORS with expected agents", () => {
      expect(AGENT_COLORS["CODER"]).toBe("#059669");
      expect(AGENT_COLORS["DEBUGGER"]).toBe("#dc2626");
      expect(AGENT_COLORS["ARCHITECT"]).toBe("#4f46e5");
    });

    it("exports AGENT_DEFAULT", () => {
      expect(AGENT_DEFAULT).toBe("#7c3aee");
    });
  });
});