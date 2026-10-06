import { describe, expect, it, vi, beforeEach } from "vitest";
import { act } from "@testing-library/react";
import {
  searchChatSessions,
  useChatSessionsStore,
  type ChatSession,
} from "../../hooks/useChatSessions";

const { mockAuthenticatedFetch } = vi.hoisted(() => ({
  mockAuthenticatedFetch: vi.fn(),
}));
vi.mock("../../lib/auth", () => ({
  authenticatedFetch: mockAuthenticatedFetch,
  authHeaders: vi.fn(() => ({})),
  getAccessToken: vi.fn(),
  clearAuth: vi.fn(),
  refreshAuth: vi.fn(),
}));

function makeSession(overrides: Partial<ChatSession> = {}): ChatSession {
  return {
    id: "s1",
    title: "Session 1",
    mode: "auto",
    project_id: null,
    created_at: "2025-01-01T00:00:00Z",
    last_active_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

describe("useChatSessionsStore", () => {
  beforeEach(() => {
    mockAuthenticatedFetch.mockReset();
    act(() => {
      useChatSessionsStore.setState({
        sessions: [],
        currentId: null,
        loading: false,
        initialized: false,
        total: 0,
        nextOffset: 0,
        loadingMore: false,
        hasMore: false,
        error: null,
      });
    });
    localStorage.clear();
  });

  it("starts with empty sessions", () => {
    expect(useChatSessionsStore.getState().sessions).toEqual([]);
  });

  it("starts with null currentId", () => {
    expect(useChatSessionsStore.getState().currentId).toBeNull();
  });

  it("starts not loading", () => {
    expect(useChatSessionsStore.getState().loading).toBe(false);
  });

  it("does not treat the default sentinel as a session", () => {
    act(() => {
      useChatSessionsStore.getState().setCurrentId("default");
    });
    expect(useChatSessionsStore.getState().currentId).toBeNull();
    expect(localStorage.getItem("nexus.chat.currentSession")).toBeNull();
  });

  it("starts with null error", () => {
    expect(useChatSessionsStore.getState().error).toBeNull();
  });

  it("setCurrentId sets current id and persists to localStorage", () => {
    act(() => {
      useChatSessionsStore.getState().setCurrentId("s1");
    });
    expect(useChatSessionsStore.getState().currentId).toBe("s1");
    expect(localStorage.getItem("nexus.chat.currentSession")).toBe("s1");
  });

  it("setCurrentId with null removes from localStorage", () => {
    act(() => {
      useChatSessionsStore.getState().setCurrentId("s1");
      useChatSessionsStore.getState().setCurrentId(null);
    });
    expect(useChatSessionsStore.getState().currentId).toBeNull();
    expect(localStorage.getItem("nexus.chat.currentSession")).toBeNull();
  });

  it("setSessions replaces sessions list", () => {
    const sessions = [makeSession(), makeSession({ id: "s2" })];
    act(() => {
      useChatSessionsStore.getState().setSessions(sessions);
    });
    expect(useChatSessionsStore.getState().sessions).toHaveLength(2);
  });

  it("setError sets error message", () => {
    act(() => {
      useChatSessionsStore.getState().setError("Failed to load");
    });
    expect(useChatSessionsStore.getState().error).toBe("Failed to load");
  });

  it("setLoading sets loading state", () => {
    act(() => {
      useChatSessionsStore.getState().setLoading(true);
    });
    expect(useChatSessionsStore.getState().loading).toBe(true);
  });

  it("refresh fetches sessions from API", async () => {
    mockAuthenticatedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ sessions: [makeSession(), makeSession({ id: "s2" })] }),
    });

    await act(async () => {
      await useChatSessionsStore.getState().refresh();
    });

    expect(useChatSessionsStore.getState().sessions).toHaveLength(2);
    expect(useChatSessionsStore.getState().loading).toBe(false);
    expect(useChatSessionsStore.getState().initialized).toBe(true);
    expect(useChatSessionsStore.getState().error).toBeNull();
  });

  it("loads the next session page without adding duplicates", async () => {
    const first = [makeSession({ id: "s1" }), makeSession({ id: "s2" })];
    const next = [makeSession({ id: "s2" }), makeSession({ id: "s3" })];
    act(() => {
      useChatSessionsStore.setState({
        sessions: first,
        initialized: true,
        total: 3,
        nextOffset: 2,
        hasMore: true,
      });
    });
    mockAuthenticatedFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ sessions: next, total: 3, offset: 2 }),
    });

    await act(async () => {
      await useChatSessionsStore.getState().loadMore();
    });

    expect(useChatSessionsStore.getState().sessions.map((session) => session.id)).toEqual([
      "s1",
      "s2",
      "s3",
    ]);
    expect(useChatSessionsStore.getState().nextOffset).toBe(4);
    expect(useChatSessionsStore.getState().hasMore).toBe(false);
    expect(String(mockAuthenticatedFetch.mock.calls[0][0])).toContain("offset=2");
  });

  it("finishes an in-flight page before refreshing and keeps the cursor advanced", async () => {
    let resolvePage: ((value: unknown) => void) | undefined;
    const pageResponse = new Promise((resolve) => {
      resolvePage = resolve;
    });
    act(() => {
      useChatSessionsStore.setState({
        sessions: [makeSession({ id: "s1" }), makeSession({ id: "s2" })],
        initialized: true,
        total: 4,
        nextOffset: 2,
        hasMore: true,
      });
    });
    mockAuthenticatedFetch
      .mockReturnValueOnce(pageResponse)
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          sessions: [makeSession({ id: "s1" }), makeSession({ id: "s2" })],
          total: 4,
          offset: 0,
        }),
      });

    let loadingPage: Promise<void> | undefined;
    let refreshing: Promise<void> | undefined;
    act(() => {
      loadingPage = useChatSessionsStore.getState().loadMore();
      refreshing = useChatSessionsStore.getState().refresh();
    });
    expect(mockAuthenticatedFetch).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolvePage?.({
        ok: true,
        json: async () => ({
          sessions: [makeSession({ id: "s3" }), makeSession({ id: "s4" })],
          total: 4,
          offset: 2,
        }),
      });
      await Promise.all([loadingPage, refreshing]);
    });

    expect(mockAuthenticatedFetch).toHaveBeenCalledTimes(2);
    expect(useChatSessionsStore.getState().sessions.map((session) => session.id)).toEqual([
      "s1",
      "s2",
      "s3",
      "s4",
    ]);
    expect(useChatSessionsStore.getState().nextOffset).toBe(4);
    expect(useChatSessionsStore.getState().hasMore).toBe(false);
  });

  it("searches persisted sessions and returns the source match label", async () => {
    mockAuthenticatedFetch.mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        sessions: [
          {
            ...makeSession({ id: "s-message" }),
            match_type: "message",
            match_message_id: "m1",
            snippet: "found in persisted message",
          },
        ],
        count: 1,
        total: 1,
        offset: 0,
        limit: 50,
      }),
    });

    const result = await searchChatSessions("finding_%", 50, 0);
    const url = new URL(String(mockAuthenticatedFetch.mock.calls[0][0]));
    expect(url.pathname).toBe("/api/sessions/search");
    expect(url.searchParams.get("q")).toBe("finding_%");
    expect(result.sessions[0]).toMatchObject({
      id: "s-message",
      match_type: "message",
      snippet: "found in persisted message",
    });
  });

  it("restores a saved session only when the server returns that session", async () => {
    localStorage.setItem("nexus.chat.currentSession", "s2");
    mockAuthenticatedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ sessions: [makeSession(), makeSession({ id: "s2" })] }),
    });

    await act(async () => {
      await useChatSessionsStore.getState().refresh();
    });

    expect(useChatSessionsStore.getState().currentId).toBe("s2");
  });

  it("chooses a real session instead of a stale saved id", async () => {
    localStorage.setItem("nexus.chat.currentSession", "deleted-session");
    mockAuthenticatedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ sessions: [makeSession()] }),
    });

    await act(async () => {
      await useChatSessionsStore.getState().refresh();
    });

    expect(useChatSessionsStore.getState().currentId).toBe("s1");
  });

  it("ensures one session after an empty list and coalesces simultaneous callers", async () => {
    mockAuthenticatedFetch
      .mockResolvedValueOnce({ ok: true, json: async () => ({ sessions: [] }) })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({
          id: "new-session",
          title: "Nova sessão",
          mode: "auto",
          project_id: null,
          created_at: "t1",
          last_active_at: "t1",
        }),
      });

    let ids: Array<string | null> = [];
    await act(async () => {
      ids = await Promise.all([
        useChatSessionsStore.getState().ensureCurrentSession(),
        useChatSessionsStore.getState().ensureCurrentSession(),
      ]);
    });

    expect(ids).toEqual(["new-session", "new-session"]);
    expect(mockAuthenticatedFetch).toHaveBeenCalledTimes(2);
    expect(useChatSessionsStore.getState().currentId).toBe("new-session");
  });

  it("refresh handles HTTP error", async () => {
    mockAuthenticatedFetch.mockResolvedValue({ ok: false, status: 500 });

    await act(async () => {
      await useChatSessionsStore.getState().refresh();
    });

    expect(useChatSessionsStore.getState().error).toBeDefined();
    expect(useChatSessionsStore.getState().loading).toBe(false);
  });

  it("refresh handles network error", async () => {
    mockAuthenticatedFetch.mockRejectedValue(new Error("Network error"));

    await act(async () => {
      await useChatSessionsStore.getState().refresh();
    });

    expect(useChatSessionsStore.getState().error).toBeDefined();
    expect(useChatSessionsStore.getState().loading).toBe(false);
  });

  it("create creates a new session", async () => {
    mockAuthenticatedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ id: "new-session", title: "Created", mode: "auto", project_id: null, created_at: "t1", last_active_at: "t1" }),
    });

    let result: ChatSession | null = null;
    await act(async () => {
      result = await useChatSessionsStore.getState().create("New Session");
    });

    expect(result).toMatchObject({ id: "new-session", title: "Created" });
  });

  it("create sends POST with title and mode", async () => {
    mockAuthenticatedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ id: "new", title: "Test", mode: "deep", project_id: null, created_at: "t", last_active_at: "t" }),
    });

    await act(async () => {
      await useChatSessionsStore.getState().create("Test", "deep");
    });

    const [url, init] = mockAuthenticatedFetch.mock.calls[0];
    expect(url).toContain("/api/sessions");
    expect(init.method).toBe("POST");
    const body = JSON.parse(init.body);
    expect(body.title).toBe("Test");
    expect(body.mode).toBe("deep");
  });

  it("does not invent a local session when creation fails", async () => {
    const mockResponse: Response = {
      ok: false, status: 500,
      text: async () => "error",
    } as any;
    mockAuthenticatedFetch.mockResolvedValue(mockResponse);

    let result: ChatSession | null = null;
    await act(async () => {
      result = await useChatSessionsStore.getState().create("New Session");
    });

    expect(result).toBeNull();
    expect(useChatSessionsStore.getState().currentId).toBeNull();
    expect(localStorage.getItem("nexus.chat.currentSession")).toBeNull();
    expect(useChatSessionsStore.getState().error).toBeDefined();
  });

  it("leaves the session unset when initial recovery and creation both fail", async () => {
    mockAuthenticatedFetch
      .mockResolvedValueOnce({ ok: true, json: async () => ({ sessions: [] }) })
      .mockResolvedValueOnce({ ok: false, status: 503, text: async () => "offline" });

    let result: string | null = "default";
    await act(async () => {
      result = await useChatSessionsStore.getState().ensureCurrentSession();
    });

    expect(result).toBeNull();
    expect(useChatSessionsStore.getState().currentId).toBeNull();
    expect(localStorage.getItem("nexus.chat.currentSession")).toBeNull();
    expect(useChatSessionsStore.getState().error).toContain("503");
  });

  it("rename updates session title", async () => {
    mockAuthenticatedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ id: "s1", title: "Renamed", mode: "auto", project_id: null, created_at: "t1", last_active_at: "t1" }),
    });

    let result: ChatSession | null = null;
    await act(async () => {
      result = await useChatSessionsStore.getState().rename("s1", "New Title");
    });

    expect(result).toMatchObject({ id: "s1", title: "Renamed" });
  });

  it("rename sends PATCH request", async () => {
    mockAuthenticatedFetch.mockResolvedValue({
      ok: true,
      json: async () => ({ id: "s1", title: "New Title", mode: "auto", project_id: null, created_at: "t", last_active_at: "t" }),
    });

    await act(async () => {
      await useChatSessionsStore.getState().rename("s1", "New Title");
    });

    const [url, init] = mockAuthenticatedFetch.mock.calls[0];
    expect(url).toContain("/api/sessions/s1");
    expect(init.method).toBe("PATCH");
  });

  it("remove deletes a session", async () => {
    mockAuthenticatedFetch.mockResolvedValue({ ok: true });

    act(() => {
      useChatSessionsStore.getState().setSessions([makeSession()]);
    });

    await act(async () => {
      await useChatSessionsStore.getState().remove("s1");
    });

    expect(useChatSessionsStore.getState().sessions).toHaveLength(0);
  });

  it("persists session to localStorage", () => {
    localStorage.setItem("nexus.chat.currentSession", "stored-id");
    expect(localStorage.getItem("nexus.chat.currentSession")).toBe("stored-id");
  });
});
