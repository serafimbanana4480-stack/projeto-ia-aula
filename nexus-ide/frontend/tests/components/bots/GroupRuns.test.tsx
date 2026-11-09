import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../../../lib/auth", () => ({ authenticatedFetch: request }));
vi.mock("../../../lib/api", () => ({ apiUrl: (path: string) => path }));
import GroupRuns from "../../../components/bots/GroupRuns";

it("starts a run and displays durable task evidence", async () => {
  const run = { id: "r1", status: "completed", request: "Rever", project_root: ".", file_path: "x.py", tasks: [{ id: "t1", bot_name: "A", provider: "local", model: "m", status: "completed", result: "resultado", error: null }], records: [{ id: "read1", task_id: "t1", kind: "tool_result", payload: { content: "ficheiro", call_id: "call1" } }] };
  request.mockReset().mockResolvedValueOnce({ ok: true, json: async () => ({ runs: [] }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ id: "r1" }) })
    .mockResolvedValueOnce({ ok: true, json: async () => ({ runs: [run] }) });
  render(<GroupRuns groupId="g1" />);
  fireEvent.click(screen.getByRole("button", { name: /Execuções com leitura/ }));
  fireEvent.change(screen.getByLabelText("Ficheiro a ler"), { target: { value: "x.py" } });
  fireEvent.change(screen.getByLabelText("Pedido da execução"), { target: { value: "Rever" } });
  fireEvent.click(screen.getByRole("button", { name: "Iniciar execução" }));
  await waitFor(() => expect(screen.getByText(/Execução r1/)).toBeTruthy());
  expect(request.mock.calls[1][0]).toBe("/api/bot-groups/g1/runs");
  expect(JSON.parse(request.mock.calls[1][1].body)).toEqual({ message: "Rever", file_path: "x.py", project_path: "." });
  expect(screen.getByText("local · m")).toBeTruthy();
  expect(screen.getByText(/tool_result · read1/)).toBeTruthy();
});
