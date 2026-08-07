"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { apiUrl } from "./api";
import {
  clearAuth,
  getAccessToken,
  getUser,
  login as loginWithEmail,
  logout as logoutAuth,
  refreshAuth,
} from "./auth";

type LegacyUser = { username: string; role: string; authenticated: boolean };

type AuthContextType = {
  user: LegacyUser;
  token: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  isLoading: boolean;
  error: string | null;
};

const ANONYMOUS: LegacyUser = {
  username: "anonymous",
  role: "guest",
  authenticated: false,
};

const AuthContext = createContext<AuthContextType>({
  user: ANONYMOUS,
  token: null,
  login: async () => {},
  logout: async () => {},
  isLoading: true,
  error: null,
});

function toLegacyUser(data: Record<string, unknown>): LegacyUser {
  return {
    username: String(data.email || data.username || data.full_name || "user"),
    role: String(data.role || "user"),
    authenticated: true,
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<LegacyUser>(() => {
    const stored = getUser();
    return stored ? toLegacyUser(stored as unknown as Record<string, unknown>) : ANONYMOUS;
  });
  const [token, setToken] = useState<string | null>(() => getAccessToken());
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMe = useCallback(async (currentToken: string | null) => {
    if (!currentToken) {
      setUser(ANONYMOUS);
      setIsLoading(false);
      return;
    }

    const requestMe = async () =>
      fetch(apiUrl("/api/auth/me"), {
        headers: { Authorization: `Bearer ${getAccessToken() || currentToken}` },
      });

    try {
      let response = await requestMe();
      if (response.status === 401 && (await refreshAuth())) {
        const refreshed = getAccessToken();
        setToken(refreshed);
        response = await requestMe();
      }
      if (!response.ok) throw new Error("Session expired");
      const data = (await response.json()) as Record<string, unknown>;
      setUser(toLegacyUser(data));
    } catch {
      clearAuth();
      setToken(null);
      setUser(ANONYMOUS);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchMe(token);
  }, [token, fetchMe]);

  async function login(username: string, password: string) {
    setError(null);
    setIsLoading(true);
    try {
      const result = await loginWithEmail({ email: username, password });
      setToken(result.access_token);
      setUser(toLegacyUser(result.user as unknown as Record<string, unknown>));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      throw err;
    } finally {
      setIsLoading(false);
    }
  }

  async function logout() {
    try {
      await logoutAuth();
    } finally {
      clearAuth();
      setToken(null);
      setUser(ANONYMOUS);
    }
  }

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isLoading, error }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
