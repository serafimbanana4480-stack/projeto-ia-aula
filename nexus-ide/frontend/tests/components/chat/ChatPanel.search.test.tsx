import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getSessionHistoryPage: vi.fn(),
  sessions: {
    sessions: [{ id: "session-1", title: "Conversa", mode: "auto", project_id: null, created_at: "", last_active_at: "" }],
    currentId: "session-1",
    initialized: true,
    error: null,
    setCurrentId: vi.fn(),
    create: vi.fn(),
    rename: vi.fn(),
    remove: vi.fn(),
    refresh: vi.fn(),
    ensureCurrentSession: vi.fn(),
  },
  stream: {
    events: [],
    streaming: false,
    busyOtherSession: false,
    error: null,
    send: vi.fn(),
    resume: vi.fn(),
    cancel: vi.fn(),
    reset: vi.fn(),
    getActiveRunId: vi.fn(() => null),
    getActiveRunSessionId: vi.fn(() => null),
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => "/",
}));

vi.mock("../../../hooks/useChatSessions", () => ({
  useChatSessions: () => mocks.sessions,
}));

vi.mock("../../../hooks/useAgentStream", () => ({
  useAgentStream: () => mocks.stream,
}));

vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api")>();
  return {
    ...actual,
    getSessionHistoryPage: (...args: unknown[]) => mocks.getSessionHistoryPage(...args),
    getProvidersStatus: vi.fn().mockResolvedValue({ llm_available: true, demo_mode: false, providers: [] }),
  };
});

vi.mock("../../../lib/sessionRecovery", () => ({
  restoreRunTimelines: vi.fn(async (messages: unknown[]) => messages),
}));

vi.mock("../../../stores/metricsStore", () => ({ initMetricsStream: vi.fn() }));
vi.mock("../../../stores/modeStore", () => {
  const state = { currentMode: "auto", modes: [], modesLoaded: true, setMode: vi.fn(), loadModes: vi.fn() };
  return { useModeStore: () => state };
});
vi.mock("../../../stores/modelStore", () => {
  const state = { activeModel: "", activeProvider: "", modelsLoaded: true, loadModels: vi.fn() };
  return { useModelStore: () => state };
});
vi.mock("../../../stores/projectStore", () => ({ useProjectStore: () => ({ currentProject: null }) }));
vi.mock("../../../stores/themeStore", () => ({ useThemeStore: () => ({ toggleTheme: vi.fn() }) }));
vi.mock("../../../stores/advancedModeStore", () => {
  const state = {
    loadCommands: vi.fn(),
    loadModes: vi.fn(),
    commandsLoading: false,
    commandsError: null,
    modes: [],
    commands: {},
  };
  return { useAdvancedModeStore: (selector: (value: typeof state) => unknown) => selector(state) };
});
vi.mock("../../../hooks/useKeyboardShortcuts", () => ({ useKeyboardShortcuts: vi.fn() }));
vi.mock("../../../hooks/useChatInput", () => {
  const clear = vi.fn();
  return { useChatInput: () => ({ draft: "", clear }) };
});
vi.mock("../../../components/chat/Toast", () => {
  const toast = { error: vi.fn(), success: vi.fn(), info: vi.fn() };
  return { useToast: () => toast };
});
vi.mock("../../../components/chat/MessageBubble", () => ({
  default: ({ message }: { message: { content: string } }) => <article>{message.content}</article>,
}));
vi.mock("../../../components/chat/BackgroundAgentsPanel", () => ({ default: () => null }));
vi.mock("../../../components/chat/ModelSelector", () => ({ default: () => null }));
vi.mock("../../../components/chat/SessionList", () => ({ default: () => null }));
vi.mock("../../../components/chat/AdvancedModeHeaderIndicator", () => ({ default: () => null }));

import ChatPanel from "../../../components/chat/ChatPanel";

function chatMessage(id: string, content: string, role: "user" | "assistant" = "assistant") {
  return { id, role, content, timestamp: "2026-09-28T10:00:00Z" };
}

