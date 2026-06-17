"use client";

import { useEffect, useState, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { isTokenValid, clearAuth } from "../../lib/auth";

const PUBLIC_PATHS = ["/login"];

const AUTH_TIMEOUT_MS =
  process.env.NODE_ENV === "development" ? 10000 : 5000;

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [checked, setChecked] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const blockedLoginRedirectRef = useRef(false);

  useEffect(() => {
    let mounted = true;

    timeoutRef.current = setTimeout(() => {
      if (mounted && !checked) {
        const isPublic = PUBLIC_PATHS.includes(pathname);
        if (!isPublic) {
          clearAuth();
          router.replace("/login?expired=1");
        }
        if (mounted) {
          setChecked(true);
        }
      }
    }, AUTH_TIMEOUT_MS);

    try {
      const isPublic = PUBLIC_PATHS.includes(pathname);
      const valid = isTokenValid();

      if (!isPublic && !valid) {
        const alreadyBlocked = blockedLoginRedirectRef.current;
        clearAuth();
        if (!alreadyBlocked) {
          blockedLoginRedirectRef.current = true;
          router.replace("/login?expired=1");
        }
      }
    } catch (e) {
      clearAuth();
      if (!PUBLIC_PATHS.includes(pathname) && !blockedLoginRedirectRef.current) {
        blockedLoginRedirectRef.current = true;
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
