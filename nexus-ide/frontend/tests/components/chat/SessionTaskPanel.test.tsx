import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SessionTodo, SessionTodoSnapshot } from "../../../lib/api";
import SessionTaskPanel, { clearSessionTodoCache, declaredTodoCount } from "../../../components/chat/SessionTaskPanel";
import { AGENT_DECLARED_TODO_CAVEAT } from "../../../lib/foldRun";
import { useChatTelemetryStore } from "../../../stores/chatTelemetryStore";

const mocks = vi.hoisted(() => ({ getSessionTodos: vi.fn(), updateSessionTodo: vi.fn() }));
vi.mock("../../../lib/api", () => ({ getSessionTodos: (...args: unknown[]) => mocks.getSessionTodos(...args), updateSessionTodo: (...args: unknown[]) => mocks.updateSessionTodo(...args) }));
const snapshot = (session_id: string, todos: SessionTodo[], counts: Record<string, number> = {}): SessionTodoSnapshot => ({ session_id, todos, counts });
const todo = (id: number, status: SessionTodo["status"], priority?: string): SessionTodo => ({ id, status, content: `Tarefa ${id}`, ...(priority ? { priority } : {}) });

describe("durable session checklist", () => {
  beforeEach(() => { mocks.getSessionTodos.mockReset(); clearSessionTodoCache(); useChatTelemetryStore.getState().clear(); });
  afterEach(() => { cleanup(); vi.useRealTimers(); });

  it("conta só os itens presentes, incluindo canceladas, sem percentagem", async () => {
    mocks.getSessionTodos.mockResolvedValue(snapshot("a", [
      todo(1, "completed"),
      todo(2, "in_progress"),
      todo(3, "cancelled"),
    ], { completed: 9, total: 9 }));
    const view = render(<SessionTaskPanel sessionId="a" />);
    await screen.findByText("Tarefa 1");
    expect(declaredTodoCount([todo(1, "completed"), todo(2, "in_progress"), todo(3, "cancelled")])).toEqual({ done: 1, total: 3 });
    expect(screen.getByText("1 de 3 concluída")).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.getByRole("note").textContent).toBe(AGENT_DECLARED_TODO_CAVEAT);
    expect(screen.getByText("Tarefa 1").closest("li")?.getAttribute("data-status")).toBe("completed");
    expect(screen.getByText("concluída")).toBeTruthy();
    expect(screen.getByText("cancelada")).toBeTruthy();
    expect(screen.getByText("Tarefa 1").className).not.toMatch(/line-through/);
    view.unmount();
    render(<SessionTaskPanel sessionId="a" />);
    expect(await screen.findByText("Tarefa 2")).toBeTruthy();
    // A second mounted copy within the throttle window reuses the latest read.
    expect(mocks.getSessionTodos).toHaveBeenCalledTimes(1);
  });

  it("mostra um empty state curto quando a sessão não tem tarefas", async () => {
    mocks.getSessionTodos.mockResolvedValue(snapshot("a", [], { total: 4, completed: 4 }));
    render(<SessionTaskPanel sessionId="a" />);
    expect(await screen.findByText("Ainda não há tarefas nesta sessão.")).toBeTruthy();
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByText(/de \d+ concluíd/)).toBeNull();
    expect(screen.getByRole("note").textContent).toBe(AGENT_DECLARED_TODO_CAVEAT);
  });

  it("guarda uma alteração manual numa tarefa hierárquica", async () => {
    const objective: SessionTodo = { id: 1, content: "Plano", type: "objective", status: "pending" };
    const task: SessionTodo = { id: 2, content: "Verificar", type: "task", parent_id: 1, status: "pending" };
    mocks.getSessionTodos.mockResolvedValue(snapshot("a", [objective, task]));
    mocks.updateSessionTodo.mockResolvedValue(snapshot("a", [objective, { ...task, status: "completed" }]));
    render(<SessionTaskPanel sessionId="a" />);
    fireEvent.click(await screen.findByRole("checkbox", { name: "Concluída: Verificar" }));
    await waitFor(() => expect(mocks.updateSessionTodo).toHaveBeenCalledWith("a", "2", { status: "completed" }));
    expect(await screen.findByText("1 / 1 concluídas · 100%")).toBeTruthy();
  });

  it("mantém o chat de pé se a telemetria da sessão vier incompleta", async () => {
    useChatTelemetryStore.setState({
      sessionId: "a",
      events: undefined as unknown as import("../../../lib/types").StreamEvent[],
    });
    mocks.getSessionTodos.mockResolvedValue(snapshot("a", []));

    expect(() => render(<SessionTaskPanel sessionId="a" />)).not.toThrow();
    expect(await screen.findByText("Ainda não há tarefas nesta sessão.")).toBeTruthy();
  });

  it("mostra erro recuperável se a API devolver uma checklist sem lista de tarefas", async () => {
    mocks.getSessionTodos.mockResolvedValue({ session_id: "a" } as SessionTodoSnapshot);
    render(<SessionTaskPanel sessionId="a" />);
    expect((await screen.findByRole("alert")).textContent).toContain("resposta da checklist da sessão é inválida");
    expect(screen.queryByText("Ainda não há tarefas nesta sessão.")).toBeNull();
  });

  it("normaliza eventos inválidos antes de guardar telemetria", () => {
    const setStream = useChatTelemetryStore.getState().setStream;
    act(() => {
      setStream("a", false, undefined as unknown as import("../../../lib/types").StreamEvent[]);
    });
    expect(useChatTelemetryStore.getState().events).toEqual([]);
  });

  it("não marca concluída só porque a leitura não falhou nem porque counts diz que sim", async () => {
    mocks.getSessionTodos.mockResolvedValue(snapshot("a", [
      todo(1, "pending"),
      todo(2, "in_progress", "high"),
    ], { completed: 2, total: 2 }));
    render(<SessionTaskPanel sessionId="a" />);
    await screen.findByText("Tarefa 1");
    expect(screen.getByText("0 de 2 concluídas")).toBeTruthy();
    expect(screen.getByText("Tarefa 1").closest("li")?.getAttribute("data-status")).toBe("pending");
    expect(screen.getByText("Tarefa 2").closest("li")?.getAttribute("data-status")).toBe("in_progress");
    expect(screen.getByText("pendente")).toBeTruthy();
    expect(screen.queryByText("concluída")).toBeNull();
    expect(screen.getByText("prioridade alta")).toBeTruthy();
    expect(screen.getByText("Tarefa 1").closest("li")?.textContent).not.toMatch(/prioridade/i);
    expect(screen.getByRole("note").textContent).toBe(AGENT_DECLARED_TODO_CAVEAT);
    expect(screen.queryByRole("progressbar")).toBeNull();
  });

  it("ignores uma resposta tardia da sessão anterior", async () => {
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

  it("mantém a última leitura quando o refresh falha", async () => {
    mocks.getSessionTodos.mockResolvedValueOnce(snapshot("a", [todo(1, "pending")]))
      .mockRejectedValueOnce(new Error("Checklist inválida"));
    render(<SessionTaskPanel sessionId="a" />);
    await screen.findByText("Tarefa 1");
    fireEvent.click(screen.getByRole("button", { name: "Atualizar checklist" }));
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("última leitura"));
    expect(screen.getByText("Tarefa 1").closest("li")?.getAttribute("data-status")).toBe("pending");
    expect(screen.queryByText("concluída")).toBeNull();
  });

  it("navega a lista com o teclado", async () => {
    mocks.getSessionTodos.mockResolvedValue(snapshot("a", [todo(1, "pending"), todo(2, "in_progress")]));
    render(<SessionTaskPanel sessionId="a" />);
    const first = await screen.findByRole("listitem", { name: /Tarefa 1/ });
    act(() => { first.focus(); });
    act(() => { fireEvent.keyDown(first, { key: "ArrowDown" }); });
    expect(document.activeElement?.textContent).toContain("Tarefa 2");
    act(() => { fireEvent.keyDown(document.activeElement as HTMLElement, { key: "ArrowUp" }); });
    expect(document.activeElement?.textContent).toContain("Tarefa 1");
  });

  it("não sobrepõe um poll lento e para quando a execução acaba", async () => {
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
