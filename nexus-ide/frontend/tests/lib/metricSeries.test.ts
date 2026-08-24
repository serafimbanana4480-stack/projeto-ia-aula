import { describe, expect, it } from "vitest";
import {
  seriesOf,
  deltaOf,
  approxP95,
  successRate,
  totalTokens,
} from "../../lib/metricSeries";
import type { SystemMetrics } from "../../stores/metricsStore";

function makeMetric(overrides: Partial<SystemMetrics> = {}): SystemMetrics {
  return {
    tokens_per_second: 0,
    active_model: "default",
    active_sessions: 0,
    queue_depth: 0,
    ram_used_bytes: 0,
    ram_total_bytes: 0,
    ram_percent: 0,
    cpu_percent: 0,
    disk_used_bytes: 0,
    disk_total_bytes: 0,
    disk_percent: 0,
    uptime_seconds: 0,
    requests_total: 0,
    requests_successful: 0,
    requests_failed: 0,
    avg_latency_ms: 0,
    ...overrides,
  } as unknown as SystemMetrics;
}

describe("lib/metricSeries", () => {
  describe("seriesOf", () => {
    it("extracts numeric values from history", () => {
      const history = [
        makeMetric({ cpu_percent: 10 }),
        makeMetric({ cpu_percent: 20 }),
        makeMetric({ cpu_percent: 30 }),
      ];
      const result = seriesOf(history, (m) => m.cpu_percent);
      expect(result).toEqual([10, 20, 30]);
    });

    it("drops null/undefined/NaN values", () => {
      const history = [
        makeMetric({ cpu_percent: 10 }),
        makeMetric({ cpu_percent: null as any }),
        makeMetric({ cpu_percent: 20 }),
        makeMetric({ cpu_percent: NaN as any }),
        makeMetric({ cpu_percent: undefined as any }),
        makeMetric({ cpu_percent: 30 }),
      ];
      const result = seriesOf(history, (m) => m.cpu_percent);
      expect(result).toEqual([10, 20, 30]);
    });

    it("returns empty for empty history", () => {
      expect(seriesOf([], (m) => m.cpu_percent)).toEqual([]);
    });

    it("respects the limit parameter", () => {
      const history = Array.from({ length: 50 }, (_, i) => makeMetric({ cpu_percent: i }));
      const result = seriesOf(history, (m) => m.cpu_percent, 10);
      expect(result).toHaveLength(10);
      expect(result[0]).toBe(40);
    });

    it("defaults limit to 40", () => {
      const history = Array.from({ length: 60 }, (_, i) => makeMetric({ cpu_percent: i }));
      const result = seriesOf(history, (m) => m.cpu_percent);
      expect(result).toHaveLength(40);
      expect(result[0]).toBe(20);
    });
  });

  describe("deltaOf", () => {
    it("returns null when series has fewer than 6 points", () => {
      expect(deltaOf([1, 2, 3, 4, 5])).toBeNull();
    });

    it("returns null for empty series", () => {
      expect(deltaOf([])).toBeNull();
    });

    it("returns null when baseline is zero", () => {
      const series = Array(10).fill(0);
      series[9] = 10;
      expect(deltaOf(series)).toBeNull();
    });

    it("calculates fractional change between halves", () => {
      const series = [10, 10, 10, 10, 10, 10, 20, 20, 20, 20, 20, 20];
      const result = deltaOf(series);
      expect(result).toBe(1.0);
    });

    it("returns 0 when older and newer halves have same mean", () => {
      const series = [5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5];
      const result = deltaOf(series);
      expect(result).toBe(0);
    });

    it("handles negative change", () => {
      const series = [20, 20, 20, 20, 20, 20, 10, 10, 10, 10, 10, 10];
      const result = deltaOf(series);
      expect(result).toBe(-0.5);
    });
  });

  describe("approxP95", () => {
    it("returns null for series with fewer than 3 values", () => {
      expect(approxP95([1])).toBeNull();
      expect(approxP95([1, 2])).toBeNull();
    });

    it("returns null for empty series", () => {
      expect(approxP95([])).toBeNull();
    });

    it("returns null when all values are 0 or negative", () => {
      expect(approxP95([0, 0, 0])).toBeNull();
    });

    it("filters out non-finite values", () => {
      const result = approxP95([1, 2, NaN, 3, Infinity, 5]);
      expect(result).toBe(5);
    });

    it("approximates 95th percentile from sorted values", () => {
      const series = Array.from({ length: 100 }, (_, i) => i + 1);
      const result = approxP95(series);
      expect(result).toBe(95);
    });

    it("handles small series", () => {
      const result = approxP95([10, 20, 30]);
      // clean length = 3, sorted = [10, 20, 30]
      // index = min(2, ceil(3*0.95)-1) = min(2, 2) = 2
      // sorted[2] = 30
      expect(result).toBe(30);
    });
  });

  describe("successRate", () => {
    it("returns null when metrics is null", () => {
      expect(successRate(null)).toBeNull();
    });

    it("returns null when total requests is 0", () => {
      expect(successRate(makeMetric({ requests_total: 0 }))).toBeNull();
    });

    it("returns null when total is undefined", () => {
      expect(successRate(makeMetric({}) as any)).toBeNull();
    });

    it("calculates success rate as fraction", () => {
      const metrics = makeMetric({ requests_total: 100, requests_successful: 75 });
      expect(successRate(metrics)).toBe(0.75);
    });

    it("returns 1.0 when all requests succeed", () => {
      const metrics = makeMetric({ requests_total: 50, requests_successful: 50 });
      expect(successRate(metrics)).toBe(1.0);
    });

    it("returns 0.0 when no requests succeed", () => {
      const metrics = makeMetric({ requests_total: 50, requests_successful: 0 });
      expect(successRate(metrics)).toBe(0);
    });
  });

  describe("totalTokens", () => {
    it("returns null when metrics is null", () => {
      expect(totalTokens(null)).toBeNull();
    });

    it("returns null when message_stats is undefined", () => {
      expect(totalTokens(makeMetric({}))).toBeNull();
    });

    it("returns null when both token fields are null", () => {
      const metrics = makeMetric({
        message_stats: { tokens_out_total: null, tokens_in_total: null } as any,
      } as any);
      expect(totalTokens(metrics)).toBeNull();
    });

    it("sums input and output tokens", () => {
      const metrics = makeMetric({
        message_stats: { tokens_out_total: 500, tokens_in_total: 300 },
      } as any);
      expect(totalTokens(metrics)).toBe(800);
    });

    it("handles one null token field", () => {
      const metrics = makeMetric({
        message_stats: { tokens_out_total: 500, tokens_in_total: null } as any,
      } as any);
      expect(totalTokens(metrics)).toBe(500);
    });
  });
});
