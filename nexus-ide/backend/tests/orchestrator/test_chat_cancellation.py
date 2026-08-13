"""Focused tests for explicit cancellation of chat SSE streams."""

from __future__ import annotations

import asyncio

import pytest
from fastapi import Request
from fastapi.responses import StreamingResponse
from starlette.responses import Response

from backend.orchestrator.cancellation import (
    CancellationRegistry,
    get_cancellation_registry,
    reset_cancellation_registry,
)
from backend.orchestrator.chat_cancellation import (
    REQUEST_ID_HEADER,
    chat_cancellation_middleware,
)
from backend.orchestrator.main import app
from backend.orchestrator.routes.chat import _stream_autonomous_execution
from backend.orchestrator.routes.cancellation_routes import cancel_request, router as cancellation_router


@pytest.fixture(autouse=True)
async def _fresh_cancellation_registry():
    """Isolate the process-wide registry and its cleanup task per test."""
    reset_cancellation_registry()
    registry = get_cancellation_registry()
    yield registry
    await registry.shutdown()
    reset_cancellation_registry()


def _chat_request(request_id: str | None = None) -> Request:
    headers = [(b"host", b"testserver")]
    if request_id is not None:
        headers.append((REQUEST_ID_HEADER.lower().encode(), request_id.encode()))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/chat",
            "raw_path": b"/api/chat",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
    )


@pytest.mark.asyncio
async def test_stream_is_registered_and_cleaned_up() -> None:
    async def source():
        yield b"first"
        yield b"second"

    async def call_next(_request: Request) -> Response:
        return StreamingResponse(source(), media_type="text/event-stream")

    request = _chat_request("request_1")
    response = await chat_cancellation_middleware(request, call_next)
    assert response.headers[REQUEST_ID_HEADER] == "request_1"
    # The inner chat/orchestrator sees the exact same cancellation entry.
    assert request.state.nexus_request_id == "request_1"
    assert get_cancellation_registry().get("request_1") is not None

    chunks = [chunk async for chunk in response.body_iterator]

    assert chunks == [b"first", b"second"]
    assert get_cancellation_registry().get("request_1") is None


@pytest.mark.asyncio
async def test_explicit_cancel_interrupts_the_blocked_stream_task() -> None:
    source_started = asyncio.Event()
    source_closed = asyncio.Event()
    never = asyncio.Event()

    async def source():
        try:
            source_started.set()
            yield b"first"
            await never.wait()
        finally:
            source_closed.set()

    async def call_next(_request: Request) -> Response:
        return StreamingResponse(source(), media_type="text/event-stream")

    request_id = "cancel_me"
    response = await chat_cancellation_middleware(_chat_request(request_id), call_next)

    async def consume() -> list[bytes]:
        return [chunk async for chunk in response.body_iterator]

    consumer = asyncio.create_task(consume())
    await source_started.wait()
    await asyncio.sleep(0)

    assert await get_cancellation_registry().cancel(request_id) is True
    assert await consumer == [b"first"]
    await source_closed.wait()
    assert get_cancellation_registry().get(request_id) is None


@pytest.mark.asyncio
async def test_non_stream_response_is_not_left_cancellable() -> None:
    async def call_next(_request: Request) -> Response:
        return Response("invalid request", status_code=422)

    response = await chat_cancellation_middleware(_chat_request("not_a_stream"), call_next)

    assert response.status_code == 422
    assert get_cancellation_registry().get("not_a_stream") is None


@pytest.mark.asyncio
async def test_cancel_route_marks_a_registered_request() -> None:
    registry = get_cancellation_registry()
    await registry.register("route_request")

    result = await cancel_request("route_request", _user={"user_id": "tester"})

    assert result == {"status": "cancelled", "request_id": "route_request"}
    assert registry.is_cancelled("route_request") is True


def test_cancellation_routes_are_mounted_on_the_main_app() -> None:
    paths = {route.path for route in cancellation_router.routes}

    # FastAPI versions differ in whether ``include_router`` keeps an
    # ``original_router`` marker or flattens routes into concrete APIRoute
    # objects.  The observable contract is that every cancellation endpoint
    # is actually reachable from the main application.
    mounted_paths = {route.path for route in app.routes}
    assert paths <= mounted_paths
    assert "/api/chat/cancel/{request_id}" in mounted_paths
    assert "/api/chat/cancel/stats" in mounted_paths


@pytest.mark.asyncio
async def test_registry_cancels_a_bound_task() -> None:
    registry = CancellationRegistry()
    await registry.register("bound_task")
    waiting_task = asyncio.create_task(asyncio.Event().wait())
    await registry.bind_stream_task("bound_task", waiting_task)

    assert await registry.cancel("bound_task") is True
    with pytest.raises(asyncio.CancelledError):
        await waiting_task


@pytest.mark.asyncio
async def test_cancelling_autonomous_sse_stops_engine_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend.orchestrator.engine as engine_module
    import backend.orchestrator.mission_control as mission_module

    started = asyncio.Event()
    execution_cancelled = asyncio.Event()
    cancel_method_called = asyncio.Event()

    class FakeEngine:
        def __init__(self, **_kwargs):
            pass

        async def execute_autonomous(self, **_kwargs):
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                execution_cancelled.set()

        async def cancel(self, _session_id: str) -> None:
            cancel_method_called.set()

    def fail_mission(*_args, **_kwargs):
        raise RuntimeError("mission disabled for cancellation test")

    monkeypatch.setattr(engine_module, "OrchestrationEngine", FakeEngine)
    monkeypatch.setattr(mission_module, "start_mission", fail_mission)

    cancellation_id = "cancel-autonomous-engine"
    await get_cancellation_registry().register(cancellation_id)
    stream = _stream_autonomous_execution(
        objective="audit",
        session_id="cancel-autonomous-engine",
        llm_client=object(),
        registry={},
        event_bus=None,
        project_path=".",
        history=[],
        context=object(),
        cancellation_request_id=cancellation_id,
    )

    async def consume() -> None:
        async for _chunk in stream:
            pass

    consumer = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), timeout=2)
    await get_cancellation_registry().cancel(cancellation_id)

    with pytest.raises(asyncio.CancelledError):
        await consumer
    await asyncio.wait_for(execution_cancelled.wait(), timeout=2)
    assert cancel_method_called.is_set()
