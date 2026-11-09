"""A chat turn must always answer, and two turns must not cross-talk.

The defects pinned here:

* the documented "the primary produced no frames" fallback was dead code (the
  ``return`` inside the ``try`` skipped it), so a primary that completed
  without a single frame ended the request with an EMPTY body — no error
  frame, no ``done`` frame, nothing for the client;
* two concurrent turns of the same session read the history after the other
  turn had already persisted its user message, so the second answer also
  addressed the first request;
* two requests that share one durable run (the same ``Idempotency-Key``)
  wrote the assistant row twice, leaving two identical rows in the
  transcript;
* a model could widen the filesystem sandbox by naming another directory in
  a tool call.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

try:  # the chat route needs the full app configuration to import
    from backend.orchestrator.routes import chat
except Exception:  # pragma: no cover - environment-dependent
    chat = None  # type: ignore[assignment]

requires_chat_route = pytest.mark.skipif(
    chat is None, reason="the chat route needs the full app configuration"
)


class _Req:
    def __init__(self, message: str, mode: str = "auto", project_path: str = "") -> None:
        self.message = message
        self.mode = mode
        self.project_path = project_path
        self.session_id = "s-defect"
        self.autonomous = False
        self.model = ""
        self.provider = ""
        self.thinking_strength = ""


def _frame_types(frames: list[str]) -> list[str]:
    return [chat._frame_type(frame) for frame in frames]


@requires_chat_route
@pytest.mark.asyncio
async def test_legacy_help_history_keeps_user_and_answer_on_the_same_run() -> None:
    from backend.orchestrator.context_manager import ContextStore
    from backend.persistence.db import get_messages

    request = _Req("/command")
    request.session_id = "s-help-run-link"
    frames = [frame async for frame in chat._run_pipeline(request, None, {}, ContextStore())]
    assert _frame_types(frames)[-1] == "done"
    rows = get_messages(request.session_id)
    user = next(row for row in rows if row["role"] == "user")
    answer = next(row for row in rows if row["role"] == "assistant")
    assert user["run_id"]
    assert answer["run_id"] == user["run_id"]


@requires_chat_route
@pytest.mark.asyncio
async def test_autonomous_journal_failure_does_not_restart_the_work(monkeypatch) -> None:
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.execution_contracts import ExecutionMode
    from backend.persistence.db import get_messages, get_session_run
    from backend.runtime.events import JournalWriteError

    request = _Req("Analisa e corrige o projeto")
    request.session_id = "s-journal-no-restart"
    monkeypatch.setattr(chat, "classify_execution_mode", lambda *_args: ExecutionMode.MISSION)

    async def source(**_kwargs):
        yield 'data: {"type":"token","content":"trabalho"}\n\n'

    async def journal_failure(frames, _run_id):
        await frames.aclose()
        raise JournalWriteError("disk unavailable")
        yield ""  # pragma: no cover - keep this an async generator

    async def unexpected_fallback(*_args, **_kwargs):
        raise AssertionError("work must not be restarted after journal failure")

    monkeypatch.setattr(chat, "_stream_autonomous_execution", source)
    monkeypatch.setattr(chat, "_ordered_autonomous_frames", journal_failure)
    monkeypatch.setattr(chat, "invoke_with_fallback", unexpected_fallback)
    frames = [json.loads(frame.removeprefix("data: ").strip()) async for frame in
              chat._run_pipeline(request, None, {}, ContextStore(), event_bus=object())]
    failure = next(frame for frame in frames if frame["type"] == "error")
    assert failure["data"]["error_category"] == "journal_write"
    assert frames[-1]["type"] == "done"
    run_id = failure["data"]["run_id"]
    assert get_session_run(run_id)["status"] == "failed"
    assert {row["run_id"] for row in get_messages(request.session_id)} == {run_id}


@requires_chat_route
def test_idempotency_key_is_scoped_to_authenticated_user_and_session() -> None:
    request = SimpleNamespace(headers={"Idempotency-Key": "same-client-key"}, state=SimpleNamespace())
    req = _Req("mesma mensagem")

    first = chat._request_idempotency_key(request, req, user_id="user-a")
    second = chat._request_idempotency_key(request, req, user_id="user-b")
    third = chat._request_idempotency_key(request, req, user_id="user-a")
    other_session = _Req("mesma mensagem")
    other_session.session_id = "s-outro"
    fourth = chat._request_idempotency_key(request, other_session, user_id="user-a")

    assert first != second
    assert first == third
    assert first != fourth
    assert first.startswith("h-")


@pytest.fixture()
def seam(monkeypatch: pytest.MonkeyPatch):
    """Replace both pipelines with recorders so only the choice is under test."""
    from backend.orchestrator.routes import chat_primary

    calls: dict[str, int] = {"legacy": 0, "primary": 0}

    async def fake_legacy(*args: Any, **kwargs: Any):
        calls["legacy"] += 1
        yield 'data: {"type": "done", "path": "legacy"}\n\n'

    monkeypatch.setattr(chat, "_run_pipeline", fake_legacy)
    return calls, chat_primary, monkeypatch


# ---------------------------------------------------------------------------
# D1 — the zero-frame fallback must run, and the turn must end with a done
# ---------------------------------------------------------------------------
@requires_chat_route
@pytest.mark.asyncio
async def test_zero_frame_primary_falls_back_to_legacy(seam) -> None:
    calls, chat_primary, monkeypatch = seam

    def silent_primary(*args: Any, **kwargs: Any):
        async def iterator():
            calls["primary"] += 1
            # A primary that completes normally without emitting a single
            # frame: the documented fallback has to take over.
            if False:  # pragma: no cover - never yields
                yield ""

        return iterator()

    monkeypatch.setattr(chat_primary, "run_primary_chat", silent_primary)
    frames = [frame async for frame in chat._select_pipeline(_Req("corrige o typo"), None, None, None)]

    assert calls["primary"] == 1
    assert calls["legacy"] == 1, "the user must still get an answer"
    assert any('"legacy"' in frame for frame in frames)


@requires_chat_route
@pytest.mark.asyncio
async def test_a_chat_turn_always_emits_a_done_frame(seam) -> None:
    calls, chat_primary, monkeypatch = seam

    def silent_primary(*args: Any, **kwargs: Any):
        async def iterator():
            calls["primary"] += 1
            if False:  # pragma: no cover - never yields
                yield ""

        return iterator()

    async def forgetful_legacy(*args: Any, **kwargs: Any):
        calls["legacy"] += 1
        yield 'data: {"type": "token", "content": "olá"}\n\n'

    monkeypatch.setattr(chat_primary, "run_primary_chat", silent_primary)
    monkeypatch.setattr(chat, "_run_pipeline", forgetful_legacy)

    frames = [
        frame async for frame in chat._select_pipeline(_Req("corrige o typo"), None, None, None)
    ]
    types = _frame_types(frames)

    # The client reads until a "done" event. Whatever the lane did, the turn
    # ends with the terminal frame.
    assert types, "the turn produced no frame at all"
    assert types[-1] == "done"
    assert types.count("done") == 1


@requires_chat_route
@pytest.mark.asyncio
async def test_a_chat_turn_always_emits_a_done_frame_after_a_partial_primary(seam) -> None:
    calls, chat_primary, monkeypatch = seam

    def partial_primary(*args: Any, **kwargs: Any):
        async def iterator():
            calls["primary"] += 1
            yield 'data: {"type": "token", "content": "olá"}\n\n'

        return iterator()

    monkeypatch.setattr(chat_primary, "run_primary_chat", partial_primary)
    frames = [
        frame async for frame in chat._select_pipeline(_Req("corrige o typo"), None, None, None)
    ]
    types = _frame_types(frames)

    assert calls["legacy"] == 0, "the legacy pipeline replayed a run already on screen"
    assert types[-1] == "done"


# ---------------------------------------------------------------------------
# D5 — two concurrent turns of one session must not see each other
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_concurrent_turns_in_one_session_do_not_see_each_other(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.orchestrator import advanced_modes
    from backend.orchestrator import registry as agent_registry
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.routes import chat_primary
    from backend.persistence.db import add_message, create_session, upsert_session_run

    session_id = "s-concurrent-turns"
    create_session(session_id=session_id, title="conversa", mode="auto")

    # Turn A is in flight: its user message is already durable.
    upsert_session_run(
        "run-a",
        session_id,
        status="running",
        execution_state="running",
        prompt="ALFA-AAA-111",
    )
    add_message(session_id, "user", "ALFA-AAA-111", run_id="run-a")
    # A finished turn is real history and must be kept.
    upsert_session_run(
        "run-done",
        session_id,
        status="completed",
        execution_state="completed",
        finished=True,
        prompt="pergunta antiga",
    )
    add_message(session_id, "assistant", "resposta antiga", run_id="run-done")

    captured: dict[str, Any] = {}

    def capture(**kwargs: Any):
        captured.update(kwargs)
        raise RuntimeError("the history was captured")

    class _NoActiveModes:
        def build_active_execution_profile(self) -> dict[str, Any]:
            return {}

        def prepare_active_execution_profile(self, _message: str) -> dict[str, Any]:
            return {}

    monkeypatch.setattr(advanced_modes, "get_orchestrator", lambda: _NoActiveModes())
    monkeypatch.setattr(agent_registry, "resolve", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(chat_primary, "make_signal_stream", capture)

    context = ContextStore()
    req = SimpleNamespace(
        message="BETA-BBB-222",
        session_id=session_id,
        project_path="",
        mode="auto",
        model="",
        provider="",
        thinking_strength="",
        autonomous=False,
    )
    decision = chat_primary.plan_turn(req.message, "auto", "")

    with pytest.raises(RuntimeError):
        async for _frame in chat_primary.run_primary_chat(
            req, object(), object(), context, decision=decision
        ):
            pass

    contents = [str(getattr(message, "content", "")) for message in captured["history"]]
    assert "ALFA-AAA-111" not in contents, "the in-flight turn leaked into this history"
    assert "resposta antiga" in contents, "real history must be kept"


# ---------------------------------------------------------------------------
# D6 — one durable run, one assistant row
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_idempotent_duplicate_does_not_create_two_assistant_rows() -> None:
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.routes import chat_primary
    from backend.persistence.db import create_session, get_messages
    from backend.runtime import primary as runtime_primary

    session_id = "s-idempotent"
    create_session(session_id=session_id, title="conversa", mode="auto")

    # Two requests with the same Idempotency-Key share ONE durable run.
    first = runtime_primary.RunLifecycle.begin(
        goal="pergunta", session_id=session_id, idempotency_key="key-1"
    )
    second = runtime_primary.RunLifecycle.begin(
        goal="pergunta", session_id=session_id, idempotency_key="key-1"
    )
    assert first is not None and second is not None
    assert first.run_id == second.run_id, "the retry must adopt the same durable run"

    outcome = SimpleNamespace(
        answer="a resposta do modelo",
        interrupted=False,
        failed=False,
        stopped=False,
        error="",
        telemetry={},
    )
    loop = SimpleNamespace(run_id=first.run_id, outcome=outcome)
    req = SimpleNamespace(message="pergunta")
    context = ContextStore()

    await chat_primary._persist(context, req, loop, session_id)
    await chat_primary._persist(context, req, loop, session_id)

    rows = get_messages(session_id, limit=50)
    assistant_rows = [row for row in rows if row.get("role") == "assistant"]
    assert len(assistant_rows) == 1, "the transcript shows the same answer twice"


@pytest.mark.asyncio
async def test_primary_persists_provider_usage_on_run_and_assistant_message() -> None:
    """A completed PRIMARY turn keeps its model/provider/token evidence durable."""
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.routes import chat_primary
    from backend.persistence.db import create_session, get_messages, get_session_run

    session_id = "s-primary-usage-persist"
    run_id = "run-primary-usage-persist"
    create_session(session_id=session_id, title="usage", mode="auto")
    verification = SimpleNamespace(ran=True, ok=True, summary="ok", command="pytest -q")
    loop = SimpleNamespace(
        run_id=run_id,
        outcome=SimpleNamespace(
            answer="resposta real",
            interrupted=False,
            failed=False,
            stopped=False,
            error="",
            telemetry={"provider_calls": 1},
            changed_files=[],
            verification=verification,
        ),
        changed_files=[],
        skill_activations=[],
    )
    req = SimpleNamespace(message="pergunta", mode="auto", model="", provider="")
    usage = {
        "input_tokens": 41,
        "output_tokens": 13,
        "total_tokens": 54,
        "cost_usd": 0.0007,
        "source": "provider",
        "provider": {"name": "openrouter", "model": "liquid/lfm-2.5-2.6b:free"},
    }

    await chat_primary._persist(ContextStore(), req, loop, session_id, usage=usage)

    assistants = [row for row in get_messages(session_id) if row["role"] == "assistant"]
    assert len(assistants) == 1
    assert assistants[0]["model_used"] == "liquid/lfm-2.5-2.6b:free"
    assert assistants[0]["tokens_in"] == 41
    assert assistants[0]["tokens_out"] == 13
    assert assistants[0]["cost_usd"] == pytest.approx(0.0007)
    saved = get_session_run(run_id)
    assert saved is not None
    assert saved["provider"] == "openrouter"
    assert saved["model"] == "liquid/lfm-2.5-2.6b:free"
    assert json.loads(saved["usage_json"]) == usage


@pytest.mark.asyncio
async def test_primary_explicit_provider_selection_is_cost_governed() -> None:
    from backend.llm.factory import ResilientLLMProvider
    from backend.orchestrator.routes import chat_primary

    provider = SimpleNamespace(provider_name="openrouter")
    manager = SimpleNamespace(providers={"openrouter": provider}, free_only=True)
    request = SimpleNamespace(provider="openrouter", model="liquid/model:free")

    selected, error = await chat_primary._request_provider_client(request, manager)

    assert error is None
    assert isinstance(selected, ResilientLLMProvider)
    assert selected.primary is provider
    assert selected.free_only is True


# ---------------------------------------------------------------------------
# D7 — the project root is server-side context
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_model_supplied_project_path_is_ignored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from backend.orchestrator.main import app
    from backend.runtime import spawn_registry
    from backend.runtime.run_context import reset_current_run_id, set_current_run_id
    from backend.tools.task_spawner import spawn_task

    trusted = str(tmp_path / "projeto")
    foreign = str(Path.home())

    # 1. The chat lane replaces the root the model asked for.
    args = chat.strip_untrusted_project_path(
        {"path": "src/app.py", "project_path": foreign}, trusted
    )
    assert args["project_path"] == trusted
    assert foreign not in [str(value) for value in args.values()]

    # 2. The tool call the client sees carries the trusted root too.
    payload = json.dumps({"path": "src/app.py", "project_path": foreign})
    events = chat._parse_inline_events(
        f"<event>tool_call|read_file|{payload}</event>", "NEXUS", trusted
    )
    tool_events = [event for event in events if event.type == "tool_call"]
    assert tool_events, "the tool call was not parsed"
    assert tool_events[0].tool_args["project_path"] == trusted

    # 3. The delegated worker inherits the trusted root, not the model's.
    captured: dict[str, Any] = {}

    class _Lifecycle:
        async def spawn(self, **kwargs: Any) -> str:
            captured.update(kwargs)
            return "inst-1"

    run_id = "run-trusted-project"
    spawn_registry.register_run_project(run_id, trusted)
    token = set_current_run_id(run_id)
    monkeypatch.setattr(app.state, "agent_lifecycle", _Lifecycle(), raising=False)
    try:
        result = await spawn_task(
            name="worker",
            description="trabalhar dentro do projeto",
            definition_of_done="o ficheiro foi alterado",
            session_id="s-trusted-project",
            project_path=foreign,
        )
    finally:
        reset_current_run_id(token)
        spawn_registry.clear_run_project(run_id)

    assert result["status"] == "spawned"
    assert captured["context"]["project_path"] == trusted
    assert captured["context"]["project_path"] != foreign
