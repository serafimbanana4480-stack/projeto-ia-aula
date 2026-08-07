"""Tests for backend.orchestrator.context_budget.

The contract these lock down, in order of importance:

1. A context that fits is returned byte-identical — budgeting must never be a
   tax on the common case.
2. CRITICAL keys survive at any budget, because losing the objective makes the
   run meaningless rather than merely degraded.
3. Eviction follows priority, and within a tier the largest value goes first.
4. Reduction is a gradient, not a cliff: collections shed entries and strings
   shed their middles before anything is dropped whole.
5. Whatever happened is reported, so a caller can tell a clean answer from one
   given on partial information.
"""

from __future__ import annotations

from backend.orchestrator.context_budget import (
    CHARS_PER_TOKEN,
    DEFAULT_PRIORITIES,
    BudgetReport,
    Priority,
    estimate_tokens,
    fit_context,
    measure_context,
)


def _text(tokens: int) -> str:
    """A string costing roughly `tokens`."""
    return "x" * int(tokens * CHARS_PER_TOKEN)


class TestEstimateTokens:
    def test_none_is_free(self) -> None:
        assert estimate_tokens(None) == 0

    def test_scalars_cost_one(self) -> None:
        assert estimate_tokens(42) == 1
        assert estimate_tokens(3.14) == 1
        assert estimate_tokens(True) == 1

    def test_string_scales_with_length(self) -> None:
        short = estimate_tokens("a" * 100)
        long = estimate_tokens("a" * 1000)
        assert long > short * 5

    def test_never_returns_zero_for_content(self) -> None:
        # A key that costs 0 would be invisible to the budget and could be
        # added without limit.
        assert estimate_tokens("a") >= 1
        assert estimate_tokens({}) >= 1

    def test_handles_unserialisable_objects(self) -> None:
        class Opaque:
            pass

        assert estimate_tokens(Opaque()) >= 1

    def test_nested_structures_counted(self) -> None:
        nested = {"a": {"b": ["c" * 400, "d" * 400]}}
        assert estimate_tokens(nested) > 100


class TestMeasureContext:
    def test_empty_is_zero(self) -> None:
        assert measure_context(None) == 0
        assert measure_context({}) == 0

    def test_sums_values(self) -> None:
        ctx = {"a": _text(100), "b": _text(200)}
        assert 250 < measure_context(ctx) < 350


class TestFitContextPassthrough:
    def test_small_context_is_untouched(self) -> None:
        ctx = {"objective": "fix a typo", "files": {"a.py": "x = 1"}}
        fitted, report = fit_context(ctx, 5000)
        assert fitted == ctx
        assert not report.degraded
        assert report.trimmed_keys == []
        assert report.dropped_keys == []

    def test_empty_context(self) -> None:
        fitted, report = fit_context(None, 5000)
        assert fitted == {}
        assert report.original_tokens == 0
        assert not report.degraded

    def test_input_is_not_mutated(self) -> None:
        ctx = {"objective": "keep me", "transcript": _text(9000)}
        snapshot = dict(ctx)
        fit_context(ctx, 500)
        assert ctx == snapshot


class TestFitContextPriority:
    def test_critical_survives_an_impossible_budget(self) -> None:
        ctx = {"objective": _text(4000), "transcript": _text(4000)}
        fitted, _ = fit_context(ctx, 100)
        assert "objective" in fitted
        assert fitted["objective"] == ctx["objective"], "CRITICAL must not be trimmed either"

    def test_low_priority_evicted_before_normal(self) -> None:
        ctx = {
            "objective": _text(50),
            "telemetry": _text(3000),
            "files": _text(3000),
        }
        fitted, report = fit_context(ctx, 4000)
        assert "telemetry" in report.dropped_keys or "telemetry" in report.trimmed_keys
        assert "objective" in fitted

    def test_phase_overrides_beat_defaults(self) -> None:
        # `diff` is HIGH by default; a RESEARCH phase declares it LOW because
        # it is reading the codebase, not reviewing a change.
        assert DEFAULT_PRIORITIES["diff"] is Priority.HIGH
        ctx = {"objective": _text(50), "diff": _text(4000), "files": _text(2000)}

        _, default_report = fit_context(ctx, 3000)
        _, override_report = fit_context(
            ctx, 3000, priorities={"diff": Priority.LOW, "files": Priority.HIGH}
        )

        touched_default = set(default_report.trimmed_keys + default_report.dropped_keys)
        touched_override = set(override_report.trimmed_keys + override_report.dropped_keys)
        assert "files" in touched_default
        assert "diff" in touched_override

    def test_unknown_keys_default_to_normal(self) -> None:
        ctx = {
            "objective": _text(50),
            "some_new_key": _text(3000),
            "debug": _text(3000),
        }
        _, report = fit_context(ctx, 3000)
        # `debug` is LOW, so it must go before the unrecognised key.
        assert "debug" in report.dropped_keys + report.trimmed_keys


