import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { foldRun } from "../../../lib/foldRun";
import type { StreamEvent } from "../../../lib/types";
import { AgentRoster } from "../../../components/chat/WorkNarration";

describe("conversa de subagente", () => {
  afterEach(() => vi.restoreAllMocks());

  it("abre o painel, alterna entre agentes sem misturar chamadas e regressa ao chat", () => {
    // jsdom does not implement the native modal API used by the real browser.
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
    HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
    const frame = (seq: number, value: Partial<StreamEvent>): StreamEvent => ({
      type: "progress", run_id: "ui-test", seq, event_id: `event-${seq}`,
      timestamp: "2026-10-27T10:00:00Z", ...value,
    });
    const events = [
      frame(1, { type: "agent_started", agent: "NEXUS", data: { kind: "run_started" } }),
      frame(2, { type: "agent_started", agent: "CODER", task_id: "a", data: { kind: "subagent_started", name: "CODER:edit", objective: "Inspecionar A", task_id: "a" } }),
      frame(3, { type: "agent_started", agent: "DEBUGGER", task_id: "b", data: { kind: "subagent_started", name: "DEBUGGER:test", objective: "Inspecionar B", task_id: "b" } }),
      frame(4, { type: "tool_call", agent: "CODER", task_id: "a", tool_name: "read_file", tool_args: { path: "a.py" }, data: { call_id: "call-a" } }),
      frame(5, { type: "tool_call", agent: "DEBUGGER", task_id: "b", tool_name: "read_file", tool_args: { path: "b.py" }, data: { call_id: "call-b" } }),
      frame(6, { type: "tool_result", agent: "CODER", task_id: "a", tool_name: "read_file", tool_result: { content: "conteúdo A" }, data: { call_id: "call-a" } }),
      frame(7, { type: "tool_result", agent: "DEBUGGER", task_id: "b", tool_name: "read_file", tool_result: { content: "conteúdo B" }, data: { call_id: "call-b" } }),
    ];
    const message = foldRun([], events).messages[0];
    render(<AgentRoster message={message} />);

    const coder = screen.getAllByTestId("agent-roster-entry").find((item) => item.getAttribute("data-agent") === "CODER")!;
    fireEvent.click(coder.querySelector("summary")!);
    fireEvent.click(within(coder).getByRole("button", { name: "Abrir conversa no painel" }));
    let panel = screen.getByRole("dialog", { name: "Painel do agente CODER" });
    expect(within(panel).getByText("Inspecionar A")).toBeTruthy();
    expect(panel.textContent).toContain("a.py");
    expect(panel.textContent).not.toContain("b.py");
    fireEvent.click(within(panel).getByRole("button", { name: "Expandir" }));
    expect(within(panel).getByRole("button", { name: "Reduzir" })).toBeTruthy();
    fireEvent.click(within(panel).getByRole("button", { name: "DEBUGGER" }));
    panel = screen.getByRole("dialog", { name: "Painel do agente DEBUGGER" });
    expect(within(panel).getByText("Inspecionar B")).toBeTruthy();
    expect(panel.textContent).toContain("b.py");
    expect(panel.textContent).not.toContain("a.py");
    fireEvent.click(within(panel).getByRole("button", { name: "Chat" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
