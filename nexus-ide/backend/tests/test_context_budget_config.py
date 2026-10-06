"""Regression tests for the context-window budget.

Locks in the fix for::

    LLM stream failed: Context overflow: 9840 tokens + 8192 output reserve
    exceeds 16384 limit (model_tier=coder).
    Breakdown: system=9840, memory=0, history=0, query=0, tools=0

That failure was static: with the ``coder`` tier capped at 16 384 and the
whole 8 192-token ``max_tokens`` reserved for output, only 8 192 remained for
a ~9 800-token system prompt.  The agent could not run on *any* input,
including an empty one.
"""

from __future__ import annotations

import pytest
import yaml

from backend.config.settings import MODELS_YAML, load_models_config
from backend.token_management import (
    MAX_RESERVE_FRACTION,
    MIN_INPUT_TOKENS,
    MODEL_CONTEXT_LIMITS,
    ContextOverflowError,
    get_context_limit,
    resolve_output_reserve,
    validate_total_budget,
)


class TestModelsYamlDeclaresContextWindows:
    def test_every_model_declares_a_context_window(self) -> None:
        """The old table claimed to mirror models.yaml, which had no such field."""
        models = load_models_config()["models"]
        missing = sorted(k for k, v in models.items() if not v.get("context_window"))
        assert missing == [], f"models without context_window: {missing}"

    def test_yaml_is_still_valid(self) -> None:
        with MODELS_YAML.open(encoding="utf-8") as fh:
            assert yaml.safe_load(fh)["models"]

    @pytest.mark.parametrize("tier", ["micro", "fast", "coder", "reasoning", "deep"])
    def test_no_tier_can_be_starved_by_its_own_output_ceiling(self, tier: str) -> None:
        """max_tokens must never leave the input without usable room."""
        cfg = load_models_config()["models"][tier]
        window = cfg["context_window"]
        reserve = resolve_output_reserve(tier, cfg["max_tokens"])
        assert window - reserve >= MIN_INPUT_TOKENS

    def test_coder_tier_fits_a_large_system_prompt(self) -> None:
        """The exact numbers from the reported failure must now pass."""
        cfg = load_models_config()["models"]["coder"]
        reserve = resolve_output_reserve("coder", cfg["max_tokens"])
        assert validate_total_budget(
            system_tokens=9840,
            model_tier="coder",
            output_reserve=reserve,
        )


class TestGetContextLimit:
    def test_config_wins_over_the_hardcoded_table(self) -> None:
        assert (
            get_context_limit("coder") == load_models_config()["models"]["coder"]["context_window"]
        )
        assert get_context_limit("coder") != MODEL_CONTEXT_LIMITS["coder"]

    def test_unknown_tier_falls_back_to_a_safe_default(self) -> None:
        assert get_context_limit("does-not-exist") == 8_192


class TestResolveOutputReserve:
    def test_reserve_is_capped_at_half_the_window(self) -> None:
        window = get_context_limit("coder")
        assert resolve_output_reserve("coder", window * 10) <= window * MAX_RESERVE_FRACTION

    def test_modest_reserve_is_left_alone(self) -> None:
        assert resolve_output_reserve("coder", 4_096) == 4_096

    def test_reserve_never_drops_below_one(self) -> None:
        assert resolve_output_reserve("coder", 0) >= 1

    def test_tiny_window_still_leaves_input_room(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import backend.token_management as tm

        # ``get_context_limit`` gained an optional ``model_id``; the double has to
        # accept the same call shape. The assertion below is unchanged.
        monkeypatch.setattr(tm, "get_context_limit", lambda _t, model_id=None: 4_096)
        assert tm.resolve_output_reserve("micro", 4_096) <= 4_096 - MIN_INPUT_TOKENS


class TestOverflowDiagnostics:
    def test_config_overflow_is_named_as_such(self) -> None:
        """A system prompt that cannot fit is a config bug, and must say so."""
        with pytest.raises(ContextOverflowError) as exc:
            validate_total_budget(
                system_tokens=9840,
                model_tier="does-not-exist",  # 8192 fallback window
                output_reserve=4_096,
            )
        assert "configuration problem" in str(exc.value)

    def test_conversation_overflow_is_named_as_such(self) -> None:
        with pytest.raises(ContextOverflowError) as exc:
            validate_total_budget(
                system_tokens=1_000,
                history_tokens=6_000,
                model_tier="does-not-exist",
                output_reserve=4_096,
            )
        assert "accumulated conversation" in str(exc.value)
        assert "history=6000" in str(exc.value)