class TestFitContextGradualReduction:
    def test_dict_sheds_entries_rather_than_being_dropped(self) -> None:
        """The regression that motivated `_shrink_value`.

        A dict of file excerpts used to be all-or-nothing: unable to trim it,
        the budgeter dropped the whole thing and finished well under budget,
        having thrown away material it had room for.
        """
        ctx = {
            "objective": _text(50),
            "files": {f"f{i}.py": _text(400) for i in range(20)},
        }
        fitted, report = fit_context(ctx, 5000)

        assert "files" in fitted, "collection should be thinned, not discarded"
        assert isinstance(fitted["files"], dict)
        assert 0 < len(fitted["files"]) < 20
        assert "files" in report.trimmed_keys

    def test_list_sheds_entries(self) -> None:
        ctx = {"objective": _text(50), "search_results": [_text(300) for _ in range(20)]}
        fitted, report = fit_context(ctx, 3000)
        assert isinstance(fitted["search_results"], list)
        assert 0 < len(fitted["search_results"]) < 20
        assert "search_results" in report.trimmed_keys

    def test_thinned_collection_says_what_is_missing(self) -> None:
        ctx = {"objective": _text(50), "files": {f"f{i}.py": _text(400) for i in range(20)}}
        fitted, _ = fit_context(ctx, 5000)
        # Silently handing back a short list invites the agent to conclude the
        # codebase only has three files.
        assert "__omitido__" in fitted["files"]

    def test_string_keeps_head_and_tail(self) -> None:
        head, tail = "COMEÇO-IMPORTANTE", "FIM-IMPORTANTE"
        ctx = {"objective": _text(50), "history": f"{head}{'m' * 40000}{tail}"}
        fitted, report = fit_context(ctx, 4000)

        assert "history" in report.trimmed_keys
        assert fitted["history"].startswith(head)
        assert fitted["history"].endswith(tail)
        assert len(fitted["history"]) < 40000

    def test_budget_is_actually_used(self) -> None:
        """Eviction should stop as soon as it fits, not keep going."""
        ctx = {
            "objective": _text(100),
            "plan": _text(2000),
            "files": {f"f{i}.py": _text(500) for i in range(20)},
            "transcript": _text(8000),
        }
        _, report = fit_context(ctx, 8000)
        assert report.final_tokens <= report.budget_tokens
        # Anything below ~0.5 means whole keys were discarded to reclaim a
        # fraction of their size — the exact bug `_shrink_value` fixed.
        assert report.utilisation > 0.7


class TestBudgetReport:
    def test_reserve_ratio_is_held_back(self) -> None:
        _, report = fit_context({"a": _text(100)}, 1000, reserve_ratio=0.2)
        assert report.budget_tokens == 800

    def test_reports_original_and_final(self) -> None:
        ctx = {"objective": _text(50), "transcript": _text(9000)}
        _, report = fit_context(ctx, 2000)
        assert report.original_tokens > report.final_tokens
        assert report.degraded

    def test_clean_run_is_not_degraded(self) -> None:
        _, report = fit_context({"objective": "tiny"}, 5000)
        assert not report.degraded

    def test_to_dict_is_serialisable(self) -> None:
        _, report = fit_context({"objective": _text(50), "debug": _text(9000)}, 1000)
        payload = report.to_dict()
        assert set(payload) == {
            "budget_tokens",
            "original_tokens",
            "final_tokens",
            "trimmed_keys",
            "dropped_keys",
            "degraded",
            "utilisation",
        }
        assert isinstance(payload["dropped_keys"], list)

    def test_utilisation_is_safe_at_zero_budget(self) -> None:
        report = BudgetReport(budget_tokens=0, original_tokens=0, final_tokens=0)
        assert report.utilisation == 0.0
