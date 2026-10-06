import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamEvent } from "../../../lib/types";

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
vi.mock("../../../stores/projectStore", () => {
  const state = { currentProject: null };
  return { useProjectStore: () => state };
});
vi.mock("../../../stores/themeStore", () => {
  const state = { toggleTheme: vi.fn() };
  return { useThemeStore: () => state };
});
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
  const toast = { error: vi.fn(), success: vi.fn(), info: vi.fn(), warning: vi.fn() };
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

function runEvents(runId: string, answer: string): StreamEvent[] {
  const timestamp = "2026-09-28T10:00:00.000Z";
  return [
    { type: "agent_started", run_id: runId, seq: 1, event_id: `${runId}-1`, agent: "NEXUS", timestamp },
    { type: "token", run_id: runId, seq: 2, event_id: `${runId}-2`, content: answer, timestamp },
    { type: "done", run_id: runId, seq: 3, event_id: `${runId}-3`, timestamp },
  ];
}

describe("ChatPanel multi-run session timeline", () => {
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
    mocks.stream.reset.mockReset().mockImplementation(() => {
      mocks.stream.events = [];
    });
    mocks.stream.send.mockReset();
    mocks.getSessionHistoryPage.mockReset().mockResolvedValue({
      messages: [],
      count: 0,
      has_more: false,
      next_cursor: null,
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

  it("keeps both responses visible after two sequential sends in one session", async () => {
    const responses = [
      runEvents("run-1", "resposta da primeira pergunta"),
      runEvents("run-2", "resposta da segunda pergunta"),
    ];
    let runIndex = 0;
    mocks.stream.send.mockImplementation(async () => {
      mocks.stream.events = [...mocks.stream.events, ...responses[runIndex++]];
      return true;
    });

    const view = render(<ChatPanel />);
    await waitFor(() => expect(mocks.getSessionHistoryPage).toHaveBeenCalledWith("session-1", 100));
    const textarea = screen.getByRole("textbox");
    const form = textarea.closest("form");
    expect(form).not.toBeNull();

    await act(async () => {
      fireEvent.change(textarea, { target: { value: "primeira pergunta" } });
      fireEvent.submit(form!);
    });
    await waitFor(() => expect(mocks.stream.send).toHaveBeenCalledTimes(1));
    view.rerender(<ChatPanel />);
    expect(await screen.findByText("resposta da primeira pergunta")).toBeTruthy();

    await act(async () => {
      fireEvent.change(textarea, { target: { value: "segunda pergunta" } });
      fireEvent.submit(form!);
    });
    await waitFor(() => expect(mocks.stream.send).toHaveBeenCalledTimes(2));
    view.rerender(<ChatPanel />);

    expect(await screen.findByText("primeira pergunta")).toBeTruthy();
    expect(await screen.findByText("resposta da primeira pergunta")).toBeTruthy();
    expect(await screen.findByText("segunda pergunta")).toBeTruthy();
    expect(await screen.findByText("resposta da segunda pergunta")).toBeTruthy();
    const renderedMessages = Array.from(document.querySelectorAll("[data-chat-message-id]"))
      .map((message) => message.textContent?.trim());
    expect(renderedMessages).toEqual([
      "primeira pergunta",
      "resposta da primeira pergunta",
      "segunda pergunta",
      "resposta da segunda pergunta",
    ]);
    expect(mocks.stream.send.mock.calls.map(([message]) => message)).toEqual([
      "primeira pergunta",
      "segunda pergunta",
    ]);
  });
});
