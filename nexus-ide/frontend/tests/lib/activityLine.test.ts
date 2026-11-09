import { describe, expect, it } from "vitest";

import { compactActivityLine, compactToolLine } from "../../lib/activityLine";
import type { RunStep } from "../../lib/types";

function step(overrides: Partial<RunStep>): RunStep {
  return {
    seq: 1,
    kind: "tool",
    label: "a usar ferramenta",
    target: "read_file",
    verb: "tool",
    status: "success",
    icon: "wrench",
    ...overrides,
  };
}

describe("compactActivityLine", () => {
  it("mostra o ficheiro lido e o intervalo de linhas", () => {
    expect(
      compactActivityLine(
        step({
          detail: { path: "nexus-ide/frontend/components/chat/MessageBubble.tsx", start_line: 1, end_line: 400 },
        }),
      ),
    ).toBe("Leu MessageBubble.tsx L1-400");
  });

  it("mostra a pesquisa e o sítio, e o comando executado", () => {
    expect(
      compactActivityLine(
        step({
          target: "grep",
          detail: { pattern: "thinking|todo", path: "nexus-ide/frontend" },
        }),
      ),
    ).toBe("Pesquisou thinking|todo em frontend");

    expect(
      compactActivityLine(
        step({ verb: "command", kind: "command", target: "pytest -q", status: "running" }),
      ),
    ).toBe("A executar pytest -q");
  });

  it("não inventa uma linha quando só há o nome da ferramenta", () => {
    expect(compactActivityLine(step({}))).toBeNull();
    expect(compactToolLine("read_file", { path: "src/chat.tsx", offset: 10, limit: 20 }, "success")).toBe(
      "Leu chat.tsx L10-29",
    );
  });

  it("não anuncia uma leitura falhada como concluída nem uma verificação ignorada como executada", () => {
    expect(compactActivityLine(step({ status: "error", detail: { path: "example.txt" } }))).toBeNull();
    expect(compactActivityLine(step({ verb: "test", kind: "test_started", status: "pending", detail: { result: { ran: false } } })))
      .toBe("Verificação não executada");
  });
});
