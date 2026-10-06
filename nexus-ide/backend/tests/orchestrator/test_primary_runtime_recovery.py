"""Truthful terminal status for primary agent runs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.orchestrator.routes import chat_primary
from backend.persistence.db import get_messages
from backend.runtime.events import RuntimeEventType
from backend.runtime.primary import (
    AgentSignal,
    AgentSignalKind,
    PrimaryLoop,
    PrimaryOutcome,
)


@pytest.mark.parametrize(
    ("failed", "stopped", "finish_reason", "expected_status"),
    [
        (True, False, "", "failed"),
        (False, True, "", "cancelled"),
        (False, False, "length", "interrupted"),
        (False, False, "stop", "completed"),
    ],
)
def test_primary_run_record_matches_actual_outcome(
    monkeypatch: pytest.MonkeyPatch,
    failed: bool,
    stopped: bool,
    finish_reason: str,
    expected_status: str,
) -> None:
    saved: list[dict] = []

    def capture(_run_id: str, _session_id: str, **fields: object) -> dict:
        saved.append(fields)
        return fields

    monkeypatch.setattr(chat_primary, "upsert_session_run", capture)
    outcome = PrimaryOutcome(run_id="run-terminal-status", failed=failed, stopped=stopped)
    loop = SimpleNamespace(
        run_id="run-terminal-status",
        outcome=outcome,
        cycles=1,
        skill_activations=[],
    )
    req = SimpleNamespace(message="do work", mode="auto", model="")

    chat_primary._persist_run_record(
        run_id=loop.run_id,
        session_id="session-terminal-status",
        req=req,
        loop=loop,
        finish_reason=finish_reason,
    )

    assert saved[0]["status"] == expected_status
    assert saved[0]["execution_state"] == expected_status
    if finish_reason == "length":
        assert outcome.interrupted is True
        assert outcome.succeeded is False
        assert "interrompida" in outcome.error


@pytest.mark.asyncio
async def test_provider_truncation_is_terminal_interruption() -> None:
    async def stream(_turn):
        yield AgentSignal(AgentSignalKind.TOKEN, text="resposta parcial")

    loop = PrimaryLoop(
        run_id="run-provider-truncated",
        query="responde",
        stream=stream,
        interruption_check=lambda: "limite do provider atingido",
    )
    events = [event async for event in loop.run()]

    assert events[-1].type is RuntimeEventType.RUN_INTERRUPTED
    assert loop.outcome.interrupted is True
    assert loop.outcome.succeeded is False
    assert not any(event.type is RuntimeEventType.RUN_COMPLETED for event in events)


@pytest.mark.asyncio
async def test_primary_loop_emits_heartbeat_while_waiting_for_provider() -> None:
    async def stream(_turn):
        import asyncio

        await asyncio.sleep(0.03)
        yield AgentSignal(AgentSignalKind.TOKEN, text="resposta")

    loop = PrimaryLoop(
        run_id="run-heartbeat",
        query="continua a trabalhar",
        stream=stream,
        heartbeat_interval_seconds=0.005,
        run_timeout=0.2,
    )
    events = [event async for event in loop.run()]

    heartbeats = [event for event in events if event.type is RuntimeEventType.HEARTBEAT]
    assert len(heartbeats) >= 2
    assert all(event.payload["blocked_on"] == "waiting_model" for event in heartbeats)
    assert all(event.payload["waiting_seconds"] > 0 for event in heartbeats)
    assert events[-1].type is RuntimeEventType.RUN_COMPLETED
    await loop.events.aclose()


@pytest.mark.asyncio
async def test_empty_provider_response_is_recorded_as_failed_experience() -> None:
    class Bus:
        success: bool | None = None
        trajectories: list[dict[str, object]] = []

        def start_trace(self, **_kwargs):
            return object()

        def record_trajectory(self, _trace, **kwargs):
            self.trajectories.append(kwargs)

        def complete(self, _trace, *, success: bool, **_kwargs):
            self.success = success

    async def stream(_turn):
        if False:
            yield AgentSignal(AgentSignalKind.TOKEN, text="unused")

    bus = Bus()
    loop = PrimaryLoop(
        run_id="run-empty-provider",
        query="responde",
        stream=stream,
        experience_bus=bus,
    )
    events = [event async for event in loop.run()]

    assert events[-1].type is RuntimeEventType.RUN_FAILED
    assert loop.outcome.failed is True
    assert bus.success is False


@pytest.mark.asyncio
async def test_cancellation_keeps_partial_answer_and_marks_experience_failed() -> None:
    import asyncio

    class Bus:
        success: bool | None = None
        trajectories: list[dict[str, object]] = []

        def start_trace(self, **_kwargs):
            return object()

        def record_trajectory(self, _trace, **kwargs):
            self.trajectories.append(kwargs)

        def complete(self, _trace, *, success: bool, **_kwargs):
            self.success = success

    token_emitted = asyncio.Event()

    async def stream(_turn):
        yield AgentSignal(AgentSignalKind.TOKEN, text="resposta parcial")
        token_emitted.set()
        await asyncio.Future()

    bus = Bus()
    loop = PrimaryLoop(
        run_id="run-cancelled-partial",
        query="faz o trabalho",
        stream=stream,
        experience_bus=bus,
    )

    async def consume() -> None:
        async for _event in loop.run():
            pass

    task = asyncio.create_task(consume())
    await asyncio.wait_for(token_emitted.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert loop.outcome.stopped is True
    assert loop.outcome.answer == "resposta parcial"
    assert loop.events_sink[-1].type is RuntimeEventType.RUN_CANCELLED
    assert bus.success is False
    assert bus.trajectories == [
        {
            "agent": "NEXUS",
            "action": "run_cancelled",
            "observation": "Run cancelled after 1 cycle(s).",
            "success": False,
            "error": "Execução cancelada.",
            "input_data": {"cycles": 1},
        }
    ]
    await loop.events.aclose()


@pytest.mark.asyncio
async def test_cancelled_partial_output_is_persisted_to_chat_transcript() -> None:
    from backend.persistence.db import create_session, get_session_run

    class Context:
        def __init__(self) -> None:
            self.messages: list[object] = []

        async def append_message(self, _session_id: str, message: object) -> None:
            self.messages.append(message)

    session_id = "session-cancelled-partial"
    run_id = "run-cancelled-partial"
    create_session(session_id=session_id, title="Cancel test", mode="auto")
    context = Context()
    verification = SimpleNamespace(ran=False, ok=False, summary="", command="")
    loop = SimpleNamespace(
        run_id=run_id,
        outcome=SimpleNamespace(
            answer="resposta parcial",
            interrupted=False,
            failed=False,
            stopped=True,
            error="cancelled",
            telemetry={},
            verification=verification,
            changed_files=[],
        ),
        cycles=1,
        changed_files=[],
        skill_activations=[],
    )
    req = SimpleNamespace(message="continua o trabalho", mode="auto", model="")

    await chat_primary._persist(context, req, loop, session_id)

    messages = get_messages(session_id)
    assert any(
        message["role"] == "assistant" and message["content"] == "resposta parcial"
        for message in messages
    )
    assert any(
        getattr(message, "role", None) == "assistant"
        and getattr(message, "content", None) == "resposta parcial"
        for message in context.messages
    )
    saved_run = get_session_run(run_id)
    assert saved_run is not None
    assert saved_run["status"] == "cancelled"
    assert saved_run["partial_output"] == "resposta parcial"


@pytest.mark.parametrize(
    ("tool_name", "args", "expected_event"),
    [
        ("run_shell", {"command": "pytest -q"}, RuntimeEventType.COMMAND_STARTED),
        ("run_tests", {"project_path": "C:/project"}, RuntimeEventType.TEST_STARTED),
    ],
)
@pytest.mark.asyncio
async def test_tool_lifecycle_has_specific_command_and_test_start_events(
    tool_name: str,
    args: dict,
    expected_event: RuntimeEventType,
) -> None:
    async def stream(_turn):
        yield AgentSignal(
            AgentSignalKind.TOOL_CALL,
            tool_name=tool_name,
            payload=args,
        )
        yield AgentSignal(
            AgentSignalKind.TOOL_RESULT,
            tool_name=tool_name,
            payload={"ok": True, "result": {"exit_code": 0, "passed": 1}},
        )
        yield AgentSignal(AgentSignalKind.TOKEN, text="feito")

    loop = PrimaryLoop(
        run_id=f"run-observed-{tool_name}",
        query="executa a ferramenta",
        stream=stream,
    )
    events = [event async for event in loop.run()]

    types = [event.type for event in events]
    assert expected_event in types
    assert types.index(RuntimeEventType.TOOL_STARTED) < types.index(expected_event)


@pytest.mark.asyncio
async def test_primary_uses_the_provider_paired_with_the_selected_model() -> None:
    local = SimpleNamespace(provider_name="lmstudio")
    openrouter = SimpleNamespace(provider_name="openrouter")
    default_client = SimpleNamespace(primary=local, fallbacks=[openrouter])
    request = SimpleNamespace(
        provider="openrouter",
        model="liquid/lfm-2.5-2.6b:free",
    )

    selected, error = await chat_primary._request_provider_client(request, default_client)

    assert selected is openrouter
    assert error is None


@pytest.mark.asyncio
async def test_primary_fails_closed_for_an_unconfigured_selected_provider() -> None:
    default_client = SimpleNamespace(primary=SimpleNamespace(provider_name="lmstudio"), fallbacks=[])
    request = SimpleNamespace(provider="openrouter", model="liquid/lfm-2.5-2.6b:free")

    selected, error = await chat_primary._request_provider_client(request, default_client)

    assert selected is None
    assert error is not None
    assert "openrouter" in error


@pytest.mark.asyncio
async def test_primary_fails_when_agent_explicitly_reports_iteration_exhaustion() -> None:
    from backend.models.api import StreamEvent

    signal = chat_primary.stream_events_to_signals(
        StreamEvent(
            type="token",
            content=(
                "[TAREFA NÃO CONCLUÍDA] O agente atingiu o limite de 8 passos "
                "sem produzir uma resposta final."
            ),
        )
    )
    assert signal is not None
    assert signal.kind is AgentSignalKind.ERROR
    assert signal.ok is False
    assert signal.payload["reason"] == "agent_incomplete"

    async def stream(_turn):
        yield signal

    loop = PrimaryLoop(
        run_id="run-agent-incomplete",
        query="executa e verifica o plano",
        stream=stream,
    )
    events = [event async for event in loop.run()]

    assert loop.outcome.failed is True
    assert any(event.type is RuntimeEventType.RUN_FAILED for event in events)
    assert not any(event.type is RuntimeEventType.RUN_COMPLETED for event in events)
