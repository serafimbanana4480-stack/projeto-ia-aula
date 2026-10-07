import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { mockSearch } = vi.hoisted(() => ({ mockSearch: vi.fn() }));

vi.mock("../../../hooks/useChatSessions", () => ({
  useChatSessions: () => ({
    sessions: [
      {
        id: "local-match",
        title: "Deploy project",
        mode: "auto",
        project_id: null,
        created_at: "2026-01-01T00:00:00Z",
        last_active_at: "2026-01-01T00:00:00Z",
        message_count: 3,
      },
    ],
    currentId: "local-match",
    setCurrentId: vi.fn(),
    create: vi.fn(),
    rename: vi.fn(),
    remove: vi.fn(),
    loading: false,
    loadingMore: false,
    hasMore: false,
    total: 1,
    error: null,
    refresh: vi.fn(),
    loadMore: vi.fn(),
  }),
  searchChatSessions: mockSearch,
}));

import SessionList from "../../../components/chat/SessionList";

describe("SessionList search", () => {
  afterEach(() => {
    vi.useRealTimers();
    mockSearch.mockReset();
  });

  it("deduplicates a locally matched session while keeping its message snippet", async () => {
    vi.useFakeTimers();
    mockSearch.mockResolvedValue({
      sessions: [
        {
          id: "local-match",
          title: "Deploy project",
          mode: "auto",
          project_id: null,
          created_at: "2026-01-01T00:00:00Z",
          last_active_at: "2026-01-01T00:00:00Z",
          match_type: "message",
          match_message_id: "message-1",
          snippet: "deploy marker inside this saved message",
        },
        {
          id: "remote-only",
          title: "Old notes",
          mode: "auto",
          project_id: null,
          created_at: "2025-01-01T00:00:00Z",
          last_active_at: "2025-01-01T00:00:00Z",
          match_type: "message",
          match_message_id: "message-2",
          snippet: "matching text outside the loaded list",
        },
      ],
      count: 2,
      total: 2,
      offset: 0,
      limit: 50,
    });

    render(<SessionList />);
    fireEvent.change(screen.getByPlaceholderText("Filtrar..."), {
      target: { value: "deploy" },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(220);
      await Promise.resolve();
    });

    expect(mockSearch).toHaveBeenCalledWith("deploy", 50, 0);
    expect(screen.getAllByText("Deploy project")).toHaveLength(1);
    expect(screen.getByText("deploy marker inside this saved message")).toBeTruthy();
    expect(screen.getByText("Old notes")).toBeTruthy();
  });
});
