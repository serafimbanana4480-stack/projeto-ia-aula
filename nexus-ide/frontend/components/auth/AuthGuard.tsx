"use client";

import { useEffect, useState, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { isTokenValid, clearAuth, autoLoginDev, isAutoLoginEnabled, refreshAuth, getRefreshToken } from "../../lib/auth";

const PUBLIC_PATHS = ["/login"];

const AUTH_TIMEOUT_MS =
  process.env.NODE_ENV === "development" ? 15000 : 5000;

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const checkedRef = useRef(false);

  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const blockedLoginRedirectRef = useRef(false);
  const autoLoginAttempted = useRef(false);
  // Guards against running the auth check more than once per mount. Without
  // this, including `checked` in the dependency array re-triggers the effect
  // after `setChecked(true)`, which — combined with React StrictMode's
  // double-invocation in dev — could leave the guard stuck on the loading
  // spinner (the "blank screen" symptom).
  const checkStartedRef = useRef(false);

  useEffect(() => {
    if (checkStartedRef.current) return;
    checkStartedRef.current = true;
    let mounted = true;

    const finish = (err?: unknown) => {
      if (!mounted) return;
      if (err) {
        setError(err instanceof Error ? err.message : "Authentication check failed.");
      }
      checkedRef.current = true;
      setChecked(true);
    };

    const doCheck = async () => {
      // Start the guard timeout before any network-backed auto-login attempt.
      // A stalled backend must never keep the entire UI on an infinite spinner.
      timeoutRef.current = setTimeout(() => {
        if (mounted && !checkedRef.current) {
          const isPublic = PUBLIC_PATHS.includes(pathname);
          if (!isPublic) {
            clearAuth();
            router.replace("/login?expired=1");
          }
          finish();
        }
      }, AUTH_TIMEOUT_MS);

      const isPublic = PUBLIC_PATHS.includes(pathname);

      // The login page owns its dev auto-login attempt. Running it here too
      // creates two concurrent authentication requests and can overload the
      // backend while the database pool is still warming up.
      if (!isPublic && !autoLoginAttempted.current && isAutoLoginEnabled()) {
        autoLoginAttempted.current = true;
        try {
          await autoLoginDev();
        } catch {
          // auto-login failed silently
        }
      }

      try {
        const valid = isTokenValid();

        if (!isPublic && !valid) {
          // Access token expired — try a silent refresh before giving up.
          if (getRefreshToken()) {
            const refreshed = await refreshAuth();
            if (refreshed && isTokenValid()) {
              finish();
              return;
            }
          }
          const alreadyBlocked = blockedLoginRedirectRef.current;
          clearAuth();
          if (!alreadyBlocked) {
            blockedLoginRedirectRef.current = true;
            router.replace("/login?expired=1");
          }
        }
        finish();
      } catch (e) {
        clearAuth();
        if (!PUBLIC_PATHS.includes(pathname) && !blockedLoginRedirectRef.current) {
          blockedLoginRedirectRef.current = true;
          router.replace("/login?expired=1");
        }
        finish(e);
      }
    };

    doCheck();

    return () => {
      mounted = false;
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
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
        <h1 className="mb-2 text-xl font-semibold text-red-400">Authentication Error</h1>
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
