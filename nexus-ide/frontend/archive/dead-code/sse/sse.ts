/**
 * SSE (Server-Sent Events) utility for reliable EventSource connections
 * with error handling and automatic reconnection.
 */

interface SSEOptions {
  url: string;
  onMessage: (data: any) => void;
  onError?: (error: Event) => void;
  maxReconnectAttempts?: number;
  reconnectDelay?: number;
}

export function createSSEConnection({
  url,
  onMessage,
  onError,
  maxReconnectAttempts = 5,
  reconnectDelay = 3000,
}: SSEOptions): () => void {
  let eventSource: EventSource | null = null;
  let reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  let reconnectAttempts = 0;

  const connect = () => {
    try {
      eventSource = new EventSource(url);
      
      eventSource.onopen = () => {
        console.log(`SSE connected to ${url}`);
        reconnectAttempts = 0;
      };

      eventSource.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data);
          onMessage(data);
        } catch (error) {
          console.error(`Failed to parse SSE data from ${url}:`, error);
        }
      };

      eventSource.onerror = (error) => {
        console.error(`SSE error from ${url}:`, error);
        eventSource?.close();
        onError?.(error);
        
        if (reconnectAttempts < maxReconnectAttempts) {
          reconnectAttempts++;
          const delay = reconnectDelay * Math.pow(2, reconnectAttempts - 1);
          reconnectTimeout = setTimeout(connect, delay);
        }
      };
    } catch (error) {
      console.error(`Failed to create EventSource for ${url}:`, error);
    }
  };

  connect();

  return () => {
    eventSource?.close();
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout);
    }
  };
}

/**
 * Consistent error handling utility
 */
export function handleApiError(error: unknown, context: string): void {
  console.error(`[${context}] Error:`, error);
  // Optionally add user notification logic here
}

/**
 * Safe JSON parser with error handling
 */
export function safeJsonParse<T>(json: string, fallback: T): T {
  try {
    return JSON.parse(json) as T;
  } catch (error) {
    console.error("Failed to parse JSON:", error);
    return fallback;
  }
}

/**
 * Safe array slice to prevent memory issues
 */
export function safeSlice<T>(array: T[], maxLength: number): T[] {
  return array.length > maxLength ? array.slice(0, maxLength) : array;
}
