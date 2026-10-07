import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import MissionPanel from "../../../components/dashboard/MissionPanel";

const { mockAuthenticatedFetch } = vi.hoisted(() => ({
  mockAuthenticatedFetch: vi.fn(),
}));

vi.mock("../../../lib/api", () => ({ apiUrl: (path: string) => path }));
vi.mock("../../../lib/auth", () => ({ authenticatedFetch: mockAuthenticatedFetch }));

vi.mock("../../../components/ui/Surface", () => ({
  Surface: ({ children }: { children: ReactNode }) => <section>{children}</section>,
  SurfaceHeader: ({ title, subtitle }: { title: string; subtitle?: string }) => (
    <header>
      <h2>{title}</h2>
      {subtitle ? <p>{subtitle}</p> : null}
    </header>
  ),
}));

vi.mock("../../../components/ui/Card", () => ({
  CardEmpty: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  CardStat: ({ label, value }: { label: string; value: ReactNode }) => (
    <div>{label}: {value}</div>
  ),
}));

function response(status: number, body: unknown): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => body,
  } as Response;
}

const activeMission = {
  id: "mission-1",
  title: "Missão de regressão",
  state: "executing",
  phase_label: "Execução",
  progress: 0.25,
  active_agents: 1,
  tasks_total: 2,
  tasks_done: 0,
  files_changed: [],
  tests_passed: 0,
  tests_failed: 0,
  risks: [],
  unresolved: [],
  brief: null,
  plan: null,
  waves: [],
  decisions: [],
  timeline: [],
  verifications: [],
};

describe("MissionPanel", () => {
  beforeEach(() => {
    vi.useRealTimers();
    mockAuthenticatedFetch.mockReset();
  });

  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("shows an initial loading state before the first response", async () => {
    let resolveRequest: (value: Response) => void = () => undefined;
    mockAuthenticatedFetch.mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveRequest = resolve;
      }),
    );

    render(<MissionPanel />);
    expect(screen.getByText("A carregar Mission Control…")).toBeTruthy();

    await act(async () => {
      resolveRequest(response(200, { active: false, mission: null }));
    });
    expect(screen.getByText(/Nenhuma missão em curso/)).toBeTruthy();
  });

  it("uses authenticatedFetch and shows authentication errors without stale mission data", async () => {
    vi.useFakeTimers();
    mockAuthenticatedFetch
      .mockResolvedValueOnce(response(200, { active: true, mission: activeMission }))
      .mockResolvedValueOnce(response(401, {}));

    render(<MissionPanel />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Missão de regressão")).toBeTruthy();
    expect(mockAuthenticatedFetch).toHaveBeenCalledWith(
      "/api/mission/current",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(screen.getByText("Autenticação necessária para ver Mission Control.")).toBeTruthy();
    expect(screen.queryByText("Missão de regressão")).toBeNull();
  });

  it("keeps a visible warning when polling fails after a mission was loaded", async () => {
    mockAuthenticatedFetch
      .mockResolvedValueOnce(response(200, { active: true, mission: activeMission }))
      .mockResolvedValueOnce(response(503, {}));
    vi.useFakeTimers();

    render(<MissionPanel />);
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByText("Missão de regressão")).toBeTruthy();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(screen.getByRole("alert").textContent).toContain("HTTP 503");
    expect(screen.getByRole("alert").textContent).toContain("podem estar desatualizados");
    expect(screen.getByText("Missão de regressão")).toBeTruthy();
  });

  it("prevents overlapping polls and exposes the tab relationships and keyboard model", async () => {
    let resolveRequest: (value: Response) => void = () => undefined;
    mockAuthenticatedFetch.mockReturnValue(
      new Promise<Response>((resolve) => {
        resolveRequest = resolve;
      }),
    );
    vi.useFakeTimers();

    render(<MissionPanel />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    expect(mockAuthenticatedFetch).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveRequest(response(200, { active: true, mission: activeMission }));
    });

    const briefTab = screen.getByRole("tab", { name: "Brief" });
    const planTab = screen.getByRole("tab", { name: "Plano" });
    expect(briefTab.getAttribute("aria-controls")).toBe("mission-tabpanel");
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe("mission-tab-brief");

    fireEvent.keyDown(briefTab, { key: "ArrowRight" });
    expect(planTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(planTab);
    expect(screen.getByRole("tabpanel").getAttribute("aria-labelledby")).toBe("mission-tab-plan");
  });
});
