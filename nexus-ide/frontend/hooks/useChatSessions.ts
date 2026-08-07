"use client";
import { useEffect, useRef } from "react";
import { create } from "zustand";
import { authenticatedFetch } from "../lib/auth";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface ChatSession {
  id: string;
  title: string;
  mode: string;
  project_id: string | null;
  created_at: string;
  last_active_at: string;
  message_count?: number;
}

const SESSION_KEY = "nexus.chat.currentSession";

interface ChatSessionsState {
  sessions: ChatSession[];
  currentId: string | null;
  loading: boolean;
  error: string | null;
  // Actions
  setCurrentId: (id: string | null) => void;
  setSessions: (sessions: ChatSession[]) => void;
  setError: (err: string | null) => void;
  setLoading: (loading: boolean) => void;
  refresh: () => Promise<void>;
  create: (title?: string, mode?: string) => Promise<ChatSession | null>;
  rename: (id: string, title: string) => Promise<ChatSession | null>;
  remove: (id: string) => Promise<void>;
}

/**
 * Shared Zustand store for chat sessions so SessionList and ChatPanel
 * stay in sync. Replaces the previous per-component useState implementation
 * which created two independent state stores — clicking a session in the
 * sidebar would not propagate to the chat panel because each component
 * held its own copy of the data.
 */
export const useChatSessionsStore = create<ChatSessionsState>((set, get) => ({
  sessions: [],
  currentId: null,
  loading: false,
  error: null,

  setCurrentId: (id) => {
    set({ currentId: id });
    try {
      if (id) localStorage.setItem(SESSION_KEY, id);
      else localStorage.removeItem(SESSION_KEY);
    } catch {}
  },

  setSessions: (sessions) => set({ sessions }),
  setError: (error) => set({ error }),
  setLoading: (loading) => set({ loading }),

  refresh: async () => {
    set({ loading: true });
    try {
      const res = await authenticatedFetch(`${API_BASE}/api/sessions?limit=100`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      set({ sessions: data.sessions || [], error: null });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
    } finally {
      set({ loading: false });
    }
  },

  create: async (title: string = "Nova sessão", mode: string = "auto") => {
    try {
      const res = await authenticatedFetch(`${API_BASE}/api/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, mode }),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`HTTP ${res.status}: ${txt}`);
      }
      const session = (await res.json()) as ChatSession;
      set((s) => ({
        sessions: [session, ...s.sessions],
        currentId: session.id,
      }));
      try {
        localStorage.setItem(SESSION_KEY, session.id);
      } catch {}
      return session;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      const localId = `local-${Date.now()}`;
      set({ currentId: localId });
      try {
        localStorage.setItem(SESSION_KEY, localId);
      } catch {}
      return {
        id: localId,
        title,
        mode,
        project_id: null,
        created_at: new Date().toISOString(),
        last_active_at: new Date().toISOString(),
        message_count: 0,
      };
    }
  },

  rename: async (id: string, title: string) => {
    try {
      const res = await authenticatedFetch(`${API_BASE}/api/sessions/${id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const updated = (await res.json()) as ChatSession;
      set((s) => ({
        sessions: s.sessions.map((sess) => (sess.id === id ? updated : sess)),
      }));
      return updated;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return null;
    }
  },

  remove: async (id: string) => {
    try {
      const res = await authenticatedFetch(`${API_BASE}/api/sessions/${id}`, {
        method: "DELETE",
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
    }
    const { currentId } = get();
    set((s) => ({
      sessions: s.sessions.filter((sess) => sess.id !== id),
      currentId: currentId === id ? null : currentId,
    }));
    if (currentId === id) {
      try {
        localStorage.removeItem(SESSION_KEY);
      } catch {}
    }
  },
}));

/**
 * Convenience hook that returns the store state + stable action references.
 * The store itself is a singleton, so all consumers see the same data.
 */
export function useChatSessions() {
  const sessions = useChatSessionsStore((s) => s.sessions);
  const currentId = useChatSessionsStore((s) => s.currentId);
  const loading = useChatSessionsStore((s) => s.loading);
  const error = useChatSessionsStore((s) => s.error);
  const setCurrentId = useChatSessionsStore((s) => s.setCurrentId);
  const refresh = useChatSessionsStore((s) => s.refresh);
  const create = useChatSessionsStore((s) => s.create);
  const rename = useChatSessionsStore((s) => s.rename);
  const remove = useChatSessionsStore((s) => s.remove);

  const initializedRef = useRef(false);

  // Load active session id from localStorage on mount
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const stored = localStorage.getItem(SESSION_KEY);
      if (stored && !currentId) {
        setCurrentId(stored);
      }
    } catch {}
  }, [currentId, setCurrentId]);

  // Initial load + auto-refresh every 30s
  useEffect(() => {
    if (initializedRef.current) return;
    initializedRef.current = true;
    void refresh();
    const id = setInterval(() => void refresh(), 30_000);
    return () => clearInterval(id);
    // refresh is a stable Zustand action; we deliberately run only on mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-run refresh when the active session changes so message counts
  // and last_active_at stay fresh.
  useEffect(() => {
    if (!currentId) return;
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentId]);

  return { sessions, currentId, setCurrentId, create, rename, remove, loading, error, refresh };
}

export { useChatSessions as useChatSessionsDefault };
