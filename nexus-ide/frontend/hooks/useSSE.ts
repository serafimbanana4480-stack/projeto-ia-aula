"use client";
import { useEffect, useState } from "react";
import type { StreamEvent } from "../lib/types";

// Parses an SSE body stream into typed events.
// TODO: implement proper cancellation and reconnection.
export function useSSE(url: string | null) {
  const [events, setEvents] = useState<StreamEvent[]>([]);

  useEffect(() => {
    if (!url) return;
    const source = new EventSource(url);
    source.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data) as StreamEvent;
        setEvents((prev) => [...prev, evt]);
      } catch {
        /* ignore malformed chunks */
      }
    };
    return () => source.close();
  }, [url]);

  return events;
}
