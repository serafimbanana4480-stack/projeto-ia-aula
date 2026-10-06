from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi import FastAPI
from starlette.requests import Request

from backend.models.api import ChatRequest, StreamEvent
from backend.orchestrator import advanced_modes
from backend.orchestrator.routes import chat


def test_chat_route_persists_run_terminal_state_for_the_infinity_goal(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class _Orchestrator:
        def record_execution_outcome(self, **kwargs: object) -> bool:
            captured.update(kwargs)
            return True

    monkeypatch.setattr(advanced_modes, "get_orchestrator", lambda: _Orchestrator())
    request = SimpleNamespace(
        state=SimpleNamespace(
            nexus_infinity_execution={
                "mode_id": "forge",
                "session_id": "session-1",
                "goal_id": "goal-1",
                "run_id": "run-1",
            }
        )
    )

    recorded = chat._finalize_infinity_execution(
        request,
        outcome="completed",
        verification={"ran": True, "ok": True, "summary": "4 tests passed"},
    )

    assert recorded is True
    assert captured == {
        "mode_id": "forge",
        "session_id": "session-1",
        "goal_id": "goal-1",
        "run_id": "run-1",
        "outcome": "completed",
        "error": "",
        "error_category": "",
        "verification": {"ran": True, "ok": True, "summary": "4 tests passed"},
    }


def test_chat_sse_records_verification_before_sending_terminal_done(monkeypatch) -> None:
    captured: list[dict[str, object]] = []

    class _Orchestrator:
        def record_execution_outcome(self, **kwargs: object) -> bool:
            captured.append(dict(kwargs))
            return True

    app = FastAPI()
    app.state.llm_client = object()
    app.state.context = object()
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/chat",
        "raw_path": b"/api/chat",
        "query_string": b"",
        "headers": [],
        "client": ("test", 1),
        "server": ("test", 80),
        "app": app,
        "state": {
            "nexus_infinity_execution": {
                "mode_id": "forge",
                "session_id": "session-2",
                "goal_id": "goal-2",
                "run_id": "run-2",
            }
        },
    }
    request = Request(scope)

    def pipeline(*_args: object, **_kwargs: object):
        async def frames():
            yield chat._sse(
                StreamEvent(
                    type="metric",
                    data={"ran": True, "ok": True, "summary": "3 tests passed"},
                )
            )
            yield chat._sse(StreamEvent(type="done"))

        return frames()

    monkeypatch.setattr(chat, "_select_pipeline", pipeline)
    monkeypatch.setattr(chat, "get_registry", lambda _app: object())
    monkeypatch.setattr(advanced_modes, "get_orchestrator", lambda: _Orchestrator())
    async def drain() -> list[bytes]:
        response = await chat.chat(
            ChatRequest(message="Implement the requested change", session_id="session-2"),
            request,
            # An authenticated principal, like every other direct call to the
            # route. ``chat`` rejects a missing user id with 401 by design, so
            # an empty dict would test an unauthenticated request instead of
            # the SSE verification ordering this test is about.
            _user={"user_id": "tester"},
        )
        return [chunk async for chunk in response.body_iterator]

    frames = asyncio.run(drain())

    assert len(frames) == 2
    assert captured[0]["outcome"] == "completed"
    assert captured[0]["verification"] == {
        "ran": True,
        "ok": True,
        "summary": "3 tests passed",
    }
