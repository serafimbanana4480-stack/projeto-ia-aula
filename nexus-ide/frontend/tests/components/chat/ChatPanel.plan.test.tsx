import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const modeState = {
    currentMode: "auto",
    modes: [] as Array<{ id: string }>,
    modesLoaded: true,
    setMode: vi.fn(),
    loadModes: vi.fn(),
  };
  return {
    getSessionHistoryPage: vi.fn(),
    getSessionRuns: vi.fn(),
    createPlan: vi.fn(),
    continuePlan: vi.fn(),
    approvePlan: vi.fn(),
    executePlan: vi.fn(),
    getPlanStatus: vi.fn(),
    cancelPlan: vi.fn(),
    search: "",
    routerReplace: vi.fn(),
    modeState,
    sessions: {
      sessions: [{ id: "session-1", title: "Conversa", mode: "plan", project_id: null, created_at: "", last_active_at: "" }],
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
  };
});

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: mocks.routerReplace, refresh: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(mocks.search),
  usePathname: () => "/",
}));

vi.mock("../../../hooks/useChatSessions", () => ({ useChatSessions: () => mocks.sessions }));
vi.mock("../../../hooks/useAgentStream", () => ({ useAgentStream: () => mocks.stream }));
vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../../lib/api")>();
  return {
    ...actual,
    getSessionHistoryPage: (...args: unknown[]) => mocks.getSessionHistoryPage(...args),
    getSessionRuns: (...args: unknown[]) => mocks.getSessionRuns(...args),
    createPlan: (...args: unknown[]) => mocks.createPlan(...args),
    continuePlan: (...args: unknown[]) => mocks.continuePlan(...args),
    approvePlan: (...args: unknown[]) => mocks.approvePlan(...args),
    executePlan: (...args: unknown[]) => mocks.executePlan(...args),
    getPlanStatus: (...args: unknown[]) => mocks.getPlanStatus(...args),
    cancelPlan: (...args: unknown[]) => mocks.cancelPlan(...args),
    getProvidersStatus: vi.fn().mockResolvedValue({ llm_available: true, demo_mode: false, providers: [] }),
  };
});

vi.mock("../../../lib/sessionRecovery", () => ({
  restoreRunTimelines: vi.fn(async (messages: unknown[]) => messages),
}));
vi.mock("../../../stores/metricsStore", () => ({ initMetricsStream: vi.fn() }));
vi.mock("../../../stores/modeStore", () => ({ useModeStore: () => mocks.modeState }));
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
vi.mock("../../../components/dashboard/RuntimeReadinessBanner", () => ({ default: () => null }));

import ChatPanel from "../../../components/chat/ChatPanel";

const waitingStatus = {
  plan_id: "plan-1",
  status: "awaiting_approval",
  title: "Plano",
  total_steps: 1,
  steps: [{ task_id: "step-1", name: "Passo", description: "", agent: "CODER", status: "pending", depends_on: [], priority: "medium", error_message: "" }],
  requires_approval: true,
  approved: false,
};

function createPlanResult() {
  return {
    status: "ready",
    source: "planner",
    error: null,
    deterministic_proposal: null,
    plan: {
      plan_id: "plan-1",
      title: "Plano",
      description: "",
      total_steps: 1,
      parallel_layers: 1,
      risk_level: "low",
      requires_approval: true,
      steps: waitingStatus.steps,
    },
  };
}

