"use client";
import { useEffect, useState } from "react";

export interface MetricsSnapshot {
  tokens_per_second: number;
  active_model: string;
  active_sessions: number;
  queue_depth: number;
  ram_used_bytes: number;
}

// Subscribes to the dashboard SSE stream and returns the most recent snapshot.
// TODO: back by zustand store so multiple components share one connection.
export function useMetrics() {
  const [metrics, setMetrics] = useState<MetricsSnapshot | null>(null);

  useEffect(() => {
    const src = new EventSource("/api/dashboard/stream");
    src.onmessage = (e) => {
      try {
        setMetrics(JSON.parse(e.data));
      } catch {
        /* ignore */
      }
    };
    return () => src.close();
  }, []);

  return metrics;
}
