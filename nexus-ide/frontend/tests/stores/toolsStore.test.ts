import { describe, expect, it, vi, beforeEach } from "vitest";
import { act } from "@testing-library/react";
import { useToolsStore } from "../../stores/toolsStore";

const { mockGetTools, mockToggleTool } = vi.hoisted(() => ({
  mockGetTools: vi.fn(),
  mockToggleTool: vi.fn(),
}));

vi.mock("../../lib/api", () => ({
  getTools: mockGetTools,
  toggleTool: mockToggleTool,
}));

vi.mock("../../lib/log", () => ({
  log: { error: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

describe("useToolsStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    act(() => {
      useToolsStore.setState({
        tools: [],
        toolsLoaded: false,
        toolsLoading: false,
        toolsError: null,
      });
    });
  });

  it("initializes with empty tools", () => {
    expect(useToolsStore.getState().tools).toEqual([]);
  });

  it("initializes as not loaded", () => {
    expect(useToolsStore.getState().toolsLoaded).toBe(false);
  });

  it("initializes not loading", () => {
    expect(useToolsStore.getState().toolsLoading).toBe(false);
  });

  it("initializes with null error", () => {
    expect(useToolsStore.getState().toolsError).toBeNull();
  });

  it("setTools replaces tools list and marks loaded", () => {
    const tools = [
      { name: "bash", description: "Run bash commands", enabled: true, schema: {} },
      { name: "grep", description: "Search files", enabled: false, schema: {} },
    ];
    act(() => {
      useToolsStore.getState().setTools(tools);
    });
    expect(useToolsStore.getState().tools).toHaveLength(2);
    expect(useToolsStore.getState().tools[0].name).toBe("bash");
    expect(useToolsStore.getState().toolsLoaded).toBe(true);
  });

  it("loadTools short-circuits when already loaded", async () => {
    act(() => {
      useToolsStore.setState({ toolsLoaded: true });
    });
    await act(async () => {
      await useToolsStore.getState().loadTools();
    });
    expect(mockGetTools).not.toHaveBeenCalled();
  });

  it("loadTools short-circuits when already loading", async () => {
    act(() => {
      useToolsStore.setState({ toolsLoading: true });
    });
    await act(async () => {
      await useToolsStore.getState().loadTools();
    });
    expect(mockGetTools).not.toHaveBeenCalled();
  });

  it("loadTools fetches tools on first call", async () => {
    const mockTools = [
      { name: "bash", description: "Run bash", enabled: true, schema: {} },
      { name: "grep", description: "Search", enabled: true, schema: {} },
    ];
    mockGetTools.mockResolvedValue(mockTools);

    await act(async () => {
      await useToolsStore.getState().loadTools();
    });

    expect(mockGetTools).toHaveBeenCalledTimes(1);
    expect(useToolsStore.getState().tools).toHaveLength(2);
    expect(useToolsStore.getState().tools[0].name).toBe("bash");
    expect(useToolsStore.getState().toolsLoaded).toBe(true);
    expect(useToolsStore.getState().toolsLoading).toBe(false);
  });

  it("loadTools handles errors", async () => {
    mockGetTools.mockRejectedValue(new Error("Failed to load"));

    await act(async () => {
      await useToolsStore.getState().loadTools();
    });

    expect(useToolsStore.getState().toolsError).toBe("Failed to load");
    expect(useToolsStore.getState().toolsLoading).toBe(false);
  });

  it("loadTools sets loading state during fetch", async () => {
    mockGetTools.mockImplementation(() => new Promise(() => {}));

    const promise = act(async () => {
      await useToolsStore.getState().loadTools();
    });

    expect(useToolsStore.getState().toolsLoading).toBe(true);
    expect(useToolsStore.getState().toolsError).toBeNull();

    void promise;
  });

  it("toggleTool toggles enabled state", async () => {
    act(() => {
      useToolsStore.setState({
        tools: [{ name: "bash", description: "Run bash", enabled: true, schema: {} }],
      });
    });
    mockToggleTool.mockResolvedValue(undefined);

    await act(async () => {
      await useToolsStore.getState().toggleTool("bash");
    });

    const tool = useToolsStore.getState().tools[0];
    expect(tool.enabled).toBe(false);
    expect(mockToggleTool).toHaveBeenCalledWith("bash", false);
  });

  it("toggleTool reverts on API error", async () => {
    act(() => {
      useToolsStore.setState({
        tools: [{ name: "bash", description: "Run bash", enabled: true, schema: {} }],
      });
    });
    mockToggleTool.mockRejectedValue(new Error("API error"));

    await act(async () => {
      await useToolsStore.getState().toggleTool("bash");
    });

    const tool = useToolsStore.getState().tools[0];
    expect(tool.enabled).toBe(true); // reverted to original
  });

  it("toggleTool does nothing for unknown tool", async () => {
    act(() => {
      useToolsStore.setState({
        tools: [{ name: "bash", description: "Run bash", enabled: true, schema: {} }],
      });
    });
    mockToggleTool.mockResolvedValue(undefined);

    await act(async () => {
      await useToolsStore.getState().toggleTool("unknown");
    });

    expect(mockToggleTool).not.toHaveBeenCalled();
  });
});
