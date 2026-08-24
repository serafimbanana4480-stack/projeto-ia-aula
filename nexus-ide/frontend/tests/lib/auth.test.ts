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
} from "../../lib/auth";

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
});
