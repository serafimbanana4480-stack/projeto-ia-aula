import { describe, expect, it } from "vitest";

import {
  RunEventBuffer,
  dedupeAndOrder,
  isOrderable,
  type RuntimeEventLike,
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
  });

  it("reports no gaps for a complete timeline", () => {
    const buffer = new RunEventBuffer();
    [1, 2, 3].forEach((seq) => buffer.push(event(seq)));
    expect(buffer.missingSeqs()).toEqual([]);
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
});
