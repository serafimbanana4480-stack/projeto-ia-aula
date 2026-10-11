"use client";
import { useEffect, useState } from "react";
import { getAccessToken } from "../lib/auth";

export interface MetricsSnapshot {
  tokens_per_second: number;
  active_model: string;
  active_sessions: number;
  queue_depth: number;
  ram_used_bytes: number;
}

/**
 * LEGACY / ORPHAN: no production component imports this hook any more (only
 * `tests/hooks/useMetrics.test.ts`); the dashboard is fed by
 * `stores/metricsStore.ts`. It is kept working rather than removed, and the
 * stream is now opened with the access token because the backend no longer
 * answers anonymous requests.
 */
export function useMetrics() {
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);

  useEffect(() => {
    const baseUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
    const controller = new AbortController();
    const token = getAccessToken();

    void (async () => {
      try {
        const response = await fetch(`${baseUrl}/api/system/metrics/stream`, {
          headers: {
            Accept: "text/event-stream",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) return;

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split(/\r?\n\r?\n/);
          buffer = frames.pop() ?? "";

          for (const frame of frames) {
            const payload = frame
              .split(/\r?\n/)
              .filter((line) => line.startsWith("data:"))
              .map((line) => line.slice(5).trimStart())
              .join("\n");
            if (!payload) continue;
            try {
              setMetrics(JSON.parse(payload) as MetricsSnapshot);
            } catch {
              // Ignore malformed frames, exactly as the EventSource version did.
            }
          }
        }
      } catch {
        // Ignore stream errors; the hook exposes no connection state.
      }
    })();

    return () => controller.abort();
  }, []);

  return metrics;
}
