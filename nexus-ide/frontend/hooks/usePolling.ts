"use client";

import { useCallback, useEffect, useRef, useState } from "react";

export interface UsePollingOptions {
  /** When false the fetcher is not scheduled/run. Default: true. */
  enabled?: boolean;
  /** Run the fetcher immediately on mount (and when inputs change). Default: true. */
  immediate?: boolean;
}

export interface UsePollingResult {
  /** True while a fetch is in-flight. */
  running: boolean;
  /** Manually trigger a fetch (also resets the interval clock). */
  refresh: () => Promise<void>;
}

/**
 * Shared polling hook used to consolidate the ad-hoc `setInterval` patterns
 * scattered across dashboard widgets (AlertFeed, GuardianWidget, ...).
 *
 * - Runs `fetcher` immediately (unless `immediate: false`) and on a
 *   `setInterval` of `intervalMs`.
 * - Pauses automatically while the document is hidden (Page Visibility API)
 *   and resumes on visibility regain, triggering an immediate refresh so the
 *   UI does not show stale data after returning to the tab.
 * - Swallows errors thrown by `fetcher` so a single failing poll never
 *   crashes the host component. Callers are expected to surface failures via
 *   the shared store (e.g. `setAlertsError`).
 * - Cleans up the timer on unmount and on every dependency change.
 *
 * The `fetcher` identity is captured via a ref so callers can pass an inline
 * closure without retriggering the effect each render; `enabled` and
 * `intervalMs` changes DO reschedule.
 */
export function usePolling(
  fetcher: () => Promise<void>,
  intervalMs: number,
  options: UsePollingOptions = {},
): UsePollingResult {
  const { enabled = true, immediate = true } = options;
  const [running, setRunning] = useState(false);

  const fetcherRef = useRef(fetcher);
  useEffect(() => {
    fetcherRef.current = fetcher;
  }, [fetcher]);

  const runningRef = useRef(false);
  const mountedRef = useRef(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const hiddenRef = useRef(false);

  const run = useCallback(async (): Promise<void> => {
    if (!mountedRef.current) return;
    if (runningRef.current) return;
    runningRef.current = true;
    setRunning(true);
    try {
      await fetcherRef.current();
    } catch {
      // Swallow — callers own error state via the store.
    } finally {
      runningRef.current = false;
      if (mountedRef.current) setRunning(false);
    }
  }, []);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const schedule = useCallback(() => {
    clearTimer();
    if (!enabled || intervalMs <= 0) return;
    timerRef.current = setInterval(() => {
      if (hiddenRef.current) return;
      void run();
    }, intervalMs);
  }, [clearTimer, enabled, intervalMs, run]);

  const refresh = useCallback(async (): Promise<void> => {
    clearTimer();
    await run();
    if (mountedRef.current) schedule();
    return;
  }, [clearTimer, run, schedule]);

  useEffect(() => {
    mountedRef.current = true;
    hiddenRef.current =
      typeof document !== "undefined" ? document.hidden : false;

    if (enabled) {
      if (immediate) void run();
      schedule();
    }

    const onVisibility = () => {
      if (!mountedRef.current) return;
      const hidden = document.hidden;
      hiddenRef.current = hidden;
      if (!hidden && enabled) {
        // Resumed — refresh now and restart the clock so data is fresh.
        void refresh();
      }
    };

    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", onVisibility);
    }

    return () => {
      mountedRef.current = false;
      clearTimer();
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", onVisibility);
      }
    };
  }, [enabled, immediate, run, schedule, clearTimer, refresh]);

  return { running, refresh };
}
