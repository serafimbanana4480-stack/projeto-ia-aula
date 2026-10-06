"""Focused tests for the model-id versus router-tier request contract."""

from backend.orchestrator.routes.chat import _resolve_model_selection


def test_concrete_model_id_matching_tier_is_unambiguous() -> None:
    assert _resolve_model_selection("coder", model_is_concrete=True) == ("", "coder")


def test_tier_without_provider_remains_router_tier() -> None:
    assert _resolve_model_selection("coder") == ("coder", "")


def test_concrete_model_and_auto_selection() -> None:
    assert _resolve_model_selection("openai/gpt-4.1") == ("", "openai/gpt-4.1")
    assert _resolve_model_selection("", "") == ("", "")
    assert _resolve_model_selection("auto", "") == ("", "")
