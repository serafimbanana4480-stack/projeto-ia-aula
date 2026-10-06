import { describe, expect, it, beforeEach } from "vitest";
import {
  RunEventBuffer,
  dedupeAndOrder,
  isOrderable,
  type RuntimeEventLike,
  type OrderedEvent,
} from "../../lib/eventOrdering";

const event = (
  seq: number,
  overrides: Partial<RuntimeEventLike> = {},
): RuntimeEventLike => ({
  run_id: "run-1",
  seq,
  event_id: `e${seq}`,
  type: "status_update",
  ts: 1_700_000_000,
  ...overrides,
});

function makeEvent(
  type: string,
  seq: number,
  eventId: string,
  runId: string = "run-1",
  extra: Record<string, unknown> = {},
): OrderedEvent {
  return {
    type,
    seq,
    event_id: eventId,
    run_id: runId,
    ...extra,
  };
}

describe("event ordering", () => {
  it("restores order when events arrive shuffled", () => {
    const buffer = new RunEventBuffer();
    [3, 1, 4, 2].forEach((seq) => buffer.push(event(seq)));

    expect(buffer.events().map((e) => e.seq)).toEqual([1, 2, 3, 4]);
  });

  it("keeps order when every event shares one coarse timestamp", () => {
    // Reproduces the Windows 15.6 ms timer case: sorting by ts is undefined.
    const buffer = new RunEventBuffer();
    [5, 2, 1, 4, 3].forEach((seq) => buffer.push(event(seq, { ts: 1_700_000_000 })));

    expect(buffer.events().map((e) => e.seq)).toEqual([1, 2, 3, 4, 5]);
  });

  it("drops duplicates delivered by a replay", () => {
    const buffer = new RunEventBuffer();
    expect(buffer.push(event(1))).toBe(true);
    expect(buffer.push(event(1))).toBe(false);
    expect(buffer.events()).toHaveLength(1);
  });

  it("refuses events from a different run", () => {
    const buffer = new RunEventBuffer();
    buffer.push(event(1));
    expect(buffer.push(event(2, { run_id: "run-0", event_id: "old" }))).toBe(false);
    expect(buffer.events().map((e) => e.event_id)).toEqual(["e1"]);
  });

  it("reports the highest rendered seq so a refresh can resume", () => {
    const buffer = new RunEventBuffer();
    [1, 2, 3].forEach((seq) => buffer.push(event(seq)));
    expect(buffer.lastSeq).toBe(3);
  });

  it("detects gaps so the client can request a replay", () => {
    const buffer = new RunEventBuffer();
    [1, 2, 5].forEach((seq) => buffer.push(event(seq)));
    expect(buffer.missingSeqs()).toEqual([3, 4]);
    expect(buffer.hasMissingSeqs()).toBe(true);
    expect(buffer.firstMissingSeq()).toBe(3);
  });

  it("reports no gaps for a complete timeline", () => {
    const buffer = new RunEventBuffer();
    [1, 2, 3].forEach((seq) => buffer.push(event(seq)));
    expect(buffer.missingSeqs()).toEqual([]);
    expect(buffer.hasMissingSeqs()).toBe(false);
    expect(buffer.firstMissingSeq()).toBeNull();
  });

  it("detects the first gap without scanning a large missing range", () => {
    const buffer = new RunEventBuffer();
    buffer.push(event(1_000_000));

    expect(buffer.firstMissingSeq()).toBe(1);
    expect(buffer.hasMissingSeqs()).toBe(true);
  });

  it("advances the contiguous frontier when a replay fills gaps", () => {
    const buffer = new RunEventBuffer();
    [1, 2, 5].forEach((seq) => buffer.push(event(seq)));
    expect(buffer.firstMissingSeq()).toBe(3);

    [3, 4].forEach((seq) => buffer.push(event(seq)));

    expect(buffer.hasMissingSeqs()).toBe(false);
    expect(buffer.firstMissingSeq()).toBeNull();
  });

  it("resets cleanly between runs so stale state cannot leak", () => {
    const buffer = new RunEventBuffer();
    [1, 2, 3].forEach((seq) => buffer.push(event(seq)));
    buffer.reset("run-2");

    expect(buffer.events()).toEqual([]);
    expect(buffer.lastSeq).toBe(0);
    expect(buffer.push(event(1, { run_id: "run-2", event_id: "n1" }))).toBe(true);
  });

  it("still renders legacy events that carry no sequence", () => {
    const legacy = { type: "token", content: "hello" } as RuntimeEventLike;
    expect(isOrderable(legacy)).toBe(false);

    const buffer = new RunEventBuffer();
    buffer.push(event(1));
    buffer.push(legacy);
    expect(buffer.events()).toHaveLength(2);
  });

  it("orders a batch in one call", () => {
    const ordered = dedupeAndOrder([event(2), event(1), event(2)]);
    expect(ordered.map((e) => e.seq)).toEqual([1, 2]);
  });

  // ─── Extended coverage ─────────────────────────────────────────────────

  describe("isOrderable edge cases", () => {
    it("returns false when run_id is missing", () => {
      const e: RuntimeEventLike = { type: "token", seq: 1, event_id: "e1" };
      expect(isOrderable(e)).toBe(false);
    });

    it("returns false when run_id is empty string", () => {
      const e: RuntimeEventLike = { type: "token", run_id: "", seq: 1, event_id: "e1" };
      expect(isOrderable(e)).toBe(false);
    });

    it("returns false when seq is missing", () => {
      const e: RuntimeEventLike = { type: "token", run_id: "r", event_id: "e1" };
      expect(isOrderable(e)).toBe(false);
    });

    it("returns false when seq is not a number", () => {
      const e: RuntimeEventLike = { type: "token", run_id: "r", seq: "1" as any, event_id: "e1" };
      expect(isOrderable(e)).toBe(false);
    });

    it("returns false when seq is NaN", () => {
      const e: RuntimeEventLike = { type: "token", run_id: "r", seq: NaN, event_id: "e1" };
      expect(isOrderable(e)).toBe(false);
    });

    it("returns false when event_id is missing", () => {
      const e: RuntimeEventLike = { type: "token", run_id: "r", seq: 1 };
      expect(isOrderable(e)).toBe(false);
    });

    it("returns false when event_id is empty string", () => {
      const e: RuntimeEventLike = { type: "token", run_id: "r", seq: 1, event_id: "" };
      expect(isOrderable(e)).toBe(false);
    });

    it("returns true for complete event", () => {
      expect(isOrderable(makeEvent("token", 1, "e1", "run-1"))).toBe(true);
    });
  });

  describe("RunEventBuffer", () => {
    let buffer: RunEventBuffer;

    beforeEach(() => {
      buffer = new RunEventBuffer();
    });

    it("starts with null runId", () => {
      expect(buffer.currentRunId).toBeNull();
    });

    it("starts with lastSeq 0", () => {
      expect(buffer.lastSeq).toBe(0);
    });

    it("returns empty events array initially", () => {
      expect(buffer.events()).toEqual([]);
    });

    it("accepts events from a new run only if runId is null", () => {
      const buf = new RunEventBuffer();
      buf.push(makeEvent("token", 1, "e1", "run-X"));
      expect(buf.currentRunId).toBe("run-X");
      buf.push(makeEvent("token", 2, "e2", "run-X"));
      expect(buf.events()).toHaveLength(2);
    });

    it("accepts extra data fields", () => {
      buffer.push(makeEvent("progress", 1, "e1", "run-1", { phase: "planning", progress: 0.5 }));
      const events = buffer.events();
      expect((events[0] as any).phase).toBe("planning");
    });

    it("handles large seq numbers", () => {
      buffer.push(makeEvent("token", 1000000, "e1"));
      buffer.push(makeEvent("token", 999999, "e2"));
      const events = buffer.events();
      expect(events.map((e: any) => e.seq)).toEqual([999999, 1000000]);
    });

    it("push returns false for out-of-run events", () => {
      const buf = new RunEventBuffer();
      buf.push(makeEvent("token", 1, "e1", "run-1"));
      expect(buf.push(makeEvent("token", 2, "e2", "run-2"))).toBe(false);
    });

    it("push returns false for duplicate events", () => {
      buffer.push(makeEvent("token", 1, "dup"));
      const result = buffer.push(makeEvent("token", 2, "dup"));
      expect(result).toBe(false);
      expect(buffer.events()).toHaveLength(1);
    });

    it("reset clears all state", () => {
      buffer.push(makeEvent("token", 1, "e1"));
      buffer.push(makeEvent("token", 2, "e2"));
      buffer.reset();
      expect(buffer.events()).toEqual([]);
      expect(buffer.lastSeq).toBe(0);
      expect(buffer.currentRunId).toBeNull();
    });
  });

  describe("dedupeAndOrder", () => {
    it("returns empty array for empty input", () => {
      expect(dedupeAndOrder([])).toEqual([]);
    });

    it("throws on null input (iteration protocol)", () => {
      expect(() => dedupeAndOrder(null as any)).toThrow();
    });

    it("preserves extra fields on events", () => {
      const events: RuntimeEventLike[] = [
        makeEvent("progress", 1, "e1", "run-1", { progress: 0.8, phase: "testing" }),
      ];
      const result = dedupeAndOrder(events) as OrderedEvent[];
      expect((result[0] as any).phase).toBe("testing");
      expect((result[0] as any).progress).toBe(0.8);
    });

    it("keeps separate runs and orders each run without dropping later turns", () => {
      const events: RuntimeEventLike[] = [
        makeEvent("token", 2, "same-event-id", "run-1"),
        makeEvent("token", 1, "first-run-first", "run-1"),
        makeEvent("token", 2, "same-event-id", "run-2"),
        makeEvent("token", 1, "second-run-first", "run-2"),
        makeEvent("token", 2, "same-event-id", "run-1"),
      ];
      const result = dedupeAndOrder(events);
      expect(result).toHaveLength(4);
      expect(result.map((item) => `${item.run_id}:${item.seq}`)).toEqual([
        "run-1:1",
        "run-1:2",
        "run-2:1",
        "run-2:2",
      ]);
    });

    it("keeps an unsequenced local error between the runs where it occurred", () => {
      const localError: RuntimeEventLike = {
        type: "error",
        content: "falha local no pedido anterior",
      };
      const result = dedupeAndOrder([
        makeEvent("token", 2, "first-run-second", "run-1"),
        makeEvent("token", 1, "first-run-first", "run-1"),
        localError,
        makeEvent("token", 1, "second-run-first", "run-2"),
      ]);

      expect(result).toHaveLength(4);
      expect(result.map((item) => item.type)).toEqual(["token", "token", "error", "token"]);
      expect(result[2]).toBe(localError);
      expect(result[3].run_id).toBe("run-2");
    });

    it("deduplicates by event_id in batch", () => {
      const e = event(2);
      const result = dedupeAndOrder([event(2), event(1), e]);
      expect(result.map((x: any) => x.seq)).toEqual([1, 2]);
    });
  });
});
