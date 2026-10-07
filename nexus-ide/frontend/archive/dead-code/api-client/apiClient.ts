import { getCircuitBreaker } from "@/lib/circuitBreaker";
import { apiUrl } from "@/lib/api";

interface ApiClientConfig {
  timeout?: number;
  retries?: number;
  retryDelay?: number;
}

class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
    public endpoint?: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function fetchWithTimeout(
  url: string,
  options: RequestInit,
  timeout: number
): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error instanceof Error && error.name === "AbortError") {
      throw new ApiError(`Request timeout after ${timeout}ms`, undefined, url);
    }
    throw error;
  }
}

async function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function fetchWithRetry<T>(
  endpoint: string,
  options: RequestInit = {},
  config: ApiClientConfig = {}
): Promise<T> {
  const {
    timeout = 10000,
    retries = 3,
    retryDelay = 1000,
  } = config;

  const url = apiUrl(endpoint);
  const circuitBreaker = getCircuitBreaker(endpoint);

  let lastError: Error | null = null;

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      // Check circuit breaker first
      const result = await circuitBreaker.execute(async () => {
        const response = await fetchWithTimeout(url, options, timeout);

        if (!response.ok) {
          throw new ApiError(
            `HTTP ${response.status}: ${response.statusText}`,
            response.status,
            endpoint
          );
        }

        return response.json();
      });

      return result;
    } catch (error) {
      lastError = error as Error;

      // Don't retry on client errors (4xx)
      if (error instanceof ApiError && error.status && error.status >= 400 && error.status < 500) {
        throw error;
      }

      // Don't retry after last attempt
      if (attempt === retries) {
        break;
      }

      // Exponential backoff
      const delay = retryDelay * Math.pow(2, attempt);
      await sleep(delay);
    }
  }

  throw lastError || new ApiError("Request failed after retries");
}

// Offline detection
export function isOnline(): boolean {
  return typeof navigator !== "undefined" ? navigator.onLine : true;
}

// Request queue for offline mode
class RequestQueue {
  private queue: Array<{ endpoint: string; options: RequestInit; config: ApiClientConfig }> = [];

  add(endpoint: string, options: RequestInit, config: ApiClientConfig) {
    this.queue.push({ endpoint, options, config });
    this.saveToStorage();
  }

  async processAll() {
    const requests = [...this.queue];
    this.queue = [];
    this.saveToStorage();

    for (const request of requests) {
      try {
        await fetchWithRetry(request.endpoint, request.options, request.config);
      } catch (error) {
        console.error("Failed to process queued request:", error);
        // Re-queue failed requests
        this.queue.push(request);
      }
    }

    if (this.queue.length > 0) {
      this.saveToStorage();
    }
  }

  private saveToStorage() {
    if (typeof localStorage !== "undefined") {
      localStorage.setItem("requestQueue", JSON.stringify(this.queue));
    }
  }

  private loadFromStorage() {
    if (typeof localStorage !== "undefined") {
      const saved = localStorage.getItem("requestQueue");
      if (saved) {
        try {
          this.queue = JSON.parse(saved);
        } catch (error) {
          console.error("Failed to load request queue:", error);
        }
      }
    }
  }

  constructor() {
    this.loadFromStorage();

    // Listen for online events
    if (typeof window !== "undefined") {
      window.addEventListener("online", () => {
        if (this.queue.length > 0) {
          this.processAll();
        }
      });
    }
  }
}

export const requestQueue = new RequestQueue();

export { ApiError, getCircuitBreaker };
