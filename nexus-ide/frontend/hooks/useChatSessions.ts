"use client";
import { useEffect } from "react";
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

export interface SessionSearchMatch extends ChatSession {
  match_type: "title" | "mode" | "message";
  match_message_id?: string | null;
  snippet?: string | null;
}

export interface SessionSearchResponse {
  sessions: SessionSearchMatch[];
  count: number;
  total: number;
  offset: number;
  limit: number;
}

const SESSION_KEY = "nexus.chat.currentSession";

let refreshPromise: Promise<void> | null = null;
let ensureCurrentSessionPromise: Promise<string | null> | null = null;
let loadMorePromise: Promise<void> | null = null;

interface ChatSessionsState {
  sessions: ChatSession[];
  currentId: string | null;
  loading: boolean;
  initialized: boolean;
  total: number;
  nextOffset: number;
  loadingMore: boolean;
  hasMore: boolean;
  error: string | null;
  // Actions
  setCurrentId: (id: string | null) => void;
  setSessions: (sessions: ChatSession[]) => void;
  setError: (err: string | null) => void;
  setLoading: (loading: boolean) => void;
  refresh: () => Promise<void>;
  loadMore: () => Promise<void>;
  ensureCurrentSession: () => Promise<string | null>;
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
  initialized: false,
  total: 0,
  nextOffset: 0,
  loadingMore: false,
  hasMore: false,
  error: null,

  setCurrentId: (id) => {
    const safeId = id === "default" || id?.startsWith("local-") ? null : id;
    set({ currentId: safeId });
    try {
      if (safeId) localStorage.setItem(SESSION_KEY, safeId);
      else localStorage.removeItem(SESSION_KEY);
    } catch {}
  },

  setSessions: (sessions) => set({ sessions }),
  setError: (error) => set({ error }),
  setLoading: (loading) => set({ loading }),

