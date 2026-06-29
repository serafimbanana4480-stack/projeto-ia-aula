import { useEffect, useState, useRef } from 'react';

export function useSSE<T>(url: string | null, options: any = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState<'connecting' | 'connected' | 'disconnected' | 'error'>('disconnected');
  const eventSourceRef = useRef<EventSource | null>(null);
  const dataHistoryRef = useRef<T[]>([]);

  useEffect(() => {
    if (!url) {
      setConnectionStatus('disconnected');
      return;
    }

    setConnectionStatus('connecting');
    const eventSource = new EventSource(url);
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      setIsConnected(true);
      setConnectionStatus('connected');
      setError(null);
    };

    eventSource.onmessage = (event) => {
      try {
        const parsedData = JSON.parse(event.data);
        setData(parsedData);
        dataHistoryRef.current.push(parsedData);
      } catch (e) {
        console.error('Failed to parse SSE data:', e);
        setError(e as Error);
      }
    };

    eventSource.onerror = (error) => {
      console.error('SSE error:', error);
      setError(new Error('SSE connection error'));
      setIsConnected(false);
      setConnectionStatus('error');
    };

    return () => {
      eventSource.close();
    };
  }, [url]);

  const manualReconnect = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
    setConnectionStatus('connecting');
  };

  const disconnect = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }
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
