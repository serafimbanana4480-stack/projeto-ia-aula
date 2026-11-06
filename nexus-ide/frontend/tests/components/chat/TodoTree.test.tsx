import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import TodoTree from "../../../components/chat/TodoTree";
import type { SessionTodo } from "../../../lib/api";

describe("hierarchical todo view", () => {
  it("counts tasks only, expands branches and searches descendants", () => {
    const todos: SessionTodo[] = [
      { id: 1, content: "Sistema", type: "objective", status: "pending" },
      { id: 2, content: "Backend", type: "category", parent_id: 1, status: "pending" },
      { id: 3, content: "Testes", type: "task", parent_id: 2, status: "completed", criteria: ["Passam"] },
      { id: 4, content: "MCP", type: "task", parent_id: 2, status: "failed", priority: "high" },
    ];
    render(<TodoTree todos={todos} />);
    expect(screen.getByText("1 / 2 concluídas · 50%")).toBeTruthy();
    expect(screen.getByText("Backend")).toBeTruthy();
    expect(screen.getByRole("checkbox", { name: "Progresso de Sistema" }).getAttribute("aria-checked")).toBe("mixed");
    fireEvent.change(screen.getByLabelText("Pesquisar tarefas"), { target: { value: "Testes" } });
    expect(screen.getByText("Testes")).toBeTruthy();
    expect(screen.queryByText("MCP")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ver regras e critérios" }));
    expect(screen.getByText("Critério: Passam")).toBeTruthy();
  });
});
