"""Regression coverage for projectless primary turns and iteration exhaustion."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.agents.base import AgentAction, AgentBase, AgentRequest
from backend.models.api import StreamEvent
from backend.orchestrator.routes import chat_primary
from backend.runtime.events import RuntimeEventType
from backend.runtime.primary import AgentSignalKind, PrimaryLoop
from backend.runtime.triage import RequestClass, triage_request

REPOSITORY_AUDIT = (
    "# Auditoria ao próprio sistema\n\n"
    "Audita o funcionamento real e investiga o código do projeto.\n\n"
    "**Repositório principal:** `C:\\Users\\rodri\\Desktop\\nexus`\n"
    "Analisa o backend e reporta as limitações com evidências."
)


def test_explicit_repository_audit_requires_selection_but_never_selects_a_path() -> None:
    decision = triage_request(REPOSITORY_AUDIT, has_project=False)
    assert chat_primary._requires_selected_project(
        REPOSITORY_AUDIT, decision, has_project=False
    )
    assert not chat_primary._requires_selected_project(
        REPOSITORY_AUDIT, decision, has_project=True
    )


def test_projectless_tool_tasks_can_select_global_skills() -> None:
    decision = triage_request(
        "Pesquisa fontes oficiais sobre Python",
        requested_mode="auto",
        has_project=False,
    )
    assert decision.request_class is RequestClass.DIRECT
    assert chat_primary._should_select_automatic_skills(object(), decision)
    assert not chat_primary._should_select_automatic_skills(None, decision)

    conversational = triage_request("O que é Python?", has_project=False)
    assert not chat_primary._should_select_automatic_skills(object(), conversational)


@pytest.mark.parametrize(
    "message",
    [
        "Lista as skills disponíveis nesta sessão.",
        "Explica como se faz uma auditoria a um repositório.",
        "Repositório principal: C:\\example\\demo\nEscreve um slogan para o produto.",
        "Audita este excerto de código: print('hello').",
    ],
)
def test_project_selection_preflight_does_not_block_general_requests(message: str) -> None:
    decision = triage_request(message, has_project=False)
    assert not chat_primary._requires_selected_project(message, decision, has_project=False)


def test_projectless_tool_turns_can_use_results_within_existing_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("NEXUS_PRIMARY_MAX_ITERATIONS", raising=False)
    work = triage_request("Lista as skills disponíveis nesta sessão.", has_project=False)
    greeting = triage_request("olá", has_project=False)
    ambiguous = triage_request("faz", has_project=False)
    assert work.request_class is RequestClass.DIRECT
    assert chat_primary._primary_max_iterations(
        work, has_project=False, advanced_mode_iteration_cap=None
    ) == 12
    assert chat_primary._primary_max_iterations(
        work, has_project=True, advanced_mode_iteration_cap=None
    ) == 25
    assert chat_primary._primary_max_iterations(
        greeting, has_project=False, advanced_mode_iteration_cap=None
    ) == 1
    assert chat_primary._primary_max_iterations(
        ambiguous, has_project=False, advanced_mode_iteration_cap=None
    ) == 1
    assert chat_primary._primary_max_iterations(
        work, has_project=False, advanced_mode_iteration_cap=2
    ) == 2
    monkeypatch.setenv("NEXUS_PRIMARY_MAX_ITERATIONS", "2")
    assert chat_primary._primary_max_iterations(
        work, has_project=False, advanced_mode_iteration_cap=None
    ) == 2
    for invalid in ("0", "-1", "not-a-number"):
        monkeypatch.setenv("NEXUS_PRIMARY_MAX_ITERATIONS", invalid)
        assert chat_primary._primary_max_iterations(
            work, has_project=False, advanced_mode_iteration_cap=None
        ) == 12


def test_iteration_limit_reason_is_visible_without_exposing_arbitrary_text() -> None:
    signal = chat_primary.stream_events_to_signals(
        StreamEvent(
            type="token",
            content=(
                "[TAREFA NÃO CONCLUÍDA] O agente atingiu o limite de 1 passos "
                "sem produzir uma resposta final. Extra private text."
            ),
        )
    )
    assert signal is not None and signal.kind is AgentSignalKind.ERROR
    assert "limite de 1 passo" in signal.text
    assert "seleciona um projeto" in signal.text
    assert "Extra private text" not in signal.text
    assert signal.payload["cause"] == "iteration_limit"

    selected = chat_primary.stream_events_to_signals(
        StreamEvent(
            type="token",
            content=(
                "[TAREFA NÃO CONCLUÍDA] O agente atingiu o limite de 8 passos "
                "sem produzir uma resposta final."
            ),
        ),
        trusted_project_path="C:/test-project",
    )
    assert selected is not None and "limite de 8 passos" in selected.text
    assert "seleciona um projeto" not in selected.text


@pytest.mark.asyncio
async def test_no_project_tool_call_gets_a_follow_up_and_an_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.agents import base

    calls: list[str] = []

    async def fake_execute_tool(name: str, _session: str, _args: dict, **_kwargs: object) -> dict:
        calls.append(name)
        return {"tool": name, "result": {"skills": [{"name": "example-skill"}]}}

    monkeypatch.setattr(base, "execute_tool", fake_execute_tool)
    monkeypatch.setattr(base, "get_conversation_logger", lambda _session: MagicMock())

    class ScriptedAgent(AgentBase):
        name = "NEXUS"
        model_key = "nano"
        prompt_file = "nexus_primary"
        supported_actions = {
            AgentAction.LIST_SKILLS, AgentAction.MCP_LIST_TOOLS,
            AgentAction.LOAD_SKILL, AgentAction.GET_SESSION_STATUS,
        }
        turns = 0
        saw_result = False

        async def stream_llm(self, _request: AgentRequest, **kwargs: object) -> AsyncIterator[str]:
            self.turns += 1
            tool_calls = [
                '{"name":"list_skills","arguments":{}}',
                '{"name":"mcp_list_tools","arguments":{}}',
                '{"name":"load_skill","arguments":{"name":"example-skill"}}',
                '{"name":"get_session_status","arguments":{"session_id":"projectless-tool-test"}}',
            ]
            if self.turns <= len(tool_calls):
                yield f'```tool\n{tool_calls[self.turns - 1]}\n```'
            else:
                self.saw_result = "example-skill" in str(kwargs.get("context", ""))
                yield "A skill disponível é example-skill."

        def run(self, request: AgentRequest) -> AsyncIterator[str]:
            return self._run_react_loop(request)

    message = "Lista as skills disponíveis nesta sessão."
    decision = triage_request(message, has_project=False)
    policy = chat_primary._tool_policy_context(decision, has_project=False)
    assert "list_skills" in policy["_allowed_tools"]
    assert "read_file" not in policy["_allowed_tools"]
    agent = ScriptedAgent()
    stream = chat_primary.make_signal_stream(
        agent=agent,
        llm_client=object(),
        session_id="projectless-tool-test",
        run_id="projectless-tool-test",
        project_path="",
        history=[],
        agent_context={**policy, "_nexus_primary": True},
        max_iterations=chat_primary._primary_max_iterations(
            decision, has_project=False, advanced_mode_iteration_cap=None
        ),
        autonomous=False,
    )
    loop = PrimaryLoop(
        run_id="projectless-tool-test", query=message, project_path="", stream=stream,
        max_cycles=1,
    )
    events = [event async for event in loop.run()]
    await loop.events.aclose()

    assert calls == ["list_skills", "mcp_list_tools", "load_skill", "get_session_status"]
    assert agent.turns == 5 and agent.saw_result
    assert any(event.type is RuntimeEventType.TOOL_COMPLETED for event in events)
    assert events[-1].type is RuntimeEventType.RUN_COMPLETED
    assert not any(event.type is RuntimeEventType.RUN_FAILED for event in events)
    assert "example-skill" in loop.outcome.answer


@pytest.mark.asyncio
async def test_repository_preflight_is_persisted_without_calling_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from backend.orchestrator import advanced_modes, registry
    from backend.orchestrator.routes import chat
    from backend.persistence import db

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("The missing-project preflight must not call the provider or agent")

    class Context:
        def __init__(self) -> None:
            self.messages: list[object] = []

        async def get_history(self, _session: str) -> list[object]:
            return []

        async def append_message(self, _session: str, message: object) -> None:
            self.messages.append(message)

    async def not_answered(*_args: object, **_kwargs: object) -> bool:
        return False

    saved: list[dict] = []
    monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "1")
    monkeypatch.delenv("NEXUS_LEGACY_PLANNED", raising=False)
    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: False)
    monkeypatch.setattr(chat_primary, "_primary_journal_path", lambda _run: None)
    monkeypatch.setattr(chat_primary, "_primary_run_user_id", lambda _session: "")
    monkeypatch.setattr(chat_primary, "_request_provider_client", forbidden)
    monkeypatch.setattr(chat_primary, "build_usage_metric", forbidden)
    monkeypatch.setattr(chat_primary, "_run_already_answered", not_answered)
    monkeypatch.setattr(registry, "resolve", forbidden)
    monkeypatch.setattr(
        advanced_modes, "get_orchestrator",
        lambda: SimpleNamespace(build_active_execution_profile=lambda: {}),
    )
    monkeypatch.setattr(db, "add_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(db, "upsert_session_run", lambda *_args, **kw: saved.append(kw))
    monkeypatch.setattr(chat_primary, "upsert_session_run", lambda *_args, **kw: saved.append(kw))
    request = SimpleNamespace(
        message=REPOSITORY_AUDIT,
        session_id="preflight-test",
        mode="auto",
        project_path="",
        model="",
        provider="",
        autonomous=False,
    )
    context = Context()
    frames = [
        json.loads(frame.removeprefix("data: ").strip())
        async for frame in chat._select_pipeline(
            request, object(), {}, context, user_id="test-user"
        )
    ]

    errors = [frame for frame in frames if frame.get("type") == "error"]
    assert errors and "nenhum projeto foi selecionado" in str(errors[0].get("content", ""))
    assert any(row.get("status") == "failed" for row in saved)
    assert any(
        getattr(message, "role", None) == "assistant"
        and "nenhum projeto foi selecionado" in getattr(message, "content", "")
        for message in context.messages
    )


@pytest.mark.asyncio
async def test_other_explicit_directory_stops_before_routing(tmp_path: Path) -> None:
    from backend.orchestrator.routes import chat

    selected = tmp_path / "selected"
    other = tmp_path / "other project"
    selected.mkdir()
    other.mkdir()
    request = SimpleNamespace(
        message=f'Analisa "{other}"', session_id="project-conflict", project_path=str(selected)
    )
    frames = [
        json.loads(frame.removeprefix("data: ").strip())
        async for frame in chat._select_pipeline(request, object(), {}, object())
    ]
    assert [frame["type"] for frame in frames] == ["error", "done"]
    assert "fora do projeto selecionado" in frames[0]["content"]


@pytest.mark.asyncio
async def test_selected_project_runs_real_file_tool_inside_its_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from backend.agents import base
    from backend.core import skill_runtime
    from backend.orchestrator import advanced_modes
    from backend.orchestrator import registry as agent_registry
    from backend.orchestrator.routes import chat
    from backend.persistence import db
    from backend.tools import registry as tool_registry

    project = tmp_path / "selected-project"
    project.mkdir()
    (project / "README.md").write_text("selected-project-evidence", encoding="utf-8")
    other = tmp_path / "model-selected-project"
    other.mkdir()
    (other / "README.md").write_text("wrong-project-data", encoding="utf-8")

    class ScriptedAgent(AgentBase):
        name = "NEXUS"
        model_key = "nano"
        prompt_file = "nexus_primary"
        supported_actions = {AgentAction.READ_FILE}
        turns = 0
        saw_selected = False

        async def stream_llm(self, _request: AgentRequest, **kwargs: object) -> AsyncIterator[str]:
            self.turns += 1
            if self.turns == 1:
                args = {"name": "read_file", "arguments": {
                    "path": "README.md", "project_path": str(other),
                }}
                yield f"```tool\n{json.dumps(args)}\n```"
            else:
                context = str(kwargs.get("context", ""))
                self.saw_selected = (
                    "selected-project-evidence" in context and "wrong-project-data" not in context
                )
                yield "O ficheiro contém selected-project-evidence."

        def run(self, request: AgentRequest) -> AsyncIterator[str]:
            return self._run_react_loop(request)

    class Context:
        async def get_history(self, _session: str) -> list[object]:
            return []

        async def append_message(self, _session: str, _message: object) -> None:
            return None

    async def selected_provider(_request: object, client: object) -> tuple[object, None]:
        return client, None

    async def not_answered(*_args: object, **_kwargs: object) -> bool:
        return False

    agent = ScriptedAgent()
    saved: list[dict] = []
    monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "1")
    monkeypatch.delenv("NEXUS_LEGACY_PLANNED", raising=False)
    monkeypatch.setenv("NEXUS_EXPERIENCE_OFF", "1")
    monkeypatch.setattr(base, "get_conversation_logger", lambda _session: MagicMock())
    monkeypatch.setattr(tool_registry, "_HAVE_TOOL_CACHE", False)
    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: False)
    monkeypatch.setattr(chat_primary, "_primary_journal_path", lambda _run: None)
    monkeypatch.setattr(chat_primary, "_request_provider_client", selected_provider)
    monkeypatch.setattr(chat_primary, "_run_already_answered", not_answered)
    monkeypatch.setattr(agent_registry, "resolve", lambda *_args: agent)
    monkeypatch.setattr(
        advanced_modes, "get_orchestrator",
        lambda: SimpleNamespace(
            build_active_execution_profile=lambda: {},
            prepare_active_execution_profile=lambda _message: {},
        ),
    )
    monkeypatch.setattr(
        skill_runtime, "select_skills_for_agent",
        lambda *_args, **_kwargs: {"skills": [], "context": ""},
    )
    monkeypatch.setattr(db, "add_message", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(db, "upsert_session_run", lambda *_args, **kw: saved.append(kw))
    monkeypatch.setattr(chat_primary, "upsert_session_run", lambda *_args, **kw: saved.append(kw))
    request = SimpleNamespace(
        message="Analisa o README do projeto e explica o conteúdo.",
        session_id="selected-project-test",
        mode="auto",
        project_path=str(project),
        model="",
        provider="",
        autonomous=False,
    )
    frames = [
        json.loads(frame.removeprefix("data: ").strip())
        async for frame in chat._select_pipeline(
            request, object(), {}, Context(), user_id="test-user"
        )
    ]

    assert agent.turns == 2 and agent.saw_selected
    assert any(frame.get("type") == "tool_result" for frame in frames)
    assert not any(frame.get("type") == "error" for frame in frames)
    assert any(row.get("status") == "completed" for row in saved)

    decision = chat_primary.plan_turn(request.message, request.mode, "")
    projectless_policy = chat_primary._tool_policy_context(decision, has_project=False)
    blocked = await tool_registry.execute_tool(
        "read_file", "projectless-test", {"path": "README.md"},
        project_path="", allowed_tools=projectless_policy["_allowed_tools"],
    )
    assert blocked["ok"] is False


def test_http_preflight_returns_and_persists_an_actionable_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.orchestrator import advanced_modes
    from backend.orchestrator.context_manager import ContextStore
    from backend.orchestrator.routes import chat
    from backend.persistence.db import get_messages, get_session_run

    def forbidden(*_args: object, **_kwargs: object) -> None:
        pytest.fail("The missing-project HTTP request must not call the provider")

    monkeypatch.setenv("NEXUS_PRIMARY_ENABLED", "1")
    monkeypatch.delenv("NEXUS_LEGACY_PLANNED", raising=False)
    monkeypatch.setenv("NEXUS_EXPERIENCE_OFF", "1")
    monkeypatch.setattr(chat, "get_registry", lambda _app: {})
    monkeypatch.setattr(chat, "_find_idempotent_primary_run", lambda **_kwargs: None)
    monkeypatch.setattr(chat_primary, "run_integration_enabled", lambda: False)
    monkeypatch.setattr(chat_primary, "_primary_journal_path", lambda _run: None)
    monkeypatch.setattr(chat_primary, "_request_provider_client", forbidden)
    monkeypatch.setattr(
        advanced_modes, "get_orchestrator",
        lambda: SimpleNamespace(build_active_execution_profile=lambda: {}),
    )
    app = FastAPI()
    app.include_router(chat.router, prefix="/api")
    app.dependency_overrides[chat.require_auth] = lambda: {"user_id": "test-user"}
    app.state.llm_client = object()
    app.state.context = ContextStore()

    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={"message": REPOSITORY_AUDIT, "session_id": "preflight-http"},
        )

    assert response.status_code == 200
    frames = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    error = next(frame for frame in frames if frame.get("type") == "error")
    assert "nenhum projeto foi selecionado" in error["content"]
    assert frames[-1]["type"] == "done"
    run_id = error["run_id"]
    saved_run = get_session_run(run_id)
    assert saved_run is not None and saved_run["status"] == "failed"
    assert "nenhum projeto foi selecionado" in saved_run["error"]
    assert any(
        message["role"] == "assistant"
        and "nenhum projeto foi selecionado" in message["content"]
        for message in get_messages("preflight-http")
    )