  refresh: () => {
    if (refreshPromise) return refreshPromise;

    const request = (async () => {
      set({ loading: true });
      try {
        // Let an already-requested next page finish first. If refresh and
        // loadMore race, the older offset response can otherwise overwrite
        // the refreshed cursor and make the next click skip a page.
        if (loadMorePromise) await loadMorePromise;

        const res = await authenticatedFetch(`${API_BASE}/api/sessions?limit=100&offset=0`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const pageSessions: ChatSession[] = Array.isArray(data.sessions) ? data.sessions : [];
        const currentId = get().currentId;
        let storedId: string | null = null;
        try {
          storedId = localStorage.getItem(SESSION_KEY);
        } catch {}

        const preferredId = currentId ?? storedId;
        const retained = get().sessions;
        const retainedById = new Map(retained.map((session) => [session.id, session]));
        const pageIds = new Set(pageSessions.map((session) => session.id));
        let preferredSession =
          pageSessions.find((session) => session.id === preferredId) ??
          retainedById.get(preferredId ?? "");

        // A paged list cannot prove that a saved, older session was deleted.
        // Resolve that id directly so a routine refresh never throws the user
        // out of a conversation merely because it is beyond the first page.
        let preservePreferredId = false;
        if (preferredId && !preferredSession) {
          try {
            const selected = await authenticatedFetch(
              `${API_BASE}/api/sessions/${encodeURIComponent(preferredId)}`,
            );
            if (selected.ok) preferredSession = (await selected.json()) as ChatSession;
            else preservePreferredId = selected.status !== 404;
          } catch {
            // Preserve the selection on a transient detail lookup failure.
            preservePreferredId = true;
          }
        }

        const nextCurrentId =
          preferredSession?.id ??
          (preservePreferredId ? preferredId : null) ??
          pageSessions[0]?.id ??
          null;
        const unseenRetained = retained.filter((session) => !pageIds.has(session.id));
        if (preferredSession && !pageIds.has(preferredSession.id)) {
          retainedById.set(preferredSession.id, preferredSession);
          if (!unseenRetained.some((session) => session.id === preferredSession?.id)) {
            unseenRetained.push(preferredSession);
          }
        }
        const nextSessions = [...pageSessions, ...unseenRetained];
        const total = Number.isFinite(data.total) ? Math.max(0, Number(data.total)) : pageSessions.length;
        const nextOffset = Math.max(
          Number(data.offset ?? 0) + pageSessions.length,
          get().nextOffset,
        );
        set({
          sessions: nextSessions,
          currentId: nextCurrentId,
          total,
          nextOffset,
          hasMore: nextOffset < total,
          error: null,
        });
        try {
          if (nextCurrentId) localStorage.setItem(SESSION_KEY, nextCurrentId);
          else localStorage.removeItem(SESSION_KEY);
        } catch {}
      } catch (e) {
        set({ error: e instanceof Error ? e.message : String(e) });
      } finally {
        set({ loading: false, initialized: true });
      }
    })();

    refreshPromise = request;
    const clearRefresh = () => {
      if (refreshPromise === request) refreshPromise = null;
    };
    void request.then(clearRefresh, clearRefresh);
    return request;
  },

  loadMore: () => {
    if (loadMorePromise) return loadMorePromise;
    const { loading, loadingMore, hasMore } = get();
    if (loading || loadingMore || !hasMore) return Promise.resolve();

    const request = (async () => {
      set({ loadingMore: true });
      try {
        const offset = get().nextOffset;
        const res = await authenticatedFetch(
          `${API_BASE}/api/sessions?limit=100&offset=${offset}`,
        );
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        const page: ChatSession[] = Array.isArray(data.sessions) ? data.sessions : [];
        set((state) => {
          const ids = new Set(state.sessions.map((session) => session.id));
          const additions = page.filter((session) => !ids.has(session.id));
          const responseOffset = Number.isFinite(data.offset) ? Number(data.offset) : offset;
          const nextOffset = Math.max(state.nextOffset, responseOffset + page.length);
          const total = Number.isFinite(data.total) ? Math.max(0, Number(data.total)) : state.total;
          return {
            sessions: [...state.sessions, ...additions],
            total,
            nextOffset,
            hasMore: nextOffset < total,
            error: null,
          };
        });
      } catch (e) {
        set({ error: e instanceof Error ? e.message : String(e) });
      } finally {
        set({ loadingMore: false });
      }
    })();
    loadMorePromise = request;
    const clearLoadMore = () => {
      if (loadMorePromise === request) loadMorePromise = null;
    };
    void request.then(clearLoadMore, clearLoadMore);
    return request;
  },

  ensureCurrentSession: () => {
    const currentId = get().currentId;
    if (currentId && currentId !== "default") return Promise.resolve(currentId);
    if (ensureCurrentSessionPromise) return ensureCurrentSessionPromise;

    const request = (async () => {
      if (!get().initialized || get().loading) await get().refresh();
      const availableId = get().currentId;
      if (availableId && availableId !== "default") return availableId;
      return (await get().create("Nova sessão"))?.id ?? null;
    })();

    ensureCurrentSessionPromise = request;
    const clearEnsure = () => {
      if (ensureCurrentSessionPromise === request) ensureCurrentSessionPromise = null;
    };
    void request.then(clearEnsure, clearEnsure);
    return request;
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
        sessions: [session, ...s.sessions.filter((existing) => existing.id !== session.id)],
        currentId: session.id,
        total: Math.max(s.total + 1, s.sessions.length + 1),
        hasMore: s.nextOffset < Math.max(s.total + 1, s.sessions.length + 1),
        error: null,
      }));
      try {
        localStorage.setItem(SESSION_KEY, session.id);
      } catch {}
      return session;
    } catch (e) {
      set({ error: e instanceof Error ? e.message : String(e) });
      return null;
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
    const remaining = get().sessions.filter((session) => session.id !== id);
    const nextCurrentId = currentId === id ? remaining[0]?.id ?? null : currentId;
    set({ sessions: remaining, currentId: nextCurrentId });
    if (currentId === id) {
      try {
        if (nextCurrentId) localStorage.setItem(SESSION_KEY, nextCurrentId);
        else localStorage.removeItem(SESSION_KEY);
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
  const initialized = useChatSessionsStore((s) => s.initialized);
  const total = useChatSessionsStore((s) => s.total);
  const loadingMore = useChatSessionsStore((s) => s.loadingMore);
  const hasMore = useChatSessionsStore((s) => s.hasMore);
  const error = useChatSessionsStore((s) => s.error);
  const setCurrentId = useChatSessionsStore((s) => s.setCurrentId);
  const refresh = useChatSessionsStore((s) => s.refresh);
  const loadMore = useChatSessionsStore((s) => s.loadMore);
  const ensureCurrentSession = useChatSessionsStore((s) => s.ensureCurrentSession);
  const create = useChatSessionsStore((s) => s.create);
  const rename = useChatSessionsStore((s) => s.rename);
  const remove = useChatSessionsStore((s) => s.remove);

  // Initial load + auto-refresh every 30s
  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 30_000);
    return () => clearInterval(id);
    // refresh is a stable Zustand action; the store coalesces simultaneous callers.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    sessions,
    currentId,
    setCurrentId,
    create,
    rename,
    remove,
    loading,
    initialized,
    total,
    loadingMore,
    hasMore,
    error,
    refresh,
    loadMore,
    ensureCurrentSession,
  };
}

export async function searchChatSessions(
  query: string,
  limit = 50,
  offset = 0,
): Promise<SessionSearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit), offset: String(offset) });
  const response = await authenticatedFetch(`${API_BASE}/api/sessions/search?${params}`);
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  return {
    sessions: Array.isArray(data.sessions) ? data.sessions : [],
    count: Number(data.count ?? 0),
    total: Number(data.total ?? 0),
    offset: Number(data.offset ?? offset),
    limit: Number(data.limit ?? limit),
  };
}

export { useChatSessions as useChatSessionsDefault };
