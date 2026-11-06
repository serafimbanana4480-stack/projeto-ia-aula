import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import LiveWorkCard from "../../../components/chat/LiveWorkCard";
import type { ChatMessage } from "../../../lib/types";

describe("LiveWorkCard", () => {
  it("mostra ferramentas ativas e aprovações sem contar a mesma falha duas vezes", () => {
    const message: ChatMessage = {
      id: "live", role: "assistant", content: "", timestamp: "2026-10-27T00:00:00Z",
      steps: [{ seq: 1, kind: "tool_failed", label: "Falhou", target: "read_file", verb: "tool", status: "error", icon: "wrench" }],
      toolCalls: [
        { id: "failed", name: "read_file", args: {}, status: "error", timestamp: "2026-10-27T00:00:00Z" },
        { id: "running", name: "list_dir", args: {}, status: "running", timestamp: "2026-10-27T00:00:01Z" },
        { id: "approval", name: "write_file", args: {}, status: "awaiting_confirmation", timestamp: "2026-10-27T00:00:02Z" },
      ],
    };
    render(<LiveWorkCard message={message} />);
    expect(screen.getByText("1 ferramenta em execução")).toBeTruthy();
    expect(screen.getByText("1 aprovação pendente")).toBeTruthy();
    expect(screen.getByText("Problemas reportados")).toBeTruthy();
    expect(screen.queryByText("2 erros")).toBeNull();
  });
});
