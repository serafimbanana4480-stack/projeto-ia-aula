"use client";

import { useEffect, useState } from "react";
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
  useEffect(() => {
    let mounted = true;
    let finished = false;

    const finish = (err?: unknown) => {
      if (!mounted || finished) return;
      finished = true;
      if (err) {
        setError(err instanceof Error ? err.message : "Authentication check failed.");
      }
      setChecked(true);
    };

    setChecked(false);
    setError(null);
    const timeout = setTimeout(() => {
      finish(new Error("Não foi possível confirmar a sessão a tempo. Verifica a ligação ao backend e tenta novamente."));
    }, AUTH_TIMEOUT_MS);

    const doCheck = async () => {
      const isPublic = PUBLIC_PATHS.includes(pathname);
      try {
        if (isPublic) {
          finish();
          return;
        }
        const hadSession = Boolean(getRefreshToken());
        if (!isTokenValid() && hadSession) {
          await refreshAuth();
        }
        if (!isTokenValid() && isAutoLoginEnabled()) {
          await autoLoginDev();
        }
        if (!mounted || finished) return;
        if (!isTokenValid()) {
          clearAuth();
          router.replace(hadSession ? "/login?expired=1" : "/login");
          return;
        }
        finish();
      } catch (e) {
        finish(e);
      }
    };

    doCheck();

    return () => {
      mounted = false;
      clearTimeout(timeout);
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
        <h1 className="mb-2 text-xl font-semibold text-red-400">Não foi possível verificar a sessão</h1>
        <p className="mb-6 text-sm text-gray-400">{error}</p>
        <button
          onClick={() => window.location.reload()}
          className="rounded bg-[#7c6afb] px-4 py-2 text-sm font-medium hover:bg-[#6b5ce7]"
        >
          Tentar novamente
        </button>
      </div>
    );
  }

  return <>{children}</>;
}
