import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../../../lib/auth", () => ({ authenticatedFetch: request }));
vi.mock("../../../lib/api", () => ({ apiUrl: (path: string) => path }));
import GroupRuns from "../../../components/bots/GroupRuns";

const response = (body: unknown) => ({ ok: true, status: 200, json: async () => body });

it("starts a run and displays durable task evidence", async () => {
  const run = { id: "r1", status: "completed", request: "Rever", project_root: ".", file_path: "x.py", tasks: [{ id: "t1", bot_name: "A", provider: "local", model: "m", status: "completed", result: "resultado", error: null }], records: [{ id: "read1", task_id: "t1", kind: "tool_result", payload: { content: "ficheiro", call_id: "call1" } }] };
  request.mockReset().mockResolvedValueOnce({ ok: true, json: async () => ({ runs: [] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "r1" }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ runs: [run] }) });
  render(<GroupRuns groupId="g1" />);
  fireEvent.click(screen.getByRole("button", { name: /Execuções de equipa/ }));
  fireEvent.change(screen.getByLabelText("Ficheiro a ler"), { target: { value: "x.py" } });
  fireEvent.change(screen.getByLabelText("Pedido da execução"), { target: { value: "Rever" } });
  fireEvent.click(screen.getByRole("button", { name: "Iniciar execução" }));
  await waitFor(() => expect(screen.getByText(/Execução r1/)).toBeTruthy());
  expect(request.mock.calls[1][0]).toBe("/api/bot-groups/g1/runs");
  expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({ message: "Rever", file_path: "x.py", project_path: "." });
  expect(screen.getByText("local · m")).toBeTruthy();
  expect(screen.getByText(/tool_result · read1/)).toBeTruthy();
});

it("renders legacy_file, primary and unknown engines without inventing a state", async () => {
  const runs = [
    {
      id: "run-abc", run_id: "run-abc", execution_engine: "primary", state: "running", status: "running",
      request: "Pedido PRIMARY", tasks: [], records: [
        { id: "v1", task_id: "t1", kind: "verification", payload: { verified: true, summary: "teste passou" } },
      ],
    },
    {
      id: "legacy1", execution_engine: "legacy_file", status: "completed",
      request: "Pedido legacy", project_root: ".", file_path: "x.py", tasks: [], records: [],
    },
    {
      id: "old1", status: "completed", request: "Pedido antigo", tasks: [], records: [],
    },
  ];
  request.mockReset().mockResolvedValueOnce(response({ runs }));
  render(<GroupRuns groupId="g1" />);
  fireEvent.click(screen.getByRole("button", { name: /Execuções de equipa/ }));
  await screen.findByText(/Execução legacy1/);
  expect(screen.getByText(/Execução run-abc · PRIMARY/)).toBeTruthy();
  expect(screen.getByText(/Execução legacy1 · Leitura de ficheiro/)).toBeTruthy();
  expect(screen.getByText(/Execução old1 · Motor não indicado/)).toBeTruthy();
  expect(screen.getAllByText("Concluída").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("Em execução")).toBeTruthy();
  expect(screen.getByText("Verificado")).toBeTruthy();
  expect(screen.getAllByText(/Sem verificação registada/).length).toBe(2);
  expect(screen.getByText("Parar")).toBeTruthy();
});

it("resumes a paused run and cancels a live primary run through their endpoints", async () => {
  const paused = { id: "run-p", run_id: "run-p", execution_engine: "primary", state: "paused", status: "paused", request: "Retomar", tasks: [], records: [] };
  const running = { id: "run-r", run_id: "run-r", execution_engine: "primary", state: "running", status: "running", request: "Parar", tasks: [], records: [] };
  request.mockReset()
    .mockResolvedValueOnce(response({ runs: [paused, running] }))
    .mockResolvedValueOnce(response({ resumed: true, status: "running" }))
    .mockResolvedValueOnce(response({ runs: [{ ...paused, state: "running", status: "running" }, running] }))
    .mockResolvedValueOnce(response({ cancelled: true, status: "cancelling" }))
    .mockResolvedValueOnce(response({ runs: [{ ...paused, state: "running", status: "running" }, { ...running, state: "cancelling", status: "cancelling" }] }));
  render(<GroupRuns groupId="g1" />);
  fireEvent.click(screen.getByRole("button", { name: /Execuções de equipa/ }));
  await screen.findByText(/Execução run-p/);
  fireEvent.click(screen.getAllByRole("button", { name: "Retomar" })[0]!);
  await waitFor(() => expect(request.mock.calls.some((call) => String(call[0]).endsWith("/runs/run-p/resume"))).toBe(true));
  await waitFor(() => expect(screen.getAllByTestId("group-run-state").some((node) => node.textContent === "Em execução")).toBe(true));
  const runningCard = screen.getByText(/Execução run-r/).closest("details");
  expect(runningCard).toBeTruthy();
  fireEvent.click(within(runningCard as HTMLElement).getByRole("button", { name: "Parar" }));
  await waitFor(() => expect(request.mock.calls.some((call) => String(call[0]).endsWith("/runs/run-r/cancel"))).toBe(true));
});
