interface CircuitBreakerConfig {
  failureThreshold: number;
  recoveryTimeout: number;
  monitoringPeriod: number;
}

interface CircuitBreakerState {
  isOpen: boolean;
  failureCount: number;
  lastFailureTime: number | null;
  nextAttemptTime: number | null;
}

class CircuitBreaker {
  private state: CircuitBreakerState = {
    isOpen: false,
    failureCount: 0,
    lastFailureTime: null,
    nextAttemptTime: null,
  };

  constructor(private config: CircuitBreakerConfig) {}

  private reset() {
    this.state = {
      isOpen: false,
      failureCount: 0,
      lastFailureTime: null,
      nextAttemptTime: null,
    };
  }

  private open() {
    this.state.isOpen = true;
    this.state.nextAttemptTime = Date.now() + this.config.recoveryTimeout;
  }

  private halfOpen() {
    this.state.isOpen = false;
    this.state.failureCount = 0;
  }

  async execute<T>(fn: () => Promise<T>): Promise<T> {
    // Check if circuit is open
    if (this.state.isOpen) {
      if (Date.now() < (this.state.nextAttemptTime || 0)) {
        throw new Error("Circuit breaker is open");
      }
      // Recovery timeout elapsed, try half-open state
      this.halfOpen();
    }

    try {
      const result = await fn();
      // Success, reset failure count
      if (this.state.failureCount > 0) {
        this.state.failureCount = Math.max(0, this.state.failureCount - 1);
      }
      return result;
    } catch (error) {
      this.state.failureCount++;
      this.state.lastFailureTime = Date.now();

      // Open circuit if threshold reached
      if (this.state.failureCount >= this.config.failureThreshold) {
        this.open();
      }

      throw error;
    }
  }

  getState() {
    return { ...this.state };
  }
}

// Circuit breaker instances for different endpoints
const circuitBreakers = new Map<string, CircuitBreaker>();

function getCircuitBreaker(endpoint: string): CircuitBreaker {
  if (!circuitBreakers.has(endpoint)) {
    circuitBreakers.set(
      endpoint,
      new CircuitBreaker({
        failureThreshold: 5,
        recoveryTimeout: 30000, // 30 seconds
        monitoringPeriod: 60000, // 1 minute
      })
    );
  }
  return circuitBreakers.get(endpoint)!;
}

export { CircuitBreaker, getCircuitBreaker };
