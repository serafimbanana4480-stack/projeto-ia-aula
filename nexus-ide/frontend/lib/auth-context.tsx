"use client";

import React, { createContext, useContext, useEffect, useState, useCallback } from "react";
import { apiUrl } from "./api";

type User = { username: string; role: string; authenticated: boolean };

type AuthContextType = {
  user: User;
  token: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  isLoading: boolean;
  error: string | null;
};

const AuthContext = createContext<AuthContextType>({
  user: { username: "anonymous", role: "guest", authenticated: false },
  token: null,
  login: async () => {},
  logout: async () => {},
  isLoading: true,
  error: null,
});

function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("nexus_token");
}

function setStoredToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) localStorage.setItem("nexus_token", token);
  else localStorage.removeItem("nexus_token");
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User>({
    username: "anonymous",
    role: "guest",
    authenticated: false,
  });
  const [token, setToken] = useState<string | null>(getStoredToken);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchMe = useCallback(async (currentToken: string | null) => {
    if (!currentToken) {
      setUser({ username: "anonymous", role: "guest", authenticated: false });
      setIsLoading(false);
      return;
    }
    try {
          const res = await fetch(apiUrl("/api/auth/me"), {
            headers: { Authorization: `Bearer ${currentToken}` },
          });
      if (!res.ok) throw new Error("Session expired");
      const data = await res.json();
      if (data.authenticated) {
        setUser({
          username: data.username || "unknown",
          role: data.role || "user",
          authenticated: true,
        });
      } else {
        setStoredToken(null);
        setToken(null);
        setUser({ username: "anonymous", role: "guest", authenticated: false });
      }
    } catch {
      setStoredToken(null);
      setToken(null);
      setUser({ username: "anonymous", role: "guest", authenticated: false });
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchMe(token);
  }, [token, fetchMe]);

  async function login(username: string, password: string) {
    setError(null);
    setIsLoading(true);
    try {
      const res = await fetch(apiUrl("/api/auth/login"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      const data = await res.json();
      if (!res.ok) {
        throw new Error(data.detail || "Login failed");
      }
      setStoredToken(data.access_token);
      setToken(data.access_token);
      setUser({
        username: data.username || username,
        role: data.role || "user",
        authenticated: true,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
      throw err;
    } finally {
      setIsLoading(false);
    }
  }

  async function logout() {
    try {
      const currentToken = getStoredToken();
      if (currentToken) {
              await fetch(apiUrl("/api/auth/logout"), {
                method: "POST",
                headers: { Authorization: `Bearer ${currentToken}` },
              });
      }
    } catch {
      // ignore logout errors
    } finally {
      setStoredToken(null);
      setToken(null);
      setUser({ username: "anonymous", role: "guest", authenticated: false });
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
