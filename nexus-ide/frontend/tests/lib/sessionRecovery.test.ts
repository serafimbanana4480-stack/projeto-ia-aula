import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  getSessionRunsPage: vi.fn(),
  replayRunEvents: vi.fn(),
}));

vi.mock("../../lib/api", () => ({ getSessionRunsPage: mocks.getSessionRunsPage }));
vi.mock("../../hooks/useAgentStream", () => ({ replayRunEvents: mocks.replayRunEvents }));

import { restoreRunTimelines } from "../../lib/sessionRecovery";
import type { ChatMessage } from "../../lib/types";

describe("restoreRunTimelines", () => {
  beforeEach(() => {
    mocks.getSessionRunsPage.mockReset();
    mocks.replayRunEvents.mockReset().mockResolvedValue([]);
  });

  it("restores identical answers by run id and uses durable file evidence without a journal", async () => {
    mocks.getSessionRunsPage.mockResolvedValue({ runs: [
      {
        id: "run-second",
        session_id: "session-1",
        status: "completed",
        evidence: { changed_files: ["src/second.ts", " src/second.ts "] },
      },
      {
        id: "run-first",
        session_id: "session-1",
        status: "completed",
        evidence: { changed_files: ["src/first.ts"] },
      },
    ], has_more: false, next_offset: 2 });

    const history: ChatMessage[] = [
      { id: "message-first", runId: "run-first", role: "assistant", content: "Done", timestamp: "1" },
      { id: "message-second", runId: "run-second", role: "assistant", content: "Done", timestamp: "2" },
    ];

    const restored = await restoreRunTimelines(history, "session-1");

    expect(restored[0].metadata?.changedFiles).toEqual(["src/first.ts"]);
    expect(restored[1].metadata?.changedFiles).toEqual(["src/second.ts"]);
    expect(restored[0].activities?.[0]).toMatchObject({
      title: "Execução concluída",
      status: "success",
      data: { run_id: "run-first", source: "persisted_checkpoint" },
    });
    expect(mocks.replayRunEvents).toHaveBeenCalledWith("session-1", "run-first", expect.any(AbortSignal));
    expect(mocks.replayRunEvents).toHaveBeenCalledWith("session-1", "run-second", expect.any(AbortSignal));
  });

  it("keeps persisted messages visible when the optional run endpoint fails", async () => {
    const history: ChatMessage[] = [
      { id: "message-1", role: "assistant", content: "Saved", timestamp: "1" },
    ];
    mocks.getSessionRunsPage.mockRejectedValue(new Error("offline"));

    await expect(restoreRunTimelines(history, "session-1")).resolves.toEqual(history);
  });

  it("recovers a run older than the default 20 and skips runs absent from this page", async () => {
    const runs = Array.from({ length: 25 }, (_, index) => ({
      id: `run-${index}`,
      session_id: "session-1",
      status: "completed",
      evidence: { changed_files: [`src/${index}.ts`] },
    }));
    mocks.getSessionRunsPage.mockResolvedValue({ runs, has_more: false, next_offset: runs.length });
    const history: ChatMessage[] = [
      {
        id: "old-message",
        runId: "run-0",
        role: "assistant",
        content: "The oldest visible answer",
        timestamp: "1",
      },
    ];

    const restored = await restoreRunTimelines(history, "session-1");

    expect(mocks.getSessionRunsPage).toHaveBeenCalledWith("session-1", 100, 0, expect.any(AbortSignal));
    expect(restored[0].metadata?.changedFiles).toEqual(["src/0.ts"]);
    expect(mocks.replayRunEvents).toHaveBeenCalledTimes(1);
    expect(mocks.replayRunEvents).toHaveBeenCalledWith(
      "session-1",
      "run-0",
      expect.any(AbortSignal),
    );
  });

  it("does not replay unrelated runs when the page has no legacy assistant messages", async () => {
    mocks.getSessionRunsPage.mockResolvedValue({ runs: [
      { id: "run-1", session_id: "session-1", status: "completed" },
    ], has_more: false, next_offset: 1 });
    const history: ChatMessage[] = [
      { id: "user-1", role: "user", content: "hello", timestamp: "1" },
    ];

    await expect(restoreRunTimelines(history, "session-1")).resolves.toEqual(history);
    expect(mocks.getSessionRunsPage).not.toHaveBeenCalled();
    expect(mocks.replayRunEvents).not.toHaveBeenCalled();
  });

  it("pages past 100 unrelated checkpoints, stops when visible run ids are found, and replays only them", async () => {
    const firstPage = Array.from({ length: 100 }, (_, index) => ({
      id: `unrelated-${index}`,
      session_id: "session-1",
      status: "completed",
    }));
    const secondPage = [
      { id: "run-old-linked", session_id: "session-1", status: "completed", evidence: { changed_files: ["old.ts"] } },
      { id: "run-new-linked", session_id: "session-1", status: "completed", evidence: { changed_files: ["new.ts"] } },
      { id: "unrelated-after-linked", session_id: "session-1", status: "completed" },
    ];
    mocks.getSessionRunsPage
      .mockResolvedValueOnce({ runs: firstPage, has_more: true, next_offset: 100 })
      .mockResolvedValueOnce({ runs: secondPage, has_more: true, next_offset: 103 });
    const history: ChatMessage[] = [
      { id: "old-message", runId: "run-old-linked", role: "assistant", content: "old", timestamp: "1" },
      { id: "new-message", runId: "run-new-linked", role: "assistant", content: "new", timestamp: "2" },
    ];

    const restored = await restoreRunTimelines(history, "session-1");

    expect(mocks.getSessionRunsPage).toHaveBeenNthCalledWith(1, "session-1", 100, 0, expect.any(AbortSignal));
    expect(mocks.getSessionRunsPage).toHaveBeenNthCalledWith(2, "session-1", 100, 100, expect.any(AbortSignal));
    expect(mocks.getSessionRunsPage).toHaveBeenCalledTimes(2);
    expect(restored[0].metadata?.changedFiles).toEqual(["old.ts"]);
    expect(restored[1].metadata?.changedFiles).toEqual(["new.ts"]);
    expect(mocks.replayRunEvents).toHaveBeenCalledTimes(2);
    expect(mocks.replayRunEvents).toHaveBeenCalledWith("session-1", "run-old-linked", expect.any(AbortSignal));
    expect(mocks.replayRunEvents).toHaveBeenCalledWith("session-1", "run-new-linked", expect.any(AbortSignal));
    expect(mocks.replayRunEvents).not.toHaveBeenCalledWith("session-1", "unrelated-after-linked", expect.anything());
  });

  it("stops at the explicit five-page cap if the requested run is still not found", async () => {
    mocks.getSessionRunsPage.mockImplementation(async (_sessionId: string, _limit: number, offset: number) => ({
      runs: [{ id: `unrelated-${offset}`, session_id: "session-1", status: "completed" }],
      has_more: true,
      next_offset: offset + 100,
    }));
    const history: ChatMessage[] = [
      { id: "old-message", runId: "run-outside-scan-cap", role: "assistant", content: "saved", timestamp: "1" },
    ];

    const restored = await restoreRunTimelines(history, "session-1");

    expect(restored).toEqual(history);
    expect(mocks.getSessionRunsPage).toHaveBeenCalledTimes(5);
    expect(mocks.replayRunEvents).not.toHaveBeenCalled();
  });

  it("applies the recovery deadline to the run-list request too", async () => {
    vi.useFakeTimers();
    try {
      let receivedSignal: AbortSignal | undefined;
      mocks.getSessionRunsPage.mockImplementation(
        (_sessionId: string, _limit: number, _offset: number, signal: AbortSignal) =>
          new Promise((resolve) => {
            receivedSignal = signal;
            signal.addEventListener(
              "abort",
              () => resolve({ runs: [], has_more: false, next_offset: 0 }),
              { once: true },
            );
          }),
      );
      const history: ChatMessage[] = [
        { id: "saved-answer", runId: "run-pending", role: "assistant", content: "Saved", timestamp: "1" },
      ];

      const recovery = restoreRunTimelines(history, "session-1");
      await Promise.resolve();
      expect(receivedSignal).toBeInstanceOf(AbortSignal);

      await vi.advanceTimersByTimeAsync(6_000);
      await expect(recovery).resolves.toEqual(history);
      expect(receivedSignal?.aborted).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });
});
