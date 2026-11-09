import React, { StrictMode } from "react";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AuthGuard from "../../components/auth/AuthGuard";
import * as auth from "../../lib/auth";

const replace = vi.fn();
const router = { replace };
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  usePathname: () => "/",
}));
vi.mock("../../lib/auth", () => ({
  isTokenValid: vi.fn(), clearAuth: vi.fn(), autoLoginDev: vi.fn(),
  isAutoLoginEnabled: vi.fn(), refreshAuth: vi.fn(), getRefreshToken: vi.fn(),
}));

describe("AuthGuard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(auth.isTokenValid).mockReturnValue(false);
    vi.mocked(auth.isAutoLoginEnabled).mockReturnValue(false);
    vi.mocked(auth.getRefreshToken).mockReturnValue("refresh");
  });
  afterEach(() => vi.useRealTimers());

  it("keeps credentials when refresh fails temporarily", async () => {
    vi.mocked(auth.refreshAuth).mockRejectedValue(new Error("backend indisponível"));
    render(<AuthGuard>Conteúdo</AuthGuard>);
    expect(await screen.findByText("backend indisponível")).toBeTruthy();
    expect(auth.clearAuth).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  it("does not erase credentials or redirect when refresh takes too long", async () => {
    vi.useFakeTimers();
    vi.mocked(auth.refreshAuth).mockReturnValue(new Promise(() => {}));
    render(<AuthGuard>Conteúdo</AuthGuard>);
    await act(async () => { await vi.advanceTimersByTimeAsync(16000); });
    expect(screen.getByText(/Não foi possível confirmar a sessão a tempo/)).toBeTruthy();
    expect(auth.clearAuth).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
  });

  it("completes the check under React Strict Mode", async () => {
    vi.mocked(auth.isTokenValid).mockReturnValue(true);
    render(<StrictMode><AuthGuard>Conteúdo</AuthGuard></StrictMode>);
    await waitFor(() => expect(screen.getByText("Conteúdo")).toBeTruthy());
  });

  it("redirects an unauthenticated visitor without claiming expiry", async () => {
    vi.mocked(auth.getRefreshToken).mockReturnValue(null);
    render(<AuthGuard>Conteúdo</AuthGuard>);
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/login"));
  });
});
