import { describe, expect, it } from "vitest";
import type { StreamEvent } from "../../lib/types";
import { deriveAgents, toLifecycle, toolAction, toolKind } from "../../lib/runLifecycle";

const event = (partial: Partial<StreamEvent> & Pick<StreamEvent, "type">): StreamEvent => ({
  timestamp: "2026-01-01T00:00:00Z",
  run_id: "run-1",
  ...partial,
});

describe("runLifecycle", () => {
  it("maps the existing SSE frames onto one lifecycle vocabulary", () => {
    expect(toLifecycle(event({ type: "token", content: "oi", seq: 1, event_id: "d" }), 0)?.type).toBe("message.delta");
    expect(toLifecycle(event({ type: "tool_call", tool_name: "read_file", seq: 2, event_id: "t" }), 1)?.type).toBe("tool.started");
    expect(toLifecycle(event({ type: "done", seq: 3, event_id: "z", data: { cancelled: true } }), 2)?.type).toBe("run.cancelled");
    expect(toLifecycle(event({ type: "error", content: "falhou", seq: 4, event_id: "e" }), 3)?.type).toBe("run.failed");
  });

  it("builds a parent and child only from agents that were spawned", () => {
    const events: StreamEvent[] = [
      event({ type: "agent_started", agent: "NEXUS", seq: 1, event_id: "a", task_id: "root" }),
      event({
        type: "agent_started",
        agent: "CODER",
        seq: 2,
        event_id: "b",
        task_id: "child",
        data: { delegated: true, parent_id: "root", task: "editar README" },
      }),
      event({ type: "tool_call", agent: "CODER", tool_name: "write_file", tool_args: { path: "README.md" }, seq: 3, event_id: "c", task_id: "child" }),
      event({ type: "agent_finished", agent: "CODER", seq: 4, event_id: "d", task_id: "child" }),
    ];
    const nodes = deriveAgents(events);
    expect(nodes.map((node) => node.name)).toEqual(["NEXUS", "CODER"]);
    const child = nodes[1];
    expect(child.parentId).toBe("root");
    expect(child.state).toBe("COMPLETED");
    expect(child.task).toBe("editar README");
    expect(child.files).toEqual(["README.md"]);
    expect(child.tools).toEqual(["write_file"]);
  });

  it("closes every still-open agent when the run completes", () => {
    const events: StreamEvent[] = [
      event({ type: "agent_started", agent: "NEXUS", seq: 1, event_id: "a", task_id: "root" }),
      event({
        type: "agent_started",
        agent: "CODER",
        seq: 2,
        event_id: "b",
        task_id: "child",
        data: { parent_id: "root" },
      }),
      event({ type: "agent_finished", agent: "CODER", seq: 3, event_id: "c", task_id: "child" }),
      event({ type: "done", seq: 4, event_id: "d" }),
    ];
    const nodes = deriveAgents(events);
    expect(nodes.find((node) => node.name === "CODER")?.state).toBe("COMPLETED");
    expect(nodes.find((node) => node.name === "NEXUS")?.state).toBe("COMPLETED");
  });

  it("does not invent an agent when only a tool ran", () => {
    const nodes = deriveAgents([
      event({ type: "tool_call", tool_name: "read_file", tool_args: { path: "a.txt" }, seq: 1, event_id: "t" }),
    ]);
    expect(nodes).toEqual([]);
  });

  it("describes a tool by kind and target", () => {
    expect(toolKind("execute_terminal")).toBe("terminal");
    expect(toolAction("read_file", { path: "src/app.ts" })).toBe("src/app.ts");
  });
});
