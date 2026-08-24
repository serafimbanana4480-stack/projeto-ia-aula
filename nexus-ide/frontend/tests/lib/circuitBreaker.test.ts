import { describe, expect, it, vi } from "vitest";
import { CircuitBreaker, getCircuitBreaker } from "../../lib/circuitBreaker";

describe("lib/circuitBreaker", () => {
  describe("CircuitBreaker", () => {
    it("executes and returns result on success", async () => {
      const cb = new CircuitBreaker({ failureThreshold: 3, recoveryTimeout: 1000, monitoringPeriod: 5000 });
      const fn = vi.fn().mockResolvedValue("success");
      const result = await cb.execute(fn);
      expect(result).toBe("success");
      expect(fn).toHaveBeenCalledTimes(1);
    });

    it("throws on failure", async () => {
      const cb = new CircuitBreaker({ failureThreshold: 3, recoveryTimeout: 1000, monitoringPeriod: 5000 });
      const fn = vi.fn().mockImplementation(() => {
        throw new Error("operation failed");
      });
      await expect(cb.execute(fn)).rejects.toThrow("operation failed");
    });

    it("opens circuit after threshold reached", async () => {
      const cb = new CircuitBreaker({ failureThreshold: 2, recoveryTimeout: 1000, monitoringPeriod: 5000 });
      const fn = vi.fn().mockRejectedValue(new Error("fail"));

      await expect(cb.execute(fn)).rejects.toThrow("fail");
      await expect(cb.execute(fn)).rejects.toThrow("fail");

      const state = cb.getState();
      expect(state.isOpen).toBe(true);
      expect(state.failureCount).toBe(2);
    });

    it("throws 'Circuit breaker is open' when circuit is open", async () => {
      const cb = new CircuitBreaker({ failureThreshold: 1, recoveryTimeout: 10000, monitoringPeriod: 5000 });
      const fn = vi.fn().mockRejectedValue(new Error("fail"));

      await expect(cb.execute(fn)).rejects.toThrow("fail");

      const state = cb.getState();
      expect(state.isOpen).toBe(true);

      await expect(cb.execute(fn)).rejects.toThrow("Circuit breaker is open");
    });

    it("transitions to half-open after recovery timeout", async () => {
      const cb = new CircuitBreaker({ failureThreshold: 1, recoveryTimeout: 50, monitoringPeriod: 5000 });
      const fn = vi.fn().mockRejectedValueOnce(new Error("fail")).mockResolvedValueOnce("recovered");

      await expect(cb.execute(fn)).rejects.toThrow("fail");
      expect(cb.getState().isOpen).toBe(true);

      // Wait for recovery timeout
      await new Promise((resolve) => setTimeout(resolve, 80));

      const result = await cb.execute(fn);
      expect(result).toBe("recovered");
      expect(cb.getState().isOpen).toBe(false);
      expect(cb.getState().failureCount).toBe(0);
    });

    it("increments failure count on failure", async () => {
      const cb = new CircuitBreaker({ failureThreshold: 5, recoveryTimeout: 10000, monitoringPeriod: 5000 });
      const fn = vi.fn().mockRejectedValue(new Error("fail"));

      await expect(cb.execute(fn)).rejects.toThrow("fail");
      await expect(cb.execute(fn)).rejects.toThrow("fail");

      const state = cb.getState();
      expect(state.failureCount).toBe(2);
    });

    it("decrements failure count on success when below threshold", async () => {
      const cb = new CircuitBreaker({ failureThreshold: 5, recoveryTimeout: 10000, monitoringPeriod: 5000 });
      const fn = vi.fn().mockRejectedValueOnce(new Error("fail")).mockResolvedValueOnce("ok");

      await expect(cb.execute(fn)).rejects.toThrow("fail");
      expect(cb.getState().failureCount).toBe(1);
      expect(cb.getState().isOpen).toBe(false);

      await cb.execute(fn);
      expect(cb.getState().failureCount).toBe(0);
      expect(cb.getState().isOpen).toBe(false);
    });

    it("records lastFailureTime on failure", async () => {
      const before = Date.now();
      const cb = new CircuitBreaker({ failureThreshold: 5, recoveryTimeout: 10000, monitoringPeriod: 5000 });
      const fn = vi.fn().mockRejectedValue(new Error("fail"));

      await expect(cb.execute(fn)).rejects.toThrow();
      const after = Date.now();

      const state = cb.getState();
      expect(state.lastFailureTime).not.toBeNull();
      expect(state.lastFailureTime!).toBeGreaterThanOrEqual(before);
      expect(state.lastFailureTime!).toBeLessThanOrEqual(after);
    });

    it("sets nextAttemptTime when opening", async () => {
      const cb = new CircuitBreaker({ failureThreshold: 1, recoveryTimeout: 5000, monitoringPeriod: 5000 });
      const fn = vi.fn().mockRejectedValue(new Error("fail"));

      const before = Date.now();
      await expect(cb.execute(fn)).rejects.toThrow("fail");
      const after = Date.now();

      const state = cb.getState();
      expect(state.nextAttemptTime).not.toBeNull();
      expect(state.nextAttemptTime!).toBeGreaterThanOrEqual(before + 5000);
      expect(state.nextAttemptTime!).toBeLessThanOrEqual(after + 5000);
    });

    it("does not open when failure count is below threshold", async () => {
      const cb = new CircuitBreaker({ failureThreshold: 3, recoveryTimeout: 10000, monitoringPeriod: 5000 });
      const fn = vi.fn().mockRejectedValue(new Error("fail"));

      await expect(cb.execute(fn)).rejects.toThrow();
      await expect(cb.execute(fn)).rejects.toThrow();

      expect(cb.getState().isOpen).toBe(false);
      expect(cb.getState().failureCount).toBe(2);
    });
  });

  describe("getCircuitBreaker", () => {
    it("creates a breaker for a new endpoint", () => {
      const cb = getCircuitBreaker("/api/test");
      expect(cb).toBeInstanceOf(CircuitBreaker);
    });

    it("returns the same breaker for the same endpoint", () => {
      const cb1 = getCircuitBreaker("/api/same");
      const cb2 = getCircuitBreaker("/api/same");
      expect(cb1).toBe(cb2);
    });

    it("returns different breakers for different endpoints", () => {
      const cb1 = getCircuitBreaker("/api/endpoint-a");
      const cb2 = getCircuitBreaker("/api/endpoint-b");
      expect(cb1).not.toBe(cb2);
    });

    it("created breaker has correct config", () => {
      const cb = getCircuitBreaker("/api/config-test");
      const state = cb.getState();
      expect(state.isOpen).toBe(false);
      expect(state.failureCount).toBe(0);
      expect(state.lastFailureTime).toBeNull();
      expect(state.nextAttemptTime).toBeNull();
    });
  });
});
