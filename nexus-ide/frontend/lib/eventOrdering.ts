/**
 * Ordering and de-duplication for runtime events.
 *
 * The backend guarantees a total order per run via `(run_id, seq)`. The UI
 * must never fall back to arrival order or to `timestamp`: `time.time()` has
 * ~15.6 ms granularity on Windows, so a burst of events shares one value and
 * sorting by it renders an arbitrary permutation — which is what made agents
 * appear to start out of order.
 *
 * Responsibilities of this module:
 *  - drop duplicates by `event_id` (replay after a reconnect re-sends events);
 *  - keep a single run's timeline strictly ordered by `seq`;
 *  - discard events belonging to a previous run of the same session, which is
 *    what made stale files and test counts reappear in a new run;
 *  - detect gaps so the client can ask the server to replay them.
 */

export interface RuntimeEventLike {
  run_id?: string;
  seq?: number;
  event_id?: string;
  type: string;
  agent_id?: string;
  task_id?: string;
  ts?: number;
  payload?: Record<string, unknown>;
  [key: string]: unknown;
}

export interface OrderedEvent extends RuntimeEventLike {
  run_id: string;
  seq: number;
  event_id: string;
}

/** True when the event carries the ordering contract the UI needs. */
export function isOrderable(event: RuntimeEventLike): event is OrderedEvent {
  return (
    typeof event.run_id === "string" &&
    event.run_id.length > 0 &&
    typeof event.seq === "number" &&
    Number.isFinite(event.seq) &&
    typeof event.event_id === "string" &&
    event.event_id.length > 0
  );
}

/**
 * Accumulates the events of exactly one run, in order, without duplicates.
 *
 * Legacy events that carry no `seq` are appended in arrival order after the
 * ordered ones so an older backend still renders something sensible.
 */
export class RunEventBuffer {
  private readonly seen = new Set<string>();
  private ordered: OrderedEvent[] = [];
  private legacy: RuntimeEventLike[] = [];
  private readonly pendingSeqs = new Set<number>();
  private contiguousSeq = 0;
  private highestSeq = 0;
  private runId: string | null = null;

  constructor(runId?: string) {
    this.runId = runId ?? null;
  }

  /** The run this buffer is bound to, or null before the first event. */
  get currentRunId(): string | null {
    return this.runId;
  }

  /** Highest sequence number rendered so far — send this on reconnect. */
  get lastSeq(): number {
    return this.highestSeq;
  }

  /**
   * Add one event.
   *
   * @returns `true` when the event was accepted, `false` when it was a
   * duplicate or belonged to a different run.
   */
  push(event: RuntimeEventLike): boolean {
    if (!isOrderable(event)) {
      this.legacy.push(event);
      return true;
    }

    if (this.runId === null) {
      this.runId = event.run_id;
    } else if (event.run_id !== this.runId) {
      // An event from another run must not leak into this timeline.
      return false;
    }

    if (this.seen.has(event.event_id)) {
      return false;
    }
    this.seen.add(event.event_id);

    // Insert in order. The common case is an append, so scan from the end.
    let index = this.ordered.length;
    while (index > 0 && this.ordered[index - 1].seq > event.seq) {
      index -= 1;
    }
    this.ordered.splice(index, 0, event);
    this.highestSeq = Math.max(this.highestSeq, event.seq);
    if (Number.isSafeInteger(event.seq) && event.seq > 0) {
      this.pendingSeqs.add(event.seq);
      while (this.pendingSeqs.delete(this.contiguousSeq + 1)) {
        this.contiguousSeq += 1;
      }
    }
    return true;
  }

  /** Reset for a new run; called when the user sends a new message. */
  reset(runId?: string): void {
    this.seen.clear();
    this.ordered = [];
    this.legacy = [];
    this.pendingSeqs.clear();
    this.contiguousSeq = 0;
    this.highestSeq = 0;
    this.runId = runId ?? null;
  }

  /** The timeline to render. */
  events(): RuntimeEventLike[] {
    return [...this.ordered, ...this.legacy];
  }

  /** Whether the ordered journal has a missing sequence, checked in O(1). */
  hasMissingSeqs(): boolean {
    return this.contiguousSeq < this.highestSeq;
  }

  /** First missing sequence for replay; null means the journal is contiguous. */
  firstMissingSeq(): number | null {
    return this.hasMissingSeqs() ? this.contiguousSeq + 1 : null;
  }

  /**
   * Sequence numbers that were never received.
   *
   * A non-empty result means the client dropped events (a full queue, a
   * dropped connection) and should request a replay from `lastSeq`.
   */
  missingSeqs(): number[] {
    const gaps: number[] = [];
    let expected = 1;
    for (const event of this.ordered) {
      if (!Number.isSafeInteger(event.seq) || event.seq < 1) continue;
      while (expected < event.seq) gaps.push(expected++);
      if (event.seq === expected) expected += 1;
    }
    while (expected <= this.highestSeq) gaps.push(expected++);
    return gaps;
  }
}

/** One-shot ordering for an accumulated session batch, which can contain many runs. */
export function dedupeAndOrder(events: RuntimeEventLike[]): RuntimeEventLike[] {
  const orderedRuns = new Map<string, RunEventBuffer>();
  const timeline: Array<
    | { index: number; runId: string }
    | { index: number; event: RuntimeEventLike }
  > = [];

  for (const [index, event] of events.entries()) {
    if (!isOrderable(event)) {
      timeline.push({ index, event });
      continue;
    }

    let buffer = orderedRuns.get(event.run_id);
    if (!buffer) {
      buffer = new RunEventBuffer(event.run_id);
      orderedRuns.set(event.run_id, buffer);
      timeline.push({ index, runId: event.run_id });
    }
    buffer.push(event);
  }

  // Sequence numbers are comparable only inside a run. Keep each run's
  // ordered batch at its first observed position so local events (for example,
  // a request error without a run envelope) stay between the runs where they
  // occurred instead of being pushed to the end of the whole session.
  return timeline
    .sort((left, right) => left.index - right.index)
    .flatMap((entry) =>
      "runId" in entry
        ? orderedRuns.get(entry.runId)?.events() ?? []
        : [entry.event],
    );
}
