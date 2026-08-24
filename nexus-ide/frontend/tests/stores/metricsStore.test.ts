import { describe, expect, it, vi, beforeEach } from "vitest";
import { act } from "@testing-library/react";
import { useMetricsStore } from "../../stores/metricsStore";

const { mockGetMetricsHistory } = vi.hoisted(() => ({
  mockGetMetricsHistory: vi.fn(),
}));

vi.mock("../../lib/api", () => ({
  apiUrl: (path: string) => `/api${path}`,
  getMetricsHistory: mockGetMetricsHistory,
}));

vi.mock("../../lib/auth", () => ({
  authenticatedFetch: vi.fn(),
  authHeaders: vi.fn(() => ({})),
  getAccessToken: vi.fn(() => null),
  isAuthenticated: vi.fn(() => false),
  isAutoLoginEnabled: vi.fn(() => false),
  autoLoginDev: vi.fn(),
}));

vi.mock("../../lib/log", () => ({
  log: { error: vi.fn(), warn: vi.fn(), info: vi.fn(), debug: vi.fn() },
}));

describe("useMetricsStore", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    act(() => {
      useMetricsStore.setState({
        metrics: null,
        history: [],
        backendOnline: false,
        connectionStatus: "connecting",
        connectionMode: "none",
        lastUpdate: "—",
        historySeries: {},
        historyLoading: false,
        historyError: null,
        alerts: [],
        alertsError: null,
        alertsLoading: false,
        guardian: null,
        guardianError: null,
        guardianLoading: false,
      });
    });
  });

  describe("initial state", () => {
    it("starts with null metrics", () => {
      expect(useMetricsStore.getState().metrics).toBeNull();
    });

    it("starts with empty history", () => {
      expect(useMetricsStore.getState().history).toEqual([]);
    });

    it("starts with backendOffline", () => {
      expect(useMetricsStore.getState().backendOnline).toBe(false);
    });

    it("starts with connecting status", () => {
      expect(useMetricsStore.getState().connectionStatus).toBe("connecting");
    });

    it("starts with none connection mode", () => {
      expect(useMetricsStore.getState().connectionMode).toBe("none");
    });

    it("starts with empty historySeries", () => {
      expect(useMetricsStore.getState().historySeries).toEqual({});
    });

    it("starts with empty alerts", () => {
      expect(useMetricsStore.getState().alerts).toEqual([]);
    });

    it("starts with null guardian", () => {
      expect(useMetricsStore.getState().guardian).toBeNull();
    });
  });

  describe("_setMetrics", () => {
    it("sets metrics and marks backend online", () => {
      const metrics = {
        tokens_per_second: 100,
        active_model: "gpt-4",
        active_sessions: 2,
        queue_depth: 0,
        ram_used_bytes: 1000,
        ram_total_bytes: 2000,
        ram_percent: 50,
        cpu_percent: 25,
        disk_used_bytes: 500,
        disk_total_bytes: 1000,
        disk_percent: 50,
        uptime_seconds: 3600,
        requests_total: 100,
        requests_successful: 90,
        requests_failed: 10,
        avg_latency_ms: 50,
        timestamp: Date.now(),
      };
      act(() => {
        useMetricsStore.getState()._setMetrics(metrics as any);
      });
      expect(useMetricsStore.getState().metrics).toEqual(metrics);
      expect(useMetricsStore.getState().backendOnline).toBe(true);
      expect(useMetricsStore.getState().connectionStatus).toBe("connected");
    });

    it("sets degraded status when all requests fail", () => {
      const metrics = {
        tokens_per_second: 100,
        active_model: "gpt-4",
        active_sessions: 0,
        queue_depth: 0,
        ram_used_bytes: 1000,
        ram_total_bytes: 2000,
        ram_percent: 50,
        cpu_percent: 25,
        disk_used_bytes: 500,
        disk_total_bytes: 1000,
        disk_percent: 50,
        uptime_seconds: 3600,
        requests_total: 100,
        requests_successful: 0,
        requests_failed: 100,
        avg_latency_ms: 50,
        timestamp: Date.now(),
      };
      act(() => {
        useMetricsStore.getState()._setMetrics(metrics as any);
      });
      expect(useMetricsStore.getState().connectionStatus).toBe("degraded");
    });

    it("sets connected status when requests have some success", () => {
      const metrics = {
        tokens_per_second: 100,
        active_model: "gpt-4",
        active_sessions: 0,
        queue_depth: 0,
        ram_used_bytes: 1000,
        ram_total_bytes: 2000,
        ram_percent: 50,
        cpu_percent: 25,
        disk_used_bytes: 500,
        disk_total_bytes: 1000,
        disk_percent: 50,
        uptime_seconds: 3600,
        requests_total: 0,
        requests_successful: 0,
        requests_failed: 0,
        avg_latency_ms: 50,
        timestamp: Date.now(),
      };
      act(() => {
        useMetricsStore.getState()._setMetrics(metrics as any);
      });
      expect(useMetricsStore.getState().connectionStatus).toBe("connected");
    });

    it("appends to history with max 100 entries", () => {
      const metrics = {
        tokens_per_second: 100,
        active_model: "gpt-4",
        active_sessions: 0,
        queue_depth: 0,
        ram_used_bytes: 1000,
        ram_total_bytes: 2000,
        ram_percent: 50,
        cpu_percent: 25,
        disk_used_bytes: 500,
        disk_total_bytes: 1000,
        disk_percent: 50,
        uptime_seconds: 3600,
        requests_total: 0,
        requests_successful: 0,
        requests_failed: 0,
        avg_latency_ms: 50,
        timestamp: Date.now(),
      };
      for (let i = 0; i < 150; i++) {
        act(() => {
          useMetricsStore.getState()._setMetrics({ ...metrics, timestamp: i });
        });
      }
      expect(useMetricsStore.getState().history).toHaveLength(100);
    });
  });

  describe("_setBackendOnline", () => {
    it("sets backendOnline", () => {
      act(() => {
        useMetricsStore.getState()._setBackendOnline(true);
      });
      expect(useMetricsStore.getState().backendOnline).toBe(true);
    });
  });

  describe("_setConnectionStatus", () => {
    it("sets connectionStatus", () => {
      act(() => {
        useMetricsStore.getState()._setConnectionStatus("offline");
      });
      expect(useMetricsStore.getState().connectionStatus).toBe("offline");
    });
  });

  describe("_setConnectionMode", () => {
    it("sets connectionMode", () => {
      act(() => {
        useMetricsStore.getState()._setConnectionMode("sse");
      });
      expect(useMetricsStore.getState().connectionMode).toBe("sse");
    });
  });

  describe("loadHistory", () => {
    it("loads history series on success", async () => {
      mockGetMetricsHistory.mockResolvedValue([
        { timestamp: 1000, value: 10 },
        { timestamp: 2000, value: 20 },
      ]);

      await act(async () => {
        await useMetricsStore.getState().loadHistory("cpu_percent", 3600);
      });

      expect(useMetricsStore.getState().historySeries["cpu_percent"]).toHaveLength(2);
      expect(useMetricsStore.getState().historySeries["cpu_percent"][0]).toEqual({ t: 1000, v: 10 });
      expect(useMetricsStore.getState().historyLoading).toBe(false);
      expect(useMetricsStore.getState().historyError).toBeNull();
    });

    it("handles error from API", async () => {
      mockGetMetricsHistory.mockRejectedValue(new Error("Fetch failed"));

      await act(async () => {
        await useMetricsStore.getState().loadHistory("cpu_percent", 3600);
      });

      expect(useMetricsStore.getState().historyError).toBe("Fetch failed");
      expect(useMetricsStore.getState().historyLoading).toBe(false);
    });

    it("sets loading state during fetch", async () => {
      mockGetMetricsHistory.mockImplementation(() => new Promise(() => {}));

      const promise = act(async () => {
        await useMetricsStore.getState().loadHistory("cpu_percent");
      });

      expect(useMetricsStore.getState().historyLoading).toBe(true);

      void promise;
    });

    it("normalizes different history formats", async () => {
      // Test with {t, v} format
      mockGetMetricsHistory.mockResolvedValue([{ t: 100, v: 50 }]);

      await act(async () => {
        await useMetricsStore.getState().loadHistory("metric1");
      });

      expect(useMetricsStore.getState().historySeries["metric1"]).toEqual([{ t: 100, v: 50 }]);
    });

    it("normalizes {timestamp, value} format", async () => {
      mockGetMetricsHistory.mockResolvedValue([{ timestamp: 200, value: 75 }]);

      await act(async () => {
        await useMetricsStore.getState().loadHistory("metric2");
      });

      expect(useMetricsStore.getState().historySeries["metric2"]).toEqual([{ t: 200, v: 75 }]);
    });

    it("handles wrapper object with data array", async () => {
      mockGetMetricsHistory.mockResolvedValue({ data: [{ timestamp: 300, value: 60 }] });

      await act(async () => {
        await useMetricsStore.getState().loadHistory("metric3");
      });

      expect(useMetricsStore.getState().historySeries["metric3"]).toEqual([{ t: 300, v: 60 }]);
    });

    it("returns empty series for invalid data", async () => {
      mockGetMetricsHistory.mockResolvedValue("invalid string data");

      await act(async () => {
        await useMetricsStore.getState().loadHistory("metric4");
      });

      expect(useMetricsStore.getState().historySeries["metric4"]).toEqual([]);
    });

    it("skips invalid points with NaN values", async () => {
      mockGetMetricsHistory.mockResolvedValue([{ timestamp: "invalid", value: 10 }, { timestamp: 200, value: 20 }]);

      await act(async () => {
        await useMetricsStore.getState().loadHistory("metric5");
      });

      expect(useMetricsStore.getState().historySeries["metric5"]).toEqual([{ t: 200, v: 20 }]);
    });
  });

  describe("clearHistory", () => {
    it("clears specific metric history", () => {
      act(() => {
        useMetricsStore.setState({
          historySeries: { metric1: [{ t: 1, v: 1 }], metric2: [{ t: 2, v: 2 }] },
        });
      });

      act(() => {
        useMetricsStore.getState().clearHistory("metric1");
      });

      expect(useMetricsStore.getState().historySeries["metric1"]).toBeUndefined();
      expect(useMetricsStore.getState().historySeries["metric2"]).toBeDefined();
    });

    it("clears all history when no metric specified", () => {
      act(() => {
        useMetricsStore.setState({
          historySeries: { metric1: [{ t: 1, v: 1 }], metric2: [{ t: 2, v: 2 }] },
        });
      });

      act(() => {
        useMetricsStore.getState().clearHistory();
      });

      expect(useMetricsStore.getState().historySeries).toEqual({});
    });
  });

  describe("alerts", () => {
    it("setAlerts stores array", () => {
      act(() => {
        useMetricsStore.getState().setAlerts([{ type: "error", msg: "test" }]);
      });
      expect(useMetricsStore.getState().alerts).toHaveLength(1);
    });

    it("setAlerts stores empty array for non-array input", () => {
      act(() => {
        useMetricsStore.getState().setAlerts(null as any);
      });
      expect(useMetricsStore.getState().alerts).toEqual([]);
    });

    it("setAlertsError sets error message", () => {
      act(() => {
        useMetricsStore.getState().setAlertsError("Failed to load alerts");
      });
      expect(useMetricsStore.getState().alertsError).toBe("Failed to load alerts");
    });

    it("setAlertsLoading sets loading state", () => {
      act(() => {
        useMetricsStore.getState().setAlertsLoading(true);
      });
      expect(useMetricsStore.getState().alertsLoading).toBe(true);
    });
  });

  describe("guardian", () => {
    it("setGuardian stores data", () => {
      act(() => {
        useMetricsStore.getState().setGuardian({ running: true, pending: 3 });
      });
      expect(useMetricsStore.getState().guardian?.running).toBe(true);
      expect(useMetricsStore.getState().guardian?.pending).toBe(3);
    });

    it("setGuardianError sets error message", () => {
      act(() => {
        useMetricsStore.getState().setGuardianError("Guardian error");
      });
      expect(useMetricsStore.getState().guardianError).toBe("Guardian error");
    });

    it("setGuardianLoading sets loading state", () => {
      act(() => {
        useMetricsStore.getState().setGuardianLoading(true);
      });
      expect(useMetricsStore.getState().guardianLoading).toBe(true);
    });
  });
});
