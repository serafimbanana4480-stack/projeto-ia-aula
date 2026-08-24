import { describe, expect, it, vi, beforeEach } from "vitest";
import { act } from "@testing-library/react";
import { useProviderStore } from "../../stores/providerStore";

const { mockGetProviderCatalog, mockValidateProviderKey, mockGetProviderModels, mockRefreshProviderCatalog } = vi.hoisted(() => ({
  mockGetProviderCatalog: vi.fn(),
  mockValidateProviderKey: vi.fn(),
  mockGetProviderModels: vi.fn(),
  mockRefreshProviderCatalog: vi.fn(),
}));

vi.mock("../../lib/api", () => ({
  getProviderCatalog: mockGetProviderCatalog,
  getProviderModels: mockGetProviderModels,
  refreshProviderCatalog: mockRefreshProviderCatalog,
  validateProviderKey: mockValidateProviderKey,
}));

describe("useProviderStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    act(() => {
      useProviderStore.setState({
        providers: [],
        loading: false,
        error: null,
        loaded: false,
        keyTests: {},
        modelsByProvider: {},
      });
    });
  });

  it("initializes with empty providers", () => {
    expect(useProviderStore.getState().providers).toEqual([]);
  });

  it("initializes as not loaded", () => {
    expect(useProviderStore.getState().loaded).toBe(false);
  });

  it("initializes not loading", () => {
    expect(useProviderStore.getState().loading).toBe(false);
  });

  it("initializes with null error", () => {
    expect(useProviderStore.getState().error).toBeNull();
  });

  it("initializes with empty keyTests", () => {
    expect(useProviderStore.getState().keyTests).toEqual({});
  });

  it("initializes with empty modelsByProvider", () => {
    expect(useProviderStore.getState().modelsByProvider).toEqual({});
  });

  it("loadProviders fetches catalog on first call", async () => {
    const mockProviders = [
      { id: "openai", name: "OpenAI", type: "openai" },
      { id: "anthropic", name: "Anthropic", type: "anthropic" },
    ];
    mockGetProviderCatalog.mockResolvedValue(mockProviders);

    await act(async () => {
      await useProviderStore.getState().loadProviders();
    });

    expect(mockGetProviderCatalog).toHaveBeenCalledTimes(1);
    expect(useProviderStore.getState().providers).toHaveLength(2);
    expect(useProviderStore.getState().loaded).toBe(true);
  });

  it("loadProviders short-circuits when already loading", async () => {
    act(() => {
      useProviderStore.setState({ loading: true });
    });
    await act(async () => {
      await useProviderStore.getState().loadProviders();
    });
    expect(mockGetProviderCatalog).not.toHaveBeenCalled();
  });

  it("loadProviders handles errors", async () => {
    mockGetProviderCatalog.mockRejectedValue(new Error("Network error"));

    await act(async () => {
      await useProviderStore.getState().loadProviders();
    });

    expect(useProviderStore.getState().loaded).toBe(true);
    expect(useProviderStore.getState().loading).toBe(false);
    expect(useProviderStore.getState().error).toBe("Network error");
  });

  it("testKey sets testing status then valid on success", async () => {
    mockValidateProviderKey.mockResolvedValue({ provider: "openai", valid: true, error: null, models_count: 10 });

    const promise = useProviderStore.getState().testKey("openai", "test-key");

    expect(useProviderStore.getState().keyTests["openai"]?.status).toBe("testing");

    await act(async () => {
      await promise;
    });

    const testState = useProviderStore.getState().keyTests["openai"];
    expect(testState?.status).toBe("valid");
    expect(testState?.result?.valid).toBe(true);
    expect(testState?.testedAt).toBeGreaterThan(0);
  });

  it("testKey sets invalid status when key is invalid", async () => {
    mockValidateProviderKey.mockResolvedValue({ provider: "openai", valid: false, error: "Invalid key", models_count: 0 });

    await act(async () => {
      await useProviderStore.getState().testKey("openai", "bad-key");
    });

    expect(useProviderStore.getState().keyTests["openai"]?.status).toBe("invalid");
  });

  it("testKey handles API error", async () => {
    mockValidateProviderKey.mockRejectedValue(new Error("Connection failed"));

    await act(async () => {
      await useProviderStore.getState().testKey("openai", "test-key");
    });

    const testState = useProviderStore.getState().keyTests["openai"];
    expect(testState?.status).toBe("invalid");
    expect(testState?.result?.valid).toBe(false);
    expect(testState?.result?.error).toBe("Connection failed");
  });

  it("testKey passes undefined apiKey when not provided", async () => {
    mockValidateProviderKey.mockResolvedValue({ provider: "openai", valid: true, error: null, models_count: 5 });

    await act(async () => {
      await useProviderStore.getState().testKey("openai");
    });

    expect(mockValidateProviderKey).toHaveBeenCalledWith("openai", undefined);
  });

  it("loadProviderModels sets loading state", async () => {
    mockGetProviderModels.mockImplementation(() => new Promise(() => {}));

    const promise = act(async () => {
      await useProviderStore.getState().loadProviderModels("openai");
    });

    expect(useProviderStore.getState().modelsByProvider["openai"]?.loading).toBe(true);
    expect(useProviderStore.getState().modelsByProvider["openai"]?.error).toBeNull();

    void promise;
  });

  it("loadProviderModels short-circuits when already loading", async () => {
    act(() => {
      useProviderStore.setState({
        modelsByProvider: { openai: { models: [], loading: true, error: null, cached: false, fetchedAt: 0 } },
      });
    });
    await act(async () => {
      await useProviderStore.getState().loadProviderModels("openai");
    });
    expect(mockGetProviderModels).not.toHaveBeenCalled();
  });

  it("loadProviderModels stores models on success", async () => {
    mockGetProviderModels.mockResolvedValue({
      models: [{ id: "gpt-4", name: "GPT-4" }],
      cached: true,
      fetched_at: 1234567890,
    });

    await act(async () => {
      await useProviderStore.getState().loadProviderModels("openai");
    });

    const state = useProviderStore.getState().modelsByProvider["openai"];
    expect(state?.models).toHaveLength(1);
    expect(state?.models[0].id).toBe("gpt-4");
    expect(state?.cached).toBe(true);
    expect(state?.fetchedAt).toBe(1234567890);
    expect(state?.loading).toBe(false);
  });

  it("loadProviderModels handles errors", async () => {
    mockGetProviderModels.mockRejectedValue(new Error("Failed to fetch"));

    await act(async () => {
      await useProviderStore.getState().loadProviderModels("openai");
    });

    const state = useProviderStore.getState().modelsByProvider["openai"];
    expect(state?.error).toBe("Failed to fetch");
    expect(state?.loading).toBe(false);
  });

  it("clearKeyTest removes key test state", () => {
    act(() => {
      useProviderStore.setState({
        keyTests: { openai: { status: "valid", result: { provider: "openai", valid: true, error: null, models_count: 10 }, testedAt: 123 } },
      });
    });

    act(() => {
      useProviderStore.getState().clearKeyTest("openai");
    });

    expect(useProviderStore.getState().keyTests["openai"]).toBeUndefined();
  });

  it("clearKeyTest does nothing for unknown provider", () => {
    act(() => {
      useProviderStore.setState({ keyTests: {} });
      useProviderStore.getState().clearKeyTest("unknown");
    });
    expect(useProviderStore.getState().keyTests).toEqual({});
  });

  it("invalidate refreshes catalog and reloads providers", async () => {
    mockRefreshProviderCatalog.mockResolvedValue(undefined);
    mockGetProviderCatalog.mockResolvedValue([{ id: "openai", name: "OpenAI", type: "openai" }]);

    await act(async () => {
      await useProviderStore.getState().invalidate();
    });

    expect(mockRefreshProviderCatalog).toHaveBeenCalledTimes(1);
    expect(mockGetProviderCatalog).toHaveBeenCalledTimes(1);
    expect(useProviderStore.getState().loaded).toBe(true);
  });
});
