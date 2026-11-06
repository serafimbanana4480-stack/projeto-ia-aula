"use client";

import { useEffect } from "react";
import { AlertTriangle } from "lucide-react";

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
    <div className="flex min-h-[60vh] items-center justify-center p-4">
      <div role="alert" className="nx-elev-2 max-w-md rounded-nx-lg p-6 text-center">
        <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-nexus-accent4/10 text-nexus-accent4">
          <AlertTriangle className="h-6 w-6" aria-hidden="true" />
        </div>
        <h2 className="mb-2 text-lg font-semibold text-nexus-text">Erro no Dashboard</h2>
        <p className="mb-1 text-sm text-nexus-muted">{message}</p>
        {error?.digest && (
          <p className="mb-4 font-mono text-xs text-nexus-faint">ID: {error.digest}</p>
        )}
        <button
          type="button"
          onClick={reset}
          className="mt-4 inline-flex min-h-10 items-center justify-center rounded-xl border border-nexus-border bg-nexus-card px-4 text-sm font-medium text-nexus-text transition-colors hover:border-nexus-accent/40 hover:text-nexus-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-nexus-accent"
        >
          Tentar novamente
        </button>
      </div>
    </div>
  );
}
