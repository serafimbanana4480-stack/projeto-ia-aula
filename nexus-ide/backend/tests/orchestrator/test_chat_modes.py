"""Execution-mode classification and routing metadata contracts."""

from backend.orchestrator.execution_contracts import ExecutionMode
from backend.orchestrator.routes.chat import classify_execution_mode


def test_informational_questions_are_chat() -> None:
    assert classify_execution_mode("quanto é 2+2?", "auto", "") is ExecutionMode.CHAT
    assert classify_execution_mode("explica Python", "auto", "") is ExecutionMode.CHAT
    assert classify_execution_mode("como funciona a autenticação?", "auto", "") is ExecutionMode.CHAT


def test_single_word_topics_remain_chat() -> None:
    for message in ("backend", "testes", "autenticação"):
        assert classify_execution_mode(message, "auto", "") is ExecutionMode.CHAT


def test_action_with_bounded_assistance_is_assisted() -> None:
    assert (
        classify_execution_mode(
            "corrige este erro neste ficheiro e executa o teste X", "auto", ""
        )
        is ExecutionMode.ASSISTED
    )


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
    assert classify_execution_mode("/mission analyze this project", "auto", "") is ExecutionMode.MISSION


def test_explicit_modes_are_honoured() -> None:
    assert classify_execution_mode("tell me about Python", "chat", "") is ExecutionMode.CHAT
    assert classify_execution_mode("fix this file", "assisted", "") is ExecutionMode.ASSISTED
    assert classify_execution_mode("summarize the repo", "mission", "") is ExecutionMode.MISSION
