"""Truthful terminal status for primary agent runs."""

from __future__ import annotations

import json
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
    PrimaryTurn,
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
    from backend.llm.factory import ResilientLLMProvider

    local = SimpleNamespace(provider_name="lmstudio")
    openrouter = SimpleNamespace(provider_name="openrouter")
    default_client = SimpleNamespace(primary=local, fallbacks=[openrouter])
    request = SimpleNamespace(
        provider="openrouter",
        model="liquid/lfm-2.5-2.6b:free",
    )

    selected, error = await chat_primary._request_provider_client(request, default_client)

    assert isinstance(selected, ResilientLLMProvider)
    assert selected.primary is openrouter
    assert selected.fallbacks == []
    assert error is None


@pytest.mark.asyncio
async def test_primary_pinned_primary_provider_does_not_fall_through_to_another_provider() -> None:
    from backend.llm.factory import ResilientLLMProvider

    openrouter = SimpleNamespace(provider_name="openrouter")
    fallback = SimpleNamespace(provider_name="lmstudio")
    default_client = ResilientLLMProvider(openrouter, [fallback])
    request = SimpleNamespace(provider="openrouter", model="liquid/model:free")

    selected, error = await chat_primary._request_provider_client(request, default_client)

    assert error is None
    assert isinstance(selected, ResilientLLMProvider)
    assert selected.primary is openrouter
    assert selected.fallbacks == []


@pytest.mark.asyncio
@pytest.mark.parametrize("request_provider", ["lmstudio", ""])
async def test_primary_passes_selected_provider_role_model_when_model_is_omitted(
    monkeypatch: pytest.MonkeyPatch,
    request_provider: str,
) -> None:
    from backend.orchestrator import advanced_modes
    from backend.orchestrator import registry as agent_registry
    from backend.orchestrator.context_manager import ContextStore

    roles_seen: list[str] = []

    class LMStudioWrapper:
        provider_name = "lmstudio"

        def resolve_model(self, role: str) -> str:
            roles_seen.append(role)
            return "spark-x2.5-4b" if role == "coder" else role

    provider = LMStudioWrapper()
    if request_provider:
        client = SimpleNamespace(providers={"lmstudio": provider}, free_only=False)
    else:
        from backend.llm.factory import ResilientLLMProvider

        client = ResilientLLMProvider(provider, [])
    agent = SimpleNamespace(model_key="coder")
    captured: dict[str, object] = {}

    class StopAfterSelection(Exception):
        pass

    class NoActiveModes:
        def build_active_execution_profile(self) -> dict[str, object]:
            return {}

        def prepare_active_execution_profile(self, _message: str) -> dict[str, object]:
            return {}

    def capture_stream_factory(**kwargs: object) -> None:
        captured.update(kwargs)
        raise StopAfterSelection

    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: False)
    monkeypatch.setattr(advanced_modes, "get_orchestrator", lambda: NoActiveModes())
    monkeypatch.setattr(agent_registry, "resolve", lambda *_args: agent)
    monkeypatch.setattr(chat_primary, "make_signal_stream", capture_stream_factory)

    request = SimpleNamespace(
        message="Olá",
        session_id="session-provider-role-model",
        project_path="",
        mode="auto",
        model="",
        provider=request_provider,
        model_is_concrete=False,
        thinking_strength="",
        autonomous=False,
    )
    with pytest.raises(StopAfterSelection):
        async for _frame in chat_primary.run_primary_chat(
            request,
            client,
            {},
            ContextStore(),
            decision=chat_primary.plan_turn("Olá", "auto", ""),
            owner_id="user-provider-role-model",
        ):
            pass

    selected_client = captured["llm_client"]
    assert selected_client.primary is provider
    assert captured["agent_context"]["_model_override"] == "spark-x2.5-4b"
    assert roles_seen == ["coder"]


