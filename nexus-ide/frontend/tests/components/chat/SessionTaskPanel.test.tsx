import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionTodo, SessionTodoSnapshot } from "../../../lib/api";
import SessionTaskPanel from "../../../components/chat/SessionTaskPanel";
import { useChatTelemetryStore } from "../../../stores/chatTelemetryStore";

const mocks = vi.hoisted(() => ({ getSessionTodos: vi.fn() }));
vi.mock("../../../lib/api", () => ({ getSessionTodos: (...args: unknown[]) => mocks.getSessionTodos(...args) }));
const snapshot = (session_id: string, todos: SessionTodo[]): SessionTodoSnapshot => ({ session_id, todos, counts: {} });
const todo = (id: number, status: SessionTodo["status"]): SessionTodo => ({ id, status, content: `Tarefa ${id}` });

describe("durable session checklist", () => {
  beforeEach(() => { mocks.getSessionTodos.mockReset(); useChatTelemetryStore.getState().clear(); });
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it("restores persisted tasks and excludes cancelled tasks from actionable progress", async () => {
    mocks.getSessionTodos.mockResolvedValue(snapshot("a", [todo(1, "completed"), todo(2, "in_progress"), todo(3, "cancelled")]));
    const view = render(<SessionTaskPanel sessionId="a" />);
    await screen.findByText("Tarefa 1");
    expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("50");
    expect(screen.getByRole("note").textContent).toMatch(/declarados pelo agente.*não verifica/i);
    expect(screen.getByText("Marcada como concluída")).toBeTruthy();
    expect(screen.getByText("Cancelada")).toBeTruthy();
    view.unmount();
    render(<SessionTaskPanel sessionId="a" />);
    expect(await screen.findByText("Tarefa 2")).toBeTruthy();
    expect(mocks.getSessionTodos).toHaveBeenCalledTimes(2);
  });

  it("ignores a late response from the previous session", async () => {
    let resolve!: (value: SessionTodoSnapshot) => void;
    mocks.getSessionTodos.mockImplementationOnce(() => new Promise((done) => { resolve = done; }))
      .mockResolvedValueOnce(snapshot("b", [{ ...todo(2, "pending"), content: "Sessão B" }]));
    const view = render(<SessionTaskPanel sessionId="a" />);
    view.rerender(<SessionTaskPanel sessionId="b" />);
    await screen.findByText("Sessão B");
    await act(async () => { resolve(snapshot("a", [{ ...todo(1, "completed"), content: "Sessão A" }])); });
    expect(screen.queryByText("Sessão A")).toBeNull();
    expect(screen.getByText("Sessão B")).toBeTruthy();
  });

  it("keeps the last durable snapshot visible when refresh fails", async () => {
    mocks.getSessionTodos.mockResolvedValueOnce(snapshot("a", [todo(1, "pending")]))
      .mockRejectedValueOnce(new Error("Checklist inválida"));
    render(<SessionTaskPanel sessionId="a" />);
    await screen.findByText("Tarefa 1");
    fireEvent.click(screen.getByRole("button", { name: "Atualizar checklist" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("última leitura"));
    expect(screen.getByText("Tarefa 1")).toBeTruthy();
  });

  it("does not overlap a slow poll and stops polling after a run finishes", async () => {
    vi.useFakeTimers();
    let resolve!: (value: SessionTodoSnapshot) => void;
    mocks.getSessionTodos.mockImplementationOnce(() => new Promise((done) => { resolve = done; }))
      .mockResolvedValue(snapshot("a", [todo(1, "completed")]));
    useChatTelemetryStore.getState().setStream("a", true, []);
    render(<SessionTaskPanel sessionId="a" />);
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(mocks.getSessionTodos).toHaveBeenCalledTimes(1);
    await act(async () => { resolve(snapshot("a", [todo(1, "pending")])); });
    await act(async () => { useChatTelemetryStore.getState().setStream("a", false, []); });
    const calls = mocks.getSessionTodos.mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(15_000); });
    expect(mocks.getSessionTodos).toHaveBeenCalledTimes(calls);
  });
});
