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

  it("does not report success when the run timeline contains tool errors", () => {
    render(<ExecutionActivity items={items} hasErrors />);

    expect(screen.getByRole("button", { name: /concluída com problemas/i })).toBeTruthy();
    expect(screen.queryByRole("button", { name: /trabalho concluído/i })).toBeNull();
  });

  // The panel used to say "Trabalho concluído" with a green check whenever no
  // activity was an `error` — including when the only thing it had was a
  // `warning` saying the run had been interrupted.
  it("não anuncia trabalho concluído quando a única evidência é uma activity de warning", () => {
    const { container } = render(
      <ExecutionActivity
        items={[
          {
            id: "checkpoint-run-1",
            kind: "status",
            title: "Execução interrompida",
            status: "warning",
            timestamp: "2026-07-27T10:00:02Z",
            data: { run_id: "run-1", source: "persisted_checkpoint" },
          },
        ]}
      />,
    );

    expect(screen.queryByRole("button", { name: /trabalho concluído/i })).toBeNull();
    expect(screen.getByRole("button", { name: /1 problema durante a execução/i })).toBeTruthy();
    expect(container.querySelector(".text-emerald-400")).toBeNull();
    expect(container.querySelector(".text-rose-400")).not.toBeNull();
  });

  it("não inventa uma conclusão a partir de atividades que não reportaram sucesso", () => {
    const { container } = render(
      <ExecutionActivity
        items={[
          {
            id: "plan-1",
            kind: "plan",
            title: "Plano de execução preparado",
            status: "pending",
            timestamp: "2026-07-27T10:00:00Z",
          },
        ]}
      />,
    );

    expect(screen.queryByRole("button", { name: /trabalho concluído/i })).toBeNull();
    expect(
      screen.getByRole("button", { name: /execução sem estado final confirmado/i }),
    ).toBeTruthy();
    expect(container.querySelector(".text-emerald-400")).toBeNull();
  });

  it("mostra a execução cancelada sem o verde de conclusão", () => {
    const { container } = render(
      <ExecutionActivity
        items={[
          {
            id: "cancel-1",
            kind: "status",
            title: "execução parada a pedido do utilizador",
            status: "cancelled",
            timestamp: "2026-07-27T10:00:00Z",
          },
        ]}
      />,
    );

    expect(screen.getByRole("button", { name: /execução cancelada/i })).toBeTruthy();
    expect(container.querySelector(".text-emerald-400")).toBeNull();
  });

  it("compacta leituras adjacentes com contagens recebidas e permite rever cada evento", () => {
    render(
      <ExecutionActivity
        items={[
          { id: "r1", kind: "status", title: "li 2 ficheiro(s)", detail: "duas leituras", status: "success", timestamp: "t1", data: { kind: "file_read", count: 2 } },
          { id: "r2", kind: "status", title: "li 3 ficheiro(s)", detail: "três leituras", status: "success", timestamp: "t2", data: { kind: "file_read", count: 3 } },
        ]}
        isStreaming={false}
      />,
    );

    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByText("Leu 5 ficheiros")).toBeTruthy();
    expect(screen.getByText("2 leituras")).toBeTruthy();
    fireEvent.click(screen.getByText("Leu 5 ficheiros"));
    expect(screen.getByText("duas leituras")).toBeTruthy();
    expect(screen.getByText("três leituras")).toBeTruthy();
  });

  it("virtualiza 500 atividades e permite navegar até uma linha fora da janela", () => {
    const manyItems = Array.from({ length: 500 }, (_, index) => ({
      id: `activity-${index}`,
      kind: "status" as const,
      title: `Atividade ${index}`,
      status: "success" as const,
      timestamp: `2026-09-27T00:${String(Math.floor(index / 60)).padStart(2, "0")}:${String(index % 60).padStart(2, "0")}Z`,
    }));
    render(<ExecutionActivity items={manyItems} />);

    fireEvent.click(screen.getByRole("button", { expanded: false }));
    const viewport = screen.getByTestId("execution-activity-body");
    expect(screen.getAllByTestId("execution-activity-row").length).toBeLessThan(30);

    fireEvent.scroll(viewport, { target: { scrollTop: 48 * 300 } });
    expect(screen.getAllByTestId("execution-activity-row").length).toBeLessThan(30);
    expect(screen.getByText("Atividade 300")).toBeTruthy();
  });

  it("virtualiza também os detalhes de 10.000 leituras agrupadas", () => {
    const reads = Array.from({ length: 10_000 }, (_, index) => ({
      id: `read-${index}`,
      kind: "status" as const,
      title: `Leitura ${index}`,
      detail: `src/file-${index}.py`,
      status: "success" as const,
      timestamp: `t${index}`,
      data: { kind: "file_read", count: 1 },
    }));
    render(<ExecutionActivity items={reads} />);

    fireEvent.click(screen.getByRole("button", { expanded: false }));
    fireEvent.click(screen.getByText("Leu 10000 ficheiros"));
    const viewport = screen.getByTestId("file-read-viewport");
    expect(screen.getAllByTestId("file-read-row").length).toBeLessThan(20);
    expect(screen.getByText("src/file-0.py")).toBeTruthy();

    fireEvent.scroll(viewport, { target: { scrollTop: 24 * 5_000 } });
    expect(screen.getAllByTestId("file-read-row").length).toBeLessThan(20);
    expect(screen.getByText("src/file-5000.py")).toBeTruthy();
  });
});
