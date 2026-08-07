import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAdvancedModeStore } from "../../stores/advancedModeStore";

describe("advancedModeStore slash commands", () => {
  beforeEach(() => {
    window.localStorage.clear();
    useAdvancedModeStore.setState({
      commands: {},
      commandsLoading: false,
      commandsError: null,
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
});