@pytest.mark.asyncio
async def test_primary_dispatches_pinned_lmstudio_model_to_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.agents.nexus_primary import NexusPrimaryAgent
    from backend.orchestrator import advanced_modes
    from backend.orchestrator import registry as agent_registry
    from backend.orchestrator.context_manager import ContextStore

    dispatched: list[tuple[str, str]] = []

    class LMStudioWrapper:
        provider_name = "lmstudio"
        last_model = ""
        last_finish_reason = "stop"
        last_usage: dict[str, int] = {}

        async def chat_stream(self, model: str, messages: list[dict], **_kwargs):
            dispatched.append((self.provider_name, model))
            self.last_model = model
            yield "Resposta fixture do provider."

    class NoActiveModes:
        def build_active_execution_profile(self) -> dict[str, object]:
            return {}

        def prepare_active_execution_profile(self, _message: str) -> dict[str, object]:
            return {}

    agent = NexusPrimaryAgent()
    agent.system_prompt = lambda: "prompt fixture"
    provider = LMStudioWrapper()
    client = SimpleNamespace(providers={"lmstudio": provider}, free_only=False)
    monkeypatch.setenv("NEXUS_ADVISOR_ENABLED", "0")
    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: False)
    monkeypatch.setattr(advanced_modes, "get_orchestrator", lambda: NoActiveModes())
    monkeypatch.setattr(agent_registry, "resolve", lambda *_args: agent)

    request = SimpleNamespace(
        message="Olá",
        session_id="session-primary-pinned-lmstudio-model",
        project_path="",
        mode="auto",
        model="spark-x2.5-4b",
        provider="lmstudio",
        model_is_concrete=True,
        thinking_strength="",
        autonomous=False,
    )
    frames = [
        frame
        async for frame in chat_primary.run_primary_chat(
            request,
            client,
            {},
            ContextStore(),
            decision=chat_primary.plan_turn("Olá", "auto", ""),
            owner_id="user-primary-pinned-lmstudio-model",
        )
    ]

    assert dispatched == [("lmstudio", "spark-x2.5-4b")]
    assert any('"type":"done"' in frame for frame in frames)


@pytest.mark.asyncio
async def test_primary_reports_journal_failure_before_contacting_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path,
) -> None:
    from backend.agents.nexus_primary import NexusPrimaryAgent
    from backend.orchestrator import advanced_modes
    from backend.orchestrator import registry as agent_registry
    from backend.orchestrator.context_manager import ContextStore
    from backend.persistence.db import get_messages, get_session_run
    from backend.runtime import events as runtime_events

    called = []

    class Provider:
        provider_name = "lmstudio"

        async def chat_stream(self, model, messages, **_kwargs):
            called.append(model)
            yield "Não devia ser enviado."

    class NoActiveModes:
        def build_active_execution_profile(self):
            return {}

        def prepare_active_execution_profile(self, _message):
            return {}

    def broken_append(_path, _line):
        raise OSError("journal unavailable")

    monkeypatch.setenv("NEXUS_EVENT_JOURNAL", "1")
    monkeypatch.setattr(runtime_events, "run_event_journal_path", lambda _run_id: tmp_path / "run.jsonl")
    monkeypatch.setattr(runtime_events, "_append_line", broken_append)
    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: False)
    monkeypatch.setattr(advanced_modes, "get_orchestrator", lambda: NoActiveModes())
    monkeypatch.setattr(agent_registry, "resolve", lambda *_args: NexusPrimaryAgent())
    request = SimpleNamespace(
        message="Olá", session_id="session-journal-failure", project_path="", mode="auto",
        model="spark-x2.5-4b", provider="lmstudio", model_is_concrete=True,
        thinking_strength="", autonomous=False,
    )
    client = SimpleNamespace(providers={"lmstudio": Provider()}, free_only=False)
    frames = [json.loads(frame.removeprefix("data: ").strip()) async for frame in
              chat_primary.run_primary_chat(request, client, {}, ContextStore(),
                  decision=chat_primary.plan_turn("Olá", "auto", ""), owner_id="fixture")]

    failure = next(frame for frame in frames if frame["type"] == "error")
    assert failure["data"]["error_category"] == "journal_write"
    assert not called
    assert not any(frame["type"] in {"routing", "token"} for frame in frames)
    assert get_session_run(failure["data"]["run_id"])["status"] == "failed"
    saved = get_messages(request.session_id)
    assert all("Nada foi alterado" not in row["content"] for row in saved)
    assert frames[-1]["type"] == "done"


