import { useEffect, useState, useRef } from 'react';
import { getAccessToken } from '../lib/auth';

/**
 * Cap on the retained frame history. Matches `MAX_EVENTS` in
 * `stores/realTimeStore.ts`; without it a dashboard left open overnight on a
 * chatty stream grew this array without limit.
 */
const MAX_HISTORY = 200;

/**
 * Options for `useSSE`.
 *
 * This used to be `options: any = {}` and was then never read — the `any`
 * silenced the compiler on a parameter that did nothing, and
 * `useRealTimeStream` dutifully forwarded a whole `UseRealTimeStreamOptions`
 * object (`maxRetries`, `maxBackoffMs`, `initialBackoffMs`) into a hook that
 * ignored every field. Callers reasonably believed those knobs were wired.
 *
 * They are still not wired, so the honest thing is to stop advertising them:
 * the second parameter is gone and the only supported call is
 * `useSSE<T>(url)`. Reintroduce it with a real interface when a knob is
 * actually implemented — reconnect backoff is the obvious first candidate.
 */
export function useSSE<T>(url: string | null) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('disconnected');
  const abortControllerRef = useRef<AbortController | null>(null);
  // State, not a ref. The history used to be a `useRef` array that was pushed
  // to in place and then returned straight from render: the array identity
  // never changed, so every consumer's `useEffect([events])` stopped firing
  // after the first frame. `useRealTimeStream` therefore fed exactly one event
  // to `realTimeStore` and then silently dropped the rest of the stream.
  const [events, setEvents] = useState<T[]>([]);
  const [reconnectNonce, setReconnectNonce] = useState(0);

  useEffect(() => {
    if (!url) {
      setConnectionStatus('disconnected');
      return;
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    setConnectionStatus('connecting');
    const token = getAccessToken();

    void (async () => {
      try {
        const response = await fetch(url, {
          headers: {
            Accept: 'text/event-stream',
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          throw new Error(`SSE connection failed with HTTP ${response.status}`);
        }

        setIsConnected(true);
        setConnectionStatus('connected');
        setError(null);
        // A new connection starts a new history: a reconnect must not replay
        // the previous stream's frames as if they were fresh.
        setEvents([]);

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        while (!controller.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          const frames = buffer.split(/\r?\n\r?\n/);
          buffer = frames.pop() ?? '';

          for (const frame of frames) {
            const payload = frame
              .split(/\r?\n/)
              .filter((line) => line.startsWith('data:'))
              .map((line) => line.slice(5).trimStart())
              .join('\n');
            if (!payload) continue;
            try {
              const parsedData = JSON.parse(payload) as T;
              setData(parsedData);
              setEvents((current) =>
                current.length >= MAX_HISTORY
                  ? [...current.slice(current.length - MAX_HISTORY + 1), parsedData]
                  : [...current, parsedData],
              );
            } catch (parseError) {
              console.error('Failed to parse SSE data:', parseError);
              setError(parseError as Error);
            }
          }
        }
      } catch (streamError) {
        if (controller.signal.aborted) return;
        console.error('SSE error:', streamError);
        setError(streamError instanceof Error ? streamError : new Error('SSE connection error'));
        setIsConnected(false);
        setConnectionStatus('error');
      }
    })();

    return () => {
      controller.abort();
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
    };
  }, [url, reconnectNonce]);

  const manualReconnect = () => {
    abortControllerRef.current?.abort();
    setConnectionStatus('connecting');
    setReconnectNonce((value) => value + 1);
  };

  const disconnect = () => {
    abortControllerRef.current?.abort();
    setConnectionStatus('disconnected');
    setIsConnected(false);
  };

  return {
    data,
    events,
    error,
    isConnected,
    connectionStatus,
    manualReconnect,
    disconnect
  };
}
