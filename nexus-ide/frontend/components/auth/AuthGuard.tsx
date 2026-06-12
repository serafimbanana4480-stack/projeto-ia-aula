"use client";

import { useEffect, useState, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { isTokenValid, clearAuth } from "../../lib/auth";
import { initMetricsStream } from "../../stores/metricsStore";

const PUBLIC_PATHS = ["/login"];

// Longer timeout during dev to avoid "Authentication check timed out" while
// Next.js is hot-reloading or the browser is under heavy load.
const AUTH_TIMEOUT_MS =
  process.env.NODE_ENV === "development" ? 10000 : 5000;

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let mounted = true;

    timeoutRef.current = setTimeout(() => {
      if (mounted && !checked) {
        // If we hit the safety timeout, clear any stale token and force the
        // user back to the login page instead of showing a dead-end error.
        clearAuth();
        if (!PUBLIC_PATHS.includes(pathname)) {
          router.replace("/login?expired=1");
        }
        setChecked(true);
      }
    }, AUTH_TIMEOUT_MS);

    try {
      const isPublic = PUBLIC_PATHS.includes(pathname);
      const valid = isTokenValid();

      if (valid) {
        // Ensure the metrics stream is running after (re-)authentication.
        try {
          initMetricsStream();
        } catch {
          /* ignore init errors */
        }
      }

      if (!isPublic && !valid) {
        // Clean expired/invalid token immediately to prevent repeated loops.
        clearAuth();
        router.replace("/login?expired=1");
      }
    } catch (e) {
      // On any unexpected error, clear auth and redirect rather than hanging.
      clearAuth();
      if (!PUBLIC_PATHS.includes(pathname)) {
        router.replace("/login?expired=1");
      }
      if (mounted) {
        setError(
          e instanceof Error ? e.message : "Authentication check failed."
        );
      }
    } finally {
      if (mounted) {
        setChecked(true);
      }
    }

    return () => {
      mounted = false;
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, router]);

  if (!checked && !error) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-[#0b0b14]">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-[#7c6afb] border-t-transparent" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-screen w-screen flex-col items-center justify-center bg-[#0b0b14] text-white">
        <h1 className="mb-2 text-xl font-semibold text-red-400">
          Authentication Error
        </h1>
        <p className="mb-6 text-sm text-gray-400">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="rounded bg-[#7c6afb] px-4 py-2 text-sm font-medium hover:bg-[#6b5ce7]"
        >
          Reload Page
        </button>
      </div>
    );
  }

  return <>{children}</>;
}