@pytest.mark.asyncio
async def test_primary_fails_closed_for_an_unconfigured_selected_provider() -> None:
    default_client = SimpleNamespace(primary=SimpleNamespace(provider_name="lmstudio"), fallbacks=[])
    request = SimpleNamespace(provider="openrouter", model="liquid/lfm-2.5-2.6b:free")

    selected, error = await chat_primary._request_provider_client(request, default_client)

    assert selected is None
    assert error is not None
    assert "openrouter" in error


@pytest.mark.asyncio
async def test_primary_fails_closed_when_a_pinned_model_has_no_resolved_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_catalog_models() -> dict[str, list[dict[str, str]]]:
        return {"models": []}

    monkeypatch.setattr("backend.llm.model_catalog.aggregate_models", no_catalog_models)
    default_client = SimpleNamespace(provider_name="lmstudio")
    request = SimpleNamespace(provider="", model="unknown-provider/model-x")

    selected, error = await chat_primary._request_provider_client(request, default_client)

    assert selected is None
    assert error is not None
    assert "unknown-provider/model-x" in error


@pytest.mark.asyncio
async def test_primary_resolves_provider_for_concrete_model_without_separator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.llm.factory import ResilientLLMProvider

    async def catalog_models() -> dict[str, list[dict[str, str]]]:
        return {"models": [{"id": "local-model", "provider": "ollama"}]}

    monkeypatch.setattr("backend.llm.model_catalog.aggregate_models", catalog_models)
    local = SimpleNamespace(provider_name="lmstudio")
    ollama = SimpleNamespace(provider_name="ollama")
    default_client = SimpleNamespace(primary=local, fallbacks=[ollama])
    request = SimpleNamespace(
        provider="",
        model="local-model",
        model_is_concrete=False,
    )

    selected, error = await chat_primary._request_provider_client(request, default_client)

    assert isinstance(selected, ResilientLLMProvider)
    assert selected.primary is ollama
    assert selected.fallbacks == []
    assert error is None


@pytest.mark.asyncio
async def test_provider_selection_error_fails_adopted_run_and_resets_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json

    calls: list[tuple[str, object]] = []

    class Lifecycle:
        run_id = "adopted-run-id"
        closed = False

        def fail(self, reason: str) -> None:
            calls.append(("failed", reason))
            self.closed = True

    lifecycle = Lifecycle()
    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: True)
    monkeypatch.setattr(chat_primary.RunLifecycle, "begin", lambda **_kwargs: lifecycle)
    monkeypatch.setattr(chat_primary, "_primary_run_user_id", lambda _session: "")
    monkeypatch.setattr(
        chat_primary,
        "_publish_run_context",
        lambda run_id: calls.append(("published", run_id)) or "context-token",
    )
    monkeypatch.setattr(
        chat_primary,
        "_clear_run_context",
        lambda token: calls.append(("cleared", token)),
    )

    async def provider_error(_req, _client):
        return None, "provider unavailable"

    monkeypatch.setattr(chat_primary, "_request_provider_client", provider_error)
    req = SimpleNamespace(
        session_id="provider-error-session",
        project_path="",
        message="responde",
        provider="missing",
        model="model-x",
    )
    frames = [
        json.loads(frame.removeprefix("data: ").strip())
        async for frame in chat_primary.run_primary_chat(
            req,
            object(),
            object(),
            SimpleNamespace(),
            decision=chat_primary.plan_turn("responde", "auto", ""),
        )
    ]

    assert ("published", "adopted-run-id") in calls
    assert ("failed", "provider selection failed: provider unavailable") in calls
    assert ("cleared", "context-token") in calls
    assert frames[0]["data"]["run_id"] == "adopted-run-id"


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


def test_primary_classifies_incomplete_synthesis_marker_as_failure() -> None:
    from backend.models.api import StreamEvent

    signal = chat_primary.stream_events_to_signals(
        StreamEvent(
            type="token",
            content=(
                "[RECOLHA CONCLUÍDA — SÍNTESE INCOMPLETA] As ferramentas correram, "
                "mas o modelo não produziu a análise final."
            ),
        )
    )

    assert signal is not None
    assert signal.kind is AgentSignalKind.ERROR
    assert signal.ok is False
    assert signal.payload["reason"] == "agent_incomplete"


