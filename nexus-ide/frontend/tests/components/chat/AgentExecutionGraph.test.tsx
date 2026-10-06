import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AgentExecutionGraph from "../../../components/chat/AgentExecutionGraph";
import { buildExecutionGraph } from "../../../lib/executionGraph";
import type { ActivityItem } from "../../../lib/types";

const activities: ActivityItem[] = [
  {
    id: "agent-task-a",
    kind: "agent",
    title: "ANALYZER concluiu",
    agent: "ANALYZER",
    status: "success",
    timestamp: "2026-09-27T00:00:01Z",
    data: { task_id: "task-a", name: "ANALYZER", objective: "Inspecionar módulos" },
  },
  {
    id: "agent-task-b",
    kind: "agent",
    title: "REVIEWER começou",
    agent: "REVIEWER",
    status: "running",
    timestamp: "2026-09-27T00:00:02Z",
    data: {
      task_id: "task-b",
      name: "REVIEWER",
      objective: "Rever a alteração",
      depends_on: ["task-a"],
    },
  },
];

describe("AgentExecutionGraph", () => {
  it("shows the reported dependency and opens an inspector for a selected task", () => {
    render(<AgentExecutionGraph graph={buildExecutionGraph(activities)} />);

    expect(screen.getByTestId("execution-graph-edge").getAttribute("aria-label")).toBe(
      "REVIEWER depende de ANALYZER",
    );
    expect(screen.getByText(/não representam relações pai-filho/i)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /REVIEWER/ }));
    const inspector = screen.getByTestId("execution-graph-inspector");
    expect(inspector.textContent).toContain("Rever a alteração");
    expect(inspector.textContent).toContain("task-b");
    expect(inspector.textContent).toContain("ANALYZER");
    expect(inspector.textContent).not.toContain("Modelo");
    expect(inspector.textContent).not.toContain("Duração");
  });

  it("does not draw an edge when the referenced task is missing", () => {
    const graph = buildExecutionGraph([
      {
        ...activities[1],
        data: { task_id: "task-b", name: "REVIEWER", depends_on: ["missing"] },
      },
    ]);
    render(<AgentExecutionGraph graph={graph} />);

    expect(screen.queryByTestId("execution-graph-edge")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain("sem a tarefa correspondente");
  });
});
