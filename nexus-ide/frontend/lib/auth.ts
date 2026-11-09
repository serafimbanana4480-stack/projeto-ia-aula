"use client";

import { apiUrl, ApiError } from "./api";

const TOKEN_KEY = "nexus.access_token";
const REFRESH_TOKEN_KEY = "nexus.refresh_token";
const USER_KEY = "nexus.user";
const REFRESH_REQUEST_ID_KEY = "nexus.refresh.request_id";
const AUTH_REQUEST_TIMEOUT_MS = 10000;
const REFRESH_MAX_ATTEMPTS = 10;
const REFRESH_RETRY_DELAY_MS = 15000;

let refreshInFlight: Promise<boolean> | null = null;

async function fetchAuth(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), AUTH_REQUEST_TIMEOUT_MS);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    throw new ApiError(
      "Failed to connect to the server",
      0,
      error instanceof Error ? error.message : "Unknown error",
    );
  } finally {
    window.clearTimeout(timeoutId);
  }
}

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
  refresh_token?: string;
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

export function getRefreshToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(REFRESH_TOKEN_KEY);
}

export function setRefreshToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(REFRESH_TOKEN_KEY, token);
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
  window.localStorage.removeItem(REFRESH_TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
  window.localStorage.removeItem(REFRESH_REQUEST_ID_KEY);
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

/**
 * Fetch an authenticated resource and transparently retry once after an
 * expired access token is exchanged through the refresh-token endpoint.
 *
 * Requests passed here must have replayable bodies (or no body), because a
 * 401 response may cause the request to be sent a second time.
 */
export async function authenticatedFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  const request = () => {
    const headers = new Headers(init.headers);
    for (const [key, value] of Object.entries(authHeaders())) {
      headers.set(key, value);
    }
    return fetch(input, { ...init, headers });
  };

  try {
    const response = await request();
    if (response.status !== 401) return response;

    if (!(await refreshAuth())) return response;
    return request();
  } catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError(
      "Failed to connect to the server",
      0,
      error instanceof Error ? error.message : "Unknown error",
    );
  }
}

export async function login(credentials: LoginCredentials): Promise<LoginResult> {
  let response: Response;
  try {
    response = await fetchAuth(apiUrl("/api/auth/login"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(credentials),
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(
        `O backend não respondeu a tempo. Confirma que está ativo em ${apiUrl("/")}.`,
      );
    }
    throw error;
  }

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
  if (result.refresh_token) setRefreshToken(result.refresh_token);
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

/**
 * Attempt to obtain a fresh access token using the stored refresh token.
 * Returns true on success (new access token stored), false if the refresh
 * token is missing or rejected by the server. On failure the auth state is
 * cleared so the caller can redirect to login.
 */
function getOrCreateRefreshRequestId(): string {
  try {
    const existing = window.localStorage.getItem(REFRESH_REQUEST_ID_KEY);
    if (existing) return existing;
  } catch {
    // The in-memory ID still keeps this invocation's retries idempotent when
    // storage is unavailable; it simply cannot survive a page reload.
  }

  const generated = window.crypto.randomUUID();
  try {
    window.localStorage.setItem(REFRESH_REQUEST_ID_KEY, generated);
    return window.localStorage.getItem(REFRESH_REQUEST_ID_KEY) || generated;
  } catch {
    return generated;
  }
}

function clearRefreshRequestId(): void {
  try {
    window.localStorage.removeItem(REFRESH_REQUEST_ID_KEY);
  } catch {
    // A stale key is harmless: the server scopes it to the refresh-token JTI.
  }
}

function waitForRefreshRetry(): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, REFRESH_RETRY_DELAY_MS));
}

function isTransientRefreshStatus(status: number): boolean {
  return status === 0 || status === 408 || status === 425 || status === 429 || status >= 500;
}

