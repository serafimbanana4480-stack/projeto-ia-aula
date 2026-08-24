import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import RunTimeline from "../../../components/chat/RunTimeline";
import type { ChatMessage } from "../../../lib/types";

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

describe("RunTimeline", () => {
  it("não renderiza nada quando não há passos nem actividade", () => {
    const { container } = render(
      <RunTimeline message={makeMessage()} isStreaming={false} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renderiza uma linha por passo, ordenada por seq", () => {
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

    const rows = screen.getAllByTestId("run-step");
    // seq 1 (tool) vem antes do seq 3 (file), mesmo tendo sido inserido depois
    expect(rows[0].textContent).toContain("a usar ferramenta");
    expect(rows[1].textContent).toContain("a ler");
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

    expect(screen.getByText("fase: verificar")).toBeTruthy();
    expect(screen.getByText("1s 500ms")).toBeTruthy();
    expect(screen.getByText("15 tokens")).toBeTruthy();
  });
});
