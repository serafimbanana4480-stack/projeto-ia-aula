import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAdvancedModeStore } from "../../stores/advancedModeStore";

describe("advancedModeStore slash commands", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useAdvancedModeStore.setState({
      commands: {},
      commandsLoading: false,
      commandsError: null,
      modes: {}, groups: {}, activeModeIds: [], health: null, executionProfile: null,
      loading: false, error: null, actionError: null, pendingModeIds: [], lastSyncedAt: null,
    });
    vi.restoreAllMocks();
  });

  it("loads commands with the canonical access token", async () => {
    window.localStorage.setItem("nexus.access_token", "access-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          commands: {
            forge: {
              aliases: ["/forge", "/f"],
              description: "Fábrica de projetos",
              mode: "forge",
            },
          },
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await useAdvancedModeStore.getState().loadCommands();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toMatch(/\/api\/advanced-modes\/commands$/);
    expect(new Headers(init.headers).get("Authorization")).toBe("Bearer access-token");
    expect(useAdvancedModeStore.getState().commands.forge.aliases).toEqual(["/forge", "/f"]);
    expect(useAdvancedModeStore.getState().commandsError).toBeNull();
    expect(useAdvancedModeStore.getState().commandsLoading).toBe(false);
  });

  it("exposes an API failure instead of leaving an invisible empty menu", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 403 })));

    await useAdvancedModeStore.getState().loadCommands();

    expect(useAdvancedModeStore.getState().commands).toEqual({});
    expect(useAdvancedModeStore.getState().commandsError).toContain("HTTP 403");
    expect(useAdvancedModeStore.getState().commandsLoading).toBe(false);
  });

  it("rejects malformed command entries without crashing autocomplete", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            commands: {
              valid: { aliases: ["/valid"], description: "Válido", mode: "valid" },
              malformed: { aliases: null },
            },
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await useAdvancedModeStore.getState().loadCommands();

    expect(Object.keys(useAdvancedModeStore.getState().commands)).toEqual(["valid"]);
  });

  const health = (active: boolean) => ({
    healthy: true, total_modes: 1, active_modes: active ? 1 : 0, groups: {},
    modes: { forge: { active, available: true, session_count: active ? 1 : 0,
      total_session_count: 7, active_session_count: active ? 1 : 0,
      group: "productivity", display_name: "Forge", description: "Construir", icon: "hammer", color: "#fff" } },
    execution_profile: { active_mode_ids: active ? ["forge"] : [], applied_mode_ids: active ? ["forge"] : [],
      policy_mode_ids: [], primary_mode: active ? "forge" : null, preferred_agent: "CODER", force_autonomous: false, summary: "profile" },
  });
  const jsonResponse = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  it("refreshes modes, active IDs and the execution profile from one server snapshot", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(health(true))));
    await useAdvancedModeStore.getState().refreshHealth();
    expect(useAdvancedModeStore.getState().activeModeIds).toEqual(["forge"]);
    expect(useAdvancedModeStore.getState().modes.forge.active).toBe(true);
    expect(useAdvancedModeStore.getState().executionProfile?.primary_mode).toBe("forge");
    expect(useAdvancedModeStore.getState().modes.forge.total_session_count).toBe(7);
  });

  it("does not arm a mode when the server rejects its activation", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(health(false)))
      .mockResolvedValueOnce(jsonResponse({ detail: "Policy rejected" }, 403));
    vi.stubGlobal("fetch", fetchMock);
    await useAdvancedModeStore.getState().loadModes();
    const result = await useAdvancedModeStore.getState().activateMode("forge");
    expect(result.success).toBe(false);
    expect(useAdvancedModeStore.getState().modes.forge.active).toBe(false);
    expect(useAdvancedModeStore.getState().activeModeIds).toEqual([]);
    expect(useAdvancedModeStore.getState().actionError).toBe("Policy rejected");
    expect(useAdvancedModeStore.getState().pendingModeIds).toEqual([]);
  });

  it("keeps activation idempotent and reloads the actual session counts", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(jsonResponse(health(false)))
      .mockResolvedValueOnce(jsonResponse({ success: true, session_id: "actual-session" }))
      .mockResolvedValueOnce(jsonResponse(health(true)))
      .mockResolvedValueOnce(jsonResponse({ success: true, session_id: "actual-session" }))
      .mockResolvedValueOnce(jsonResponse(health(true)));
    vi.stubGlobal("fetch", fetchMock);
    await useAdvancedModeStore.getState().loadModes();
    await useAdvancedModeStore.getState().activateMode("forge");
    await useAdvancedModeStore.getState().activateMode("forge");
    expect(useAdvancedModeStore.getState().activeModeIds).toEqual(["forge"]);
    expect(useAdvancedModeStore.getState().modes.forge.session_count).toBe(1);
    expect(useAdvancedModeStore.getState().modes.forge.total_session_count).toBe(7);
  });

  it("never restores an outdated poll after an activation is confirmed", async () => {
    let resolveOld!: (response: Response) => void;
    const fetchMock = vi.fn().mockImplementationOnce(() => new Promise<Response>((resolve) => { resolveOld = resolve; }))
      .mockResolvedValueOnce(jsonResponse({ success: true }))
      .mockResolvedValueOnce(jsonResponse(health(true)));
    vi.stubGlobal("fetch", fetchMock);
    const oldPoll = useAdvancedModeStore.getState().loadModes();
    const activating = useAdvancedModeStore.getState().activateMode("forge");
    await new Promise((resolve) => setTimeout(resolve, 0));
    resolveOld(jsonResponse(health(false)));
    await Promise.all([oldPoll, activating]);
    expect(useAdvancedModeStore.getState().modes.forge.active).toBe(true);
    expect(useAdvancedModeStore.getState().executionProfile?.primary_mode).toBe("forge");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("deduplicates concurrent health requests from two UI surfaces", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(health(true))));
    await Promise.all([useAdvancedModeStore.getState().loadModes(), useAdvancedModeStore.getState().loadModes()]);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("preserves the last snapshot but exposes a refresh failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(jsonResponse(health(true)))
      .mockResolvedValueOnce(new Response("upstream failure", { status: 503 })));
    await useAdvancedModeStore.getState().loadModes();
    await useAdvancedModeStore.getState().refreshHealth();
    expect(useAdvancedModeStore.getState().modes.forge.active).toBe(true);
    expect(useAdvancedModeStore.getState().error).toContain("HTTP 503");
  });
});
