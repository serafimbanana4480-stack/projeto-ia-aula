import { describe, expect, it } from "vitest";
import { getChatComposerPlaceholder, isChatComposerSendDisabled } from "../../../lib/chatComposer";

describe("chat composer session gating", () => {
  it("uses concise Portuguese prompts for idle, streaming, and blocked states", () => {
    expect(getChatComposerPlaceholder({ busyOtherSession: false, streaming: false })).toBe(
      "Escreve o que queres fazer…  (/ comandos · @ contexto)",
    );
    expect(getChatComposerPlaceholder({ busyOtherSession: false, streaming: true })).toBe(
      "Envia uma orientação ao NEXUS…",
    );
    expect(getChatComposerPlaceholder({ busyOtherSession: true, streaming: true })).toBe(
      "Outra conversa está a gerar…",
    );
  });

  it("enables submit only for non-empty input and a valid real session", () => {
    const valid = {
      input: "Continua esta conversa",
      sessionId: "session-valid",
      busyOtherSession: false,
      planCreating: false,
      streaming: false,
    };
    expect(isChatComposerSendDisabled(valid)).toBe(false);
    expect(isChatComposerSendDisabled({ ...valid, sessionId: "" })).toBe(true);
    expect(isChatComposerSendDisabled({ ...valid, sessionId: "default" })).toBe(true);
    expect(isChatComposerSendDisabled({ ...valid, sessionId: "local-offline" })).toBe(true);
    expect(isChatComposerSendDisabled({ ...valid, input: "  " })).toBe(true);
    expect(isChatComposerSendDisabled({ ...valid, busyOtherSession: true })).toBe(true);
  });
});
