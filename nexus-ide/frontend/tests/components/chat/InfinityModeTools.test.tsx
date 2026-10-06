import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InfinityModeTools } from "../../../components/infinity/InfinityModeTools";
import { useAdvancedModeStore, type AdvancedMode } from "../../../stores/advancedModeStore";

vi.mock("../../../lib/api", () => ({ apiUrl: (path: string) => path }));
const originalRefresh = useAdvancedModeStore.getState().refreshHealth;
const mode = (id: string): AdvancedMode => ({ mode_id: id, display_name: id, description: "",
  group: "infinity", icon: "bot", color: "#fff", active: true, available: true, session_count: 1,
  sessions: [{ session_id: "saved-session", state: "active", start_time: "", updated_time: "", goal_count: 0 }] });
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("Infinity mode tools", () => {
  beforeEach(() => {
    localStorage.clear(); localStorage.setItem("nexus.access_token", "isolated-token");
    useAdvancedModeStore.setState({ refreshHealth: vi.fn().mockResolvedValue(undefined) });
  });
  afterEach(() => { cleanup(); useAdvancedModeStore.setState({ refreshHealth: originalRefresh }); vi.unstubAllGlobals(); });

  it("submits a typed risk check and shows that install approval is required", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ gate_passed: false, requires_approval: true, findings: ["Requires approval"] }));
    vi.stubGlobal("fetch", fetchMock);
    render(<InfinityModeTools mode={mode("sentinel")} />);
    fireEvent.change(screen.getByLabelText("Ação a verificar"), { target: { value: "Install package" } });
    fireEvent.change(screen.getByLabelText("Nível de risco"), { target: { value: "2" } });
    fireEvent.click(screen.getByRole("button", { name: "Verificar risco" }));
    expect(await screen.findByText("Aprovação necessária")).toBeTruthy();
    const [path, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(path).toBe("/api/advanced-modes/sentinel/check");
    expect(JSON.parse(String(init.body))).toEqual({ action: "Install package", risk_level: 2, files: [] });
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer isolated-token");
    expect(screen.getByText(/não medidas por este formulário/)).toBeTruthy();
  });

  it("exposes a server failure instead of presenting a risk pass", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response({ detail: "Check unavailable" }, 503)));
    render(<InfinityModeTools mode={mode("sentinel")} />);
    fireEvent.change(screen.getByLabelText("Ação a verificar"), { target: { value: "Read file" } });
    fireEvent.click(screen.getByRole("button", { name: "Verificar risco" }));
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", "Check unavailable");
    expect(screen.queryByText(/Sem bloqueio identificado/)).toBeNull();
  });

  it("submits all seven absolute scores and keeps a tournament tie visible", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ winner: null, status: "TIE" }));
    vi.stubGlobal("fetch", fetchMock);
    render(<InfinityModeTools mode={mode("multiverse")} />);
    fireEvent.change(screen.getByLabelText("Alternativa 1"), { target: { value: "Implementation A" } });
    fireEvent.change(screen.getByLabelText("Alternativa 2"), { target: { value: "Implementation B" } });
    for (const input of screen.getAllByRole("spinbutton")) fireEvent.change(input, { target: { value: "70" } });
    fireEvent.click(screen.getByRole("button", { name: "Comparar pontuações" }));
    expect(await screen.findByText("Empate nas pontuações submetidas")).toBeTruthy();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    const body = JSON.parse(String(init.body));
    expect(body.entries).toHaveLength(2);
    expect(Object.keys(body.entries[0].scores)).toHaveLength(7);
    expect(body.entries[0].scores.security).toBe(70);
    expect(body.entries[1].scores.complexity).toBe(70);
  });

  it("submits an advisor claim for an existing session and refreshes recorded metrics", async () => {
    const fetchMock = vi.fn().mockResolvedValue(response({ verdict: "BLOCKED", findings: ["Missing tests"] }));
    vi.stubGlobal("fetch", fetchMock);
    render(<InfinityModeTools mode={mode("advisor-infinity")} />);
    fireEvent.change(screen.getByLabelText("Sessão do Advisor"), { target: { value: "saved-session" } });
    fireEvent.change(screen.getByLabelText("Conclusão a rever"), { target: { value: "All done" } });
    fireEvent.click(screen.getByRole("button", { name: "Rever conclusão" }));
    expect(await screen.findByText("Conclusão bloqueada")).toBeTruthy();
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({ session_id: "saved-session", claim: "All done", evidence: {} });
    await waitFor(() => expect(useAdvancedModeStore.getState().refreshHealth).toHaveBeenCalledOnce());
  });
});
