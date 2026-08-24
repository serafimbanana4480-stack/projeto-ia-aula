import { describe, expect, it, vi, beforeEach } from "vitest";
import { act } from "@testing-library/react";
import { useModeStore, type Mode } from "../../stores/modeStore";

// Mock authenticatedFetch at the module level using vi.hoisted
const { mockAuthenticatedFetch } = vi.hoisted(() => ({
  mockAuthenticatedFetch: vi.fn(),
}));
vi.mock("../../lib/auth", () => ({
  authenticatedFetch: mockAuthenticatedFetch,
  authHeaders: vi.fn(() => ({})),
  getAccessToken: vi.fn(),
  clearAuth: vi.fn(),
  refreshAuth: vi.fn(),
}));

describe("modeStore", () => {
  beforeEach(() => {
    mockAuthenticatedFetch.mockReset();
    act(() => {
      useModeStore.setState({
        currentMode: "auto",
        modes: [],
        modesLoaded: false,
        modesLoading: false,
        modesError: null,
        usingFallback: false,
      });
    });
    localStorage.clear();
  });

  it("starts with auto mode", () => {
    expect(useModeStore.getState().currentMode).toBe("auto");
  });

  it("starts with empty modes", () => {
    expect(useModeStore.getState().modes).toEqual([]);
  });

  it("starts not loaded", () => {
    expect(useModeStore.getState().modesLoaded).toBe(false);
  });

  it("starts not loading", () => {
    expect(useModeStore.getState().modesLoading).toBe(false);
  });

  it("starts with null error", () => {
    expect(useModeStore.getState().modesError).toBeNull();
  });

  it("starts with usingFallback false", () => {
    expect(useModeStore.getState().usingFallback).toBe(false);
  });

  it("setMode changes current mode", () => {
    act(() => {
      useModeStore.getState().setMode("deep");
    });
    expect(useModeStore.getState().currentMode).toBe("deep");
  });

  it("setMode persists to localStorage", () => {
    act(() => {
      useModeStore.getState().setMode("deep");
    });
    expect(localStorage.getItem("nexus.currentMode")).toBe("deep");
  });

  it("setModes replaces modes list", () => {
    const modes: Mode[] = [
      { id: "auto", description: "Auto", default_agent: "NEXUS", default_model: "auto", router: "auto", tools_enabled: [] },
      { id: "deep", description: "Deep", default_agent: "ARCHITECT", default_model: "deep", router: "auto", tools_enabled: [] },
    ];
    act(() => {
      useModeStore.getState().setModes(modes);
    });
    expect(useModeStore.getState().modes).toHaveLength(2);
    expect(useModeStore.getState().modes[0].id).toBe("auto");
    expect(useModeStore.getState().modes[1].id).toBe("deep");
  });

  it("loadModes short-circuits when already loaded", async () => {
    act(() => {
      useModeStore.setState({ modesLoaded: true });
    });
    await act(async () => {
      await useModeStore.getState().loadModes();
    });
    expect(mockAuthenticatedFetch).not.toHaveBeenCalled();
  });

  it("loadModes short-circuits when already loading", async () => {
    act(() => {
      useModeStore.setState({ modesLoading: true });
    });
    await act(async () => {
      await useModeStore.getState().loadModes();
    });
    expect(mockAuthenticatedFetch).not.toHaveBeenCalled();
  });

  it("loadModes handles successful response", async () => {
    mockAuthenticatedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        modes: {
          auto: { description: "Auto mode", default_agent: "NEXUS", default_model: "auto" },
          deep: { description: "Deep mode", default_agent: "ARCHITECT", default_model: "deep" },
        },
      }),
    });

    await act(async () => {
      await useModeStore.getState().loadModes();
    });

    expect(useModeStore.getState().modesLoaded).toBe(true);
    expect(useModeStore.getState().modesLoading).toBe(false);
    expect(useModeStore.getState().modes).toHaveLength(2);
    expect(useModeStore.getState().modes[0].id).toBe("auto");
    expect(useModeStore.getState().modes[1].id).toBe("deep");
  });

  it("loadModes handles HTTP error", async () => {
    mockAuthenticatedFetch.mockResolvedValue({ ok: false, status: 500 });

    await act(async () => {
      await useModeStore.getState().loadModes();
    });

    expect(useModeStore.getState().modesLoaded).toBe(true);
    expect(useModeStore.getState().modesLoading).toBe(false);
    expect(useModeStore.getState().modesError).toBeDefined();
    expect(useModeStore.getState().usingFallback).toBe(true);
  });

  it("loadModes handles network error", async () => {
    mockAuthenticatedFetch.mockRejectedValue(new Error("Network error"));

    await act(async () => {
      await useModeStore.getState().loadModes();
    });

    expect(useModeStore.getState().modesError).toBeDefined();
    expect(useModeStore.getState().usingFallback).toBe(true);
    expect(useModeStore.getState().modes).toEqual([]);
  });

  it("loadModes resets to auto if current mode not in loaded modes", async () => {
    act(() => {
      useModeStore.setState({ currentMode: "nonexistent" });
    });
    mockAuthenticatedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        modes: {
          auto: { description: "Auto", default_agent: "NEXUS", default_model: "auto" },
        },
      }),
    });

    await act(async () => {
      await useModeStore.getState().loadModes();
    });

    expect(useModeStore.getState().currentMode).toBe("auto");
  });

  it("loadModes maps mode fields with defaults", async () => {
    mockAuthenticatedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({
        modes: {
          test_mode: {
            description: "Test",
            default_agent: "CODER",
            default_model: "test-model",
            router: "auto",
            tools_enabled: ["tool1", "tool2"],
            system_prompt_addon: "extra prompt",
          },
        },
      }),
    });

    await act(async () => {
      await useModeStore.getState().loadModes();
    });

    const mode = useModeStore.getState().modes[0];
    expect(mode.id).toBe("test_mode");
    expect(mode.description).toBe("Test");
    expect(mode.default_agent).toBe("CODER");
    expect(mode.default_model).toBe("test-model");
    expect(mode.router).toBe("auto");
    expect(mode.tools_enabled).toEqual(["tool1", "tool2"]);
    expect(mode.system_prompt_addon).toBe("extra prompt");
  });
});

