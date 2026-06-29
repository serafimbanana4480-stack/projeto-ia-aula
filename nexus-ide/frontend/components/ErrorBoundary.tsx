"use client";

import React, { Component, ErrorInfo, ReactNode } from "react";
import { log } from "../lib/log";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
  errorInfo: ErrorInfo | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
    };
  }

  static getDerivedStateFromError(error: Error): State {
    return {
      hasError: true,
      error,
      errorInfo: null,
    };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo): void {
    this.setState({
      error,
      errorInfo,
    });
    log.error("ErrorBoundary caught an error:", error, errorInfo);
  }

  handleReset = (): void => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });
  };

  render(): ReactNode {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <div className="flex h-screen w-full items-center justify-center bg-nexus-bg p-4">
          <div className="max-w-lg rounded-lg border border-nexus-border bg-nexus-card p-6 shadow-lg">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-red-500/10 text-red-500">
                <svg
                  className="h-6 w-6"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
                  />
                </svg>
              </div>
              <div>
                <h2 className="text-lg font-semibold text-nexus-text">
                  Something went wrong
                </h2>
                <p className="text-sm text-nexus-muted">
                  An unexpected error occurred
                </p>
              </div>
            </div>

            {this.state.error && (
              <div className="mb-4 rounded bg-nexus-bg p-3">
                <p className="mb-2 text-xs font-medium text-nexus-muted">
                  Error message:
                </p>
                <pre className="overflow-auto text-xs text-red-400">
                  {this.state.error.toString()}
                </pre>
              </div>
            )}

            {process.env.NODE_ENV === "development" && this.state.errorInfo && (
              <details className="mb-4">
                <summary className="cursor-pointer text-sm font-medium text-nexus-muted hover:text-nexus-text">
                  Error details
                </summary>
                <pre className="mt-2 overflow-auto rounded bg-nexus-bg p-3 text-xs text-nexus-muted">
                  {this.state.errorInfo.componentStack}
                </pre>
              </details>
            )}

            <button
              onClick={this.handleReset}
              className="w-full rounded-lg bg-nexus-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-nexus-accent/90"
            >
              Try again
            </button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}