import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));

vi.mock("../../../lib/auth", () => ({ authenticatedFetch: request }));
vi.mock("../../../lib/api", () => ({ apiUrl: (path: string) => path }));
vi.mock("../../../lib/bots", () => ({
  listBots: vi.fn(async () => []),
  createBot: vi.fn(),
  updateBot: vi.fn(),
  removeBot: vi.fn(),
  getRoomMemory: vi.fn(async () => ({ pins: [], seen: {} })),
  updateRoomMemory: vi.fn(async () => ({ pins: [], seen: {} })),
}));

import GroupWorkspace from "../../../components/bots/GroupWorkspace";

const bots = ["Pixel", "Atlas"].map((name, index) => ({
  id: `b${index}`,
  session_id: `s${index}`,
  name,
  description: index === 0 ? "Programação" : "Revisão",
  instructions: "",
  provider: "lmstudio",
  model: `model${index}`,
  archived: false,
  last_message: null,
  last_active_at: "",
}));
const group = { id: "g1", name: "Equipa", bot_ids: ["b0", "b1"], last_message: "feito" };
const userMessage = (runId: string) => ({ id: "u1", role: "user", content: "Corrige o bug", bot_id: null, bot_name: null, created_at: "2026-11-13T10:00:00Z", run_id: runId, seq: 1 });
const assistantMessage = (runId: string, content = "Proposta do bot") => ({ id: "a1", role: "assistant", content, bot_id: "b0", bot_name: "Pixel", created_at: "2026-11-13T10:00:02Z", run_id: runId, seq: 4 });

const json = (body: unknown, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => body });
const frame = (event: Record<string, unknown>) => `data: ${JSON.stringify(event)}\n\n`;

const run = (overrides: Record<string, unknown>) => ({
  id: "r1",
  run_id: "r1",
  status: "completed",
  state: "completed",
  execution_engine: "primary",
  request: "Corrige o bug",
  project_root: "C:/projeto",
  file_path: "",
  tasks: [],
  records: [],
  ...overrides,
});

function streamBody(chunks: string[], failAfterChunk = false): ReadableStream<Uint8Array> {
  let sent = false;
  return new ReadableStream({
    pull(controller) {
      if (!sent) {
        sent = true;
        controller.enqueue(new TextEncoder().encode(chunks.join("")));
        return;
      }
      if (failAfterChunk) {
        controller.error(new Error("connection reset"));
        return;
      }
      controller.close();
    },
  });
}

function queue(...responses: unknown[]) {
  for (const response of responses) request.mockResolvedValueOnce(response);
}

