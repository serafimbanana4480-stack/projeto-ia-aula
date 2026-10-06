import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamEvent } from "../../../lib/types";

const mocks = vi.hoisted(() => ({
  getSessionHistoryPage: vi.fn(),
  sessions: {
    sessions: [
      { id: "session-1", title: "Conversa 1", mode: "auto", project_id: null, created_at: "", last_active_at: "" },
      { id: "session-2", title: "Conversa 2", mode: "auto", project_id: null, created_at: "", last_active_at: "" },
    ],
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
    events: [] as unknown[],
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
vi.mock("../../../hooks/useChatSessions", () => ({ useChatSessions: () => mocks.sessions }));
vi.mock("../../../hooks/useAgentStream", () => ({ useAgentStream: () => mocks.stream }));
vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api")>();
  return {
    ...actual,
    getSessionHistoryPage: (...args: unknown[]) => mocks.getSessionHistoryPage(...args),
    getProvidersStatus: vi.fn().mockResolvedValue({ llm_available: true, demo_mode: false, providers: [] }),
  };
});
vi.mock("../../../lib/sessionRecovery", () => ({ restoreRunTimelines: vi.fn(async (messages: unknown[]) => messages) }));
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
  const state = { loadCommands: vi.fn(), loadModes: vi.fn(), commandsLoading: false, commandsError: null, modes: [], commands: {} };
  return { useAdvancedModeStore: (selector: (value: typeof state) => unknown) => selector(state) };
});
vi.mock("../../../hooks/useKeyboardShortcuts", () => ({ useKeyboardShortcuts: vi.fn() }));
vi.mock("../../../hooks/useChatInput", () => ({ useChatInput: () => ({ draft: "", clear: vi.fn() }) }));
vi.mock("../../../components/chat/Toast", () => ({
  useToast: () => ({ error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() }),
}));
vi.mock("../../../components/chat/MessageBubble", () => ({
  default: ({ message }: { message: { content: string } }) => <article>{message.content}</article>,
}));
vi.mock("../../../components/chat/BackgroundAgentsPanel", () => ({ default: () => null }));
vi.mock("../../../components/chat/ModelSelector", () => ({ default: () => null }));
vi.mock("../../../components/chat/SessionList", () => ({ default: () => null }));
vi.mock("../../../components/chat/AdvancedModeHeaderIndicator", () => ({ default: () => null }));

import ChatPanel from "../../../components/chat/ChatPanel";

function runEvents(runId: string, answer: string): StreamEvent[] {
  const timestamp = `2026-09-28T10:00:0${runId.endsWith("1") ? "1" : "2"}.000Z`;
  return [
    { type: "agent_started", run_id: runId, seq: 1, event_id: `${runId}-1`, agent: "NEXUS", timestamp },
    { type: "token", run_id: runId, seq: 2, event_id: `${runId}-2`, content: answer, timestamp },
    { type: "done", run_id: runId, seq: 3, event_id: `${runId}-3`, timestamp },
  ];
}

