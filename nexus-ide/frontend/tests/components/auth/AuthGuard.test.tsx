import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

const { autoLoginDev, isTokenValid, replace } = vi.hoisted(() => ({
  autoLoginDev: vi.fn(),
  isTokenValid: vi.fn(),
  replace: vi.fn(),
}));
vi.mock("next/navigation", () => ({ usePathname: () => "/bots", useRouter: () => ({ replace }) }));
vi.mock("../../../lib/auth", () => ({
  autoLoginDev,
  isTokenValid,
  isAutoLoginEnabled: () => true,
  getRefreshToken: () => null,
  clearAuth: vi.fn(),
  refreshAuth: vi.fn(),
}));

import AuthGuard from "../../../components/auth/AuthGuard";

it("retoma a verificação após o reinício do efeito em Strict Mode", async () => {
  let finishLogin!: () => void;
  isTokenValid.mockReturnValue(false);
  autoLoginDev.mockReturnValue(new Promise<void>((resolve) => { finishLogin = resolve; }));
  render(<StrictMode><AuthGuard><p>Área de bots</p></AuthGuard></StrictMode>);
  expect(screen.getByRole("status")).toBeTruthy();
  await act(async () => {
    isTokenValid.mockReturnValue(true);
    finishLogin();
  });
  expect(screen.getByText("Área de bots")).toBeTruthy();
  expect(autoLoginDev).toHaveBeenCalledTimes(1);
  expect(replace).not.toHaveBeenCalled();
});
