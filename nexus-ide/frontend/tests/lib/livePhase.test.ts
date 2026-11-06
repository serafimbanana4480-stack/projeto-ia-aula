import { describe, expect, it } from "vitest";
import { deriveLivePhase } from "../../lib/livePhase";
import type { StreamEvent } from "../../lib/types";

const event = (type: StreamEvent["type"], extra: Partial<StreamEvent> = {}): StreamEvent => ({
  type,
  timestamp: "2026-10-27T00:00:00Z",
  ...extra,
});

describe("deriveLivePhase", () => {
  it("não inventa plano ou exploração quando só existe reflexão", () => {
    expect(deriveLivePhase([event("thinking", { agent: "CODER" })])).toEqual({
      line: "CODER: reflexão reportada",
      agents: ["CODER"],
    });
  });

  it("mostra a ferramenta como resultado recebido quando já terminou", () => {
    expect(deriveLivePhase([
      event("tool_call", { tool_name: "read_file", agent: "CODER" }),
      event("tool_result", { tool_name: "read_file", agent: "CODER" }),
    ]).line).toBe("Resultado de read_file recebido");
  });

  it("não mantém a ferramenta ativa depois de uma falha", () => {
    expect(deriveLivePhase([
      event("tool_call", { tool_name: "read_file" }),
      event("tool_error", { tool_name: "read_file" }),
    ]).line).toBe("Falha em read_file");
  });
});
