import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../../../lib/auth", () => ({ authenticatedFetch: request }));
vi.mock("../../../lib/api", () => ({ apiUrl: (path: string) => path }));
import GroupWorkspace from "../../../components/bots/GroupWorkspace";

const bots = ["Pixel", "Atlas"].map((name, i) => ({ id: `b${i}`, session_id: `s${i}`, name, description: "", instructions: "", provider: "lmstudio", model: `model${i}`, archived: false, last_message: null, last_active_at: "" }));
const group = { id: "g1", name: "Equipa", bot_ids: ["b0", "b1"], last_message: null };
const json = (body: unknown) => ({ ok: true, json: async () => body });

describe("GroupWorkspace", () => {
  beforeEach(() => request.mockReset());

  it("cria grupo com os bots escolhidos", async () => {
    request.mockResolvedValueOnce(json({ groups: [] })).mockResolvedValueOnce(json(group)).mockResolvedValueOnce(json({ messages: [] }));
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    await screen.findByText("Ainda não tens grupos. Cria um para começar.");
    fireEvent.click(screen.getAllByRole("button", { name: "Criar grupo" })[0]);
    fireEvent.change(screen.getByLabelText("Nome do grupo"), { target: { value: "Equipa" } });
    fireEvent.click(screen.getByRole("checkbox", { name: /Pixel/ }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Atlas/ }));
    fireEvent.click(screen.getAllByRole("button", { name: "Criar grupo" }).at(-1)!);
    await screen.findByRole("heading", { name: "Equipa" });
    const [, options] = request.mock.calls[1];
    expect(JSON.parse(options.body)).toEqual({ name: "Equipa", bot_ids: ["b0", "b1"] });
  });

  it("apresenta cada bot e reconcilia as respostas gravadas", async () => {
    const first = { id: "m1", role: "user", content: "Olá", bot_id: null, bot_name: null, created_at: "now" };
    const second = { id: "m2", role: "assistant", content: "Resposta partilhada", bot_id: "b0", bot_name: "Pixel", created_at: "now" };
    const frames = [ { type: "user_message", message: first }, { type: "agent_started", bot_id: "b0", bot_name: "Pixel" }, { type: "token", content: "Resposta partilhada" }, { type: "agent_message", message: second }, { type: "done", status: "completed" } ].map((item) => `data: ${JSON.stringify(item)}\n\n`).join("");
    const stream = new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode(frames)); controller.close(); } });
    request.mockResolvedValueOnce(json({ groups: [group] })).mockResolvedValueOnce(json({ messages: [] })).mockResolvedValueOnce({ ok: true, body: stream }).mockResolvedValueOnce(json({ messages: [first, second] })).mockResolvedValueOnce(json({ groups: [group] }));
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    const input = await screen.findByRole("textbox", { name: "Mensagem para o grupo" });
    await waitFor(() => expect((input as HTMLTextAreaElement).disabled).toBe(false));
    fireEvent.change(input, { target: { value: "Olá" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar ao grupo" }));
    expect(await screen.findByText("Resposta partilhada")).toBeTruthy();
    await waitFor(() => expect(screen.getAllByText("Resposta partilhada")).toHaveLength(1));
    expect(screen.getByText("Pixel", { selector: "p" })).toBeTruthy();
    expect(request.mock.calls[2][1].body).not.toContain('"max_turns"');
  });

  it("recupera páginas anteriores sem repetir mensagens", async () => {
    const newer = { id: "m2", role: "assistant", content: "Resposta recente", bot_id: "b1", bot_name: "Atlas", created_at: "now" };
    const older = { id: "m1", role: "user", content: "Pergunta anterior", bot_id: null, bot_name: null, created_at: "then" };
    request.mockResolvedValueOnce(json({ groups: [group] }))
      .mockResolvedValueOnce(json({ messages: [newer], has_more: true, next_before: "m2" }))
      .mockResolvedValueOnce(json({ messages: [older, newer], has_more: false, next_before: null }));
    render(<GroupWorkspace bots={bots} onBack={vi.fn()} />);
    fireEvent.click(await screen.findByRole("button", { name: /Equipa/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Carregar mensagens anteriores" }));
    await screen.findByText("Pergunta anterior");
    expect(screen.getAllByText("Resposta recente")).toHaveLength(1);
    expect(request.mock.calls[2][0]).toContain("before=m2");
  });
});
