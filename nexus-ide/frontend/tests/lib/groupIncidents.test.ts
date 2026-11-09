import { describe, expect, it } from "vitest";
import { groupEquivalentErrors, type GroupTranscriptMessage } from "../../lib/groupIncidents";

function message(partial: Partial<GroupTranscriptMessage> & Pick<GroupTranscriptMessage, "id" | "role" | "content">): GroupTranscriptMessage {
  return {
    bot_id: partial.bot_id ?? null,
    bot_name: partial.bot_name ?? null,
    created_at: partial.created_at ?? "2026-11-09T10:00:00Z",
    ...partial,
  };
}

const kilo = "O Kilo está bloqueado pela política só gratuita. Revê essa política e a configuração do fornecedor em Definições.";

describe("groupEquivalentErrors", () => {
  it("agrupa erros equivalentes da mesma volta e preserva a ordem técnica", () => {
    const items = groupEquivalentErrors([
      message({ id: "u1", role: "user", content: "bom dia" }),
      message({ id: "e1", role: "error", content: kilo, bot_id: "forge", bot_name: "FORGE" }),
      message({ id: "e2", role: "error", content: `${kilo}\n`, bot_id: "debug", bot_name: "Debugger" }),
      message({ id: "e3", role: "error", content: kilo, bot_id: "forge", bot_name: "FORGE" }),
    ]);
    expect(items).toHaveLength(2);
    expect(items[0]).toMatchObject({ kind: "message" });
    expect(items[1]?.kind).toBe("incident");
    if (items[1]?.kind !== "incident") return;
    expect(items[1].messages.map((item) => item.id)).toEqual(["e1", "e2", "e3"]);
    expect(items[1].turnUser?.content).toBe("bom dia");
  });

  it("não junta o mesmo texto quando há uma mensagem do utilizador pelo meio", () => {
    const items = groupEquivalentErrors([
      message({ id: "e1", role: "error", content: kilo, bot_name: "FORGE" }),
      message({ id: "u1", role: "user", content: "outra volta" }),
      message({ id: "e2", role: "error", content: kilo, bot_name: "Debugger" }),
    ]);
    expect(items.filter((item) => item.kind === "incident")).toHaveLength(2);
  });

  it("mantém respostas de agentes fora do incidente", () => {
    const items = groupEquivalentErrors([
      message({ id: "a1", role: "assistant", content: "Plano pronto", bot_name: "FORGE" }),
      message({ id: "e1", role: "error", content: "timeout", bot_name: "Debugger" }),
    ]);
    expect(items.map((item) => item.kind)).toEqual(["message", "incident"]);
  });
});
