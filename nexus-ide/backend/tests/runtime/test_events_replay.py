"""Gap replay on ``GET /api/sessions/{id}/events`` (the after_seq contract).

The frontend's ``RunEventBuffer`` detects missing sequence numbers mid-stream
and asks this endpoint to replay everything after the end of its contiguous
prefix. These tests pin that contract:

* ``after_seq`` filters the persisted backlog to ``seq > after_seq``;
* replayed frames carry the ``(run_id, seq, event_id)`` envelope at the frame
  root, where the frontend buffer reads it;
* the store round-trips ``run_id``/``seq`` so replays survive a restart.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.orchestrator.events import EventStore, EventType, OrchestratorEvent
from backend.orchestrator.routes import sessions as sessions_routes


def _ordered_event(
    seq: int,
    *,
    run_id: str = "run-1",
    session_id: str = "session-1",
    event_type: EventType = EventType.TOKEN,
) -> OrchestratorEvent:
    return OrchestratorEvent(
        event_type=event_type,
        source="NEXUS",
        session_id=session_id,
        run_id=run_id,
        seq=seq,
        task_id=run_id,
        data={"run_id": run_id, "seq": seq},
        content=f"event-{seq}",
        timestamp=1_700_000_000.0 + seq,
    )


class _FakeRequest:
    def __init__(self) -> None:
        self.app = SimpleNamespace(state=SimpleNamespace(event_bus=None))

    async def is_disconnected(self) -> bool:
        return False


class _FakeStore:
    def __init__(self, events: list[OrchestratorEvent]) -> None:
        self.events = events

    def load_window(self, _since: float, _until: float) -> list[OrchestratorEvent]:
        return list(self.events)


async def _frames(response) -> list[str]:
    return [frame async for frame in response.body_iterator]


def _payload(frame: str) -> dict:
    return json.loads(frame.split("data: ", 1)[1])


async def _endpoint(
    monkeypatch: pytest.MonkeyPatch,
    store: _FakeStore,
    *,
    run_id: str | None = "run-1",
    after_seq: int = 0,
):
    async def false_async():
        return False

    monkeypatch.setattr(
        sessions_routes,
        "get_session_for_user",
        lambda _session_id, _user_id: {"id": "session-1"},
    )
    monkeypatch.setattr(sessions_routes, "get_event_store", lambda: store)
    monkeypatch.setattr(
        "backend.persistence.db.get_session_run",
        lambda requested_id: {
            "id": requested_id,
            "session_id": "session-1",
            "status": "completed",
        },
    )
    return await sessions_routes.session_events_endpoint(
        "session-1",
        _FakeRequest(),
        run_id=run_id,
        after_seq=after_seq,
        _user={"sub": "test"},
    )


async def test_after_seq_filters_replayed_backlog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gap replay returns only seq > after_seq, then closes with done."""
    store = _FakeStore([_ordered_event(seq) for seq in range(1, 5)])

    response = await _endpoint(monkeypatch, store, after_seq=2)
    payloads = [_payload(frame) for frame in await _frames(response)]

    assert [p["data"]["seq"] for p in payloads if p["type"] != "done"] == [3, 4]
    assert payloads[-1]["type"] == "done"


async def test_without_after_seq_replays_everything(monkeypatch: pytest.MonkeyPatch) -> None:
    store = _FakeStore([_ordered_event(seq) for seq in range(1, 5)])

    response = await _endpoint(monkeypatch, store)
    payloads = [_payload(frame) for frame in await _frames(response)]

    assert [p["data"]["seq"] for p in payloads if p["type"] != "done"] == [1, 2, 3, 4]


async def test_replayed_frames_carry_top_level_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The frontend RunEventBuffer reads run_id/seq/event_id at frame root."""
    store = _FakeStore([_ordered_event(7, run_id="run-x")])

    response = await _endpoint(monkeypatch, store, run_id="run-x")
    payloads = [_payload(frame) for frame in await _frames(response)]

    body = payloads[0]
    assert body["run_id"] == "run-x"
    assert body["seq"] == 7
    assert isinstance(body["event_id"], str) and body["event_id"]
    assert body["task_id"] == "run-x"
    assert body["data"]["replayed"] is True


async def test_envelope_fallback_reads_seq_from_data_for_legacy_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rows persisted before top-level seq keep their gap-replay eligibility."""
    legacy = _ordered_event(9)
    legacy.seq = 0  # as if loaded from an old NDJSON line without the field
    store = _FakeStore([legacy])

    response = await _endpoint(monkeypatch, store, after_seq=8)
    payloads = [_payload(frame) for frame in await _frames(response)]

    assert payloads[0]["seq"] == 9
    assert payloads[0]["run_id"] == "run-1"


