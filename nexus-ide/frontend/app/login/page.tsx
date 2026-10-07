"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  login,
  autoLoginDev,
  isAutoLoginEnabled,
} from "../../lib/auth";

const APP_PASSWORD = process.env.NEXT_PUBLIC_APP_PASSWORD ?? "5748";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const expired = searchParams.get("expired") === "1";

  const autoLoginActive = isAutoLoginEnabled();
  const autoLoginDisabled = process.env.NEXT_PUBLIC_AUTO_LOGIN === "false";
  const devEmail = process.env.NEXT_PUBLIC_DEV_EMAIL ?? "admin@nexus-ide.com";
  const devPassword = process.env.NEXT_PUBLIC_DEV_PASSWORD ?? APP_PASSWORD;

  const [password, setPassword] = useState(autoLoginActive && !autoLoginDisabled ? devPassword : APP_PASSWORD);
  const [error, setError] = useState<string | null>(expired ? "Sessão expirada. Por favor introduza a password novamente." : null);
  const [loading, setLoading] = useState(false);
  const [autoLoginAttempting, setAutoLoginAttempting] = useState(false);
  const autoLoginTried = useRef(false);

  useEffect(() => {
    if (!autoLoginActive || autoLoginDisabled || autoLoginTried.current) return;
    autoLoginTried.current = true;
    setAutoLoginAttempting(true);
    autoLoginDev()
      .then((success) => {
        if (success) {
          router.replace("/");
        }
      })
      .catch(() => {})
      .finally(() => setAutoLoginAttempting(false));
  }, [router, autoLoginActive, autoLoginDisabled]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login({ email: devEmail, password });
      router.replace("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Password incorreta");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#0b0b14] px-4">
      <div className="w-full max-w-sm rounded-2xl border border-[#1e1e2d] bg-[#161622] p-8 shadow-2xl">
        <div className="mb-6 text-center">
          <h1 className="text-2xl font-semibold text-white">NEXUS IDE</h1>
          <p className="mt-2 text-sm text-[#9ca3af">Introduza a password para continuar</p>
        </div>

        {autoLoginActive && !autoLoginDisabled && (
          <div className="mb-4 rounded-lg border border-[#7c6afb]/30 bg-[#7c6afb]/10 px-4 py-3 text-sm text-[#b8b3ff]">
            Modo testes — login automático ativo
            {autoLoginAttempting && " (a tentar...)"}
          </div>
        )}

        {error && (
          <div className="mb-4 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="password" className="mb-1 block text-sm font-medium text-[#e8e8ed]">
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              autoFocus
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-lg border border-[#2a2a3c] bg-[#0f0f18] px-4 py-2.5 text-sm text-white placeholder-[#6b7280] outline-none transition focus:border-[#7c6afb] focus:ring-1 focus:ring-[#7c6afb]"
              placeholder="••••"
            />
          </div>

          <button
            type="submit"
            disabled={loading || autoLoginAttempting}
            className="flex w-full items-center justify-center rounded-lg bg-[#7c6afb] px-4 py-2.5 text-sm font-medium text-white transition hover:bg-[#6b5ce6] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading || autoLoginAttempting ? (
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
            ) : (
              "Entrar"
            )}
          </button>
        </form>
      </div>
    </div>
  );
}
