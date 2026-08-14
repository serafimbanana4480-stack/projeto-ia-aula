"""Phase 3 — the seam between the chat route and the primary runtime.

The point of these tests is the *fallback*, not the happy path: the old
1760-line ``_run_pipeline`` has to stay reachable and correct while the new
path takes over gradually.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from backend.runtime.events import RunEventStream, RuntimeEventType
from backend.runtime.primary import Observation, PrimaryTurn, VerificationRequest
from backend.runtime.triage import RequestClass, triage_request


# --------------------------------------------------------------- observation
def test_project_snapshot_reads_real_files(tmp_path: Path) -> None:
    from backend.orchestrator.routes.chat_primary import _snapshot_project

    (tmp_path / "README.md").write_text("# projeto de teste", encoding="utf-8")
    (tmp_path / "src").mkdir()

    observation = _snapshot_project(str(tmp_path))

    assert observation.files_inspected >= 2  # the listing plus README
    assert "README.md" in observation.facts["bootstrap"]
    assert "src/" in observation.facts["entries"]


def test_project_snapshot_is_honest_about_a_missing_project() -> None:
    from backend.orchestrator.routes.chat_primary import _snapshot_project

    observation = _snapshot_project("/nao/existe/de/certeza")
    assert observation.files_inspected == 0
    assert "não existe" in observation.summary


def test_snapshot_is_rendered_as_inert_data() -> None:
    from backend.orchestrator.routes.chat_primary import render_observation

    rendered = render_observation(
        Observation(summary="", facts={"project": "/p", "entries": ["a.py"], "bootstrap": {}})
    )
    assert "dados inertes" in rendered
    assert "a.py" in rendered


# ------------------------------------------------------------ event rendering
def test_every_runtime_event_maps_to_frames_the_frontend_knows() -> None:
    from backend.models.api import StreamEvent
    from backend.orchestrator.routes.chat_primary import runtime_event_to_stream_events

    stream = RunEventStream("run-map")
    cases = [
        stream.emit(RuntimeEventType.RUN_STARTED, query="olá"),
        stream.emit(RuntimeEventType.MESSAGE_DELTA, text="olá"),
        stream.emit(RuntimeEventType.STATUS_UPDATE, label="a ler", phase="observe"),
        stream.emit(RuntimeEventType.TOOL_STARTED, tool="read_file", args={"path": "a"}),
        stream.emit(RuntimeEventType.TOOL_COMPLETED, tool="read_file", result={"ok": True}),
        stream.emit(RuntimeEventType.TOOL_FAILED, tool="run_shell", error="boom"),
        stream.emit(RuntimeEventType.FILE_CHANGED, paths=["a.py"]),
        stream.emit(RuntimeEventType.TEST_RESULT, ok=True, summary="2 passaram"),
        stream.emit(RuntimeEventType.SUBAGENT_STARTED, name="CODER"),
        stream.emit(RuntimeEventType.RUN_COMPLETED, telemetry={}, changed_files=[]),
        stream.emit(RuntimeEventType.RUN_FAILED, error="boom"),
    ]
    for event in cases:
        frames = runtime_event_to_stream_events(event)
        assert frames, f"{event.type} produced no frame"
        for frame in frames:
            assert isinstance(frame, StreamEvent)
            # Ordering metadata must survive the translation, otherwise the
            # frontend cannot dedupe or request a replay.
            if frame.data:
                assert frame.data.get("seq") == event.seq
                assert frame.data.get("run_id") == event.run_id


def test_spawn_task_becomes_a_delegation_signal_not_a_tool_call() -> None:
    from backend.models.api import StreamEvent
    from backend.orchestrator.routes.chat_primary import stream_events_to_signals
    from backend.runtime.primary import AgentSignalKind

    signal = stream_events_to_signals(
        StreamEvent(type="tool_call", tool_name="spawn_task", tool_args={"name": "CODER"})
    )
    assert signal is not None
    assert signal.kind is AgentSignalKind.DELEGATE

    other = stream_events_to_signals(
        StreamEvent(type="tool_call", tool_name="read_file", tool_args={"path": "a"})
    )
    assert other is not None
    assert other.kind is AgentSignalKind.TOOL_CALL


def test_the_turn_carries_observation_and_feedback_to_the_model() -> None:
    from backend.orchestrator.routes.chat_primary import _compose_query

    composed = _compose_query(
        PrimaryTurn(
            query="corrige o bug",
            cycle=2,
            observation=Observation(summary="", facts={"project": "/p", "entries": ["a.py"]}),
            feedback="A verificação falhou: 1 teste vermelho",
            guidance=("não mexas na API pública",),
        )
    )
    assert "corrige o bug" in composed
    assert "a.py" in composed
    assert "1 teste vermelho" in composed
    assert "não mexas na API pública" in composed


# ---------------------------------------------------------------- the fallback
try:  # the chat route needs the full app configuration to import
    from backend.orchestrator.routes import chat
except Exception:  # pragma: no cover - environment-dependent
    chat = None

requires_chat_route = pytest.mark.skipif(
    chat is None, reason="the chat route needs the full app configuration"
)


class _Req:
    def __init__(self, message: str, mode: str = "auto", project_path: str = "") -> None:
        self.message = message
        self.mode = mode
        self.project_path = project_path
        self.session_id = "s1"
        self.autonomous = False
        self.model = ""


async def _drain(generator) -> list[str]:
    return [frame async for frame in generator]


@pytest.fixture()
def seam(monkeypatch):
    """Replace both pipelines with recorders so only the choice is under test."""
    from backend.orchestrator.routes import chat_primary

    calls: dict[str, int] = {"legacy": 0, "primary": 0}

    async def fake_legacy(*args, **kwargs) -> AsyncIterator[str]:
        calls["legacy"] += 1
        yield 'data: {"type": "done", "path": "legacy"}\n\n'

    monkeypatch.setattr(chat, "_run_pipeline", fake_legacy)
    return calls, chat_primary, monkeypatch


@requires_chat_route
@pytest.mark.asyncio
async def test_direct_turns_go_to_the_primary_agent(seam) -> None:
    calls, chat_primary, monkeypatch = seam

    def fake_primary(*args, **kwargs) -> AsyncIterator[str]:
        async def iterator() -> AsyncIterator[str]:
            calls["primary"] += 1
            yield 'data: {"type": "done", "path": "nexus_primary"}\n\n'

        return iterator()

    monkeypatch.setattr(chat_primary, "run_primary_chat", fake_primary)
    frames = await _drain(
        chat._select_pipeline(_Req("corrige o typo no README"), None, None, None)
    )
    assert calls == {"legacy": 0, "primary": 1}
    assert "nexus_primary" in frames[-1]


@requires_chat_route
@pytest.mark.asyncio
async def test_planned_turns_still_use_the_legacy_pipeline(seam) -> None:
    calls, _chat_primary, _monkeypatch = seam
    message = (
        "audita o módulo de autenticação todo, implementa o refresh token que falta, "
        "escreve testes de integração para os dois fluxos e documenta as mudanças no "
        "README para a equipa saber o que mudou"
    )
    assert triage_request(message).request_class is RequestClass.PLANNED

    frames = await _drain(chat._select_pipeline(_Req(message), None, None, None))
    assert calls["legacy"] == 1
    assert calls["primary"] == 0
    assert "legacy" in frames[-1]


@requires_chat_route
@pytest.mark.asyncio
async def test_the_feature_flag_reverts_to_the_legacy_pipeline(seam, monkeypatch) -> None:
    calls, _chat_primary, _mp = seam
    monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "0")

    await _drain(chat._select_pipeline(_Req("corrige o typo"), None, None, None))
    assert calls["legacy"] == 1
    assert calls["primary"] == 0


@requires_chat_route
@pytest.mark.asyncio
async def test_a_failure_before_the_first_frame_falls_back_silently(seam) -> None:
    calls, chat_primary, monkeypatch = seam

    def exploding(*args, **kwargs) -> AsyncIterator[str]:
        async def iterator() -> AsyncIterator[str]:
            calls["primary"] += 1
            raise RuntimeError("the primary runtime is broken")
            yield ""  # pragma: no cover

        return iterator()

    monkeypatch.setattr(chat_primary, "run_primary_chat", exploding)
    frames = await _drain(chat._select_pipeline(_Req("corrige o typo"), None, None, None))

    assert calls["primary"] == 1
    assert calls["legacy"] == 1, "the user must still get an answer"
    assert "legacy" in frames[-1]


@requires_chat_route
@pytest.mark.asyncio
async def test_a_failure_after_streaming_starts_does_not_restart_the_turn(seam) -> None:
    """Restarting a half-rendered run would duplicate output in the browser."""
    calls, chat_primary, monkeypatch = seam

    def half_broken(*args, **kwargs) -> AsyncIterator[str]:
        async def iterator() -> AsyncIterator[str]:
            calls["primary"] += 1
            yield 'data: {"type": "token", "content": "olá"}\n\n'
            raise RuntimeError("provider died mid-stream")

        return iterator()

    monkeypatch.setattr(chat_primary, "run_primary_chat", half_broken)
    frames = await _drain(chat._select_pipeline(_Req("corrige o typo"), None, None, None))

    assert calls["legacy"] == 0, "the legacy pipeline replayed a run already on screen"
    assert any('"type":"error"' in f.replace(" ", "") for f in frames)
    assert any('"type":"done"' in f.replace(" ", "") for f in frames)


@requires_chat_route
@pytest.mark.asyncio
async def test_cancellation_propagates_instead_of_falling_back(seam) -> None:
    calls, chat_primary, monkeypatch = seam

    def cancelled(*args, **kwargs) -> AsyncIterator[str]:
        async def iterator() -> AsyncIterator[str]:
            raise asyncio.CancelledError
            yield ""  # pragma: no cover

        return iterator()

    monkeypatch.setattr(chat_primary, "run_primary_chat", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await _drain(chat._select_pipeline(_Req("corrige o typo"), None, None, None))
    assert calls["legacy"] == 0


# ------------------------------------------------------------ steering registry
def test_the_steering_registry_only_knows_live_runs() -> None:
    from backend.runtime import steering_registry
    from backend.runtime.primary import SteeringChannel

    channel = SteeringChannel()
    steering_registry.register_run("run-x", channel, session_id="s1")
    assert steering_registry.get_channel("run-x") is channel
    assert "run-x" in steering_registry.list_active_runs("s1")

    steering_registry.unregister_run("run-x")
    assert steering_registry.get_channel("run-x") is None


def test_stopping_an_unknown_run_is_not_an_error() -> None:
    from backend.runtime import steering_registry

    assert steering_registry.get_channel("run-que-nao-existe") is None


def test_verification_request_defaults_are_conservative() -> None:
    request = VerificationRequest(turn=PrimaryTurn(query="x"))
    assert request.changed_files == ()
    assert request.forced is False
