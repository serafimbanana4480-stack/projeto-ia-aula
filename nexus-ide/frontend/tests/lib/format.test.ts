import { describe, expect, it, vi } from "vitest";
import {
  EMPTY,
  formatCompact,
  formatContext,
  formatLatency,
  formatUsd,
  formatPricePer1M,
  formatUptime,
  formatPercent,
  formatRelativeTime,
  formatBytes,
} from "../../lib/format";

describe("lib/format", () => {
  describe("EMPTY", () => {
    it("is an em-dash", () => {
      expect(EMPTY).toBe("—");
    });
  });

  describe("formatCompact", () => {
    it("handles null", () => {
      expect(formatCompact(null)).toBe(EMPTY);
    });
    it("handles undefined", () => {
      expect(formatCompact(undefined)).toBe(EMPTY);
    });
    it("handles NaN", () => {
      expect(formatCompact(NaN)).toBe(EMPTY);
    });
    it("formats thousands as K", () => {
      expect(formatCompact(1500)).toBe("1.5K");
    });
    it("formats millions as M", () => {
      expect(formatCompact(1_500_000)).toBe("1.5M");
    });
    it("formats billions as B", () => {
      expect(formatCompact(1_500_000_000)).toBe("1.5B");
    });
    it("formats small numbers with locale", () => {
      expect(formatCompact(1234)).toBe("1.2K");
    });
    it("formats zero", () => {
      expect(formatCompact(0)).toBe("0");
    });
    it("formats negative numbers", () => {
      expect(formatCompact(-1500)).toBe("-1.5K");
    });
    it("formats negative millions", () => {
      expect(formatCompact(-2_500_000)).toBe("-2.5M");
    });
  });

  describe("formatContext", () => {
    it("returns EMPTY for null", () => {
      expect(formatContext(null)).toBe(EMPTY);
    });
    it("returns EMPTY for undefined", () => {
      expect(formatContext(undefined)).toBe(EMPTY);
    });
    it("returns EMPTY for 0", () => {
      expect(formatContext(0)).toBe(EMPTY);
    });
    it("formats tokens in K", () => {
      expect(formatContext(8000)).toBe("8K");
    });
    it("formats rounded K", () => {
      expect(formatContext(8500)).toBe("9K");
    });
    it("formats millions as M with integer", () => {
      expect(formatContext(2_000_000)).toBe("2M");
    });
    it("formats millions as M with decimal", () => {
      expect(formatContext(1_500_000)).toBe("1.5M");
    });
  });

  describe("formatLatency", () => {
    it("returns EMPTY for null", () => {
      expect(formatLatency(null)).toBe(EMPTY);
    });
    it("returns EMPTY for undefined", () => {
      expect(formatLatency(undefined)).toBe(EMPTY);
    });
    it("returns EMPTY for 0", () => {
      expect(formatLatency(0)).toBe(EMPTY);
    });
    it("returns EMPTY for negative", () => {
      expect(formatLatency(-1)).toBe(EMPTY);
    });
    it("returns EMPTY for NaN", () => {
      expect(formatLatency(NaN)).toBe(EMPTY);
    });
    it("formats milliseconds", () => {
      expect(formatLatency(820)).toBe("820 ms");
    });
    it("formats seconds", () => {
      expect(formatLatency(2400)).toBe("2.40 s");
    });
    it("formats exactly 1000ms as 1.00 s", () => {
      expect(formatLatency(1000)).toBe("1.00 s");
    });
  });

  describe("formatUsd", () => {
    it("returns EMPTY for null", () => {
      expect(formatUsd(null)).toBe(EMPTY);
    });
    it("returns EMPTY for undefined", () => {
      expect(formatUsd(undefined)).toBe(EMPTY);
    });
    it("returns EMPTY for NaN", () => {
      expect(formatUsd(NaN)).toBe(EMPTY);
    });
    it("formats zero as $0", () => {
      expect(formatUsd(0)).toBe("$0");
    });
    it("formats sub-cent with 4 decimals", () => {
      expect(formatUsd(0.005)).toBe("$0.0050");
    });
    it("formats sub-dollar with 3 decimals", () => {
      expect(formatUsd(0.5)).toBe("$0.500");
    });
    it("formats dollar amounts with 2 decimals", () => {
      expect(formatUsd(1.5)).toBe("$1.50");
    });
    it("formats large amounts", () => {
      expect(formatUsd(12345.67)).toBe("$12345.67");
    });
    it("formats negative amounts", () => {
      expect(formatUsd(-1.5)).toBe("$-1.50");
    });
  });

  describe("formatPricePer1M", () => {
    it("returns EMPTY for null", () => {
      expect(formatPricePer1M(null)).toBe(EMPTY);
    });
    it("returns EMPTY for NaN", () => {
      expect(formatPricePer1M(NaN)).toBe(EMPTY);
    });
    it("formats zero as grátis", () => {
      expect(formatPricePer1M(0)).toBe("grátis");
    });
    it("formats sub-1 with 2 decimals", () => {
      expect(formatPricePer1M(0.5)).toBe("$0.50");
    });
    it("formats 1 or above with 2 decimals", () => {
      expect(formatPricePer1M(5)).toBe("$5.00");
    });
    it("formats large prices", () => {
      expect(formatPricePer1M(15.5)).toBe("$15.50");
    });
  });

  describe("formatUptime", () => {
    it("returns EMPTY for null", () => {
      expect(formatUptime(null)).toBe(EMPTY);
    });
    it("returns EMPTY for undefined", () => {
      expect(formatUptime(undefined)).toBe(EMPTY);
    });
    it("returns EMPTY for NaN", () => {
      expect(formatUptime(NaN)).toBe(EMPTY);
    });
    it("returns EMPTY for negative", () => {
      expect(formatUptime(-1)).toBe(EMPTY);
    });
    it("formats seconds", () => {
      expect(formatUptime(45)).toBe("45s");
    });
    it("formats minutes and seconds", () => {
      expect(formatUptime(750)).toBe("12m 30s");
    });
    it("formats hours", () => {
      expect(formatUptime(3600)).toBe("1.0h");
    });
    it("formats days", () => {
      expect(formatUptime(86400)).toBe("1.0d");
    });
    it("formats zero", () => {
      expect(formatUptime(0)).toBe("0s");
    });
  });

  describe("formatPercent", () => {
    it("returns EMPTY for null", () => {
      expect(formatPercent(null)).toBe(EMPTY);
    });
    it("returns EMPTY for undefined", () => {
      expect(formatPercent(undefined)).toBe(EMPTY);
    });
    it("returns EMPTY for NaN", () => {
      expect(formatPercent(NaN)).toBe(EMPTY);
    });
    it("formats fraction to percent", () => {
      expect(formatPercent(0.87)).toBe("87.0%");
    });
    it("formats with custom digits", () => {
      expect(formatPercent(0.876, { digits: 2 })).toBe("87.60%");
    });
    it("formats alreadyPercent value", () => {
      expect(formatPercent(87, { alreadyPercent: true })).toBe("87.0%");
    });
    it("formats alreadyPercent with custom digits", () => {
      expect(formatPercent(87.5, { alreadyPercent: true, digits: 0 })).toBe("88%");
    });
    it("formats zero", () => {
      expect(formatPercent(0)).toBe("0.0%");
    });
    it("formats 1.0 as 100%", () => {
      expect(formatPercent(1.0)).toBe("100.0%");
    });
  });

  describe("formatRelativeTime", () => {
    it("returns EMPTY for null", () => {
      expect(formatRelativeTime(null)).toBe(EMPTY);
    });
    it("returns EMPTY for undefined", () => {
      expect(formatRelativeTime(undefined)).toBe(EMPTY);
    });
    it("returns EMPTY for 0", () => {
      expect(formatRelativeTime(0)).toBe(EMPTY);
    });
    it("returns EMPTY for NaN", () => {
      expect(formatRelativeTime(NaN)).toBe(EMPTY);
    });
    it("returns 'agora' for recent timestamps", () => {
      const now = Date.now() / 1000;
      expect(formatRelativeTime(now)).toBe("agora");
    });
    it("formats seconds ago", () => {
      const now = Date.now() / 1000;
      const result = formatRelativeTime(now - 30);
      expect(result).toBe("30s atrás");
    });
    it("formats minutes ago", () => {
      const now = Date.now() / 1000;
      const result = formatRelativeTime(now - 120);
      expect(result).toBe("2m atrás");
    });
    it("formats hours ago", () => {
      const now = Date.now() / 1000;
      const result = formatRelativeTime(now - 7200);
      expect(result).toMatch(/2\.0h atrás|2h atrás/);
    });
    it("formats days ago", () => {
      const now = Date.now() / 1000;
      const result = formatRelativeTime(now - 86400 * 2);
      expect(result).toMatch(/2\.0d atrás|2d atrás/);
    });
    it("returns EMPTY for future timestamps", () => {
      const now = Date.now() / 1000;
      const result = formatRelativeTime(now + 100);
      expect(result).toBe(EMPTY);
    });
    it("accepts millisecond timestamps", () => {
      const now = Date.now();
      const result = formatRelativeTime(now - 30000);
      expect(result).toBe("30s atrás");
    });
  });

  describe("formatBytes", () => {
    it("returns EMPTY for null", () => {
      expect(formatBytes(null)).toBe(EMPTY);
    });
    it("returns EMPTY for undefined", () => {
      expect(formatBytes(undefined)).toBe(EMPTY);
    });
    it("returns EMPTY for 0", () => {
      expect(formatBytes(0)).toBe(EMPTY);
    });
    it("returns EMPTY for negative", () => {
      expect(formatBytes(-1)).toBe(EMPTY);
    });
    it("returns EMPTY for NaN", () => {
      expect(formatBytes(NaN)).toBe(EMPTY);
    });
    it("formats bytes", () => {
      expect(formatBytes(500)).toBe("500 B");
    });
    it("formats kilobytes", () => {
      expect(formatBytes(1024)).toBe("1.0 KB");
    });
    it("formats megabytes", () => {
      expect(formatBytes(1_048_576)).toBe("1.0 MB");
    });
    it("formats gigabytes", () => {
      expect(formatBytes(1_073_741_824)).toBe("1.0 GB");
    });
    it("formats terabytes", () => {
      expect(formatBytes(1_099_511_627_776)).toBe("1.0 TB");
    });
    it("caps at TB for very large values", () => {
      const result = formatBytes(1.5e15);
      expect(result).toContain("TB");
    });
    it("formats small KB values with decimal", () => {
      expect(formatBytes(1536)).toBe("1.5 KB");
    });
  });
});
