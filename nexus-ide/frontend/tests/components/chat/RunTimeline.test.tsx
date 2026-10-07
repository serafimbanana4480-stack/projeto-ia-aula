import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import RunTimeline from "../../../components/chat/RunTimeline";
import { AGENT_DECLARED_TODO_CAVEAT } from "../../../lib/foldRun";
import type { ChatMessage, RunStep } from "../../../lib/types";

function makeMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: "m1",
    role: "assistant",
    agent: "NEXUS",
    content: "Pronto.",
    timestamp: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

/** Open the collapsed timeline, the way a user does. */
function expand(): void {
  fireEvent.click(screen.getByTestId("run-timeline-toggle"));
}

/** The collapsed header of one rendered run. */
function headerOf(container: HTMLElement): HTMLElement {
  const header = container.querySelector('[data-testid="run-timeline-toggle"]');
  if (!header) throw new Error("run header not rendered");
  return header as HTMLElement;
}

/** The green completion mark. Only a run that REPORTED completion may have it. */
function showsGreenCompletion(container: HTMLElement): boolean {
  return headerOf(container).querySelector(".text-emerald-400") !== null;
}

/** The status pill stating what the run actually reported. */
function outcomePill(container: HTMLElement): string | null {
  return headerOf(container).querySelector('[data-testid="run-outcome-pill"]')?.textContent ?? null;
}

function makeStep(overrides: Partial<RunStep> & Pick<RunStep, "seq" | "kind">): RunStep {
  return {
    label: "passo",
    target: "",
    verb: "status",
    status: "success",
    icon: "activity",
    ...overrides,
  } as RunStep;
}

