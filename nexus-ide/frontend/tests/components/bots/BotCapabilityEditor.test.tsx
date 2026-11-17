import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { list, history, send, stream, resolveTool, updateBot, createBot } = vi.hoisted(() => ({
  list: vi.fn(),
  history: vi.fn(),
  send: vi.fn(),
  resolveTool: vi.fn(),
  stream: { events: [] as unknown[], streaming: false },
  updateBot: vi.fn(async (id: string, changes: Record<string, unknown>) => ({ id, ...changes })),
  createBot: vi.fn(async (settings: Record<string, unknown>) => ({ id: "bot-new", ...settings })),
}));

vi.mock("../../../lib/bots", () => ({
  listBots: list,
  createBot,
  updateBot,
  removeBot: vi.fn(),
  getRoomMemory: vi.fn(async () => ({ pins: [], seen: {} })),
  updateRoomMemory: vi.fn(async () => ({ pins: [], seen: {} })),
  BOT_CAPABILITY_KEYS: [
    "read", "research", "tasks", "memory", "write", "shell", "browser", "mcp", "auto_accept",
  ],
  DEFAULT_BOT_CAPABILITIES: {
    read: true, research: true, tasks: true, memory: true, write: true,
    shell: true, browser: true, mcp: true, auto_accept: true,
  },
}));
vi.mock("../../../lib/api", () => ({
  apiUrl: (path: string) => path,
  getSessionHistoryPage: history,
  getProviderCatalog: vi.fn(async () => []),
  getProviderModels: vi.fn(async () => ({ models: [], cached: true, configured: false, error: null })),
}));
vi.mock("../../../lib/auth", () => ({ authenticatedFetch: vi.fn(async () => ({ ok: true, json: async () => ({ groups: [] }) })) }));
vi.mock("../../../hooks/useAgentStream", () => ({
  useAgentStream: () => ({
    events: stream.events, streaming: stream.streaming, busyOtherSession: false, error: null,
    send, cancel: vi.fn(), resolveToolConfirmation: resolveTool,
  }),
}));
vi.mock("../../../components/chat/MessageCodeBlock", () => ({ default: () => null }));

import BotsWorkspace from "../../../components/bots/BotsWorkspace";

/** jsdom has no <dialog> implementation; the editor needs showModal(). */
beforeEach(() => {
  const dialog = HTMLDialogElement.prototype as unknown as {
    showModal: (this: HTMLDialogElement) => void;
    close: (this: HTMLDialogElement) => void;
  };
  dialog.showModal = vi.fn(function showModal(this: HTMLDialogElement) {
    this.open = true;
  });
  dialog.close = vi.fn(function close(this: HTMLDialogElement) {
    this.open = false;
  });
});

function openEditor() {
  render(<BotsWorkspace />);
  fireEvent.click(screen.getAllByRole("button", { name: /Criar bot/ })[0]);
  return screen.findByRole("heading", { name: "Criar bot" });
}

describe("editor de capacidades do bot", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    stream.events = [];
    stream.streaming = false;
    send.mockResolvedValue(true);
    resolveTool.mockReset().mockResolvedValue(true);
    list.mockResolvedValue([]);
    history.mockResolvedValue({ messages: [], has_more: false, next_cursor: null });
  });

  it("oferece um controlo real para cada capacidade", () => {
    openEditor();
    for (const label of [
      "Leitura de ficheiros", "Pesquisa web", "Tarefas e skills", "Memória",
      "Escrita no projeto", "Shell e testes", "Browser", "MCP", "Aceitação automática",
    ]) {
      expect(screen.getByRole("switch", { name: label }).getAttribute("aria-checked")).toBe("true");
    }
  });

  it("grava a escolha do utilizador em vez de aplicar um valor por omissão", () => {
    openEditor();
    fireEvent.click(screen.getByRole("switch", { name: "Shell e testes" }));
    fireEvent.click(screen.getByRole("switch", { name: "Memória" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Nome" }), { target: { value: "Forge" } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar bot" }));

    expect(createBot).toHaveBeenCalledTimes(1);
    expect(createBot.mock.calls[0][0].capabilities).toMatchObject({
      read: true, research: true, tasks: true, memory: false,
      write: true, shell: false, browser: true, mcp: true, auto_accept: true,
    });
  });

  it("diz quais as capacidades que precisam de um projeto", () => {
    openEditor();
    // read, write and shell are the three project-bound families.
    expect(screen.getAllByText(/Precisa de um projeto selecionado\./)).toHaveLength(3);
    expect(screen.getByText(/Sem projeto selecionado, apenas pesquisa web/)).toBeTruthy();
  });
});
