import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  getAccessToken,
  setAccessToken,
  getRefreshToken,
  setRefreshToken,
  setUser,
  getUser,
  clearAuth,
  isAuthenticated,
  isTokenValid,
  authHeaders,
  refreshAuth,
} from "../../lib/auth";
import { webSearch } from "../../lib/api";

const TOKEN_KEY = "nexus.access_token";
const REFRESH_TOKEN_KEY = "nexus.refresh_token";
const USER_KEY = "nexus.user";

// Helper to create a fake JWT token for testing
function makeFakeJWT(payload: Record<string, unknown>): string {
  const header = btoa(JSON.stringify({ alg: "HS256", typ: "JWT" }));
  const body = btoa(JSON.stringify(payload));
  const signature = "fake-signature";
  return `${header}.${body}.${signature}`;
}

describe("lib/auth", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    localStorage.clear();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe("token management", () => {
    it("getAccessToken returns null when no token stored", () => {
      expect(getAccessToken()).toBeNull();
    });

    it("setAccessToken stores token in localStorage", () => {
      setAccessToken("my-token");
      expect(localStorage.getItem(TOKEN_KEY)).toBe("my-token");
    });

    it("getAccessToken returns stored token", () => {
      setAccessToken("my-token");
      expect(getAccessToken()).toBe("my-token");
    });

    it("setAccessToken overwrites existing token", () => {
      setAccessToken("token1");
      setAccessToken("token2");
      expect(getAccessToken()).toBe("token2");
    });
  });

  describe("refresh token", () => {
    it("getRefreshToken returns null when no token stored", () => {
      expect(getRefreshToken()).toBeNull();
    });

    it("setRefreshToken stores token", () => {
      setRefreshToken("refresh-token");
      expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBe("refresh-token");
    });

    it("getRefreshToken returns stored token", () => {
      setRefreshToken("refresh-token");
      expect(getRefreshToken()).toBe("refresh-token");
    });
  });

  describe("user management", () => {
    it("getUser returns null when no user stored", () => {
      expect(getUser()).toBeNull();
    });

    it("setUser stores user as JSON", () => {
      const user = { id: "u1", email: "test@test.com", full_name: "Test User", is_active: true, created_at: "2025" };
      setUser(user);
      expect(localStorage.getItem(USER_KEY)).toBe(JSON.stringify(user));
    });

    it("getUser returns parsed user", () => {
      const user = { id: "u1", email: "test@test.com", full_name: "Test User", is_active: true, created_at: "2025" };
      setUser(user);
      const retrieved = getUser();
      expect(retrieved).toEqual(user);
    });

    it("getUser returns null on invalid JSON", () => {
      localStorage.setItem(USER_KEY, "invalid-json");
      expect(getUser()).toBeNull();
    });
  });

  describe("clearAuth", () => {
    it("removes all auth tokens and user", () => {
      setAccessToken("token");
      setRefreshToken("refresh");
      setUser({ id: "u1", email: "t@t.com", full_name: "Test", is_active: true, created_at: "2025" });

      clearAuth();

      expect(localStorage.getItem(TOKEN_KEY)).toBeNull();
      expect(localStorage.getItem(REFRESH_TOKEN_KEY)).toBeNull();
      expect(localStorage.getItem(USER_KEY)).toBeNull();
    });
  });

  describe("isAuthenticated", () => {
    it("returns false when no token", () => {
      expect(isAuthenticated()).toBe(false);
    });

    it("returns true when token exists", () => {
      setAccessToken("token");
      expect(isAuthenticated()).toBe(true);
    });
  });

  describe("isTokenValid", () => {
    it("returns false when no token", () => {
      expect(isTokenValid()).toBe(false);
    });

    it("returns false for invalid token format", () => {
      setAccessToken("invalid-token");
      expect(isTokenValid()).toBe(false);
    });

    it("returns false for token without exp claim", () => {
      const token = makeFakeJWT({ sub: "user1" });
      setAccessToken(token);
      expect(isTokenValid()).toBe(false);
    });

    it("returns true for valid future-expiring token", () => {
      const token = makeFakeJWT({ exp: Math.floor(Date.now() / 1000) + 3600 });
      setAccessToken(token);
      expect(isTokenValid()).toBe(true);
    });

    it("returns false for expired token", () => {
      const token = makeFakeJWT({ exp: Math.floor(Date.now() / 1000) - 3600 });
      setAccessToken(token);
      expect(isTokenValid()).toBe(false);
    });

    it("returns false for token expiring in less than 10 seconds", () => {
      const exp = Math.floor(Date.now() / 1000) + 5;
      const token = makeFakeJWT({ exp });
      setAccessToken(token);
      expect(isTokenValid()).toBe(false);
    });
  });

  describe("authHeaders", () => {
    it("returns Content-Type without Authorization when no token", () => {
      const headers = authHeaders();
      expect(headers["Content-Type"]).toBe("application/json");
      expect(headers.Authorization).toBeUndefined();
    });

    it("includes Authorization header when token exists", () => {
      setAccessToken("my-token");
      const headers = authHeaders();
      expect(headers.Authorization).toBe("Bearer my-token");
    });
  });

  it("refreshes auth and retries the web search request after a 401", async () => {
    setAccessToken("expired-access-token");
    setRefreshToken("refresh-token-1");
    const user = {
      id: "u1",
      email: "test@test.com",
      full_name: "Test User",
      is_active: true,
      created_at: "2025",
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "expired" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        access_token: "fresh-access-token",
        refresh_token: "refresh-token-2",
        token_type: "bearer",
        user,
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        query: "capacete",
        hits: [],
        count: 0,
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));

    await expect(webSearch({ query: "capacete" })).resolves.toEqual({
      query: "capacete",
      hits: [],
      count: 0,
    });
    expect(fetchSpy).toHaveBeenCalledTimes(3);
    expect(fetchSpy.mock.calls[0][0]).toBe("http://localhost:8000/api/web_search");
    expect(new Headers(fetchSpy.mock.calls[0][1]?.headers).get("Authorization"))
      .toBe("Bearer expired-access-token");
    expect(fetchSpy.mock.calls[1][0]).toBe("http://localhost:8000/api/auth/refresh");
    expect(fetchSpy.mock.calls[2][0]).toBe("http://localhost:8000/api/web_search");
    expect(new Headers(fetchSpy.mock.calls[2][1]?.headers).get("Authorization"))
      .toBe("Bearer fresh-access-token");
  });

  it("retries a transient refresh failure after 15 seconds with the same request key", async () => {
    vi.useFakeTimers();
    setAccessToken("expired-access-token");
    setRefreshToken("refresh-token-1");
    localStorage.setItem("nexus.refresh.request_id", "stable-refresh-request-id");
    const user = {
      id: "u1",
      email: "test@test.com",
      full_name: "Test User",
      is_active: true,
      created_at: "2025",
    };
    const fetchSpy = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("temporary outage", { status: 503 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({
        access_token: "fresh-access-token",
        refresh_token: "refresh-token-2",
        token_type: "bearer",
        user,
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }));

    const refresh = refreshAuth();
    await Promise.resolve();
    await Promise.resolve();
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(getRefreshToken()).toBe("refresh-token-1");

    await vi.advanceTimersByTimeAsync(14999);
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    await expect(refresh).resolves.toBe(true);

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const firstInit = fetchSpy.mock.calls[0][1];
    const secondInit = fetchSpy.mock.calls[1][1];
    expect(JSON.parse(String(firstInit?.body))).toEqual({ refresh_token: "refresh-token-1" });
    expect(JSON.parse(String(secondInit?.body))).toEqual({ refresh_token: "refresh-token-1" });
    expect(new Headers(firstInit?.headers).get("Idempotency-Key"))
      .toBe("stable-refresh-request-id");
    expect(new Headers(secondInit?.headers).get("Idempotency-Key"))
      .toBe("stable-refresh-request-id");
    expect(getAccessToken()).toBe("fresh-access-token");
    expect(getRefreshToken()).toBe("refresh-token-2");
    expect(localStorage.getItem("nexus.refresh.request_id")).toBeNull();
  });

  it("stops after ten transient refresh attempts without clearing the session", async () => {
    vi.useFakeTimers();
    setAccessToken("expired-access-token");
    setRefreshToken("refresh-token-1");
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response("temporary outage", { status: 503 }),
    );

    const refresh = refreshAuth();
    const rejected = expect(refresh).rejects.toThrow("Refresh failed after 10 attempts");
    await Promise.resolve();
    await Promise.resolve();
    await vi.advanceTimersByTimeAsync(9 * 15000);

    await rejected;
    expect(fetchSpy).toHaveBeenCalledTimes(10);
    expect(getAccessToken()).toBe("expired-access-token");
    expect(getRefreshToken()).toBe("refresh-token-1");
    expect(localStorage.getItem("nexus.refresh.request_id")).toBeTruthy();
  });
});
