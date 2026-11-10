import { describe, expect, it } from "vitest";
import { agentActivity, applyMention, dayLabel, fileRunRole, mentionRange, previousAgentSpeaker, quoteDraft } from "../../../components/bots/chat/model";

describe("bot chat model", () => {
  it("nomeia o dia a partir da data real", () => {
    const now = new Date("2026-11-09T15:00:00Z");
    expect(dayLabel("2026-11-09T10:00:00Z", now)).toBe("Hoje");
    expect(dayLabel("2026-11-08T10:00:00Z", now)).toBe("Ontem");
    expect(dayLabel("não é data", now)).toBe("");
  });

  it("insere uma menção sem inventar encaminhamento", () => {
    const value = "revê isto @Fo";
    const range = mentionRange(value, value.length);
    expect(range).toEqual({ start: value.length - 3, query: "Fo" });
    expect(applyMention(value, value.length, "FORGE")).toEqual({ value: "revê isto @FORGE ", caret: "revê isto @FORGE ".length });
    expect(mentionRange("sem arroba", 4)).toBeNull();
  });

  it("deriva a atividade só do turno ou da tarefa", () => {
    expect(agentActivity({ name: "FORGE", configured: true, partialName: "FORGE", taskStatus: "pending" })).toBe("A responder");
    expect(agentActivity({ name: "Debugger", configured: true, partialName: null, taskStatus: "running" })).toBe("A executar");
    expect(agentActivity({ name: "PULSE", configured: false, partialName: null })).toBe("Por configurar");
    expect(fileRunRole(0, 3)).toBe("Lê o ficheiro");
    expect(fileRunRole(1, 3)).toBe("Contribuição");
    expect(fileRunRole(2, 3)).toBe("Revisão crítica");
  });

  it("só desenha passagem entre agentes consecutivos", () => {
    const items = [
      { kind: "message", message: { role: "user", id: "u", bot_id: null, bot_name: null } },
      { kind: "message", message: { role: "assistant", id: "a", bot_id: "forge", bot_name: "FORGE" } },
      { kind: "message", message: { role: "assistant", id: "b", bot_id: "debug", bot_name: "Debugger" } },
    ];
    expect(previousAgentSpeaker(items, 1)).toBeNull();
    expect(previousAgentSpeaker(items, 2)).toEqual({ id: "forge", name: "FORGE" });
    expect(quoteDraft("FORGE", "linha", "")).toContain("> linha");
  });
});
