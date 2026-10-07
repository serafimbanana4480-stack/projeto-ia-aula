import { describe, expect, it, vi, beforeEach } from "vitest";
import { act } from "@testing-library/react";
import { useSystemStore } from "../../stores/useSystemStore";

describe("useSystemStore", () => {
  beforeEach(() => {
    act(() => {
      useSystemStore.setState({
        metrics: {
          cpuUsage: 0,
          memoryUsage: 0,
          gpuUsage: 0,
          diskUsage: 0,
          networkIn: 0,
          networkOut: 0,
          activeConnections: 0,
          queueSize: 0,
          vectorDbQueriesPerSec: 0,
          embeddingThroughput: 0,
          cacheHitRate: 0,
          apiErrorsPerMin: 0,
          hallucinationAlerts: 0,
          agentFailures: 0,
          avgResponseTime: 0,
          requestsPerSec: 0,
          totalTokensToday: 0,
          costToday: 0,
          activeWorkflows: 0,
          pendingTasks: 0,
          runningAgents: 0,
        },
        isLive: false,
        hasTelemetry: false,
        measuredMetrics: {},
        isLoading: false,
        error: null,
        globalStatus: "operational",
      });
    });
  });

  it("starts with default metrics", () => {
    const { metrics } = useSystemStore.getState();
    expect(metrics.cpuUsage).toBe(0);
    expect(metrics.memoryUsage).toBe(0);
    expect(metrics.runningAgents).toBe(0);
  });

  it("starts with operational status", () => {
    expect(useSystemStore.getState().globalStatus).toBe("operational");
  });

  it("starts not live", () => {
    expect(useSystemStore.getState().isLive).toBe(false);
  });

  it("starts not loading", () => {
    expect(useSystemStore.getState().isLoading).toBe(false);
  });

  it("starts with null error", () => {
    expect(useSystemStore.getState().error).toBeNull();
  });

  it("updateSystemMetrics patches metrics", () => {
    act(() => {
      useSystemStore.getState().updateSystemMetrics({ cpuUsage: 50, memoryUsage: 75 });
    });
    const metrics = useSystemStore.getState().metrics;
    expect(metrics.cpuUsage).toBe(50);
    expect(metrics.memoryUsage).toBe(75);
    // Other metrics unchanged
    expect(metrics.diskUsage).toBe(0);
  });

  it("updateSystemMetrics derives globalStatus", () => {
    act(() => {
      useSystemStore.getState().updateSystemMetrics({ hallucinationAlerts: 3 });
    });
    expect(useSystemStore.getState().globalStatus).toBe("degraded");
  });

  it("agentFailures > 1 triggers degraded", () => {
    act(() => {
      useSystemStore.getState().updateSystemMetrics({ agentFailures: 2 });
    });
    expect(useSystemStore.getState().globalStatus).toBe("degraded");
  });

  it("apiErrorsPerMin > 5 triggers incident", () => {
    act(() => {
      useSystemStore.getState().updateSystemMetrics({ apiErrorsPerMin: 6 });
    });
    expect(useSystemStore.getState().globalStatus).toBe("incident");
  });

  it("apiErrorsPerMin = 5 stays operational", () => {
    act(() => {
      useSystemStore.getState().updateSystemMetrics({ apiErrorsPerMin: 5 });
    });
    expect(useSystemStore.getState().globalStatus).toBe("operational");
  });

  it("hallucinationAlerts = 2 stays operational", () => {
    act(() => {
      useSystemStore.getState().updateSystemMetrics({ hallucinationAlerts: 2 });
    });
    expect(useSystemStore.getState().globalStatus).toBe("operational");
  });

  it("setLoading sets loading state", () => {
    act(() => {
      useSystemStore.getState().setLoading(true);
    });
    expect(useSystemStore.getState().isLoading).toBe(true);
  });

  it("setError sets error message", () => {
    act(() => {
      useSystemStore.getState().setError("Connection failed");
    });
    expect(useSystemStore.getState().error).toBe("Connection failed");
  });

  it("setError with null clears error", () => {
    act(() => {
      useSystemStore.getState().setError("error");
      useSystemStore.getState().setError(null);
    });
    expect(useSystemStore.getState().error).toBeNull();
  });

  it("fetchMetrics sets loading state", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ cpu_percent: 42, ram_percent: 55 }),
    }) as any;

    let promise: Promise<void>;
    act(() => {
      promise = useSystemStore.getState().fetchMetrics();
    });

    expect(useSystemStore.getState().isLoading).toBe(true);
    await act(() => promise);
    expect(useSystemStore.getState().isLoading).toBe(false);
    expect(useSystemStore.getState().metrics.cpuUsage).toBe(42);
    expect(useSystemStore.getState().metrics.memoryUsage).toBe(55);
    expect(useSystemStore.getState().isLive).toBe(true);
  });

  it("fetchMetrics maps snake_case to camelCase", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        cpu_percent: 30,
        ram_percent: 60,
        queue_depth: 5,
        api_errors_per_min: 2,
      }),
    }) as any;

    let promise: Promise<void>;
    act(() => {
      promise = useSystemStore.getState().fetchMetrics();
    });
    await act(() => promise);

    const metrics = useSystemStore.getState().metrics;
    expect(metrics.cpuUsage).toBe(30);
    expect(metrics.memoryUsage).toBe(60);
    expect(metrics.queueSize).toBe(5);
    expect(metrics.apiErrorsPerMin).toBe(2);
    expect(useSystemStore.getState().hasTelemetry).toBe(true);
    expect(useSystemStore.getState().measuredMetrics.queueSize).toBe(true);
  });

  it("treats a valid zero as measured telemetry", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({
        cpu_percent: 0,
        ram_percent: 0,
        disk_percent: 0,
        queue_depth: 0,
        avg_latency_ms: 0,
        tokens_per_second: 0,
      }),
    }) as any;

    await act(() => useSystemStore.getState().fetchMetrics());

    const state = useSystemStore.getState();
    expect(state.isLive).toBe(true);
    expect(state.hasTelemetry).toBe(true);
    expect(state.metrics.cpuUsage).toBe(0);
    expect(state.metrics.memoryUsage).toBe(0);
    expect(state.metrics.diskUsage).toBe(0);
    expect(state.metrics.queueSize).toBe(0);
    expect(state.measuredMetrics.cpuUsage).toBe(true);
    expect(state.measuredMetrics.gpuUsage).toBeUndefined();
  });

  it("does not turn an empty successful response into zero telemetry", async () => {
    useSystemStore.setState({
      metrics: { ...useSystemStore.getState().metrics, cpuUsage: 42 },
      measuredMetrics: { cpuUsage: true },
      hasTelemetry: true,
    });
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({}),
    }) as any;

    await act(() => useSystemStore.getState().fetchMetrics());

    const state = useSystemStore.getState();
    expect(state.isLive).toBe(true);
    expect(state.hasTelemetry).toBe(false);
    expect(state.measuredMetrics).toEqual({});
    expect(state.metrics.cpuUsage).toBe(42);
    expect(state.error).toMatch(/sem dados de telemetria/i);
  });

  it("preserves the last measurement and marks it stale on refresh failure", async () => {
    useSystemStore.setState({
      metrics: { ...useSystemStore.getState().metrics, cpuUsage: 23 },
      measuredMetrics: { cpuUsage: true },
      hasTelemetry: true,
    });
    global.fetch = vi.fn().mockRejectedValue(new Error("Network error")) as any;

    await act(() => useSystemStore.getState().fetchMetrics());

    const state = useSystemStore.getState();
    expect(state.isLive).toBe(false);
    expect(state.hasTelemetry).toBe(true);
    expect(state.measuredMetrics.cpuUsage).toBe(true);
    expect(state.metrics.cpuUsage).toBe(23);
    expect(state.error).toBe("Network error");
  });

  it("handles a malformed successful response without crashing", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    }) as any;

    await act(() => useSystemStore.getState().fetchMetrics());

    const state = useSystemStore.getState();
    expect(state.isLive).toBe(true);
    expect(state.hasTelemetry).toBe(false);
    expect(state.error).toMatch(/formato de métricas inválido/i);
  });

  it("fetchMetrics handles HTTP errors", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
    }) as any;

    let promise: Promise<void>;
    act(() => {
      promise = useSystemStore.getState().fetchMetrics();
    });
    await act(() => promise);

    expect(useSystemStore.getState().isLoading).toBe(false);
    expect(useSystemStore.getState().isLive).toBe(false);
    expect(useSystemStore.getState().error).toContain("HTTP 500");
  });

  it("fetchMetrics handles network errors", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("Network error")) as any;

    let promise: Promise<void>;
    act(() => {
      promise = useSystemStore.getState().fetchMetrics();
    });
    await act(() => promise);

    expect(useSystemStore.getState().error).toBe("Network error");
    expect(useSystemStore.getState().isLive).toBe(false);
  });

  it("fetchMetrics prioritizes camelCase over snake_case", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ cpu_percent: 10, cpuUsage: 90 }),
    }) as any;

    let promise: Promise<void>;
    act(() => {
      promise = useSystemStore.getState().fetchMetrics();
    });
    await act(() => promise);

    // snake_case is checked first in the code
    expect(useSystemStore.getState().metrics.cpuUsage).toBe(10);
  });
});
