"""The chat must retain real event times when a run is streamed or replayed."""

import json
from datetime import UTC, datetime

from backend.orchestrator.routes.chat_primary import runtime_event_to_stream_events
from backend.orchestrator.routes.sessions import _runtime_event_to_chat_frames
from backend.runtime.events import RuntimeEvent, RuntimeEventType


def test_tool_event_time_survives_chat_conversion_and_replay() -> None:
    event = RuntimeEvent(
        run_id="timing-test",
        seq=4,
        type=RuntimeEventType.TOOL_COMPLETED,
        ts=1_700_000_000.125,
        payload={"tool": "read_file", "result": {"ok": True}},
    )
    expected = datetime.fromtimestamp(event.ts, tz=UTC).isoformat()
    assert runtime_event_to_stream_events(event)[0].timestamp == expected
    replay = json.loads(_runtime_event_to_chat_frames(event, replayed=True).removeprefix("data: "))
    assert replay["timestamp"] == expected
    assert replay["data"]["replayed"] is True


def test_invalid_historical_timestamp_does_not_break_chat_conversion() -> None:
    event = RuntimeEvent(
        run_id="timing-test",
        seq=1,
        type=RuntimeEventType.TOOL_STARTED,
        ts=float("nan"),
        payload={"tool": "read_file"},
    )
    assert runtime_event_to_stream_events(event)[0].timestamp