describe("ChatPanel live turn retention", () => {
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
    mocks.sessions.currentId = "session-1";
    mocks.stream.events = [];
    mocks.stream.streaming = false;
    mocks.stream.busyOtherSession = false;
    mocks.stream.reset.mockReset().mockImplementation(() => {
      mocks.stream.events = [];
    });
    mocks.stream.send.mockReset();
    mocks.getSessionHistoryPage.mockReset().mockResolvedValue({
      messages: [], count: 0, has_more: false, next_cursor: null,
    });
  });

  afterEach(() => {
    if (originalScrollTo) Object.defineProperty(HTMLElement.prototype, "scrollTo", originalScrollTo);
    else Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
    vi.unstubAllGlobals();
  });

  it("keeps thirty completed turns once each and bounds the live buffer to the current run", async () => {
    const turnCount = 30;
    const responses = Array.from({ length: turnCount }, (_, index) =>
      runEvents(`run-${index + 1}`, `resposta ${index + 1}`),
    );
    const eventBuffersAtSend: unknown[][] = [];
    let runIndex = 0;
    mocks.stream.send.mockImplementation(async () => {
      eventBuffersAtSend.push([...mocks.stream.events]);
      mocks.stream.events = [...responses[runIndex++]];
      return true;
    });

    const view = render(<ChatPanel />);
    await waitFor(() => expect(mocks.getSessionHistoryPage).toHaveBeenCalledWith("session-1", 100));
    const textarea = screen.getByRole("textbox");
    const form = textarea.closest("form");
    expect(form).not.toBeNull();

    for (let turnIndex = 0; turnIndex < turnCount; turnIndex += 1) {
      await act(async () => {
        fireEvent.change(textarea, { target: { value: `pergunta ${turnIndex + 1}` } });
        fireEvent.submit(form!);
      });
      await waitFor(() => expect(mocks.stream.send).toHaveBeenCalledTimes(turnIndex + 1));
      view.rerender(<ChatPanel />);
      expect(screen.getByText(`resposta ${turnIndex + 1}`)).toBeTruthy();
    }

    expect(eventBuffersAtSend).toEqual(Array.from({ length: turnCount }, () => []));
    expect((mocks.stream.events as StreamEvent[]).map((event) => event.run_id)).toEqual(
      Array.from({ length: 3 }, () => `run-${turnCount}`),
    );
    // Fifty archived messages plus the current live user/assistant bubbles.
    expect(document.querySelectorAll("[data-chat-message-id]")).toHaveLength(52);
    fireEvent.click(screen.getByRole("button", { name: /Carregar mais 8 mensagens/ }));
    const renderedMessages = Array.from(document.querySelectorAll("[data-chat-message-id]"));
    expect(renderedMessages.map((message) => message.textContent?.trim())).toEqual(
      Array.from({ length: turnCount }, (_, index) => [
        `pergunta ${index + 1}`,
        `resposta ${index + 1}`,
      ]).flat(),
    );
    const messageIds = renderedMessages.map((message) => message.getAttribute("data-chat-message-id"));
    expect(new Set(messageIds).size).toBe(messageIds.length);
  });

  it("clears an inactive session's event buffer after switching away", async () => {
    mocks.stream.send.mockImplementation(async () => {
      mocks.stream.events = runEvents("run-1", "resposta da conversa 1");
      return true;
    });
    const view = render(<ChatPanel />);
    await waitFor(() => expect(mocks.getSessionHistoryPage).toHaveBeenCalledWith("session-1", 100));
    const textarea = screen.getByRole("textbox");
    const form = textarea.closest("form");
    await act(async () => {
      fireEvent.change(textarea, { target: { value: "pergunta 1" } });
      fireEvent.submit(form!);
    });
    await waitFor(() => expect(mocks.stream.send).toHaveBeenCalledTimes(1));
    expect(mocks.stream.events).toHaveLength(3);

    mocks.sessions.currentId = "session-2";
    view.rerender(<ChatPanel />);
    await waitFor(() => expect(mocks.getSessionHistoryPage).toHaveBeenCalledWith("session-2", 100));
    await waitFor(() => expect(mocks.stream.events).toEqual([]));
  });

  it("keeps the visible message anchored when older history is prepended", async () => {
    mocks.getSessionHistoryPage.mockImplementation(
      (_sessionId: string, _limit: number, beforeId?: string) => Promise.resolve(
        beforeId
          ? {
              messages: [
                { id: "older-user", role: "user", content: "pergunta antiga", timestamp: "2026-09-28T09:00:00Z" },
                { id: "older-assistant", role: "assistant", content: "resposta antiga", timestamp: "2026-09-28T09:00:01Z" },
              ],
              count: 2, has_more: false, next_cursor: null,
            }
          : {
              messages: [
                { id: "newer-user", role: "user", content: "pergunta recente", timestamp: "2026-09-28T10:00:00Z" },
                { id: "newer-assistant", role: "assistant", content: "resposta recente", timestamp: "2026-09-28T10:00:01Z" },
              ],
              count: 2, has_more: true, next_cursor: "newer-user",
            },
      ),
    );

    render(<ChatPanel />);
    await screen.findByText("resposta recente");
    const scroller = screen.getByTestId("messages") as HTMLDivElement;
    Object.defineProperty(scroller, "scrollHeight", {
      configurable: true,
      get: () => document.querySelectorAll("[data-chat-message-id]").length * 100,
    });
    Object.defineProperty(scroller, "clientHeight", { configurable: true, value: 100 });
    scroller.scrollTop = 150;

    fireEvent.click(screen.getByRole("button", { name: "Carregar mensagens anteriores" }));
    await screen.findByText("resposta antiga");
    await waitFor(() => expect(scroller.scrollTop).toBe(350));
  });

  it("segue até ao fundo quando o mesmo balão recebe mais tokens", async () => {
    const view = render(<ChatPanel />);
    await waitFor(() => expect(mocks.getSessionHistoryPage).toHaveBeenCalledWith("session-1", 100));
    await waitFor(() => expect(screen.queryByText("A carregar conversação...")).toBeNull());
    const scroller = screen.getByTestId("messages") as HTMLDivElement;
    Object.defineProperty(scroller, "scrollHeight", { configurable: true, value: 1_000 });
    Object.defineProperty(scroller, "clientHeight", { configurable: true, value: 600 });
    scroller.scrollTop = 350;

    mocks.stream.streaming = true;
    mocks.stream.events = [
      { type: "agent_started", run_id: "live-run", seq: 1, event_id: "live-run-1", agent: "NEXUS" },
      { type: "token", run_id: "live-run", seq: 2, event_id: "live-run-2", content: "resposta parcial" },
    ];
    view.rerender(<ChatPanel />);
    expect(screen.getByText("resposta parcial")).toBeTruthy();

    scroller.scrollTop = 350;
    mocks.stream.events = [
      ...mocks.stream.events.slice(0, 1),
      { type: "token", run_id: "live-run", seq: 3, event_id: "live-run-3", content: "resposta parcial e continuada" },
    ];
    view.rerender(<ChatPanel />);

    await waitFor(() => expect(scroller.scrollTop).toBe(1_000));
    expect(screen.getByText("resposta parcial e continuada")).toBeTruthy();
  });
});
