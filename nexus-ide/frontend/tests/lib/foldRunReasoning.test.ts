/**
 * Reasoning panel contract: what a `thinking` SSE frame is allowed to do to the
 * folded message.
 *
 * These are the regressions that made the on-screen "tool reasoning" panel
 * completely non-functional:
 *   - one timeline row per streamed delta instead of one per logical block;
 *   - a red "error" X on a *successful* run that reasoned first;
 *   - `message.thinking` never populated, so the panel never mounted.
 */
import { describe, expect, it } from "vitest";
import { foldRun } from "../../lib/foldRun";
import type { StreamEvent } from "../../lib/types";

function assistant(events: StreamEvent[]) {
  const message = foldRun([], events).messages.find((item) => item.role === "assistant");
  expect(message).toBeDefined();
  return message!;
}

function thinking(
  content: string,
  seq: number,
  overrides: Partial<StreamEvent> = {},
): StreamEvent {
  return {
    type: "thinking",
    run_id: "run-reason",
    seq,
    event_id: `r-${seq}`,
    agent: "NEXUS",
    content,
    timestamp: new Date(1_700_000_000_000 + seq * 1000).toISOString(),
    ...overrides,
  };
}

describe("foldRun · painel de raciocínio", () => {
  it("popula message.thinking a partir de um frame thinking", () => {
    const message = assistant([thinking("Vou ler o ficheiro antes de responder.", 1)]);
    expect(message.thinking).toContain("Vou ler o ficheiro antes de responder.");
  });

  it("cria UM passo por bloco de raciocínio, não um por delta", () => {
    const deltas = [
      thinking("Vou ", 1),
      thinking("ler o ", 2),
      thinking("ficheiro.", 3),
    ];
    const message = assistant([...deltas]);

    const steps = message.steps ?? [];
    expect(steps.filter((step) => step.verb === "thinking")).toHaveLength(1);
    // The three deltas are still all present in the panel body.
    expect(message.thinking).toBe("Vou \nler o \nficheiro.");
    // …and the step records that it absorbed more than one frame.
    expect(steps.find((step) => step.verb === "thinking")?.repeatCount).toBe(3);
  });

  it("coalesce mesmo com o passo de agente pelo meio do stream", () => {
    // 400 deltas of reasoning is the real shape of a long thinking block.
    const events: StreamEvent[] = [];
    for (let index = 1; index <= 400; index += 1) {
      events.push(thinking(`t${index} `, index));
    }
    const message = assistant(events);
    expect((message.steps ?? []).filter((step) => step.verb === "thinking")).toHaveLength(1);
    expect(message.thinking?.length).toBeGreaterThan(400);
  });

  it("abre um passo novo quando uma nova iteração de raciocínio começa", () => {
    const message = assistant([
      thinking("thinking|iteration:1 primeira abordagem", 1),
      thinking("thinking|iteration:1 continuação", 2),
      thinking("thinking|iteration:2 segunda abordagem", 3),
    ]);
    const steps = (message.steps ?? []).filter((step) => step.verb === "thinking");
    expect(steps).toHaveLength(2);
  });

  it("fecha o passo de raciocínio com sucesso quando o run termina", () => {
    // D14: `closeDanglingWork` used to flip every still-running step to "error",
    // so a run that reasoned first ended with a red X despite succeeding.
    const message = assistant([
      thinking("A confirmar a assinatura da função.", 1),
      {
        type: "done",
        run_id: "run-reason",
        seq: 2,
        event_id: "r-done",
        timestamp: "2026-01-01T00:00:03Z",
      },
    ]);
    const step = (message.steps ?? []).find((item) => item.verb === "thinking");
    expect(step?.status).toBe("success");
  });

  it("sela o passo de raciocínio com a duração real quando a resposta começa", () => {
    const message = assistant([
      thinking("A procurar o ficheiro.", 1),
      {
        type: "token",
        run_id: "run-reason",
        seq: 2,
        event_id: "r-tok",
        content: "Encontrei.",
        timestamp: "2026-01-01T00:00:02Z",
      },
    ]);
    const step = (message.steps ?? []).find((item) => item.verb === "thinking");
    expect(step?.status).toBe("success");
    expect(typeof step?.startedAt).toBe("number");
    expect(typeof step?.durationMs).toBe("number");
    expect(step?.durationMs ?? 0).toBeGreaterThanOrEqual(0);
  });

  it("continua a marcar como erro uma ferramenta que nunca devolveu resultado", () => {
    // The fix for D14 must not hide a genuinely unfinished tool.
    const message = assistant([
      {
        type: "tool_call",
        run_id: "run-dangling",
        seq: 1,
        event_id: "d-1",
        tool_name: "run_tests",
        tool_args: {},
        timestamp: "2026-01-01T00:00:00Z",
      },
      {
        type: "done",
        run_id: "run-dangling",
        seq: 2,
        event_id: "d-2",
        timestamp: "2026-01-01T00:00:01Z",
      },
    ]);
    expect((message.steps ?? []).find((item) => item.verb === "tool")?.status).toBe("error");
  });

  it("não volta a extrair raciocínio de <thinking> colado no texto", () => {
    // D5: `sanitizeAssistantContent` already strips the tags, so the old
    // post-processing `extractThinking` was unreachable dead code. Ordering it
    // before the sanitiser instead would have overwritten the streamed
    // `message.thinking`.
    const message = assistant([
      thinking("Abordagem real do agente.", 1),
      {
        type: "token",
        run_id: "run-reason",
        seq: 2,
        event_id: "r-tok",
        content: "<thinking>resíduo antigo</thinking>Resposta final.",
        timestamp: "2026-01-01T00:00:02Z",
      },
    ]);
    expect(message.content).not.toContain("<thinking>");
    expect(message.content).toContain("Resposta final.");
    // The real, streamed reasoning survived untouched.
    expect(message.thinking).toBe("Abordagem real do agente.");
  });
});
