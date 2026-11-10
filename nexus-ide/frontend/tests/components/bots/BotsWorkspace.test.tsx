import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { list, history, send, stream } = vi.hoisted(() => ({ list: vi.fn(), history: vi.fn(), send: vi.fn(), stream: { events: [] as unknown[], streaming: false } }));
vi.mock("../../../lib/bots", () => ({ listBots: list, createBot: vi.fn(), updateBot: vi.fn(), removeBot: vi.fn() }));
vi.mock("../../../lib/api", () => ({ apiUrl: (path: string) => path, getSessionHistoryPage: history, getProviderCatalog: vi.fn(), getProviderModels: vi.fn() }));
vi.mock("../../../lib/auth", () => ({ authenticatedFetch: vi.fn(async () => ({ ok: true, json: async () => ({ groups: [] }) })) }));
vi.mock("../../../hooks/useAgentStream", () => ({
  useAgentStream: () => ({ events: stream.events, streaming: stream.streaming, busyOtherSession: false, error: null, send, cancel: vi.fn() }),
}));
vi.mock("../../../components/chat/MessageCodeBlock", () => ({ default: () => null }));

import BotsWorkspace from "../../../components/bots/BotsWorkspace";

describe("BotsWorkspace", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    stream.events = []; stream.streaming = false; send.mockResolvedValue(true);
    Element.prototype.scrollIntoView = vi.fn();
    list.mockResolvedValue([{ id: "bot-1", session_id: "session-1", name: "Pixel", description: "UI", instructions: "", provider: "lmstudio", model: "local", archived: false, last_message: null, last_active_at: "2026-11-06T00:00:00Z" }]);
  });

  it("bloqueia o envio se o histórico falhar e permite recuperá-lo", async () => {
    history.mockReset().mockRejectedValueOnce(new Error("ligação indisponível")).mockResolvedValueOnce({ messages: [], has_more: false, next_cursor: null });
    render(<BotsWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: /Pixel/ }));
    expect((await screen.findByRole("alert")).textContent).toContain("ligação indisponível");
    expect((screen.getByRole("textbox", { name: "Mensagem" }) as HTMLTextAreaElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(await screen.findByText("Olá, sou Pixel")).toBeTruthy();
    expect((screen.getByRole("textbox", { name: "Mensagem" }) as HTMLTextAreaElement).disabled).toBe(false);
  });

  it("preserva o texto quando o envio não é confirmado", async () => {
    history.mockReset().mockResolvedValue({ messages: [], has_more: false, next_cursor: null });
    send.mockResolvedValue(false);
    render(<BotsWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: /Pixel/ }));
    await screen.findByText("Olá, sou Pixel");
    const input = screen.getByRole("textbox", { name: "Mensagem" });
    fireEvent.change(input, { target: { value: "Mensagem importante" } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar mensagem" }));
    expect(await screen.findByText(/Não foi possível confirmar o envio/)).toBeTruthy();
    expect((input as HTMLTextAreaElement).value).toBe("Mensagem importante");
  });

  it("não salta para o fim enquanto se leem mensagens anteriores", async () => {
    history.mockReset().mockResolvedValue({ messages: [{ id: "old", role: "assistant", content: "Conteúdo anterior", timestamp: "2026-11-06T00:00:00Z" }], has_more: false, next_cursor: null });
    const view = render(<BotsWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: /Pixel/ }));
    await screen.findByText("Conteúdo anterior");
    const scroll = screen.getByLabelText("Mensagens da conversa");
    Object.defineProperties(scroll, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { configurable: true, value: 200 }, scrollTop: { configurable: true, writable: true, value: 100 } });
    fireEvent.scroll(scroll);
    const calls = vi.mocked(Element.prototype.scrollIntoView).mock.calls.length;
    stream.events = [{ type: "token", content: "Mais texto", timestamp: "2026-11-06T00:00:00Z" }];
    view.rerender(<BotsWorkspace />);
    expect(vi.mocked(Element.prototype.scrollIntoView).mock.calls.length).toBe(calls);
  });

  it("mantém os rascunhos separados ao mudar de conversa", async () => {
    history.mockReset().mockResolvedValue({ messages: [], has_more: false, next_cursor: null });
    list.mockResolvedValue([
      { id: "b1", session_id: "s1", name: "Pixel", description: "", instructions: "", provider: "lmstudio", model: "local", archived: false, last_message: null, last_active_at: "" },
      { id: "b2", session_id: "s2", name: "Atlas", description: "", instructions: "", provider: "lmstudio", model: "local", archived: false, last_message: null, last_active_at: "" },
    ]);
    render(<BotsWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: /Pixel/ }));
    await screen.findByText("Olá, sou Pixel");
    fireEvent.change(screen.getByRole("textbox", { name: "Mensagem" }), { target: { value: "rascunho Pixel" } });
    fireEvent.click(screen.getByRole("button", { name: /Atlas/ }));
    await screen.findByText("Olá, sou Atlas");
    expect((screen.getByRole("textbox", { name: "Mensagem" }) as HTMLTextAreaElement).value).toBe("");
    fireEvent.click(screen.getByRole("button", { name: /Pixel/ }));
    expect((screen.getByRole("textbox", { name: "Mensagem" }) as HTMLTextAreaElement).value).toBe("rascunho Pixel");
  });

  it("permite carregar mensagens anteriores sem duplicar as já visíveis", async () => {
    history.mockResolvedValueOnce({ messages: [{ id: "m2", role: "assistant", content: "Mensagem recente", timestamp: "2026-11-06T00:00:00Z" }], has_more: true, next_cursor: "m2" });
    history.mockResolvedValueOnce({ messages: [{ id: "m1", role: "user", content: "Mensagem antiga", timestamp: "2026-11-05T00:00:00Z" }, { id: "m2", role: "assistant", content: "Mensagem recente", timestamp: "2026-11-06T00:00:00Z" }], has_more: false, next_cursor: null });
    render(<BotsWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: /Pixel/ }));
    expect(await screen.findByText("Mensagem recente")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Carregar mensagens anteriores" }));
    expect(await screen.findByText("Mensagem antiga")).toBeTruthy();
    expect(screen.getAllByText("Mensagem recente")).toHaveLength(1);
    await waitFor(() => expect(screen.queryByRole("button", { name: "Carregar mensagens anteriores" })).toBeNull());
    expect(history).toHaveBeenNthCalledWith(2, "session-1", 100, "m2");
  });

  it("permite recuperar a lista depois de uma falha de carregamento", async () => {
    list.mockReset().mockRejectedValueOnce(new Error("sem ligação")).mockResolvedValueOnce([]);
    render(<BotsWorkspace />);
    expect(await screen.findByText("sem ligação")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Tentar carregar novamente" }));
    await waitFor(() => expect(screen.queryByText("sem ligação")).toBeNull());
    expect(list).toHaveBeenCalledTimes(2);
  });

  it("repõe o filtro de arquivo quando a última conversa selecionada está arquivada", async () => {
    localStorage.setItem("nexus:bots:selected", "bot-1");
    list.mockResolvedValue([{ id: "bot-1", session_id: "session-1", name: "Pixel", description: "UI", instructions: "", provider: "lmstudio", model: "local", archived: true, last_message: null, last_active_at: "" }]);
    history.mockReset().mockResolvedValue({ messages: [], has_more: false, next_cursor: null });
    render(<BotsWorkspace />);
    await screen.findByText("Olá, sou Pixel");
    expect(screen.getByRole("tab", { name: "Arquivados" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("button", { name: /Pixel/ }).getAttribute("aria-current")).toBe("true");
  });

  it("mostra as instruções e o acesso real no perfil do bot", async () => {
    list.mockResolvedValue([{ id: "bot-1", session_id: "session-1", name: "Pixel", description: "UI", instructions: "Responde com precisão", provider: "lmstudio", model: "local", archived: false, last_message: null, last_active_at: "" }]);
    history.mockReset().mockResolvedValue({ messages: [], has_more: false, next_cursor: null });
    render(<BotsWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: /Pixel/ }));
    await screen.findByText("Olá, sou Pixel");
    fireEvent.click(screen.getByRole("button", { name: "Informações do bot" }));
    expect(screen.getByText("Responde com precisão")).toBeTruthy();
    expect(screen.getByText("Modelo configurado")).toBeTruthy();
    expect(screen.getByText(/Ferramentas de leitura disponíveis conforme a configuração/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Fechar informações" }));
    expect(screen.queryByText("Responde com precisão")).toBeNull();
  });

  it("mostra a atividade emitida durante a resposta sem expor raciocínio privado", async () => {
    history.mockReset().mockResolvedValue({ messages: [], has_more: false, next_cursor: null });
    stream.streaming = true;
    stream.events = [
      { type: "thinking", content: "raciocínio privado", timestamp: "2026-11-06T00:00:00Z" },
      { type: "tool_call", tool_name: "read_file", timestamp: "2026-11-06T00:00:01Z" },
    ];
    render(<BotsWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: /Pixel/ }));
    expect(await screen.findByText("Pixel · A usar read_file")).toBeTruthy();
    expect(screen.queryByText("raciocínio privado")).toBeNull();
    fireEvent.click(screen.getByText("Atividade · 1 chamada"));
    expect(screen.getByText("Em curso")).toBeTruthy();
  });

  it("permite regressar ao fim depois de ler mensagens anteriores", async () => {
    history.mockReset().mockResolvedValue({ messages: [{ id: "old", role: "assistant", content: "Conteúdo anterior", timestamp: "2026-11-06T00:00:00Z" }], has_more: false, next_cursor: null });
    render(<BotsWorkspace />);
    fireEvent.click(await screen.findByRole("button", { name: /Pixel/ }));
    await screen.findByText("Conteúdo anterior");
    const scroll = screen.getByLabelText("Mensagens da conversa");
    Object.defineProperties(scroll, { scrollHeight: { configurable: true, value: 1000 }, clientHeight: { configurable: true, value: 200 }, scrollTop: { configurable: true, writable: true, value: 100 } });
    fireEvent.scroll(scroll);
    fireEvent.click(screen.getByRole("button", { name: "Ir para o fim" }));
    expect(screen.queryByRole("button", { name: "Ir para o fim" })).toBeNull();
    expect(Element.prototype.scrollIntoView).toHaveBeenCalledWith({ block: "end", behavior: "smooth" });
  });

  it("pesquisa também pelo modelo configurado", async () => {
    render(<BotsWorkspace />);
    await screen.findByRole("button", { name: /Pixel/ });
    fireEvent.change(screen.getByLabelText("Pesquisar conversas"), { target: { value: "  LOCAL  " } });
    expect(screen.getByRole("button", { name: /Pixel/ })).toBeTruthy();
  });
});
