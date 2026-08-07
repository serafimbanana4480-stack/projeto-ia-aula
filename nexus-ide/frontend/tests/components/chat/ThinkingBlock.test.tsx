import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ThinkingBlock, { extractStructuredPlan } from "../../../components/chat/ThinkingBlock";

const planPayload = `ORCHESTRATOR a planear
[{
  "name": "Explorar projeto",
  "description": "Identificar a estrutura e os componentes principais.",
  "agent": "ANALYZER",
  "depends_on": [],
  "priority": "high"
}, {
  "name": "Validar testes",
  "description": "Executar a suite e verificar regressões.",
  "agent": "DEBUGGER",
  "depends_on": [0],
  "priority": "medium"
}]`;

describe("ThinkingBlock", () => {
  it("converte um plano JSON do orquestrador em tarefas legíveis", () => {
    render(<ThinkingBlock content={planPayload} defaultOpen />);

    expect(screen.getByText("Plano de execução")).not.toBeNull();
    expect(screen.getByText("Explorar projeto")).not.toBeNull();
    expect(screen.getByText("ANALYZER")).not.toBeNull();
    expect(screen.getByText("Depende das tarefas 1")).not.toBeNull();
    expect(screen.queryByText(planPayload)).toBeNull();
  });

  it("mantém o pensamento normal quando não há plano estruturado", () => {
    expect(extractStructuredPlan("A analisar os ficheiros do projeto.")).toBeNull();
    render(<ThinkingBlock content="A analisar os ficheiros do projeto." defaultOpen />);
    expect(screen.getByText("A analisar os ficheiros do projeto.")).not.toBeNull();
  });
});
