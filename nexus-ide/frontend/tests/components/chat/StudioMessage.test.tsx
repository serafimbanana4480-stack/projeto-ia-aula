import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import StudioMessage from "../../../components/chat/studio/StudioMessage";
import type { ChatMessage } from "../../../lib/types";

function message(partial: Partial<ChatMessage> & Pick<ChatMessage, "role" | "content">): ChatMessage {
  return { id: "m1", timestamp: "2026-11-09T08:10:00Z", ...partial };
}

describe("StudioMessage", () => {
  it("mostra o pedido do utilizador e permite responder", () => {
    const onReply = vi.fn();
    render(<StudioMessage message={message({ role: "user", content: "Explica o parser" })} onReply={onReply} />);
    expect(screen.getByText("Tu")).toBeTruthy();
    expect(screen.getByText("Explica o parser")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Responder" }));
    expect(onReply).toHaveBeenCalledWith("Explica o parser");
  });

  it("renderiza markdown do assistente e distingue um erro", () => {
    const { rerender } = render(
      <StudioMessage message={message({ role: "assistant", content: "**Parser** valida a entrada", agent: "NEXUS" })} />,
    );
    expect(screen.getByText("Parser").tagName).toBe("STRONG");
    expect(screen.getByText("Assistente")).toBeTruthy();

    rerender(
      <StudioMessage
        message={message({
          role: "assistant",
          content: "o fornecedor recusou",
          metadata: { kind: "error", outcome: "interrupted" },
        })}
      />,
    );
    expect(screen.getByText("Interrompido")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Responder" })).toBeNull();
  });
});
