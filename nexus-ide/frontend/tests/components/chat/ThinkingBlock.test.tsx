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

  it("não renderiza nada com conteúdo vazio ou só espaços", () => {
    const empty = render(<ThinkingBlock content="" defaultOpen />).container;
    expect(empty.innerHTML).toBe("");
    // JSX string attributes do not decode escapes, so the whitespace is passed
    // as a JS expression here.
    const blank = render(<ThinkingBlock content={"   \n  "} defaultOpen />).container;
    expect(blank.innerHTML).toBe("");
  });

  it("mostra a duração real do bloco concluído", () => {
    // `durationMs` used to be destructured into `_durationMs` and discarded, so
    // a completed block always read "concluído".
    render(
      <ThinkingBlock
        content="A confirmar a assinatura da função antes de alterar o ficheiro."
        durationMs={7500}
        defaultOpen={false}
      />,
    );
    expect(screen.getByText("8s")).not.toBeNull();
    expect(screen.queryByText("concluído")).toBeNull();
  });

  it("mantém 'concluído' quando não há medição disponível", () => {
    render(<ThinkingBlock content="Uma abordagem curta e direta." defaultOpen={false} />);
    expect(screen.getByText("concluído")).not.toBeNull();
  });

  it("usa o cabeçalho de streaming enquanto o raciocínio chega", () => {
    render(<ThinkingBlock content="A analisar a estrutura do projeto." isStreaming />);
    expect(screen.getByText("A definir a abordagem")).not.toBeNull();
  });
});
