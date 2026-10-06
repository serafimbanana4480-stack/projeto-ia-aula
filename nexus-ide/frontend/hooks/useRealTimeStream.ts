"use client";

import { useEffect } from "react";
import { useSSE } from "./useSSE";
import { useRealTimeStore } from "../stores/realTimeStore";
import type { StreamEvent } from "../lib/types";

interface UseRealTimeStreamOptions {
  enabled?: boolean;
}

/** The minimum an event needs before the store is allowed to keep it. */
interface StoreableEvent {
  type: string;
  timestamp: string;
  [key: string]: unknown;
}

function isStoreableEvent(value: unknown): value is StoreableEvent {
  return (
    typeof value === "object" &&
    value !== null &&
    !Array.isArray(value) &&
    typeof (value as { type?: unknown }).type === "string" &&
    typeof (value as { timestamp?: unknown }).timestamp === "string"
  );
}

/**
 * Hook that connects SSE stream to the real-time store.
 *
 * This hook manages the SSE connection and automatically
 * adds received events to the realTimeStore for consumption
 * by dashboard components.
 *
 * @param url - The SSE endpoint URL
 * @param options - `enabled` toggles the connection without unmounting
 *
 * NOTE: `maxRetries` / `maxBackoffMs` / `initialBackoffMs` used to be part of
 * this options object and were spread into `useSSE(url, options)` — whose
 * second parameter was an unread `any`. Every one of those knobs was silently
 * inert while looking configurable. They are gone from the type so the next
 * caller cannot rely on them; reconnect backoff belongs in `useSSE`, not here.
 */
export function useRealTimeStream(
  url: string | null,
  options: UseRealTimeStreamOptions = {}
) {
  const { enabled = true } = options;
  const addEvent = useRealTimeStore((state) => state.addEvent);

  const { events, connectionStatus, error, isConnected, manualReconnect, disconnect } =
    useSSE<unknown>(enabled ? url : null);

  // Add new events to the store
  useEffect(() => {
    if (events.length === 0) return;

    // Only the newest frame is new: `events` is the whole history, and the
    // effect re-runs on every frame.
    const latestEvent = events[events.length - 1];
    if (isStoreableEvent(latestEvent)) {
      // `realTimeStore.addEvent` is declared as taking a chat `StreamEvent`,
      // whose `type` is a closed union, but the dashboard streams it is fed
      // here are not chat events — that mismatch is why this used to be a bare
      // `as any`. The guard above is the real check; the cast below is the named
      // boundary, not a way to skip a check. Widening the store's own signature
      // is the proper fix and belongs with the store, not with this hook.
      addEvent(latestEvent as unknown as StreamEvent);
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
