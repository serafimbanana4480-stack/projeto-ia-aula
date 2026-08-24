import { describe, expect, it, beforeEach, vi } from "vitest";
import { act } from "@testing-library/react";
import { useModelStore } from "../../stores/modelStore";
import type { Model } from "../../stores/modelStore";

describe("modelStore", () => {
  beforeEach(() => {
    act(() => {
      useModelStore.setState({
        activeModel: "",
        activeProvider: "",
        models: [],
        providerStatus: [],
        modelsLoaded: false,
        modelsLoading: false,
        modelsError: null,
      });
    });
  });

  it("starts with empty activeModel", () => {
    expect(useModelStore.getState().activeModel).toBe("");
  });

  it("starts with empty activeProvider", () => {
    expect(useModelStore.getState().activeProvider).toBe("");
  });

  it("starts with empty models list", () => {
    expect(useModelStore.getState().models).toEqual([]);
  });

  it("starts with empty providerStatus", () => {
    expect(useModelStore.getState().providerStatus).toEqual([]);
  });

  it("starts with modelsLoaded false", () => {
    expect(useModelStore.getState().modelsLoaded).toBe(false);
  });

  it("starts with modelsLoading false", () => {
    expect(useModelStore.getState().modelsLoading).toBe(false);
  });

  it("starts with null modelsError", () => {
    expect(useModelStore.getState().modelsError).toBeNull();
  });

  it("setActiveModel changes the active model", () => {
    act(() => {
      useModelStore.getState().setActiveModel("claude-3");
    });
    expect(useModelStore.getState().activeModel).toBe("claude-3");
  });

  it("setActiveModel with provider sets both model and provider", () => {
    act(() => {
      useModelStore.getState().setActiveModel("gpt-4", "openai");
    });
    expect(useModelStore.getState().activeModel).toBe("gpt-4");
    expect(useModelStore.getState().activeProvider).toBe("openai");
  });

  it("setActiveModel without provider defaults provider to empty string", () => {
    act(() => {
      useModelStore.getState().setActiveModel("gpt-4");
    });
    expect(useModelStore.getState().activeProvider).toBe("");
  });

  it("setModels sets models and marks loaded", () => {
    const models: Model[] = [
      { id: "gpt-4", tier: "premium", size_gb: 0, status: "available" },
      { id: "claude", tier: "premium", size_gb: 0, status: "available" },
    ];
    act(() => {
      useModelStore.getState().setModels(models);
    });
    expect(useModelStore.getState().models).toEqual(models);
    expect(useModelStore.getState().modelsLoaded).toBe(true);
  });

  it("setModels with empty array", () => {
    act(() => {
      useModelStore.getState().setModels([]);
    });
    expect(useModelStore.getState().models).toEqual([]);
    expect(useModelStore.getState().modelsLoaded).toBe(true);
  });

  it("loadModels short-circuits when already loading", async () => {
    act(() => {
      useModelStore.setState({ modelsLoading: true });
    });
    await act(async () => {
      await useModelStore.getState().loadModels();
    });
    // Should not change state
    expect(useModelStore.getState().modelsLoading).toBe(true);
  });

  it("loadModels short-circuits when already loaded (unless refresh)", async () => {
    act(() => {
      useModelStore.setState({ modelsLoaded: true, models: [{ id: "existing", tier: "x", size_gb: 0, status: "available" }] });
    });
    await act(async () => {
      await useModelStore.getState().loadModels();
    });
    // Without refresh, should keep existing models
    expect(useModelStore.getState().models).toHaveLength(1);
    expect(useModelStore.getState().models[0].id).toBe("existing");
  });

  it("loadModels sets loading state during fetch", async () => {
    // Mock getModelCatalog to track loading
    vi.mock("../../lib/api", () => ({
      getModelCatalog: vi.fn().mockImplementation(async (refresh: boolean) => {
        expect(refresh).toBe(true);
        return { models: [], providers: [] };
      }),
      ApiError: class ApiError extends Error { status: number; constructor(msg: string, status: number) { super(msg); this.status = status; } },
    }));
    await act(async () => {
      await useModelStore.getState().loadModels(true);
    });
    expect(useModelStore.getState().modelsLoading).toBe(false);
    expect(useModelStore.getState().modelsLoaded).toBe(true);
  });
});
