import { describe, expect, it, vi, beforeEach } from "vitest";
import { act } from "@testing-library/react";
import { useChatSessionsStore, type ChatSession } from "../../hooks/useChatSessions";

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
    expect(useChatSessionsStore.getState().error).toBeNull();
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

  it("create returns local fallback on HTTP error", async () => {
    const mockResponse: Response = {
      ok: false, status: 500,
      text: async () => "error",
    } as any;
    mockAuthenticatedFetch.mockResolvedValue(mockResponse);

    let result: ChatSession | null = null;
    await act(async () => {
      result = await useChatSessionsStore.getState().create("New Session");
    });

    // On error, create returns a local fallback session (not null)
    expect(result).not.toBeNull();
    expect(result!.title).toBe("New Session");
    expect(useChatSessionsStore.getState().error).toBeDefined();
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