import { describe, expect, it } from "vitest";
import { foldRun } from "../../lib/foldRun";
import { buildAgentRoster } from "../../lib/plainNarration";
import type { StreamEvent } from "../../lib/types";

describe("concurrent worker activity", () => {
  it("pairs same-named calls by task and call id, including out-of-order completion and replay", () => {
    const time = "2026-10-27T10:00:00.000Z";
    const frame = (seq: number, value: Partial<StreamEvent>): StreamEvent => ({
      run_id: "run-child", seq, event_id: `event-${seq}`, timestamp: time, ...value,
      type: value.type ?? "progress",
    });
    const events = [
      frame(1, { type: "agent_started", agent: "NEXUS", data: { kind: "run_started" } }),
      frame(2, { type: "agent_started", agent: "CODER", task_id: "a", data: { kind: "subagent_started", name: "CODER:edit", objective: "Ler A", task_id: "a" } }),
      frame(3, { type: "agent_started", agent: "DEBUGGER", task_id: "b", data: { kind: "subagent_started", name: "DEBUGGER:check", objective: "Ler B", task_id: "b" } }),
      frame(4, { type: "tool_call", agent: "CODER", task_id: "a", tool_name: "read_file", tool_args: { path: "a.py" }, data: { call_id: "call-a" } }),
      frame(5, { type: "tool_call", agent: "DEBUGGER", task_id: "b", tool_name: "read_file", tool_args: { path: "b.py" }, data: { call_id: "call-b" } }),
      frame(6, { type: "tool_result", agent: "DEBUGGER", task_id: "b", tool_name: "read_file", tool_result: { content: "B" }, data: { call_id: "call-b" } }),
      frame(7, { type: "tool_error", agent: "CODER", task_id: "a", tool_name: "read_file", tool_error: "erro A", data: { call_id: "call-a" } }),
      frame(8, { type: "agent_finished", agent: "DEBUGGER", task_id: "b", data: { kind: "subagent_completed", name: "DEBUGGER:check", status: "completed", result: "Resultado B", task_id: "b" } }),
      frame(9, { type: "agent_finished", agent: "CODER", task_id: "a", data: { kind: "subagent_completed", name: "CODER:edit", status: "failed", task_id: "a" } }),
      frame(10, { type: "token", agent: "NEXUS", content: "Resposta principal" }),
    ];
    const message = foldRun([], [events[0], ...events.slice(1).reverse(), events[4]]).messages[0];
    expect(message.content).toBe("Resposta principal");
    expect(message.agent).toBe("NEXUS");
    expect(message.toolCalls).toHaveLength(2);
    expect(message.toolCalls?.find((call) => call.taskId === "a")).toMatchObject({ status: "error", error: "erro A" });
    expect(message.toolCalls?.find((call) => call.taskId === "b")).toMatchObject({ status: "success", result: { content: "B" } });
    expect(message.steps?.find((step) => step.taskId === "a" && step.verb === "tool")?.status).toBe("error");
    expect(message.steps?.find((step) => step.taskId === "b" && step.verb === "tool")?.status).toBe("success");
    expect(buildAgentRoster(message).map((agent) => [agent.name, agent.taskId]).sort()).toEqual([
      ["CODER", "a"], ["DEBUGGER", "b"],
    ]);
  });

  it("does not match a legacy result from another task with the same role and tool", () => {
    const frame = (seq: number, value: Partial<StreamEvent>): StreamEvent => ({
      type: "progress", run_id: "legacy-child", seq, event_id: `legacy-${seq}`,
      timestamp: "2026-10-27T10:00:00Z", ...value,
    });
    const events = [
      frame(1, { type: "agent_started", agent: "NEXUS", data: { kind: "run_started" } }),
      frame(2, { type: "agent_started", agent: "CODER", task_id: "a", data: { kind: "subagent_started", name: "CODER:a", task_id: "a" } }),
      frame(3, { type: "agent_started", agent: "CODER", task_id: "b", data: { kind: "subagent_started", name: "CODER:b", task_id: "b" } }),
      frame(4, { type: "tool_call", agent: "CODER", task_id: "a", tool_name: "read_file" }),
      frame(5, { type: "tool_call", agent: "CODER", task_id: "b", tool_name: "read_file" }),
      frame(6, { type: "tool_result", agent: "CODER", task_id: "a", tool_name: "read_file", tool_result: { content: "A" } }),
    ];
    const message = foldRun([], events).messages[0];
    expect(message.toolCalls?.find((call) => call.taskId === "a")).toMatchObject({ status: "success", result: { content: "A" } });
    expect(message.toolCalls?.find((call) => call.taskId === "b")?.status).toBe("running");
    expect(message.steps?.find((step) => step.taskId === "b" && step.verb === "tool")?.status).toBe("running");
  });
});
