"""Regression tests for automatic escalation to the autonomous pipeline."""

from backend.orchestrator.routes.chat import (
    _direct_runtime_evidence_requirement,
    _is_complex_task,
)


def test_portuguese_audit_fix_test_request_is_complex() -> None:
    assert _is_complex_task(
        "Analisa este projeto, encontra os principais problemas, corrige os mais "
        "críticos, executa os testes e apresenta os resultados."
    )


def test_single_project_analysis_stays_on_the_lightweight_path() -> None:
    assert not _is_complex_task("Analisa este projeto e diz-me qual é a arquitetura principal.")


def test_informational_questions_never_escalate() -> None:
    """Questions containing strong keywords (e.g. "autenticação") ask for an
    explanation — they must not launch the multi-agent pipeline."""
    assert not _is_complex_task("como funciona a autenticação neste projeto?")
    assert not _is_complex_task("o que é o CODE_WATCHER do backend e porque corre no startup?")
    assert not _is_complex_task("explica como a base de dados está ligada neste projeto")
    assert not _is_complex_task("how does the routing pipeline decide which agent runs?")


def test_word_boundary_matching_avoids_false_positives() -> None:
    """Substring matching used to see "rever" inside "escrever" and "test"
    inside any word starting with "testa-"/"teste", escalating one-phase
    requests to full orchestration."""
    assert not _is_complex_task("escreve um poema sobre testes de software em português")
    assert not _is_complex_task("verifica o que este módulo faz por favor")


def test_two_phase_action_request_still_escalates() -> None:
    assert _is_complex_task("Analisa e testa profundamente todo o ambiente do Nexus IDE agora")
    assert _is_complex_task(
        "Audita o projeto todo, corrige os problemas encontrados e documenta os resultados finais"
    )


def test_short_messages_are_always_simple() -> None:
    assert not _is_complex_task("corrige isto")
    assert not _is_complex_task("olá")


def test_actionable_lightweight_audit_requires_substantive_evidence() -> None:
    assert (
        _direct_runtime_evidence_requirement(
            "Auditoria superficial deste projeto usando apenas a pasta"
        )
        == "substantive"
    )


def test_informational_question_does_not_force_tool_evidence() -> None:
    assert _direct_runtime_evidence_requirement("como funciona este modulo?") == ""
    assert _direct_runtime_evidence_requirement("ola, tudo bem?") == ""
