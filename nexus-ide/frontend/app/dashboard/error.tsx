"use client";

import { useEffect } from "react";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[dashboard] route error:", error);
  }, [error]);

  const message = error?.message || "Ocorreu um erro inesperado ao carregar o dashboard.";

  return (
    <main className="flex-1 overflow-auto">
      <div className="flex min-h-[60vh] items-center justify-center p-4">
        <div className="max-w-md rounded-lg border border-red-500/30 bg-nexus-panel p-6 text-center shadow-lg">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-red-500/10 text-red-400">
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              className="h-6 w-6"
              aria-hidden="true"
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m0 3.75h.007M5.91 19.25h12.18a2 2 0 001.74-2.99l-6.09-10.5a2 2 0 00-3.48 0l-6.09 10.5a2 2 0 001.74 2.99z" />
            </svg>
          </div>
          <h2 className="mb-2 text-lg font-semibold text-nexus-accent">Erro no Dashboard</h2>
          <p className="mb-1 text-sm text-gray-300">{message}</p>
          {error?.digest && (
            <p className="mb-4 font-mono text-xs text-gray-500">ID: {error.digest}</p>
          )}
          <button
            type="button"
            onClick={reset}
            className="mt-4 inline-flex items-center justify-center rounded-md border border-nexus-border bg-nexus-bg px-4 py-2 text-sm font-medium text-gray-200 transition-colors hover:border-nexus-accent hover:text-nexus-accent focus:outline-none focus:ring-2 focus:ring-nexus-accent/50"
          >
            Tentar novamente
          </button>
        </div>
      </div>
    </main>
  );
}