describe("GroupWorkspace runtime state", () => {
  beforeEach(() => {
    request.mockReset();
    vi.stubGlobal("matchMedia", () => ({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  });

  it.each([
    ["completed", "Concluída"],
    ["failed", "Falhou"],
    ["cancelled", "Cancelada"],
    ["blocked", "Bloqueada"],
    ["resuming", "A retomar"],
  ])("after reload derives %s from the associated run", async (state, label) => {
    queue(
      json({ groups: [group] }),
      json({ messages: [userMessage("r1"), assistantMessage("r1")] }),
      json({ runs: [run({ state, status: state })] }),
    );
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    const phase = await screen.findByTestId("room-state");
    await waitFor(() => expect(phase.textContent).toBe(label));
  });

  it("after reload while the run is live shows the executing run and its assigned work", async () => {
    const liveRun = run({
      state: "running",
      status: "running",
      tasks: [{ id: "t1", bot_id: "b0", bot_name: "Pixel", provider: "lmstudio", model: "model0", status: "running", result: null, error: null }],
    });
    queue(json({ groups: [group] }), json({ messages: [userMessage("r1")] }), json({ runs: [liveRun] }));
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    await waitFor(() => expect(screen.getByTestId("room-state").textContent).toBe("Em execução"));
    expect(screen.getByTestId("run-card").getAttribute("data-run-state")).toBe("running");
    expect(screen.getByText("A executar")).toBeTruthy();
  });

  it("does not attach an old run when the visible turn names a new run", async () => {
    queue(
      json({ groups: [group] }),
      json({ messages: [userMessage("r2"), assistantMessage("r2")] }),
      json({
        runs: [
          run({ id: "r1", run_id: "r1", state: "completed", status: "completed", request: "Pedido antigo" }),
          run({ id: "r2", run_id: "r2", state: "running", status: "running" }),
        ],
      }),
    );
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    await waitFor(() => expect(screen.getByTestId("room-state").textContent).toBe("Em execução"));
    expect(screen.getByTestId("run-card").getAttribute("data-run-id")).toBe("r2");
  });

  it("never falls back to Em espera when the runs request fails after a reload", async () => {
    queue(
      json({ groups: [group] }),
      json({ messages: [userMessage("r1"), assistantMessage("r1")] }),
      json({ detail: "backend offline" }, 500),
    );
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    await waitFor(() => expect(screen.getByTestId("room-state").textContent).toBe("Estado indisponível"));
  });

  it("treats a dropped connection as interrupted, not as a failed run", async () => {
    const frames = [
      frame({ type: "user_message", run_id: "r1", seq: 1, message: { ...userMessage("r1"), run_id: undefined, seq: undefined } }),
      frame({ type: "run_status", run_id: "r1", seq: 2, state: "running" }),
    ];
    queue(
      json({ groups: [group] }),
      json({ messages: [] }),
      json({ runs: [] }),
      { ok: true, status: 200, body: streamBody(frames, true) },
      json({ messages: [userMessage("r1")] }),
      json({ runs: [run({ state: "running", status: "running" })] }),
      json({ groups: [group] }),
    );
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    const input = await screen.findByRole("textbox", { name: "Mensagem para o grupo" });
    await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false));
    fireEvent.change(input, { target: { value: "Corrige o bug" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar ao grupo" }));
    await waitFor(() => expect(screen.getByTestId("room-status").textContent).toContain("Ligação interrompida"));
    await waitFor(() => expect(screen.getByTestId("room-state").textContent).toBe("Em execução"));
    expect(screen.queryByText("Falhou")).toBeNull();
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });

  it("cancels the associated run and follows the run state", async () => {
    queue(
      json({ groups: [group] }),
      json({ messages: [userMessage("r1"), assistantMessage("r1")] }),
      json({ runs: [run({ state: "running", status: "running" })] }),
      json({ cancelled: true, status: "cancelling", run_id: "r1" }),
      json({ runs: [run({ state: "cancelling", status: "cancelling" })] }),
    );
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    await waitFor(() => expect(screen.getByTestId("room-state").textContent).toBe("Em execução"));
    fireEvent.click(screen.getByRole("button", { name: "Pedir paragem do grupo" }));
    await waitFor(() => expect(request.mock.calls.some((call) => String(call[0]).endsWith("/runs/r1/cancel"))).toBe(true));
    await waitFor(() => expect(screen.getByTestId("room-state").textContent).toBe("A cancelar"));
  });

  it("resumes an interrupted run through the run endpoint", async () => {
    queue(
      json({ groups: [group] }),
      json({ messages: [userMessage("r1"), assistantMessage("r1")] }),
      json({ runs: [run({ state: "interrupted", status: "interrupted" })] }),
      json({ resumed: true, status: "running", run_id: "r1" }),
      json({ runs: [run({ state: "running", status: "running" })] }),
    );
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    const card = await screen.findByTestId("run-card");
    fireEvent.click(within(card).getByRole("button", { name: /PRIMARY/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Retomar" }));
    await waitFor(() => expect(request.mock.calls.some((call) => String(call[0]).endsWith("/runs/r1/resume"))).toBe(true));
    await waitFor(() => expect(screen.getByTestId("room-state").textContent).toBe("Em execução"));
  });

  it("shows verified work, handoffs and unverified proposals as different things", async () => {
    const verifiedRun = run({
      tasks: [
        { id: "t1", bot_id: "b0", bot_name: "Pixel", provider: "lmstudio", model: "model0", status: "completed", result: "proposta inicial", error: null },
        { id: "t2", bot_id: "b1", bot_name: "Atlas", provider: "lmstudio", model: "model1", status: "completed", result: "resultado confirmado", error: null },
      ],
      records: [
        { id: "h1", task_id: "t2", kind: "reassignment", payload: { from: "Pixel", to: "Atlas", reason: "revisão" } },
        { id: "c1", task_id: "t2", kind: "tool_call", payload: { tool: "run_tests" } },
        { id: "v1", task_id: "t2", kind: "verification", payload: { verified: true, summary: "testes passaram" } },
      ],
    });
    queue(json({ groups: [group] }), json({ messages: [userMessage("r1"), assistantMessage("r1")] }), json({ runs: [verifiedRun] }));
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    const card = await screen.findByTestId("run-card");
    expect(within(card).getByText("Reatribuições e passagens")).toBeTruthy();
    expect(within(card).getByText(/Pixel → Atlas/)).toBeTruthy();
    expect(within(card).getByText("Verificado")).toBeTruthy();
    expect(within(card).getByText(/testes passaram/)).toBeTruthy();
    expect(within(card).getByText("Resultado verificado")).toBeTruthy();
    expect(within(card).getByText("Resposta do bot (não verificada)")).toBeTruthy();
    expect(within(card).getByText("run_tests")).toBeTruthy();
  });

  it("says explicitly when there is no verification evidence", async () => {
    queue(json({ groups: [group] }), json({ messages: [userMessage("r1"), assistantMessage("r1")] }), json({ runs: [run({})] }));
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    const card = await screen.findByTestId("run-card");
    expect(within(card).getByText(/Sem verificação registada/)).toBeTruthy();
    expect(within(card).queryByText("Verificado")).toBeNull();
    expect(screen.getAllByText("Proposta do bot")).toHaveLength(1);
  });

  it("deduplicates replayed stream frames and persisted history", async () => {
    const frames = [
      frame({ type: "user_message", run_id: "r1", seq: 1, message: { id: "u1", role: "user", content: "Corrige o bug", bot_id: null, bot_name: null, created_at: "2026-11-13T10:00:00Z" } }),
      frame({ type: "token", run_id: "r1", seq: 2, content: "Olá " }),
      frame({ type: "token", run_id: "r1", seq: 3, content: "mundo" }),
      frame({ type: "token", run_id: "r1", seq: 3, content: "mundo" }),
      frame({ type: "agent_message", run_id: "r1", seq: 4, message: { id: "a1", role: "assistant", content: "Olá mundo", bot_id: "b0", bot_name: "Pixel", created_at: "2026-11-13T10:00:02Z" } }),
      frame({ type: "agent_message", run_id: "r1", seq: 4, message: { id: "a1", role: "assistant", content: "Olá mundo", bot_id: "b0", bot_name: "Pixel", created_at: "2026-11-13T10:00:02Z" } }),
      frame({ type: "done", run_id: "r1", seq: 5, status: "completed" }),
    ];
    queue(
      json({ groups: [group] }),
      json({ messages: [] }),
      json({ runs: [] }),
      { ok: true, status: 200, body: streamBody(frames) },
      json({ messages: [userMessage("r1"), assistantMessage("r1", "Olá mundo")] }),
      json({ runs: [run({})] }),
      json({ groups: [group] }),
    );
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    const input = await screen.findByRole("textbox", { name: "Mensagem para o grupo" });
    await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false));
    fireEvent.change(input, { target: { value: "Corrige o bug" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar ao grupo" }));
    await waitFor(() => expect(screen.getByTestId("room-state").textContent).toBe("Concluída"));
    expect(screen.getAllByText("Olá mundo")).toHaveLength(1);
    expect(screen.getAllByRole("article")).toHaveLength(2);
  });

  it("reopens the context verification tab without presenting proposals as proof", async () => {
    queue(json({ groups: [group] }), json({ messages: [userMessage("r1"), assistantMessage("r1")] }), json({ runs: [run({})] }));
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    await screen.findByTestId("run-card");
    fireEvent.click(screen.getByRole("button", { name: "Abrir painel de contexto" }));
    fireEvent.click(screen.getByRole("tab", { name: "Verificação" }));
    const panel = await screen.findByRole("tabpanel", { name: "Verificação" });
    expect(within(panel).getByText(/Sem verificação registada/)).toBeTruthy();
  });
});
