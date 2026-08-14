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
    return true;
  }

  /** Reset for a new run; called when the user sends a new message. */
  reset(runId?: string): void {
    this.seen.clear();
    this.ordered = [];
    this.legacy = [];
    this.highestSeq = 0;
    this.runId = runId ?? null;
  }

  /** The timeline to render. */
  events(): RuntimeEventLike[] {
    return [...this.ordered, ...this.legacy];
  }

  /**
   * Sequence numbers that were never received.
   *
   * A non-empty result means the client dropped events (a full queue, a
   * dropped connection) and should request a replay from `lastSeq`.
   */
  missingSeqs(): number[] {
    const present = new Set(this.ordered.map((event) => event.seq));
    const gaps: number[] = [];
    for (let seq = 1; seq <= this.highestSeq; seq += 1) {
      if (!present.has(seq)) gaps.push(seq);
    }
    return gaps;
  }
}

/** One-shot ordering for an arbitrary batch (e.g. a history fetch). */
export function dedupeAndOrder(events: RuntimeEventLike[]): RuntimeEventLike[] {
  const buffer = new RunEventBuffer();
  for (const event of events) buffer.push(event);
  return buffer.events();
}
