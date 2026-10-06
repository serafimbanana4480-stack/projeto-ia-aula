import { describe, expect, it } from "vitest";
import { buildExecutionGraph } from "../../lib/executionGraph";
import type { ActivityItem } from "../../lib/types";

function agentActivity(
  taskId: string,
  data: Record<string, unknown>,
  status: ActivityItem["status"] = "success",
): ActivityItem {
  return {
    id: `agent-${taskId}`,
    kind: "agent",
    title: "tarefa",
    agent: "CODER",
    status,
    timestamp: "2026-09-27T00:00:00Z",
    data: { task_id: taskId, name: "CODER", ...data },
  };
}

describe("buildExecutionGraph", () => {
  it("creates edges only for explicit dependency task IDs", () => {
    const graph = buildExecutionGraph([
      agentActivity("task-a", { objective: "Inspecionar" }),
      agentActivity("task-b", { objective: "Rever", depends_on: ["task-a"] }, "running"),
    ]);

    expect(graph.nodes.map((node) => node.taskId)).toEqual(["task-a", "task-b"]);
    expect(graph.edges).toEqual([{ fromTaskId: "task-a", toTaskId: "task-b" }]);
    expect(graph.nodes[1].objective).toBe("Rever");
    expect(graph.nodes[1].status).toBe("running");
  });

  it("does not invent edges when dependencies are absent", () => {
    const graph = buildExecutionGraph([
      agentActivity("task-a", {}),
      agentActivity("task-b", {}),
    ]);

    expect(graph.edges).toEqual([]);
    expect(graph.unresolvedDependencies).toEqual([]);
  });

  it("reports unresolved dependency IDs without drawing a false edge", () => {
    const graph = buildExecutionGraph([
      agentActivity("task-b", { depends_on: ["missing-task", "task-b", 42] }),
    ]);

    expect(graph.edges).toEqual([]);
    expect(graph.unresolvedDependencies).toEqual([
      { taskId: "task-b", dependencyTaskId: "missing-task" },
    ]);
  });

  it("accepts model and duration only when the event contains valid values", () => {
    const graph = buildExecutionGraph([
      agentActivity("task-a", { model: "local-model", duration_ms: 1250 }),
      agentActivity("task-b", { model: "", duration_ms: Number.NaN }),
    ]);

    expect(graph.nodes[0]).toMatchObject({ model: "local-model", durationMs: 1250 });
    expect(graph.nodes[1]).toMatchObject({ model: undefined, durationMs: undefined });
  });
});