async function performRefreshAuth(): Promise<boolean> {
  const refreshToken = getRefreshToken();
  if (!refreshToken) return false;

  const requestId = getOrCreateRefreshRequestId();
  let lastError: ApiError | null = null;
  for (let attempt = 1; attempt <= REFRESH_MAX_ATTEMPTS; attempt += 1) {
    let response: Response;
    try {
      response = await fetchAuth(apiUrl("/api/auth/refresh"), {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": requestId,
        },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });
    } catch (error) {
      if (!(error instanceof ApiError) || !isTransientRefreshStatus(error.status)) {
        throw error;
      }
      lastError = error;
      if (attempt === REFRESH_MAX_ATTEMPTS) break;
      await waitForRefreshRetry();
      continue;
    }

    if (response.ok) {
      const result = (await response.json()) as LoginResult;
      if (!result.access_token || !result.refresh_token) {
        throw new ApiError("The server returned an incomplete refresh response", response.status);
      }
      setAccessToken(result.access_token);
      setRefreshToken(result.refresh_token);
      if (result.user) setUser(result.user);
      clearRefreshRequestId();
      return true;
    }

    if (isTransientRefreshStatus(response.status)) {
      let responseText = "";
      try {
        responseText = await response.text();
      } catch {
        responseText = "Unable to read refresh error response";
      }
      lastError = new ApiError(
        `HTTP ${response.status}: ${response.statusText}`,
        response.status,
        responseText,
      );
      if (attempt === REFRESH_MAX_ATTEMPTS) break;
      await waitForRefreshRetry();
      continue;
    }

    if (response.status === 401 || response.status === 403) {
      // Another tab may have rotated the shared refresh token while this tab
      // was waiting. Reuse that fresh session instead of clearing it.
      const currentRefreshToken = getRefreshToken();
      if (currentRefreshToken && currentRefreshToken !== refreshToken && getAccessToken()) {
        clearRefreshRequestId();
        return true;
      }
      clearRefreshRequestId();
      clearAuth();
      return false;
    }

    let responseText = "";
    try {
      responseText = await response.text();
    } catch {
      responseText = "Unable to read refresh error response";
    }
    throw new ApiError(
      `HTTP ${response.status}: ${response.statusText}`,
      response.status,
      responseText,
    );
  }

  // Keep both tokens and the stable request key. A later API call can resume
  // this exchange and recover a response that the server may already have
  // committed.
  throw new ApiError(
    `Refresh failed after ${REFRESH_MAX_ATTEMPTS} attempts`,
    lastError?.status ?? 0,
    lastError?.responseText,
  );
}

export function refreshAuth(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = performRefreshAuth().finally(() => {
    refreshInFlight = null;
  });
  return refreshInFlight;
}

// ─────────────────────────────────────────────────────────────────────────────
// Auto-login stays development-only by default. Local test mode can opt in
// explicitly with NEXT_PUBLIC_AUTO_LOGIN=true, including a production build
// served on localhost; normal deployments remain protected by default.
// ─────────────────────────────────────────────────────────────────────────────

const AUTO_LOGIN_ENABLED =
  process.env.NEXT_PUBLIC_AUTO_LOGIN === "true" ||
  (process.env.NODE_ENV === "development" && process.env.NEXT_PUBLIC_AUTO_LOGIN !== "false");

export function isAutoLoginEnabled(): boolean {
  return AUTO_LOGIN_ENABLED;
}

/**
 * Attempt automatic login with development credentials.
 * Runs only when the explicit local-test opt-in is enabled (or in development
 * mode with the default enabled), never from arbitrary production settings.
 * Returns true if login succeeded, false otherwise.
 */
export async function autoLoginDev(): Promise<boolean> {
  if (!AUTO_LOGIN_ENABLED) return false;
  if (isTokenValid()) {
    // A locally decoded `exp` is not enough after a backend restart: the JWT
    // may still be temporally valid but signed with an old runtime secret.
    // Confirm it server-side before allowing dependent stores to initialize.
    try {
      const response = await fetchAuth(apiUrl("/api/auth/me"), {
        headers: { Authorization: `Bearer ${getAccessToken()}` },
      });
      if (response.ok) return true;
      if (response.status !== 401 && response.status !== 403) {
        throw new ApiError("Não foi possível verificar a sessão", response.status);
      }
    } catch (error) {
      // A temporary backend failure must not erase a potentially valid session.
      throw error;
    }
    clearAuth();
  }

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
