"""Regression tests for the principal-first chat lane."""

from __future__ import annotations

import pytest

from backend.agents.base import AgentAction, AgentBase, AgentRequest
from backend.orchestrator.routes.chat import _is_complex_task, _is_fast_chat_turn
from backend.tools.task_spawner import spawn_task


def test_informational_questions_stay_on_fast_lane() -> None:
    assert _is_fast_chat_turn("What is Python?") is True
    assert _is_fast_chat_turn("Como funciona a autenticação?") is True
    assert _is_complex_task("What is Python?") is False


def test_actionable_multi_phase_request_is_not_fast() -> None:
    query = "analisa o projeto, corrige os erros e executa os testes"
    assert _is_fast_chat_turn(query) is False
    assert _is_complex_task(query) is True


def test_spawn_task_receives_principal_context() -> None:
    class ProbeAgent(AgentBase):
        name = "PROBE"
        model_key = "nano"
        prompt_file = "router"
        supported_actions = {AgentAction.SPAWN_TASK}

        async def _execute(self, request):
            yield ""

    request = AgentRequest(
        session_id="chat-session",
        query="spawn",
        client=None,
        project_path="C:\\workspace",
    )
    tool, args = ProbeAgent()._prepare_tool_call(
        request,
        "spawn_task",
        {"name": "verify", "description": "Run focused tests"},
    )
    assert tool == "spawn_task"
    assert args["session_id"] == "chat-session"
    assert args["project_path"] == "C:\\workspace"
    assert args["autonomous"] is False


@pytest.mark.asyncio
async def test_spawn_task_keeps_declarative_fallback_without_runtime_manager() -> None:
    result = await spawn_task(
        name="verify",
        description="Run focused tests",
        agent="DEBUGGER",
        session_id="chat-session",
    )
    assert result["status"] == "spawned"
    assert result["agent"] == "DEBUGGER"
    assert result["depends_on"] == []
