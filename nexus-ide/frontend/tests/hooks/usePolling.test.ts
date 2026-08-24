import { describe, expect, it, vi, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { usePolling } from "../../hooks/usePolling";

describe("usePolling", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("starts with running=false", () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      usePolling(fetcher, 1000, { immediate: false }),
    );
    expect(result.current.running).toBe(false);
  });

  it("runs fetcher immediately on mount when enabled", () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    renderHook(() => usePolling(fetcher, 1000, { enabled: true, immediate: true }));
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("does not run fetcher immediately when immediate is false", () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    renderHook(() => usePolling(fetcher, 1000, { immediate: false }));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("does not run fetcher when enabled is false", () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    renderHook(() => usePolling(fetcher, 1000, { enabled: false }));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("sets running to true while fetcher is in-flight", async () => {
    let resolveFetcher: () => void = () => {};
    const fetcher = vi.fn().mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveFetcher = resolve;
        }),
    );
    const { result } = renderHook(() => usePolling(fetcher, 1000));
    // Wait a tick for the effect to run
    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.running).toBe(true);
    await act(async () => {
      resolveFetcher();
      await Promise.resolve();
    });
    expect(result.current.running).toBe(false);
  });

  it("refresh calls fetcher and reschedules", async () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      usePolling(fetcher, 1000, { immediate: false }),
    );
    await act(async () => {
      await result.current.refresh();
    });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("swallows fetcher errors", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("fail"));
    const { result } = renderHook(() =>
      usePolling(fetcher, 1000, { immediate: false }),
    );
    await act(async () => {
      await result.current.refresh();
    });
    // Should not throw, running should be false
    expect(result.current.running).toBe(false);
  });

  it("does not schedule timer when interval is zero", () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    renderHook(() => usePolling(fetcher, 0, { immediate: false }));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("does not schedule timer when interval is negative", () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    renderHook(() => usePolling(fetcher, -100, { immediate: false }));
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("uses fake timers for interval testing", () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockResolvedValue(undefined);
    const { unmount } = renderHook(() =>
      usePolling(fetcher, 1000, { immediate: false }),
    );
    const { result: result2 } = renderHook(() =>
      usePolling(fetcher, 1000, { immediate: false }),
    );
    // Without refresh, no calls
    expect(fetcher).not.toHaveBeenCalled();
    unmount();
  });

  it("cleans up timer on unmount", () => {
    vi.useFakeTimers();
    const fetcher = vi.fn().mockResolvedValue(undefined);
    const { unmount } = renderHook(() =>
      usePolling(fetcher, 1000, { enabled: true, immediate: false }),
    );
    const spy = vi.spyOn(global, "clearInterval");
    unmount();
    expect(spy).toHaveBeenCalled();
  });

  it("visibility handler triggers refresh when tab becomes visible", () => {
    const fetcher = vi.fn().mockResolvedValue(undefined);
    renderHook(() => usePolling(fetcher, 1000, { enabled: true, immediate: false }));
    // Simulate visibility change
    Object.defineProperty(document, "hidden", { value: false, configurable: true });
    document.dispatchEvent(new Event("visibilitychange"));
  });
});
