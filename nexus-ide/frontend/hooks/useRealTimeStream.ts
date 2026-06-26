"use client";

import { useEffect } from "react";
import { useSSE } from "./useSSE";
import { useRealTimeStore } from "../stores/realTimeStore";

interface UseRealTimeStreamOptions {
  enabled?: boolean;
  maxRetries?: number;
  maxBackoffMs?: number;
  initialBackoffMs?: number;
}

/**
 * Hook that connects SSE stream to the real-time store.
 *
 * This hook manages the SSE connection and automatically
 * adds received events to the realTimeStore for consumption
 * by dashboard components.
 *
 * @param url - The SSE endpoint URL
 * @param options - Configuration options for the SSE connection
 */
export function useRealTimeStream(
  url: string | null,
  options: UseRealTimeStreamOptions = {}
) {
  const { enabled = true, ...sseOptions } = options;
  const addEvent = useRealTimeStore((state) => state.addEvent);

  const { events, connectionStatus, error, isConnected, manualReconnect, disconnect } =
    useSSE(enabled ? url : null, sseOptions);

  // Add new events to the store
  useEffect(() => {
    if (events.length === 0) return;

    // Get only the new events (last one since we process in real-time)
    const latestEvent = events[events.length - 1];
    if (latestEvent && typeof latestEvent === 'object' && latestEvent !== null) {
      // Type guard to ensure the event has the required properties
      if ('type' in latestEvent && 'timestamp' in latestEvent) {
        addEvent(latestEvent as any);
      }
    }
  }, [events, addEvent]);

  return {
    connectionStatus,
    error,
    isConnected,
    manualReconnect,
    disconnect,
  };
}
