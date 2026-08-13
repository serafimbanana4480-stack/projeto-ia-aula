"""Execution-mode classification and routing metadata contracts."""

from backend.orchestrator.execution_contracts import ExecutionMode
from backend.orchestrator.routes.chat import (
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


def test_planning_blocked_never_becomes_success() -> None:
    assert _normalise_autonomous_status("planning_blocked") == "failed"
    assert _normalise_autonomous_status("blocked") == "failed"
    assert _normalise_autonomous_status("completed", failed_tasks=1) == "failed"
    assert _normalise_autonomous_status("cancelled") == "cancelled"
    assert _normalise_autonomous_status("completed") == "completed"
