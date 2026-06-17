"use client";

import { apiUrl } from "./api";

const TOKEN_KEY = "nexus.access_token";
const USER_KEY = "nexus.user";

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  created_at: string;
}

export interface LoginCredentials {
  email: string;
  password: string;
}

export interface LoginResult {
  access_token: string;
  token_type: string;
  user: User;
}

export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setAccessToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(TOKEN_KEY, token);
}

export function setUser(user: User): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
}

export function getUser(): User | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as User;
  } catch {
    return null;
  }
}

export function clearAuth(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
}

export function isAuthenticated(): boolean {
  return !!getAccessToken();
}

export function isTokenValid(): boolean {
  const token = getAccessToken();
  if (!token) return false;
  try {
    const base64Url = token.split(".")[1];
    if (!base64Url) return false;
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const jsonPayload = decodeURIComponent(
      atob(base64)
        .split("")
        .map((c) => `%${`00${c.charCodeAt(0).toString(16)}`.slice(-2)}`)
        .join(""),
    );
    const decoded = JSON.parse(jsonPayload) as { exp?: number };
    if (!decoded.exp) return false;
    return decoded.exp * 1000 > Date.now() + 10000;
  } catch {
    return false;
  }
}

export function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  return headers;
}

export async function login(credentials: LoginCredentials): Promise<LoginResult> {
  const response = await fetch(apiUrl("/api/auth/login"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(credentials),
  });

  if (!response.ok) {
    let detail = "Login failed";
    try {
      const data = await response.json();
      detail = data.detail || JSON.stringify(data);
    } catch {
      detail = `HTTP ${response.status}: ${response.statusText}`;
    }
    throw new Error(detail);
  }

  const result = (await response.json()) as LoginResult;
  setAccessToken(result.access_token);
  setUser(result.user);
  return result;
}

export async function logout(): Promise<void> {
  const token = getAccessToken();
  if (token) {
    try {
      await fetch(apiUrl("/api/auth/logout"), {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      // ignore network errors on logout
    }
  }
  clearAuth();
}

// ─────────────────────────────────────────────────────────────────────────────
// Dev-only auto-login (disabled in production unless explicitly enabled)
// ─────────────────────────────────────────────────────────────────────────────

const AUTO_LOGIN_ENABLED =
  process.env.NODE_ENV === "development" &&
  process.env.NEXT_PUBLIC_AUTO_LOGIN !== "false";

export function isAutoLoginEnabled(): boolean {
  return AUTO_LOGIN_ENABLED;
}

/**
 * Attempt automatic login with development credentials.
 * Only runs in development mode and when AUTO_LOGIN is not disabled.
 * Returns true if login succeeded, false otherwise.
 */
export async function autoLoginDev(): Promise<boolean> {
  if (!AUTO_LOGIN_ENABLED) return false;
  if (isTokenValid()) return true;

  const email = process.env.NEXT_PUBLIC_DEV_EMAIL;
  const password = process.env.NEXT_PUBLIC_DEV_PASSWORD;

  if (!email || !password) {
    console.warn("Dev auto-login skipped: NEXT_PUBLIC_DEV_EMAIL/PASSWORD not set");
    return false;
  }

  try {
    await login({ email, password });
    if (!isTokenValid()) {
      clearAuth();
      return false;
    }
    return true;
  } catch {
    return false;
  }
}
