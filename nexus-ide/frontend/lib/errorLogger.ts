interface ErrorContext {
  component?: string;
  action?: string;
  props?: any;
  userId?: string;
  sessionId?: string;
  [key: string]: any;
}

interface ErrorLog {
  message: string;
  stack?: string;
  timestamp: string;
  context: ErrorContext;
  userAgent: string;
  url: string;
}

class ErrorLogger {
  private logs: ErrorLog[] = [];
  private maxLogs = 100;
  private rateLimitCount = 0;
  private rateLimitWindow = 60000; // 1 minute
  private maxRateLimit = 10; // max 10 errors per minute

  private isRateLimited(): boolean {
    const now = Date.now();
    if (this.rateLimitCount >= this.maxRateLimit) {
      // Reset if window has passed
      this.rateLimitCount = 0;
      return false;
    }
    return false;
  }

  private incrementRateLimit() {
    this.rateLimitCount++;
    setTimeout(() => {
      this.rateLimitCount = Math.max(0, this.rateLimitCount - 1);
    }, this.rateLimitWindow);
  }

  log(error: Error, context: ErrorContext = {}) {
    if (this.isRateLimited()) {
      console.warn("Error logger rate limited");
      return;
    }

    this.incrementRateLimit();

    const errorLog: ErrorLog = {
      message: error.message,
      stack: error.stack,
      timestamp: new Date().toISOString(),
      context: {
        ...context,
        component: context.component || "Unknown",
      },
      userAgent: typeof navigator !== "undefined" ? navigator.userAgent : "Unknown",
      url: typeof window !== "undefined" ? window.location.href : "Unknown",
    };

    // Add to local logs
    this.logs.push(errorLog);
    if (this.logs.length > this.maxLogs) {
      this.logs.shift();
    }

    // Save to localStorage
    this.saveToStorage();

    // Send to backend
    this.sendToBackend(errorLog).catch((err) => {
      console.error("Failed to send error to backend:", err);
    });

    // Also log to console in development
    if (process.env.NODE_ENV === "development") {
      console.error("Error logged:", errorLog);
    }
  }

  private async sendToBackend(errorLog: ErrorLog): Promise<void> {
    try {
      const response = await fetch("/api/errors", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(errorLog),
      });

      if (!response.ok) {
        throw new Error(`Failed to send error: ${response.status}`);
      }
    } catch (error) {
      // Don't throw here to avoid infinite loops
      console.error("Failed to send error to backend:", error);
    }
  }

  private saveToStorage() {
    if (typeof localStorage !== "undefined") {
      try {
        localStorage.setItem("errorLogs", JSON.stringify(this.logs));
      } catch (error) {
        console.error("Failed to save error logs to localStorage:", error);
      }
    }
  }

  private loadFromStorage() {
    if (typeof localStorage !== "undefined") {
      try {
        const saved = localStorage.getItem("errorLogs");
        if (saved) {
          this.logs = JSON.parse(saved);
        }
      } catch (error) {
        console.error("Failed to load error logs from localStorage:", error);
      }
    }
  }

  getLogs(): ErrorLog[] {
    return [...this.logs];
  }

  clearLogs() {
    this.logs = [];
    if (typeof localStorage !== "undefined") {
      localStorage.removeItem("errorLogs");
    }
  }

  constructor() {
    this.loadFromStorage();

    // Global error handler
    if (typeof window !== "undefined") {
      window.addEventListener("error", (event) => {
        this.log(event.error || new Error(event.message), {
          type: "global",
          filename: event.filename,
          lineno: event.lineno,
          colno: event.colno,
        });
      });

      window.addEventListener("unhandledrejection", (event) => {
        this.log(event.reason || new Error("Unhandled promise rejection"), {
          type: "unhandledRejection",
        });
      });
    }
  }
}

export const errorLogger = new ErrorLogger();
