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
  const autoLoginRequest = useRef<Promise<unknown> | null>(null);
  const refreshRequest = useRef<Promise<boolean> | null>(null);

  useEffect(() => {
    if (PUBLIC_PATHS.includes(pathname)) {
      setError(null);
      setChecked(true);
      return;
    }
    let active = true;
    const finish = (valid: boolean, reason?: unknown) => {
      if (!active) return;
      active = false;
      clearTimeout(timer);
      if (!valid) {
        clearAuth();
        setChecked(false);
        router.replace("/login?expired=1");
      } else {
        setChecked(true);
      }
      setError(reason ? (reason instanceof Error ? reason.message : "Falhou a verificação da sessão.") : null);
    };
    const timer = setTimeout(() => finish(false), AUTH_TIMEOUT_MS);

    // A Strict Mode effect restart must attach to the existing request.
    async function checkSession() {
      if (!isTokenValid() && isAutoLoginEnabled()) {
        autoLoginRequest.current ??= autoLoginDev().catch(() => undefined);
        await autoLoginRequest.current;
      }
      if (!active) return;
      if (!isTokenValid() && getRefreshToken()) {
        refreshRequest.current ??= refreshAuth().finally(() => { refreshRequest.current = null; });
        await refreshRequest.current;
      }
      if (active) finish(isTokenValid());
    }
    void checkSession().catch((reason: unknown) => finish(false, reason));
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [pathname, router]);

  if (!checked && !error) {
    return (
      <div role="status" className="flex h-screen w-screen items-center justify-center bg-[var(--nx-bg)]">
        <span className="size-8 rounded-full border-2 border-[var(--nx-accent)] border-t-transparent motion-safe:animate-spin" aria-hidden="true" />
        <span className="sr-only">A verificar a sessão</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-screen w-screen flex-col items-center justify-center bg-[#0b0b14] text-white">
        <h1 className="mb-2 text-xl font-semibold text-red-400">Falha de autenticação</h1>
        <p className="mb-6 text-sm text-gray-400">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="rounded bg-[#7c6afb] px-4 py-2 text-sm font-medium hover:bg-[#6b5ce7]"
        >
          Recarregar página
        </button>
      </div>
    );
  }

  return <>{children}</>;
}
