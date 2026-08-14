"""Evidence: the event contract cannot express a total order.

These tests are deliberately written against the *observable contract* the
frontend needs in order to render a stable timeline:

* every event must carry the run it belongs to (``run_id``);
* every event must carry a strictly increasing, per-run ``seq``;
* delivery order to a subscriber must equal publish order.

They reproduce the user-visible symptom "agents appear to start out of
order" without needing a browser: if the transport cannot express order,
no frontend can restore it.
"""

from __future__ import annotations

import asyncio
import dataclasses

import pytest

from backend.orchestrator.events import (
    EventBus,
    EventStore,
    EventType,
    OrchestratorEvent,
)


def _field_names() -> set[str]:
    return {f.name for f in dataclasses.fields(OrchestratorEvent)}


def test_event_carries_monotonic_sequence() -> None:
    """An SSE consumer needs a per-run monotonic sequence to sort by."""
    assert "seq" in _field_names(), (
        "OrchestratorEvent has no monotonic 'seq'; the frontend can only "
        "order by arrival or by wall-clock timestamp, neither of which is a "
        "total order under concurrency."
    )


def test_event_carries_run_id() -> None:
    """Without run_id, events from a previous run merge into the current one."""
    assert "run_id" in _field_names(), (
        "OrchestratorEvent has no 'run_id'; events are only scoped by "
        "session_id, so a previous run's files/tests re-appear in the UI of "
        "the next run in the same session (stale-state symptom)."
    )


@pytest.mark.asyncio
async def test_events_are_orderable_when_timestamps_collide() -> None:
    """A coarse clock must not make the timeline ambiguous.

    ``time.time()`` on Windows (the user's platform) has ~15.6 ms
    granularity, so a burst of events emitted inside one scheduling slice
    shares a single timestamp. The event contract must therefore expose a
    tiebreaker that is still a total order when ``timestamp`` collides.
    """
    granularity = 0.015625  # 15.6 ms — Windows default timer resolution
    quantised = 1_700_000_000.0 - (1_700_000_000.0 % granularity)

    bus = EventBus()
    events = [
        OrchestratorEvent(
            event_type=EventType.AGENT_STARTED,
            source=f"AGENT_{i}",
            run_id="run-1",
            timestamp=quantised,
        )
        for i in range(12)
    ]
    for event in events:
        await bus.publish(event)

    # The ordering key the frontend would have to use.
    keys = [(e.timestamp, getattr(e, "seq", None)) for e in events]
    assert all(k[1] is not None for k in keys), (
        "events carry no 'seq' tiebreaker, so 12 events sharing one "
        "timestamp have no defined order"
    )
    assert len(set(keys)) == len(events), (
        f"{len(events)} events collapsed onto {len(set(keys))} ordering "
        "key(s); the timeline the user sees is an arbitrary permutation."
    )


@pytest.mark.asyncio
async def test_subscriber_delivery_preserves_publish_order(tmp_path) -> None:
    """Delivery order must equal publish order, even with a store attached.

    ``EventBus.publish`` persists via ``asyncio.to_thread`` *before*
    notifying subscribers. Two concurrent publishers therefore hand off to
    the thread pool and can be resumed in the opposite order, so the
    subscriber (the SSE stream) observes AGENT_2 starting before AGENT_1.
    """
    bus = EventBus()

    class SlowFirstStore(EventStore):
        """Make the interleaving deterministic instead of merely possible."""

        def __init__(self) -> None:
            super().__init__(store_dir=tmp_path)
            self._seen = 0

        def persist(self, event: OrchestratorEvent) -> None:  # noqa: D102
            import time as _t

            self._seen += 1
            # The first publisher is descheduled for longer than the second.
            _t.sleep(0.05 if self._seen == 1 else 0.0)

    bus.attach_store(SlowFirstStore())

    delivered: list[str] = []

    async def subscriber(event: OrchestratorEvent) -> None:
        delivered.append(event.source)

    await bus.subscribe("*", subscriber)

    async def publish(source: str) -> None:
        await bus.publish(
            OrchestratorEvent(event_type=EventType.AGENT_STARTED, source=source)
        )

    first = asyncio.create_task(publish("AGENT_1"))
    await asyncio.sleep(0)  # AGENT_1 reaches the to_thread hop first
    second = asyncio.create_task(publish("AGENT_2"))
    await asyncio.gather(first, second)

    assert delivered == ["AGENT_1", "AGENT_2"], (
        f"publish order was AGENT_1, AGENT_2 but subscribers observed "
        f"{delivered}: the bus inverts order across the persist hop."
    )