async def test_events_without_seq_are_excluded_from_narrowed_replay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unpositionable = OrchestratorEvent(
        event_type=EventType.MISSION_BRIEF,
        source="ORCHESTRATOR",
        session_id="session-1",
        task_id="run-1",
        content="no ordering key",
    )
    positioned = _ordered_event(2)
    store = _FakeStore([unpositionable, positioned])

    response = await _endpoint(monkeypatch, store, after_seq=1)
    payloads = [_payload(frame) for frame in await _frames(response)]

    assert [p["type"] for p in payloads] == ["token", "done"]


def test_event_store_roundtrip_preserves_run_and_seq(tmp_path) -> None:
    store = EventStore(store_dir=tmp_path)
    first = _ordered_event(1, run_id="run-a")
    second = _ordered_event(2, run_id="run-b")

    store.persist(first)
    store.persist(second)

    restored = {event.run_id: event for event in store.load_window(0)}
    assert restored["run-a"].seq == 1
    assert restored["run-b"].seq == 2
    assert restored["run-a"].event_id == first.event_id


async def test_primary_journal_replays_after_process_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The session recovery endpoint reads the primary runtime's durable journal."""
    from backend.runtime.events import RuntimeEvent, RuntimeEventType

    journal = tmp_path / "run-journal.jsonl"
    events = [
        RuntimeEvent(
            run_id="run-journal",
            seq=seq,
            type=RuntimeEventType.MESSAGE_DELTA,
            payload={"text": f"parte-{seq}"},
        )
        for seq in range(1, 4)
    ]
    journal.write_text(
        "".join(json.dumps(event.to_sse(), ensure_ascii=False) + "\n" for event in events),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "backend.runtime.events.run_event_journal_path",
        lambda _run_id: journal,
    )

    response = await _endpoint(
        monkeypatch,
        _FakeStore([_ordered_event(99)]),
        run_id="run-journal",
        after_seq=1,
    )
    payloads = [_payload(frame) for frame in await _frames(response)]

    assert [item["seq"] for item in payloads[:-1]] == [2, 3]
    assert [item["content"] for item in payloads[:-1]] == ["parte-2", "parte-3"]
    assert all(item["data"]["replayed"] for item in payloads[:-1])
    assert payloads[-1]["type"] == "done"


async def test_primary_live_stream_replays_backlog_and_follows_new_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refreshed client receives buffered events and then live primary events."""
    from backend.runtime.events import RunEventStream, RuntimeEventType

    run_id = "run-live-replay"
    stream = RunEventStream(run_id)
    stream.emit(RuntimeEventType.RUN_STARTED, query="test")
    monkeypatch.setattr(
        sessions_routes,
        "get_session_for_user",
        lambda _session_id, _user_id: {"id": "session-1"},
    )
    monkeypatch.setattr(sessions_routes, "get_event_store", lambda: _FakeStore([]))
    monkeypatch.setattr(
        "backend.persistence.db.get_session_run",
        lambda _run_id: {
            "id": run_id,
            "session_id": "session-1",
            "status": "running",
        },
    )

    response = await sessions_routes.session_events_endpoint(
        "session-1",
        _FakeRequest(),
        run_id=run_id,
        _user={"sub": "test"},
    )
    frames = response.body_iterator.__aiter__()
    first = _payload(await anext(frames))
    stream.emit(RuntimeEventType.MESSAGE_DELTA, text="continua")
    second = _payload(await anext(frames))
    await stream.aclose()
    final = _payload(await anext(frames))

    assert first["type"] == "agent_started"
    assert first["seq"] == 1
    assert first["data"]["replayed"] is True
    assert second["type"] == "token"
    assert second["content"] == "continua"
    assert second["seq"] == 2
    assert "replayed" not in second["data"]
    assert final["type"] == "done"
