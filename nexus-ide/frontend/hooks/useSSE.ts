import { useEffect, useState, useRef } from 'react';
import { getAccessToken } from '../lib/auth';

export function useSSE<T>(url: string | null, options: any = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('disconnected');
  const abortControllerRef = useRef<AbortController | null>(null);
  const dataHistoryRef = useRef<T[]>([]);
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
              dataHistoryRef.current.push(parsedData);
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
    events: dataHistoryRef.current,
    error, 
    isConnected, 
    connectionStatus,
    manualReconnect,
    disconnect 
  };
}