describe("RunTimeline", () => {
  it("não renderiza nada quando não há passos nem actividade", () => {
    const { container } = render(
      <RunTimeline message={makeMessage()} isStreaming={false} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("mantém o corpo fechado fora do DOM enquanto colapsado", () => {
    // The body used to stay mounted behind `className="hidden"`, so every tool
    // result of every run in a long session was in the DOM (and reachable by
    // assistive tech) even when the user never opened it.
    render(
      <RunTimeline
        message={makeMessage({
          steps: [
            {
              seq: 1,
              kind: "tool_started",
              label: "a usar ferramenta",
              target: "read_file",
              verb: "tool",
              status: "success",
              icon: "wrench",
              detail: {},
            },
          ],
        })}
        isStreaming={false}
      />,
    );

    expect(screen.getByTestId("run-timeline-toggle").getAttribute("aria-expanded")).toBe(
      "false",
    );
    expect(screen.getByTestId("run-timeline-toggle").hasAttribute("aria-controls")).toBe(false);
    expect(screen.queryAllByTestId("run-step")).toHaveLength(0);
    expect(screen.queryByTestId("run-timeline-body")).toBeNull();
  });

  it("mantém IDs de controlo únicos quando várias execuções estão na conversa", () => {
    const message = makeMessage({
      steps: [
        {
          seq: 1,
          kind: "tool_started",
          label: "a usar ferramenta",
          target: "read_file",
          verb: "tool",
          status: "success",
          icon: "wrench",
        },
      ],
    });
    const { container } = render(
      <>
        <RunTimeline message={{ ...message, id: "m1" }} isStreaming={false} />
        <RunTimeline message={{ ...message, id: "m2" }} isStreaming={false} />
      </>,
    );

    const toggles = screen.getAllByTestId("run-timeline-toggle");
    toggles.forEach((toggle) => fireEvent.click(toggle));

    const bodyIds = toggles.map((toggle) => toggle.getAttribute("aria-controls"));
    expect(new Set(bodyIds).size).toBe(2);
    expect(bodyIds.every((id) => id && container.querySelector(`#${id}`))).toBe(true);
  });

  it("renderiza uma linha por passo, ordenada por seq, depois de expandir", () => {
    render(
      <RunTimeline
        message={
          makeMessage({
            steps: [
              {
                seq: 3,
                kind: "file_read",
                label: "a ler",
                target: "b.py",
                verb: "file",
                status: "success",
                icon: "file-text",
                detail: {},
              },
              {
                seq: 1,
                kind: "tool_started",
                label: "a usar ferramenta",
                target: "read_file",
                verb: "tool",
                status: "success",
                icon: "wrench",
                detail: {},
              },
            ],
          })
        }
        isStreaming={false}
      />,
    );

    expand();

    const rows = screen.getAllByTestId("run-step");
    // seq 1 (tool) vem antes do seq 3 (file), mesmo tendo sido inserido depois
    expect(rows[0].textContent).toContain("a usar ferramenta");
    expect(rows[1].textContent).toContain("a ler");
  });

  it("mantém a tarefa atual visível antes de chegarem detalhes do run", () => {
    render(<RunTimeline message={makeMessage()} isStreaming />);

    expect(screen.getByText("Tarefa atual")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe("A iniciar execução…");
  });

  it("agrupa apenas passos adjacentes com o mesmo task_id explícito", () => {
    render(
      <RunTimeline
        message={makeMessage({
          steps: [
            { seq: 1, kind: "subagent_started", label: "começou", target: "CODER", verb: "agent", status: "success", icon: "bot", taskId: "task-1", agent: "CODER" },
            { seq: 2, kind: "waiting_dependency", label: "à espera", target: "CODER", verb: "status", status: "pending", icon: "activity", taskId: "task-1", agent: "CODER" },
          ],
        })}
        isStreaming={false}
      />,
    );

    expand();
    const group = screen.getByTestId("run-step-group");
    expect(group.textContent).toContain("CODER");
    expect(group.textContent).toContain("2 atualizações da mesma tarefa");
    expect((group as HTMLDetailsElement).open).toBe(false);

    fireEvent.click(group.querySelector("summary")!);
    expect(screen.getAllByTestId("run-step")).toHaveLength(2);
  });

  it("mostra o plano e os estados que vieram dos todos reais", () => {
    render(
      <RunTimeline
        message={makeMessage({
          activities: [
            {
              id: "plan-1",
              kind: "plan",
              title: "Plano atualizado",
              status: "running",
              timestamp: "2026-01-01T00:00:00Z",
              data: {
                todos: [
                  { id: 1, content: "Inspecionar o frontend", status: "completed" },
                  { id: 2, content: "Refatorizar a timeline", status: "in_progress" },
                ],
              },
            },
          ],
        })}
        isStreaming={false}
      />,
    );

    expand();

    expect(screen.getByText("1 de 2 concluídas")).toBeTruthy();
    expect(screen.getByText("Inspecionar o frontend")).toBeTruthy();
    expect(screen.getByText("Refatorizar a timeline")).toBeTruthy();
  });

  it("mostra o rodapé vivo com fase, tempo e tokens", () => {
    render(
      <RunTimeline
        message={
          makeMessage({
            metrics: { Input: "10", Output: "5", Total: "15" },
            metadata: {
              footer: { phase: "verificar", elapsedMs: 1500, telemetry: {} },
            },
          })
        }
        isStreaming={false}
      />,
    );

    expect(screen.getByText("verificar")).toBeTruthy();
    expect(screen.getByText("1,5s")).toBeTruthy();
    expect(screen.getByText("15 tokens")).toBeTruthy();
  });

  it("mostra o chip 'raciocinou' mesmo sem um passo de raciocínio", () => {
    render(
      <RunTimeline
        message={makeMessage({ thinking: "Vou ler o ficheiro e resumir." })}
        isStreaming={false}
      />,
    );

    expect(screen.getByText("raciocinou")).toBeTruthy();
  });

  it("mostra o chip 'raciocinou' a partir de um passo de raciocínio", () => {
    render(
      <RunTimeline
        message={makeMessage({
          steps: [
            {
              seq: 1,
              kind: "thinking",
              label: "a definir a abordagem",
              target: "",
              verb: "thinking",
              status: "success",
              icon: "brain",
              detail: {},
            },
          ],
        })}
        isStreaming={false}
      />,
    );

    expect(screen.getByText("raciocinou")).toBeTruthy();
  });

  it("mostra o painel de raciocínio com o cabeçalho e a duração reais", () => {
    render(
      <RunTimeline
        message={makeMessage({
          thinking: "Primeiro confirmo o ficheiro, depois aplico a correção.",
          steps: [
            {
              seq: 1,
              kind: "thinking",
              label: "a definir a abordagem",
              target: "",
              verb: "thinking",
              status: "success",
              icon: "brain",
              startedAt: 1_700_000_000_000,
              durationMs: 4200,
              detail: {},
            },
          ],
        })}
        isStreaming={false}
      />,
    );

    expand();

    // Not streaming -> "Resumo da abordagem", with the folded step duration.
    expect(screen.getByText("Resumo da abordagem")).toBeTruthy();
    expect(screen.getByText("4s")).toBeTruthy();
  });

  it("mostra os tokens de raciocínio no rodapé", () => {
    render(
      <RunTimeline
        message={
          makeMessage({
            metrics: { Input: "10", Output: "5", "Raciocínio": "812", Total: "827" },
          })
        }
        isStreaming={false}
      />,
    );

    expect(screen.getByText("812 em raciocínio")).toBeTruthy();
  });

  it("mostra ID, provider, simulação e origem estimada sem inventar zero de raciocínio", () => {
    render(
      <RunTimeline
        message={makeMessage({
          runId: "run-observed-123",
          metadata: {
            footer: {
              phase: "concluída",
              elapsedMs: 2500,
              telemetry: {
                input_tokens: 12,
                output_tokens: 5,
                total_tokens: 17,
                reasoning_tokens: 0,
                reasoning_source: "not_measured",
                source: "estimated",
                provider: { name: "local-provider", model: "qwen-test", simulation: true },
              },
            },
          },
        })}
        isStreaming={false}
      />,
    );

    expect(screen.getByTestId("run-id").textContent).toContain("run-observed-123");
    expect(screen.getByTestId("run-provider").textContent).toBe("local-provider · qwen-test");
    expect(screen.getByText("simulação")).toBeTruthy();
    expect(screen.getByTestId("token-source").textContent).toBe("Estimativa NEXUS");
    expect(screen.getByText("2,5s")).toBeTruthy();
    expect(screen.queryByText(/em raciocínio/)).toBeNull();
  });

  it("abre a vista de grafo com dependências explicitamente reportadas", () => {
    render(
      <RunTimeline
        message={makeMessage({
          activities: [
            {
              id: "agent-task-a",
              kind: "agent",
              title: "ANALYZER concluiu",
              agent: "ANALYZER",
              status: "success",
              timestamp: "2026-09-27T00:00:01Z",
              data: { task_id: "task-a", name: "ANALYZER", objective: "Inspecionar" },
            },
            {
              id: "agent-task-b",
              kind: "agent",
              title: "REVIEWER a executar",
              agent: "REVIEWER",
              status: "running",
              timestamp: "2026-09-27T00:00:02Z",
              data: {
                task_id: "task-b",
                name: "REVIEWER",
                objective: "Rever",
                depends_on: ["task-a"],
              },
            },
          ],
        })}
        isStreaming={false}
      />,
    );

    expand();
    fireEvent.click(screen.getByTestId("execution-view-graph"));

    expect(screen.getByTestId("execution-graph")).toBeTruthy();
    expect(screen.getByTestId("execution-graph-edge").getAttribute("aria-label")).toBe(
      "REVIEWER depende de ANALYZER",
    );
    expect(screen.getByTestId("execution-view-graph").getAttribute("aria-pressed")).toBe("true");
  });

  // Truthfulness of the collapsed header. It used to fall through to a green
  // "completed" dot for every run that had not reported a failure, which made
  // a run interrupted by a backend restart look exactly like a finished one.
  describe("estado reportado pelo run", () => {
    const toolStep = makeStep({
      seq: 1,
      kind: "tool_started",
      label: "a usar ferramenta",
      target: "read_file",
      verb: "tool",
      status: "success",
      icon: "wrench",
    });

    it("não mostra conclusão verde quando a única evidência de problema é uma activity de warning", () => {
      // `sessionRecovery` injects exactly this activity for a run the backend
      // recorded as interrupted (backend restart / killed process).
      const { container } = render(
        <RunTimeline
          message={makeMessage({
            steps: [toolStep],
            activities: [
              {
                id: "checkpoint-run-1",
                kind: "status",
                title: "Execução interrompida",
                status: "warning",
                timestamp: "2026-01-01T00:00:01Z",
                data: { run_id: "run-1", source: "persisted_checkpoint" },
              },
            ],
          })}
          isStreaming={false}
        />,
      );

      expect(showsGreenCompletion(container)).toBe(false);
      expect(outcomePill(container)).toBe("1 erro");
    });

    it("não mostra conclusão verde a partir da simples ausência de erro", () => {
      // Every step succeeded, but nothing in the run ever reported a terminal
      // state: silence is not completion.
      const { container } = render(
        <RunTimeline message={makeMessage({ steps: [toolStep] })} isStreaming={false} />,
      );

      expect(showsGreenCompletion(container)).toBe(false);
      expect(outcomePill(container)).toBe("estado final não confirmado");
    });

    it("mostra a conclusão verde quando o run reportou mesmo que terminou", () => {
      const { container } = render(
        <RunTimeline
          message={makeMessage({
            steps: [toolStep],
            metadata: { footer: { phase: "concluída" } },
            activities: [
              {
                id: "agent-n",
                kind: "agent",
                title: "NEXUS concluiu a sua parte",
                agent: "NEXUS",
                status: "success",
                timestamp: "2026-01-01T00:00:01Z",
                data: { kind: "run_completed" },
              },
            ],
          })}
          isStreaming={false}
        />,
      );

      expect(showsGreenCompletion(container)).toBe(true);
      expect(outcomePill(container)).toBeNull();
    });

    it("distingue uma execução interrompida de uma falhada e de uma cancelada", () => {
      const failed = makeMessage({
        steps: [toolStep, makeStep({ seq: 2, kind: "command_failed", status: "error", verb: "command" })],
      });
      const cancelled = makeMessage({
        steps: [
          toolStep,
          makeStep({
            seq: 2,
            kind: "run_cancelled",
            label: "execução parada a pedido do utilizador",
            status: "cancelled",
          }),
        ],
      });
      // The backend's RUN_INTERRUPTED frame — neither failed nor cancelled.
      const interrupted = makeMessage({
        steps: [
          toolStep,
          makeStep({ seq: 2, kind: "command_failed", status: "error", verb: "command" }),
          makeStep({
            seq: 3,
            kind: "run_interrupted",
            label: "execução interrompida",
            status: "warning",
          }),
        ],
      });

      const rendered = render(
        <>
          <RunTimeline message={{ ...failed, id: "f" }} isStreaming={false} />
          <RunTimeline message={{ ...cancelled, id: "c" }} isStreaming={false} />
          <RunTimeline message={{ ...interrupted, id: "i" }} isStreaming={false} />
        </>,
      );
      const headers = rendered.container.querySelectorAll('[data-testid="run-timeline-toggle"]');
      const pills = Array.from(headers).map((header) =>
        header.querySelector('[data-testid="run-outcome-pill"]')?.textContent,
      );

      expect(pills).toEqual(["1 erro", "execução cancelada", "execução interrompida"]);
      // Amber warning colour for the interruption — the same one the header
      // already uses for a warning — and no rose anywhere on it.
      expect(headers[2].querySelector(".text-amber-300")).not.toBeNull();
      expect(headers[2].querySelector(".text-rose-400")).toBeNull();
      expect(headers[2].querySelector(".text-emerald-400")).toBeNull();
      // An interrupted run is not a failed one even when it also failed a step.
      expect(headers[1].querySelector(".text-rose-400")).toBeNull();
    });

    it("declara no plano que os estados são declarados pelo agente", () => {
      render(
        <RunTimeline
          message={makeMessage({
            activities: [
              {
                id: "plan-1",
                kind: "plan",
                title: "Plano atualizado",
                status: "running",
                timestamp: "2026-01-01T00:00:00Z",
                data: { todos: [{ id: 1, content: "Refatorizar a timeline", status: "completed" }] },
              },
            ],
          })}
          isStreaming={false}
        />,
      );

      expand();

      // Same sentence, same `role="note"` semantics as the checklist and the
      // session panel: the ticks are a claim the agent made about itself.
      const caveat = screen.getByText(AGENT_DECLARED_TODO_CAVEAT);
      expect(caveat.getAttribute("role")).toBe("note");
      expect(screen.getByLabelText("Plano de execução").contains(caveat)).toBe(true);
    });
  });
});