describe("ChatPanel plan lifecycle", () => {
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
    mocks.search = "";
    mocks.routerReplace.mockReset();
    mocks.modeState.setMode.mockReset();
    mocks.modeState.currentMode = "plan";
    mocks.modeState.modes = [];
    mocks.modeState.modesLoaded = true;
    mocks.stream.events = [];
    mocks.stream.streaming = false;
    mocks.getSessionHistoryPage.mockReset().mockResolvedValue({
      messages: [], count: 0, has_more: false, next_cursor: null,
    });
    mocks.getSessionRuns.mockReset().mockResolvedValue([]);
    mocks.createPlan.mockReset().mockResolvedValue(createPlanResult());
    mocks.continuePlan.mockReset();
    mocks.approvePlan.mockReset().mockResolvedValue({ status: "approved", plan_id: "plan-1" });
    mocks.executePlan.mockReset().mockResolvedValue({ state: "completed" });
    mocks.getPlanStatus.mockReset().mockResolvedValue(waitingStatus);
    mocks.cancelPlan.mockReset().mockResolvedValue({ status: "cancelled", session_id: "session-1" });
  });

  afterEach(() => {
    cleanup();
    if (originalScrollTo) {
      Object.defineProperty(HTMLElement.prototype, "scrollTo", originalScrollTo);
    } else {
      Reflect.deleteProperty(HTMLElement.prototype, "scrollTo");
    }
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  async function createPlanInChat() {
    const view = render(<ChatPanel />);
    await waitFor(() =>
      expect(mocks.getSessionHistoryPage).toHaveBeenCalledWith("session-1", 100),
    );
    const textarea = screen.getByRole("textbox");
    const form = textarea.closest("form");
    expect(form).not.toBeNull();
    fireEvent.change(textarea, { target: { value: "Prepara um plano" } });
    await waitFor(() => expect((textarea as HTMLTextAreaElement).value).toBe("Prepara um plano"));
    fireEvent.submit(form!);
    await screen.findByText("Plano de execução");
    await waitFor(() => expect(mocks.getPlanStatus).toHaveBeenCalledWith("plan-1"));
    return {
      view,
      approveButton: screen.getByRole("button", { name: "Aprovar plano" }),
    };
  }

  it("polls before the inline approval request and clears the interval when it finishes", async () => {
    const order: string[] = [];
    let resolveApproval!: () => void;
    const approvalPending = new Promise<void>((resolve) => { resolveApproval = resolve; });
    mocks.getPlanStatus
      .mockImplementationOnce(async () => waitingStatus)
      .mockImplementationOnce(async () => {
        order.push("status");
        return { ...waitingStatus, status: "executing", approved: true };
      })
      .mockImplementationOnce(async () => ({ ...waitingStatus, status: "completed", approved: true }));
    mocks.approvePlan.mockImplementation(async () => {
      order.push("approve");
      await approvalPending;
      return { status: "approved", plan_id: "plan-1" };
    });
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    const clearIntervalSpy = vi.spyOn(globalThis, "clearInterval");

    const { approveButton } = await createPlanInChat();
    fireEvent.click(approveButton);

    await waitFor(() => expect(mocks.approvePlan).toHaveBeenCalledWith("plan-1", "session-1"));
    expect(order.slice(-2)).toEqual(["status", "approve"]);
    const planTimerIndex = setIntervalSpy.mock.calls.findIndex((call) => call[1] === 2000);
    expect(planTimerIndex).toBeGreaterThanOrEqual(0);

    await act(async () => {
      resolveApproval();
      await approvalPending;
    });
    await waitFor(() => expect(screen.getByText("Concluído")).toBeTruthy());

    const timer = setIntervalSpy.mock.results[planTimerIndex]?.value;
    expect(timer).toBeDefined();
    expect(clearIntervalSpy).toHaveBeenCalledWith(timer);
  });

  it("clears plan polling when the chat unmounts during an inline approval", async () => {
    let resolveApproval!: () => void;
    const approvalPending = new Promise<void>((resolve) => { resolveApproval = resolve; });
    mocks.getPlanStatus
      .mockImplementationOnce(async () => waitingStatus)
      .mockResolvedValue({ ...waitingStatus, status: "executing", approved: true });
    mocks.approvePlan.mockReturnValue(approvalPending);
    const setIntervalSpy = vi.spyOn(globalThis, "setInterval");
    const clearIntervalSpy = vi.spyOn(globalThis, "clearInterval");

    const { approveButton, view } = await createPlanInChat();
    fireEvent.click(approveButton);
    await waitFor(() =>
      expect(setIntervalSpy.mock.calls.some((call) => call[1] === 2000)).toBe(true),
    );
    const planTimerIndex = setIntervalSpy.mock.calls.findIndex((call) => call[1] === 2000);
    const timer = setIntervalSpy.mock.results[planTimerIndex]?.value;

    view.unmount();
    expect(clearIntervalSpy).toHaveBeenCalledWith(timer);
    await act(async () => {
      resolveApproval();
      await approvalPending;
    });
  });

  it("keeps the session's plan visible when the composer mode changes", async () => {
    const { view } = await createPlanInChat();
    mocks.modeState.currentMode = "auto";
    view.rerender(<ChatPanel />);
    expect(screen.getByRole("region", { name: "Plano de execução" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Aprovar plano" })).toBeTruthy();
    expect(mocks.stream.send).not.toHaveBeenCalled();
  });

  it("hands off a draft and valid mode together after modes load, without sending", async () => {
    mocks.search = "mode=plan&prompt=Usa+a+skill+frontend&other=keep";
    mocks.modeState.modesLoaded = false;
    const view = render(<ChatPanel />);
    await waitFor(() => expect(mocks.getSessionHistoryPage).toHaveBeenCalled());
    expect(mocks.modeState.setMode).not.toHaveBeenCalled();
    mocks.modeState.modesLoaded = true;
    mocks.modeState.modes = [{ id: "plan" }];
    view.rerender(<ChatPanel />);
    await waitFor(() => expect(mocks.modeState.setMode).toHaveBeenCalledWith("plan"));
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("Usa a skill frontend");
    expect(mocks.routerReplace).toHaveBeenCalledWith("/?other=keep", { scroll: false });
    expect(mocks.stream.send).not.toHaveBeenCalled();
  });

  it("preserves a typed draft and ignores a mode absent from the runtime catalog", async () => {
    const view = render(<ChatPanel />);
    await waitFor(() => expect(mocks.getSessionHistoryPage).toHaveBeenCalled());
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "Pedido em curso" } });
    mocks.search = "mode=unknown&prompt=Outro+pedido";
    view.rerender(<ChatPanel />);
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe("Pedido em curso");
    expect(mocks.modeState.setMode).not.toHaveBeenCalled();
  });
});
