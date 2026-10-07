"""Regression tests for the principal-first mission/chat contract."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from backend.orchestrator.events import EventType, OrchestratorEvent
from backend.orchestrator.routes import sessions as sessions_routes
from backend.orchestrator.routes.chat import (
    _mission_heartbeat_payload,
    _mission_ui_payload,
)
from backend.orchestrator.routes.sessions import _event_to_chat_frame


def _mission() -> SimpleNamespace:
    phase = SimpleNamespace(
        phase=SimpleNamespace(value="diagnosis", label="Fase 1 — Diagnóstico"),
        steps=["Mapear o projeto", "Executar testes"],
        skipped=False,
    )
    snapshot = SimpleNamespace(file_count=214, test_files=3, findings=["finding"])
    brief = SimpleNamespace(snapshot=snapshot, priorities=["Corrigir as falhas críticas"])
    return SimpleNamespace(
        id="mission-1",
        session_id="session-1",
        title="Analisar o projeto",
        state=SimpleNamespace(value="executing"),
        phase=SimpleNamespace(value="diagnosis"),
        brief=brief,
        plan=SimpleNamespace(phases=[phase]),
        contracts=[object(), object()],
        active_agents=2,
        progress=0.5,
    )


def test_mission_payload_is_compact_and_has_no_internal_brief_text() -> None:
    payload = _mission_ui_payload(_mission())

    assert payload["files_analyzed"] == 214
    assert payload["tests_total"] == 3
    assert payload["phases"][0]["steps"] == ["Mapear o projeto", "Executar testes"]
    assert "MISSION BRIEF" not in json.dumps(payload, ensure_ascii=False)
    assert "prompts" not in payload


def test_heartbeat_is_derived_from_active_task_counts() -> None:
    message, payload = _mission_heartbeat_payload(_mission(), started_at=0.0)

    assert "0/2" in message
    assert payload["heartbeat"] is True
    assert payload["active_agents"] == 2


def test_replayed_diagnostic_event_is_still_a_valid_chat_frame() -> None:
    frame = _event_to_chat_frame(
        OrchestratorEvent(
            event_type=EventType.MISSION_BRIEF,
            source="ORCHESTRATOR",
            session_id="session-1",
            data={"files_analyzed": 4, "live_object": object()},
        )
    )

    payload = json.loads(frame.split("data: ", 1)[1])
    assert payload["type"] == "mission_brief"
    assert payload["data"]["replayed"] is True
    assert payload["data"]["files_analyzed"] == 4


@pytest.mark.asyncio
async def test_completed_run_replays_events_before_closing(monkeypatch) -> None:
    event = OrchestratorEvent(
        event_type=EventType.MISSION_PLAN,
        source="ORCHESTRATOR",
        session_id="session-1",
        task_id="run-1",
        data={"mission_id": "mission-1"},
    )

    class Store:
        def load_window(self, _start: float, _end: float):
            return [event]

    async def false_async():
        return False

    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(event_bus=None)),
        is_disconnected=false_async,
    )
    monkeypatch.setattr(
        sessions_routes, "get_session_for_user", lambda _session_id, _user_id: {"id": "session-1"}
    )
    monkeypatch.setattr(sessions_routes, "get_event_store", lambda: Store())
    monkeypatch.setattr(
        "backend.persistence.db.get_session_run",
        lambda _run_id: {"id": "run-1", "status": "completed"},
    )

    response = await sessions_routes.session_events_endpoint(
        "session-1", request, run_id="run-1", _user={"sub": "test"}
    )
    frames = [frame async for frame in response.body_iterator]
    assert len(frames) == 2
    assert json.loads(frames[0].split("data: ", 1)[1])["type"] == "mission_plan"
    assert json.loads(frames[1].split("data: ", 1)[1])["type"] == "done"


@pytest.mark.asyncio
async def test_implicit_default_session_has_empty_recovery_instead_of_404(monkeypatch) -> None:
    monkeypatch.setattr(
        sessions_routes, "get_session_for_user", lambda _session_id, _user_id: None
    )

    response = await sessions_routes.get_runs_endpoint(
        "default", limit=20, _user={"sub": "test"}
    )

    assert response == {
        "runs": [],
        "count": 0,
        "has_more": False,
        "next_offset": 0,
    }
