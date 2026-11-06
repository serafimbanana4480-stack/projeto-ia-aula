/**
 * The collapsible surfaces of the chat timeline are only usable with a
 * keyboard or a screen reader if they say what they control. `RunTimeline`
 * already had `aria-expanded` / `aria-controls`; its siblings did not, and the
 * two blocks below are the ones the previous pass missed.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import ThinkingBlock, { extractStructuredPlan } from "../../../components/chat/ThinkingBlock";
import ExecutionActivity from "../../../components/chat/ExecutionActivity";
import type { ActivityItem } from "../../../lib/types";

function activity(overrides: Partial<ActivityItem> = {}): ActivityItem {
  return {
    id: "a1",
    kind: "status",
    title: "A avançar",
    status: "running",
    timestamp: "2026-01-01T00:00:00Z",
    data: {},
    ...overrides,
  };
}

describe("ThinkingBlock — collapsible accessibility", () => {
  it("expõe o estado de expansão e aponta para o corpo", () => {
    const { container } = render(<ThinkingBlock content="Vou ler o ficheiro." />);

    const toggle = screen.getByRole("button", { name: /Pensou/ });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    // `aria-controls` is no longer the hardcoded string "thinking-block-body":
    // several reasoning blocks can share one page and duplicate DOM ids broke
    // every one of them. It is now a unique `useId()`-derived id, so the
    // requirement is that it resolves to THIS block's body, not that it equals
    // a fixed literal.
    const controls = toggle.getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    // Collapsed by default when the run is over.
    expect(container.querySelector(`#${controls}`)).toBeNull();

    fireEvent.click(toggle);
    // Open, the control must point at an element that actually exists.
    expect(container.querySelector(`#${controls}`)).not.toBeNull();
  });

  it("abre e fecha ao clicar, reflectindo o estado em aria-expanded", () => {
    const { container } = render(<ThinkingBlock content="Vou ler o ficheiro." />);

    const toggle = screen.getByRole("button", { expanded: false });
    fireEvent.click(toggle);
    expect(screen.getByRole("button", { expanded: true })).toBeTruthy();
    // Unique per-block `useId()`-derived id (no longer the colliding literal
    // "thinking-block-body"), so look the body up through `aria-controls`.
    const bodyId = toggle.getAttribute("aria-controls");
    expect(bodyId).toBeTruthy();
    expect(container.querySelector(`#${bodyId}`)).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { expanded: true }));
    expect(screen.getByRole("button", { expanded: false })).toBeTruthy();
  });

  it("abre automaticamente enquanto transmite", () => {
    const { container } = render(<ThinkingBlock content="a definir" isStreaming />);
    const toggle = screen.getByRole("button", { expanded: true });
    // Id is `useId()`-derived per block; assert it resolves to the open body.
    const bodyId = toggle.getAttribute("aria-controls");
    expect(bodyId).toBeTruthy();
    expect(container.querySelector(`#${bodyId}`)).not.toBeNull();
  });

  it("não renderiza nada sem conteúdo", () => {
    const { container } = render(<ThinkingBlock content="   " />);
    expect(container.innerHTML).toBe("");
  });

  it("mostra a duração real quando o passo a fornece", () => {
    render(<ThinkingBlock content="resumo" durationMs={4200} />);
    expect(screen.getByText("4s")).toBeTruthy();
  });

  it("transforma um plano JSON numa lista de tarefas", () => {
    const plan = JSON.stringify([
      { name: "Ler o schema", description: "Confirmar as colunas", agent: "ANALYZER" },
      { name: "Escrever a migração", depends_on: [0] },
    ]);
    render(<ThinkingBlock content={`Plano:\n${plan}`} defaultOpen />);

    expect(screen.getByText("Plano de execução")).toBeTruthy();
    expect(screen.getByText("2 tarefas")).toBeTruthy();
    expect(screen.getByText("Ler o schema")).toBeTruthy();
    expect(screen.getByText("Confirmar as colunas")).toBeTruthy();
    expect(screen.getByText("Depende das tarefas 1")).toBeTruthy();
  });
});

describe("extractStructuredPlan", () => {
  it("devolve null quando não há JSON", () => {
    expect(extractStructuredPlan("apenas texto")).toBeNull();
    expect(extractStructuredPlan("[isto não é json")).toBeNull();
    expect(extractStructuredPlan("[]")).toBeNull();
  });

  it("ignora um array cujas entradas não têm campos de plano", () => {
    // A chatty answer that happens to contain a bracketed list must not be
    // rendered as a plan.
    expect(extractStructuredPlan('["a", "b", "c"]')).toBeNull();
  });

  it("rejeita um plano cujas tarefas só têm nome", () => {
    // `name` alone is not a plan: a chatty answer that happens to contain
    // `[{"name": ...}]` would otherwise be promoted to an execution plan.
    expect(extractStructuredPlan('[{"name": "Tarefa"}]')).toBeNull();
  });

  it("normaliza entradas incompletas sem as descartar", () => {
    const plan = extractStructuredPlan(
      '[{"name": "Só o nome", "priority": "high"}, {"name": "Com agente", "agent": "CODER"}]',
    );
    expect(plan).toEqual([
      {
        name: "Só o nome",
        description: "",
        agent: undefined,
        priority: "high",
        dependencies: undefined,
      },
      {
        name: "Com agente",
        description: "",
        agent: "CODER",
        priority: undefined,
        dependencies: undefined,
      },
    ]);
  });

  it("descarta dependências que não são números", () => {
    const plan = extractStructuredPlan(
      '[{"name": "T", "description": "d", "depends_on": [0, "um", null, 2]}]',
    );
    expect(plan?.[0].dependencies).toEqual([0, 2]);
  });
});

describe("ExecutionActivity — collapsible accessibility", () => {
  it("expõe o estado de expansão e aponta para a lista", () => {
    const { container } = render(
      <ExecutionActivity items={[activity()]} isStreaming={false} />,
    );

    const toggle = screen.getByRole("button", { expanded: false });
    expect(toggle.hasAttribute("aria-controls")).toBe(false);
    expect(container.querySelector('[data-testid="execution-activity-body"]')).toBeNull();

    fireEvent.click(toggle);
    const bodyId = toggle.getAttribute("aria-controls");
    expect(bodyId).toBeTruthy();
    expect(container.querySelector(`#${bodyId}`)).not.toBeNull();
  });

  it("abre e fecha ao clicar", () => {
    const { container } = render(
      <ExecutionActivity items={[activity()]} isStreaming={false} />,
    );

    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(container.querySelector('[data-testid="execution-activity-body"]')).not.toBeNull();
    expect(container.querySelectorAll("li")).toHaveLength(1);
  });

  it("pluraliza o número de atualizações em pt-PT", () => {
    // The "N atualizaçãoões" bug: a fixed suffix was appended to every count.
    const { rerender } = render(
      <ExecutionActivity items={[activity()]} isStreaming={false} />,
    );
    expect(screen.getByText("1 atualização")).toBeTruthy();

    rerender(
      <ExecutionActivity
        items={[activity(), activity({ id: "a2" }), activity({ id: "a3" })]}
        isStreaming={false}
      />,
    );
    expect(screen.getByText("3 atualizações")).toBeTruthy();
  });

  it("resume os problemas quando houve erros", () => {
    render(
      <ExecutionActivity
        items={[activity({ id: "x", status: "error" }), activity({ id: "y" })]}
        isStreaming={false}
      />,
    );
    expect(screen.getByText("1 problema durante a execução")).toBeTruthy();
  });

  it("continua visível sem itens quando houve erros", () => {
    // The error count is the whole point of the panel; an empty list must not
    // hide it.
    render(<ExecutionActivity items={[]} hasErrors isStreaming={false} />);
    expect(screen.getByText("Execução concluída com problemas")).toBeTruthy();
  });

  it("não renderiza nada sem itens e sem erros", () => {
    const { container } = render(<ExecutionActivity items={[]} isStreaming={false} />);
    expect(container.innerHTML).toBe("");
  });

  it("atribui a actividade ao agente que a produziu", () => {
    render(
      <ExecutionActivity
        items={[activity({ agent: "CODER" as never })]}
        isStreaming={false}
      />,
    );
    fireEvent.click(screen.getByRole("button", { expanded: false }));
    expect(screen.getByText("CODER")).toBeTruthy();
  });
});
