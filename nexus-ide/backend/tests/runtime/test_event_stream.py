"""Contract tests for the ordered per-run event stream."""

from __future__ import annotations

import asyncio

import pytest

from backend.runtime.events import (
    RunEventStream,
    RuntimeEvent,
    RuntimeEventType,
    dedupe_and_order,
)


def test_sequence_is_strictly_increasing() -> None:
    stream = RunEventStream("run-1")
    events = [
        stream.emit(RuntimeEventType.STATUS_UPDATE, text=f"step {i}") for i in range(20)
    ]
    assert [event.seq for event in events] == list(range(1, 21))
    assert all(event.run_id == "run-1" for event in events)


@pytest.mark.asyncio
async def test_concurrent_emitters_never_interleave_out_of_order() -> None:
    """The defect this replaces: two publishers resumed in the wrong order."""
    stream = RunEventStream("run-1")
    received: list[int] = []

    async def consume() -> None:
        async for event in stream.subscribe():
            received.append(event.seq)
            if len(received) == 200:
                break

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0)

    async def emitter(worker: int) -> None:
        for _ in range(100):
            stream.emit(RuntimeEventType.TOOL_STARTED, agent_id=f"W{worker}")
            await asyncio.sleep(0)

    await asyncio.gather(emitter(1), emitter(2))
    await asyncio.wait_for(consumer, timeout=2)

    assert received == sorted(received), "subscriber observed events out of order"
    assert received == list(range(1, 201))


@pytest.mark.asyncio
async def test_reconnect_after_refresh_resumes_without_gaps_or_duplicates() -> None:
    stream = RunEventStream("run-1")
    for i in range(5):
        stream.emit(RuntimeEventType.FILE_READ, path=f"file{i}.py")

    seen: list[int] = []

    async def consume(after: int) -> None:
        async for event in stream.subscribe(after_seq=after):
            seen.append(event.seq)
            if event.seq == 8:
                break

    consumer = asyncio.create_task(consume(3))  # browser had rendered up to seq 3
    await asyncio.sleep(0)
    for i in range(3):
        stream.emit(RuntimeEventType.FILE_READ, path=f"late{i}.py")
    await asyncio.wait_for(consumer, timeout=2)

    assert seen == [4, 5, 6, 7, 8], f"replay produced {seen}"


@pytest.mark.asyncio
async def test_slow_consumer_cannot_stall_the_agent() -> None:
    stream = RunEventStream("run-1", subscriber_queue_size=4)

    async def never_reads() -> None:
        async for _ in stream.subscribe():
            await asyncio.sleep(10)

    consumer = asyncio.create_task(never_reads())
    await asyncio.sleep(0)

    # The agent keeps emitting; a full subscriber queue must not block it.
    await asyncio.wait_for(
        asyncio.to_thread(lambda: None), timeout=1
    )  # ensure the loop is live
    for i in range(50):
        stream.emit(RuntimeEventType.MESSAGE_DELTA, text=str(i))

    assert stream.last_seq == 50
    consumer.cancel()


@pytest.mark.asyncio
async def test_journal_survives_a_backend_restart(tmp_path) -> None:
    path = tmp_path / "run-1.ndjson"
    stream = RunEventStream("run-1", journal_path=path)
    stream.start_journal()
    for i in range(10):
        stream.emit(RuntimeEventType.COMMAND_STARTED, command=f"cmd {i}")
    await stream.aclose()

    restored = RunEventStream.load_journal(path)
    assert [event.seq for event in restored] == list(range(1, 11))
    assert restored[0].payload["command"] == "cmd 0"


def test_dedupe_and_order_is_the_frontend_contract() -> None:
    events = [
        RuntimeEvent(run_id="r", seq=3, type=RuntimeEventType.STATUS_UPDATE, event_id="c"),
        RuntimeEvent(run_id="r", seq=1, type=RuntimeEventType.RUN_STARTED, event_id="a"),
        RuntimeEvent(run_id="r", seq=2, type=RuntimeEventType.TOOL_STARTED, event_id="b"),
        RuntimeEvent(run_id="r", seq=2, type=RuntimeEventType.TOOL_STARTED, event_id="b"),
    ]
    ordered = dedupe_and_order(events)
    assert [event.seq for event in ordered] == [1, 2, 3]


def test_emitting_after_close_is_an_error() -> None:
    stream = RunEventStream("run-1")
    asyncio.run(stream.aclose())
    with pytest.raises(RuntimeError, match="closed"):
        stream.emit(RuntimeEventType.STATUS_UPDATE)
