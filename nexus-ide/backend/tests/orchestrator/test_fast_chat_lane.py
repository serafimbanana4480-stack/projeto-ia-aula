"""Regression tests for the principal-first chat lane."""

from __future__ import annotations

import pytest

from backend.agents.base import AgentAction, AgentBase, AgentRequest
from backend.orchestrator.routes.chat import (
    _is_complex_task,
    _is_fast_chat_turn,
    _reclassify_no_project_content_request,
)
from backend.runtime.triage import RequestClass, triage_request
from backend.tools.task_spawner import spawn_task


def test_informational_questions_stay_on_fast_lane() -> None:
    assert _is_fast_chat_turn("What is Python?") is True
    assert _is_fast_chat_turn("Como funciona a autenticação?") is True
    assert _is_complex_task("What is Python?") is False


def test_actionable_multi_phase_request_is_not_fast() -> None:
    query = "analisa o projeto, corrige os erros e executa os testes"
    assert _is_fast_chat_turn(query) is False
    assert _is_complex_task(query) is True


def test_long_form_content_without_a_project_stays_in_the_conversation_lane() -> None:
    message = (
        "Escreve um guia detalhado em cinco secções sobre como diagnosticar um chat "
        "com streaming. Em cada secção explica uma falha comum e testes observáveis. "
        "Fecha com uma checklist e não uses ferramentas."
    )
    decision = triage_request(message, requested_mode="auto", has_project=False)
    assert decision.request_class is RequestClass.PLANNED

    routed = _reclassify_no_project_content_request(
        decision,
        message=message,
        requested_mode="auto",
        project_path="",
    )

    assert routed.request_class is RequestClass.CONVERSATIONAL
    assert routed.max_iterations == 1
    assert "long_form_content_no_project" in routed.signals


def test_explicit_plan_and_project_work_do_not_use_content_chat_override() -> None:
    message = "Escreve um guia detalhado sobre como diagnosticar erros e testes observáveis."
    explicit = triage_request("/plan " + message, requested_mode="auto", has_project=False)
    assert _reclassify_no_project_content_request(
        explicit,
        message="/plan " + message,
        requested_mode="auto",
        project_path="",
    ) is explicit

    project_decision = triage_request(message, requested_mode="auto", has_project=True)
    assert _reclassify_no_project_content_request(
        project_decision,
        message=message,
        requested_mode="auto",
        project_path="C:\\project",
    ) is project_decision


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
async def test_spawn_task_never_reports_success_without_a_real_subagent() -> None:
    """A declined or unstartable delegation must NOT read as "spawned".

    This test previously asserted the opposite: that ``spawn_task`` returned
    ``status="spawned"`` even with no lifecycle manager and no policy approval.
    The 2026-08-16 audit (P10) showed what that costs — the runtime declined
    the delegation while the tool told the model a background ANALYZER was
    running, so the model reported work to the user that never existed. A model
    can only be honest if its tools are.
    """
    result = await spawn_task(
        name="verify",
        description="Run focused tests",
        agent="DEBUGGER",
        session_id="chat-session",
    )
    assert result["status"] in {"denied", "queued", "not_started"}
    assert result["spawned"] is False
    assert result.get("background") is False
    assert result["agent"] == "DEBUGGER"
    assert "instance_id" not in result
    # The reason must be actionable for the model, not a bare status.
    assert str(result.get("reason") or result.get("error") or "").strip()