describe("ChatPanel conversation history search and navigation", () => {
  let originalScrollTo: PropertyDescriptor | undefined;

  beforeEach(() => {
    originalScrollTo = Object.getOwnPropertyDescriptor(HTMLElement.prototype, "scrollTo");
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      writable: true,
      value: vi.fn(),
    });
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) =>
      window.setTimeout(() => callback(0), 0),
    );
    vi.stubGlobal("cancelAnimationFrame", (timer: number) => window.clearTimeout(timer));
    mocks.getSessionHistoryPage.mockReset();
    mocks.sessions.currentId = "session-1";
    mocks.getSessionHistoryPage.mockImplementation((_sessionId: string, _limit: number, beforeId?: string) => {
      if (beforeId === "message-3") {
        return Promise.resolve({
          messages: [chatMessage("message-1", "lembrança antiga que procurava", "user"), chatMessage("message-2", "resposta antiga")],
          count: 2,
          has_more: false,
          next_cursor: null,
        });
      }
      if (beforeId === "message-5") {
        return Promise.resolve({
          messages: [chatMessage("message-3", "mensagem intermédia", "user"), chatMessage("message-4", "resposta intermédia")],
          count: 2,
          has_more: true,
          next_cursor: "message-3",
        });
      }
      return Promise.resolve({
        messages: [chatMessage("message-5", "mensagem recente", "user"), chatMessage("message-6", "resposta recente")],
        count: 2,
        has_more: true,
        next_cursor: "message-5",
      });
    });
  });

  afterEach(() => {
    if (originalScrollTo) {
      Object.defineProperty(HTMLElement.prototype, "scrollTo", originalScrollTo);
    } else {
      Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
    }
    vi.unstubAllGlobals();
  });

  it("reserva Ctrl/Cmd+K e abre a pesquisa da conversa com Ctrl/Cmd+F", async () => {
    render(<ChatPanel />);
    await screen.findByText("mensagem recente");

    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.queryByRole("dialog", { name: "Procurar nesta conversa" })).toBeNull();

    fireEvent.keyDown(window, { key: "f", ctrlKey: true, shiftKey: true });
    expect(screen.queryByRole("dialog", { name: "Procurar nesta conversa" })).toBeNull();

    fireEvent.keyDown(window, { key: "f", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "Procurar nesta conversa" })).toBeTruthy();
  });

  it("pesquisa páginas antigas e leva o chat à mensagem correspondente", async () => {
    render(<ChatPanel />);
    await screen.findByText("mensagem recente");

    fireEvent.keyDown(window, { key: "f", ctrlKey: true });
    fireEvent.change(screen.getByRole("textbox", { name: "Procurar nas mensagens desta conversa" }), {
      target: { value: "lembrança antiga" },
    });

    const result = await screen.findByRole("button", { name: /Tu: lembrança antiga que procurava/ });
    expect(mocks.getSessionHistoryPage).toHaveBeenCalledWith("session-1", 100, "message-5");
    expect(mocks.getSessionHistoryPage).toHaveBeenCalledWith("session-1", 100, "message-3");

    await act(async () => {
      fireEvent.click(result);
    });

    await waitFor(() => {
      expect(document.querySelector('[data-chat-message-id="message-1"]')).toBeTruthy();
    });
    const targetMessage = document.querySelector('[data-chat-message-id="message-1"]');
    expect(targetMessage?.textContent).toContain("lembrança antiga que procurava");
    expect(screen.getByText("mensagem intermédia")).toBeTruthy();
  });

  it("mantém a conversa visível e permite repetir quando falha uma página antiga", async () => {
    let olderPageAttempts = 0;
    mocks.getSessionHistoryPage.mockImplementation(
      (_sessionId: string, _limit: number, beforeId?: string) => {
        if (!beforeId) {
          return Promise.resolve({
            messages: [
              chatMessage("message-5", "mensagem recente", "user"),
              chatMessage("message-6", "resposta recente"),
            ],
            count: 2,
            has_more: true,
            next_cursor: "message-5",
          });
        }

        olderPageAttempts += 1;
        if (olderPageAttempts === 1) return Promise.reject(new Error("ligação interrompida"));
        return Promise.resolve({
          messages: [
            chatMessage("message-3", "mensagem intermédia", "user"),
            chatMessage("message-4", "resposta intermédia"),
          ],
          count: 2,
          has_more: true,
          next_cursor: "message-3",
        });
      },
    );

    render(<ChatPanel />);
    await screen.findByText("mensagem recente");
    fireEvent.click(screen.getByRole("button", { name: "Carregar mensagens anteriores" }));

    const pagingError = await screen.findByRole("alert");
    expect(pagingError.textContent).toContain("ligação interrompida");
    expect(screen.getByText("mensagem recente")).toBeTruthy();
    expect(screen.queryByText("Erro ao carregar histórico")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Tentar carregar novamente" }));
    expect(await screen.findByText("mensagem intermédia")).toBeTruthy();
    expect(screen.getByText("mensagem recente")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(olderPageAttempts).toBe(2);
  });

  it("interrompe uma cadeia de cursores que volta à mesma página", async () => {
    mocks.getSessionHistoryPage.mockImplementation(
      (_sessionId: string, _limit: number, beforeId?: string) => {
        if (!beforeId) {
          return Promise.resolve({
            messages: [chatMessage("message-5", "mensagem recente", "user"), chatMessage("message-6", "resposta recente")],
            count: 2,
            has_more: true,
            next_cursor: "message-5",
          });
        }
        return Promise.resolve({
          messages: [chatMessage("message-3", "mensagem antiga", "user"), chatMessage("message-4", "resposta antiga")],
          count: 2,
          has_more: true,
          next_cursor: "message-5",
        });
      },
    );

    render(<ChatPanel />);
    await screen.findByText("mensagem recente");
    fireEvent.click(screen.getByRole("button", { name: "Carregar mensagens anteriores" }));

    const pagingError = await screen.findByRole("alert");
    expect(pagingError.textContent).toContain("deixou de avançar");
    expect(screen.getByText("mensagem antiga")).toBeTruthy();
    expect(screen.getByText("resposta recente")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /carregar mensagens anteriores|tentar carregar novamente/i })).toBeNull();
    expect(mocks.getSessionHistoryPage).toHaveBeenCalledTimes(2);
  });

  it("marca a pesquisa como parcial se o cursor oscila entre páginas", async () => {
    mocks.getSessionHistoryPage.mockImplementation(
      (_sessionId: string, _limit: number, beforeId?: string) => {
        if (!beforeId) {
          return Promise.resolve({
            messages: [chatMessage("recent-user", "conversa recente", "user"), chatMessage("recent-assistant", "resposta recente")],
            count: 2,
            has_more: true,
            next_cursor: "cursor-a",
          });
        }
        if (beforeId === "cursor-a") {
          return Promise.resolve({
            messages: [chatMessage("older-a", "needle encontrado na página A", "user")],
            count: 1,
            has_more: true,
            next_cursor: "cursor-b",
          });
        }
        return Promise.resolve({
          messages: [chatMessage("older-b", "needle encontrado na página B", "user")],
          count: 1,
          has_more: true,
          next_cursor: "cursor-a",
        });
      },
    );

    render(<ChatPanel />);
    await screen.findByText("conversa recente");
    fireEvent.keyDown(window, { key: "f", ctrlKey: true });
    fireEvent.change(screen.getByRole("textbox", { name: "Procurar nas mensagens desta conversa" }), {
      target: { value: "needle" },
    });

    const partialSearch = await screen.findByRole("alert");
    expect(partialSearch.textContent).toContain("pesquisa ficou incompleta");
    expect(partialSearch.textContent).toContain("repetiu um cursor");
    expect(await screen.findByRole("button", { name: /needle encontrado na página A/ })).toBeTruthy();
    expect(screen.getByRole("button", { name: /needle encontrado na página B/ })).toBeTruthy();
    expect(mocks.getSessionHistoryPage).toHaveBeenCalledTimes(3);
  });

  it("expõe pesquisa parcial quando o backend diz que há mais páginas sem cursor", async () => {
    mocks.getSessionHistoryPage.mockImplementation(
      (_sessionId: string, _limit: number, beforeId?: string) => {
        if (!beforeId) {
          return Promise.resolve({
            messages: [chatMessage("recent-user", "conversa recente", "user"), chatMessage("recent-assistant", "resposta recente")],
            count: 2,
            has_more: true,
            next_cursor: "cursor-a",
          });
        }
        return Promise.resolve({
          messages: [chatMessage("older-a", "needle encontrado antes", "user")],
          count: 1,
          has_more: true,
          next_cursor: null,
        });
      },
    );

    render(<ChatPanel />);
    await screen.findByText("conversa recente");
    fireEvent.keyDown(window, { key: "f", ctrlKey: true });
    fireEvent.change(screen.getByRole("textbox", { name: "Procurar nas mensagens desta conversa" }), {
      target: { value: "needle" },
    });

    const partialSearch = await screen.findByRole("alert");
    expect(partialSearch.textContent).toContain("pesquisa ficou incompleta");
    expect(partialSearch.textContent).toContain("não forneceu um cursor válido");
    expect(await screen.findByRole("button", { name: /needle encontrado antes/ })).toBeTruthy();
    expect(mocks.getSessionHistoryPage).toHaveBeenCalledTimes(2);
  });
});
