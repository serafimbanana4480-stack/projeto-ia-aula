import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ExecutionActivity from "../../../components/chat/ExecutionActivity";

describe("ExecutionActivity", () => {
  const items = [
    {
      id: "agent-coder",
      kind: "agent" as const,
      title: "CODER recebeu trabalho delegado",
      agent: "CODER" as const,
      status: "success" as const,
      timestamp: "2026-07-27T10:00:00Z",
    },
    {
      id: "task-ui",
      kind: "task" as const,
      title: "Tarefa concluída",
      detail: "Reorganizar a apresentação das ferramentas",
      agent: "CODER" as const,
      status: "success" as const,
      timestamp: "2026-07-27T10:00:01Z",
    },
  ];

  it("summarizes delegated work and reveals details on demand", () => {
    render(<ExecutionActivity items={items} />);

    const toggle = screen.getByRole("button", { name: /trabalho concluído/i });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(toggle);

    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("CODER recebeu trabalho delegado")).toBeTruthy();
    expect(screen.getByText("Reorganizar a apresentação das ferramentas")).toBeTruthy();
  });
});
