"""Execution-mode classification and routing metadata contracts."""

import importlib
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.orchestrator.execution_contracts import ExecutionMode
from backend.orchestrator.routes.chat import (
    _ASSISTED_ALLOWED_TOOLS,
    _ASSISTED_MAX_ITERATIONS,
    _needs_project_context,
    _normalise_autonomous_status,
    _should_persist_project_memory,
    classify_execution_mode,
)


def test_project_referential_questions_request_read_only_context() -> None:
    assert _needs_project_context("Para que serve este projeto?")
    assert _needs_project_context("Summarize this repository")
    assert not _needs_project_context("Olá")


def test_informational_questions_are_chat() -> None:
    assert classify_execution_mode("quanto é 2+2?", "auto", "") is ExecutionMode.CHAT
    assert classify_execution_mode("explica Python", "auto", "") is ExecutionMode.CHAT
    assert (
        classify_execution_mode("como funciona a autenticação?", "auto", "") is ExecutionMode.CHAT
    )


def test_single_word_topics_remain_chat() -> None:
    for message in ("backend", "testes", "autenticação"):
        assert classify_execution_mode(message, "auto", "") is ExecutionMode.CHAT


def test_action_with_bounded_assistance_is_assisted() -> None:
    assert (
        classify_execution_mode("corrige este erro neste ficheiro e executa o teste X", "auto", "")
        is ExecutionMode.ASSISTED
    )


def test_chat_never_persists_project_memory_without_project() -> None:
    assert not _should_persist_project_memory(ExecutionMode.CHAT, "")
    assert not _should_persist_project_memory(ExecutionMode.CHAT, "C:/repo")
    assert _should_persist_project_memory(ExecutionMode.ASSISTED, "C:/repo")


def test_action_only_requests_are_assisted() -> None:
    for message in ("create a file", "build the backend", "update this module"):
        assert classify_execution_mode(message, "auto", "") is ExecutionMode.ASSISTED


def test_explicit_tool_reads_are_assisted_instead_of_chat() -> None:
    request = (
        "Usa a ferramenta read_file para ler README.md no projeto ativo. "
        "Não alteres ficheiros nem executes comandos."
    )

    assert classify_execution_mode(request, "auto", "C:/workspace") is ExecutionMode.ASSISTED
    assert classify_execution_mode("ler README.md", "auto", "C:/workspace") is ExecutionMode.ASSISTED
    # A conceptual question about reading files should stay in the lightweight
    # chat lane even though it contains a read verb.
    assert classify_execution_mode("Como posso ler um ficheiro?", "auto", "") is ExecutionMode.CHAT


def test_assisted_task_can_update_its_plan_without_widening_project_access() -> None:
    prompt = (
        "Confirma se o ficheiro example.txt neste projeto contém exatamente COR-TESTE: azul. "
        "Cria uma checklist de 3 passos com todo_write; mantém só um passo ativo, atualiza "
        "o progresso depois de cada ação e conclui a verificação apenas após leres o ficheiro "
        "com read_file. Não alteres ficheiros. No fim, responde com o resultado confirmado "
        "e o caminho consultado."
    )

    assert classify_execution_mode(prompt, "auto", "C:/workspace") is ExecutionMode.ASSISTED
    assert set(_ASSISTED_ALLOWED_TOOLS) == {
        "read_file",
        "search_in_files",
        "run_tests",
        "type_check",
        "todo_write",
        "todo_list",
    }
    assert _ASSISTED_MAX_ITERATIONS == 6


def test_multi_phase_or_explicit_mission_is_mission() -> None:
    assert (
        classify_execution_mode(
            "analyze the project, change the implementation, and verify the tests", "auto", ""
        )
        is ExecutionMode.MISSION
    )
    assert (
        classify_execution_mode("/mission analyze this project", "auto", "")
        is ExecutionMode.MISSION
    )


def test_long_audit_prompt_with_final_question_is_mission() -> None:
    """A success question must not hide an otherwise explicit audit workflow."""
    prompt = (
        "You are running inside Nexus IDE. Perform a complete self-evaluation of the "
        "entire Nexus system, execute real tests against its components, identify "
        "weaknesses, fix problems when safe to do so, retest everything, and produce "
        "a final engineering report. Do not assume that a component works because it "
        "exists in the codebase. Use the actual environment, terminal, filesystem, "
        "APIs, tools, agents, memory systems, model providers, backend and frontend. "
        "How capable, reliable, autonomous, efficient and maintainable is Nexus IDE "
        "right now, and what prevents it from becoming significantly better?"
    )
    assert classify_execution_mode(prompt, "auto", "C:/workspace") is ExecutionMode.MISSION


def test_explicit_modes_are_honoured() -> None:
    assert classify_execution_mode("tell me about Python", "chat", "") is ExecutionMode.CHAT
    assert classify_execution_mode("fix this file", "assisted", "") is ExecutionMode.ASSISTED
    assert classify_execution_mode("summarize the repo", "mission", "") is ExecutionMode.MISSION


@pytest.mark.asyncio
async def test_armed_autonomous_profile_keeps_simple_tool_request_on_primary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    chat_routes = importlib.import_module("backend.orchestrator.routes.chat")
    chat_primary = importlib.import_module("backend.orchestrator.routes.chat_primary")
    advanced_modes = importlib.import_module("backend.orchestrator.advanced_modes")
    monkeypatch.setattr(
        advanced_modes,
        "get_orchestrator",
        lambda: SimpleNamespace(
            build_active_execution_profile=lambda: {"force_autonomous": True}
        ),
    )
    monkeypatch.setattr(chat_primary, "is_primary_enabled", lambda: True)
    routed: list[str] = []

    async def primary(*_args: object, **_kwargs: object) -> AsyncIterator[str]:
        routed.append("primary")
        yield 'data: {"type":"done"}\n\n'

    async def legacy(*_args: object, **_kwargs: object) -> AsyncIterator[str]:
        routed.append("legacy")
        yield 'data: {"type":"done"}\n\n'

    monkeypatch.setattr(chat_primary, "run_primary_chat", primary)
    monkeypatch.setattr(chat_routes, "_run_pipeline", legacy)
    request = SimpleNamespace(
        session_id="session-tool-route",
        message=(
            "Usa a ferramenta read_file para ler README.md no projeto ativo; "
            "não alteres ficheiros nem executes comandos."
        ),
        mode="auto",
        project_path=str(tmp_path),
    )

    frames = [
        frame
        async for frame in chat_routes._select_pipeline(
            request,
            llm_client=object(),
            registry={},
            context=object(),
            user_id="audit-user",
        )
    ]

    assert routed == ["primary"]
    assert frames[-1] == 'data: {"type":"done"}\n\n'


def test_planning_blocked_never_becomes_success() -> None:
    assert _normalise_autonomous_status("planning_blocked") == "failed"
    assert _normalise_autonomous_status("blocked") == "failed"
    assert _normalise_autonomous_status("completed", failed_tasks=1) == "failed"
    assert _normalise_autonomous_status("cancelled") == "cancelled"
    assert _normalise_autonomous_status("completed") == "completed"
