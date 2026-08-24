import { useEffect, useState, useRef } from 'react';

const MAX_RETRY_DELAY_MS = 30_000;
const BASE_RETRY_DELAY_MS = 1_000;

/**
 * WebSocket with automatic reconnection.
 *
 * The first version latched ``isConnected=false`` forever after any drop
 * (network blip, backend restart) and the UI stayed "Offline" until a full
 * page reload. Retries now back off exponentially (1s → 30s) and reset on a
 * successful open.
 */
export function useWebSocket<T>(url: string) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const retryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  // Reconnect only when the hook is still mounted and the URL unchanged.
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    attemptRef.current = 0;

    const connect = () => {
      if (!aliveRef.current) return;
      let ws: WebSocket;
      try {
        ws = new WebSocket(url.replace('http://', 'ws://').replace('https://', 'wss://'));
      } catch (e) {
        setError(e instanceof Error ? e : new Error('WebSocket construction failed'));
        scheduleRetry();
        return;
      }
      wsRef.current = ws;

      ws.onopen = () => {
        attemptRef.current = 0;
        setIsConnected(true);
        setError(null);
      };

      ws.onmessage = (event) => {
        try {
          const parsedData = JSON.parse(event.data);
          setData(parsedData);
        } catch (e) {
          console.error('Failed to parse WebSocket data:', e);
          setError(e as Error);
        }
      };

      ws.onerror = () => {
        setError(new Error('WebSocket connection error'));
        setIsConnected(false);
      };

      ws.onclose = () => {
        setIsConnected(false);
        scheduleRetry();
      };
    };

    const scheduleRetry = () => {
      if (!aliveRef.current) return;
      if (retryTimer.current) clearTimeout(retryTimer.current);
      const delay = Math.min(
        BASE_RETRY_DELAY_MS * 2 ** attemptRef.current,
        MAX_RETRY_DELAY_MS,
      );
      attemptRef.current += 1;
      retryTimer.current = setTimeout(connect, delay);
    };

    connect();

    return () => {
      aliveRef.current = false;
      if (retryTimer.current) clearTimeout(retryTimer.current);
      wsRef.current?.close();
    };
  }, [url]);

  return { data, error, isConnected };
}
