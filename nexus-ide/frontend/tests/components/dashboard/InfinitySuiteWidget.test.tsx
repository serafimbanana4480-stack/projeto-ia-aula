import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import InfinitySuiteWidget from "../../../components/dashboard/InfinitySuiteWidget";
import { useAdvancedModeStore } from "../../../stores/advancedModeStore";

const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }), usePathname: () => "/dashboard" }));
vi.mock("../../../lib/api", () => ({ apiUrl: (path: string) => `http://localhost:8000${path}` }));

const modes = Object.fromEntries(Array.from({ length: 11 }, (_, index) => [
  `mode-${index + 1}`, { active: index === 0, available: true, session_count: 1,
    active_session_count: 0, total_session_count: 1, group: index < 3 ? "productivity" : "analysis",
    display_name: `Estratégia ${index + 1}`, description: `Descrição da estratégia ${index + 1}`,
    icon: "bot", color: "#8b7cf6", runtime_status: index < 4 ? "integrated" : "composed",
    runtime_summary: `Resumo ${index + 1}`, handler: null, execution_target: { kind: "agent", agent: "CODER" },
  },
]));
const snapshot = { healthy: true, active_modes: 1, total_modes: 11, modes, groups: {} };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("InfinitySuiteWidget", () => {
  beforeEach(() => {
    localStorage.clear();
    push.mockClear();
    useAdvancedModeStore.setState({ modes: {}, groups: {}, activeModeIds: [], health: null,
      executionProfile: null, loading: false, error: null, actionError: null, pendingModeIds: [], lastSyncedAt: null });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(snapshot)));
  });
  afterEach(() => vi.unstubAllGlobals());

  it("keeps a useful summary and makes all eleven modes accessible on expansion", async () => {
    render(<InfinitySuiteWidget />);
    const explore = await screen.findByRole("button", { name: "Explorar 11 modos" });
    expect(screen.getByText("1/11 configurados")).toBeTruthy();
    expect(screen.queryAllByRole("switch")).toHaveLength(0);
    expect(screen.getByText("Atividade dos workers: não medida")).toBeTruthy();
    fireEvent.click(explore);
    expect(screen.getAllByRole("switch")).toHaveLength(11);
    expect(screen.getByText("Descrição da estratégia 11")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ocultar modos" }));
    expect(screen.queryAllByRole("switch")).toHaveLength(0);
  });

  it("searches modes and filters the server-confirmed configured modes", async () => {
    render(<InfinitySuiteWidget />);
    fireEvent.click(await screen.findByRole("button", { name: "Explorar 11 modos" }));
    fireEvent.change(screen.getByRole("textbox", { name: "Pesquisar modos Infinity" }), { target: { value: "Estratégia 11" } });
    expect(screen.getAllByRole("switch")).toHaveLength(1);
    expect(screen.getByRole("switch", { name: "Configurar Estratégia 11" })).toBeTruthy();
    fireEvent.change(screen.getByRole("textbox", { name: "Pesquisar modos Infinity" }), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Configurados 1" }));
    expect(screen.getAllByRole("switch")).toHaveLength(1);
    expect(screen.getByRole("switch", { name: "Configurar Estratégia 1" }).getAttribute("aria-checked")).toBe("true");
  });

  it("preserves a prepared command across navigation from dashboard to chat", async () => {
    render(<InfinitySuiteWidget />);
    fireEvent.click(await screen.findByRole("button", { name: "Explorar 11 modos" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Preparar pedido" })[0]);
    expect(localStorage.getItem("nexus.chat.draft")).toMatch(/^\/mode-\d+ $/);
    expect(push).toHaveBeenCalledWith("/");
  });

  it("shows an activation rejection and keeps the switch off", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(response(snapshot))
      .mockResolvedValueOnce(response({ detail: "Ativação recusada" }, 403));
    vi.stubGlobal("fetch", fetchMock);
    render(<InfinitySuiteWidget />);
    fireEvent.click(await screen.findByRole("button", { name: "Explorar 11 modos" }));
    fireEvent.click(screen.getByRole("switch", { name: "Configurar Estratégia 2" }));
    expect(await screen.findByText("Ativação recusada")).toBeTruthy();
    expect(screen.getByRole("switch", { name: "Configurar Estratégia 2" }).getAttribute("aria-checked")).toBe("false");
  });

  it("marks an old snapshot and disables mutations after a failed refresh", async () => {
    render(<InfinitySuiteWidget />);
    fireEvent.click(await screen.findByRole("button", { name: "Explorar 11 modos" }));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("offline", { status: 503 })));
    await act(async () => useAdvancedModeStore.getState().refreshHealth());
    expect(screen.getByText("Leitura desatualizada")).toBeTruthy();
    expect((screen.getByRole("switch", { name: "Configurar Estratégia 1" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("shows real disk blocks without calling the catalog ready", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ ...snapshot,
      disk_guard: { write_blocked: true, threshold_percent: 5, status: "critical", snapshot: { free_percent: 2.8 } } })));
    render(<InfinitySuiteWidget />);
    expect(await screen.findByText("Execução bloqueada pelo armazenamento")).toBeTruthy();
    expect(screen.getByText(/2[,.]8% livre/)).toBeTruthy();
    await waitFor(() => expect(screen.getByText("1/11 configurados")).toBeTruthy());
  });
});