@pytest.mark.asyncio
async def test_primary_honors_request_scoped_agent_failure_verdict() -> None:
    class IncompleteAgent:
        def run(self, request):
            async def stream():
                request.context["_agent_run_success"] = False
                yield "<event>answer</event>"

            return stream()

    stream_factory = chat_primary.make_signal_stream(
        agent=IncompleteAgent(),
        llm_client=object(),
        session_id="session-agent-verdict",
        run_id="run-agent-verdict",
        project_path="",
        history=[],
        agent_context={},
        max_iterations=4,
        autonomous=False,
    )
    signals = [signal async for signal in stream_factory(PrimaryTurn(query="faz a tarefa"))]

    assert signals[-1].kind is AgentSignalKind.ERROR
    assert signals[-1].payload["reason"] == "agent_incomplete"


@pytest.mark.asyncio
@pytest.mark.parametrize("with_delegation", [True, False])
async def test_scheduler_handoff_requires_an_observed_proposal(with_delegation: bool) -> None:
    from backend.agents.event_protocol import encode_event

    class HandoffAgent:
        def run(self, request):
            async def stream():
                request.context["_agent_run_success"] = False
                request.context["_nexus_yielded_to_scheduler"] = True
                if with_delegation:
                    yield encode_event("tool_call", "spawn_task", json.dumps({
                        "name": "review", "description": "Inspect the task",
                        "definition_of_done": "Report evidence",
                    }))

            return stream()

    stream_factory = chat_primary.make_signal_stream(
        agent=HandoffAgent(), llm_client=object(), session_id="handoff-test",
        run_id="handoff-test", project_path="", history=[], agent_context={},
        max_iterations=4, autonomous=True,
    )
    signals = [signal async for signal in stream_factory(PrimaryTurn(query="faz a tarefa"))]

    if with_delegation:
        assert any(signal.kind is AgentSignalKind.DELEGATE for signal in signals)
        assert not any(signal.kind is AgentSignalKind.ERROR for signal in signals)
    else:
        assert signals[-1].kind is AgentSignalKind.ERROR
        assert signals[-1].payload["reason"] == "agent_incomplete"


@pytest.mark.asyncio
async def test_requested_delegations_reach_scheduler_before_parent_continues(tmp_path) -> None:
    from backend.agents.base import AgentAction, AgentBase

    class ScriptedPrimary(AgentBase):
        name = "NEXUS"
        model_key = "nano"
        prompt_file = "router"
        supported_actions = {AgentAction.SPAWN_TASK}

        def __init__(self):
            self.model_calls = 0
            self.turns = 0
            self.child_feedback_seen = False

        async def stream_llm(self, request, **_kwargs):
            self.model_calls += 1
            name = {1: "first", 2: "second"}[self.model_calls]
            yield '```tool\n' + json.dumps({"name": "spawn_task", "arguments": {
                "name": name, "description": f"Inspect {name}",
                "definition_of_done": "Report evidence",
            }}) + '\n```'

        async def run(self, request):
            self.turns += 1
            if self.turns == 1:
                async for token in self._run_react_loop(request):
                    yield token
            else:
                self.child_feedback_seen = "RESULTADOS DOS SUBAGENTES" in request.query
                request.context["_agent_run_success"] = True
                yield "<event>answer</event>"
                yield "Resultados recebidos."

    async def subagent(proposal):
        return f"Resultado de {proposal.name}"

    agent = ScriptedPrimary()
    stream = chat_primary.make_signal_stream(
        agent=agent, llm_client=object(), session_id="handoff-flow", run_id="handoff-flow",
        project_path=str(tmp_path), history=[], agent_context={"_nexus_primary": True},
        max_iterations=4, autonomous=True,
    )
    loop = PrimaryLoop(
        run_id="handoff-flow", query="Analisa com dois subagentes", stream=stream,
        project_path=str(tmp_path), run_subagent=subagent, max_cycles=1,
    )
    events = [event async for event in loop.run()]

    assert agent.model_calls == 2
    assert len([event for event in events if event.type is RuntimeEventType.SUBAGENT_STARTED]) == 2
    assert {result.status for result in loop.outcome.subagents} == {"completed"}
    assert agent.child_feedback_seen is True
    assert loop.outcome.failed is False
