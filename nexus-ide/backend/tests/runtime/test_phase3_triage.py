"""Phase 3 — triage keeps the planner off the critical path.

The planner cost minutes before the first tool call (see
``NEXUS_RUNTIME_REBUILD.md`` §1, C5). These tests pin the rule that decides
whether a turn pays that cost at all.
"""

from __future__ import annotations

import pytest

from backend.runtime.triage import RequestClass, triage_request


SIMPLE_TASKS = [
    "corrige o typo no README",
    "lê o ficheiro backend/main.py e diz-me o que faz",
    "adiciona um teste para a função parse_config",
    "corre os testes do backend",
    "renomeia a variável foo para bar em utils.py",
]


@pytest.mark.parametrize("message", SIMPLE_TASKS)
def test_simple_tasks_never_reach_the_planner(message: str) -> None:
    decision = triage_request(message, has_project=True)
    assert decision.request_class is RequestClass.DIRECT
    assert decision.needs_planner is False


def test_a_question_needs_no_tools() -> None:
    decision = triage_request("o que é um decorator em Python?")
    assert decision.request_class is RequestClass.CONVERSATIONAL
    assert decision.uses_tools is False
    assert decision.needs_planner is False


def test_a_question_about_the_project_still_uses_tools() -> None:
    # "que ficheiros" is a question, but it cannot be answered without
    # looking at the project, so it must not land in the tool-free lane.
    decision = triage_request("que ficheiros existem na pasta backend?", has_project=True)
    assert decision.request_class is RequestClass.DIRECT
    assert decision.uses_tools is True


def test_genuinely_multi_phase_work_is_still_planned() -> None:
    message = (
        "audita o módulo de autenticação todo, implementa o refresh token que falta, "
        "escreve testes de integração para os dois fluxos e documenta as mudanças no "
        "README para a equipa saber o que mudou"
    )
    decision = triage_request(message, has_project=True)
    assert decision.request_class is RequestClass.PLANNED
    assert decision.needs_planner is True


def test_multi_phase_but_short_is_not_worth_a_plan() -> None:
    # Three phase verbs, but the request is small enough that planning it
    # costs more than doing it.
    decision = triage_request("analisa, corrige e testa o parser", has_project=True)
    assert decision.request_class is RequestClass.DIRECT


def test_explicit_plan_command_wins() -> None:
    decision = triage_request("/plan reescrever o pipeline")
    assert decision.request_class is RequestClass.PLANNED
    assert "explicit:/plan" in decision.signals


def test_pinned_ui_mode_wins_over_heuristics() -> None:
    assert (
        triage_request("corrige o bug", requested_mode="chat").request_class
        is RequestClass.CONVERSATIONAL
    )
    assert (
        triage_request("olá", requested_mode="coder").request_class is RequestClass.DIRECT
    )


def test_triage_is_pure_and_cheap() -> None:
    """No I/O, no model call: triage must never be a source of latency."""
    import time

    started = time.perf_counter()
    for _ in range(2_000):
        triage_request("corrige o typo no README", has_project=True)
    elapsed = time.perf_counter() - started
    assert elapsed < 1.0, f"triage too slow: {elapsed:.3f}s for 2000 calls"


def test_decision_is_explainable() -> None:
    decision = triage_request("corrige o bug em backend/main.py", has_project=True)
    payload = decision.to_dict()
    assert payload["class"] == "direct"
    assert payload["reason"]
    assert "action_verb" in payload["signals"]
