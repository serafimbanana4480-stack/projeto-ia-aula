"""Tests for the RegressionGuard (FASE 8)."""
from __future__ import annotations

import pytest

from backend.evolution.engine import DEFAULT_COMPONENT_CONFIGS
from backend.evolution.registry import Experiment, ExperimentStatus
from backend.evolution.regression_guard import GateResult, RegressionGuard


def _make_experiment(
    winner: str = "challenger",
    champion_success: float = 0.8,
    challenger_success: float = 0.9,
    champion_score: float = 0.85,
    challenger_score: float = 0.90,
    champion_results: list[dict] | None = None,
    challenger_results: list[dict] | None = None,
    regression: bool = False,
    simulated: bool = False,
    extra_metrics: dict | None = None,
) -> Experiment:
    """Build an experiment for testing."""
    champ_results = champion_results or [
        {"task_id": f"t{i}", "success": True, "score": champion_score}
        for i in range(5)
    ]
    chall_results = challenger_results or [
        {"task_id": f"t{i}", "success": True, "score": challenger_score}
        for i in range(5)
    ]
    metrics = {
        "champion_success": champion_success,
        "challenger_success": challenger_success,
        "champion_score": champion_score,
        "challenger_score": challenger_score,
        "champion_results": champ_results,
        "challenger_results": chall_results,
    }
    if simulated:
        metrics["simulated"] = True
    if extra_metrics:
        metrics.update(extra_metrics)
    status = ExperimentStatus.REGRESSION if regression else ExperimentStatus.COMPLETED
    return Experiment(
        experiment_id="test-exp",
        component_kind="planner",
        champion_version="v1",
        challenger_version="v2",
        status=status,
        started_at="2024-01-01T00:00:00+00:00",
        completed_at="2024-01-01T00:01:00+00:00",
        winner=winner,
        regression_detected=regression,
        metrics=metrics,
        log="test",
    )


class TestRegressionGuard:
    def test_all_gates_pass(self) -> None:
        guard = RegressionGuard()
        exp = _make_experiment(challenger_success=0.9, challenger_score=0.90)
        report = guard.evaluate(exp)
        assert report.overall_passed is True
        assert all(g.passed for g in report.gates)

    def test_refuse_simulated_promotion(self) -> None:
        guard = RegressionGuard()
        exp = _make_experiment(simulated=True, challenger_success=0.95)
        assert guard.should_promote(exp) is False

    def test_regression_blocks_promotion(self) -> None:
        guard = RegressionGuard()
        exp = _make_experiment(regression=True, winner="champion")
        assert guard.should_promote(exp) is False

    def test_champion_wins_blocks_promotion(self) -> None:
        guard = RegressionGuard()
        exp = _make_experiment(winner="champion", champion_success=0.95)
        assert guard.should_promote(exp) is False

    def test_success_rate_drops_blocks(self) -> None:
        guard = RegressionGuard()
        exp = _make_experiment(
            winner="challenger",
            champion_success=0.9,
            challenger_success=0.7,
            challenger_score=0.85,
        )
        report = guard.evaluate(exp)
        success_gate = next(g for g in report.gates if g.gate_name == "success_rate")
        assert success_gate.passed is False
        assert report.overall_passed is False

    def test_no_new_regressions_gate(self) -> None:
        guard = RegressionGuard()
        champion_results = [
            {"task_id": "t1", "success": True, "score": 0.9},
            {"task_id": "t2", "success": True, "score": 0.9},
        ]
        challenger_results = [
            {"task_id": "t1", "success": True, "score": 0.9},
            {"task_id": "t2", "success": False, "score": 0.3},
        ]
        exp = _make_experiment(
            champion_results=champion_results,
            challenger_results=challenger_results,
            champion_success=1.0,
            challenger_success=0.5,
            champion_score=0.9,
            challenger_score=0.6,
        )
        report = guard.evaluate(exp)
        reg_gate = next(g for g in report.gates if g.gate_name == "no_new_regressions")
        assert reg_gate.passed is False

    def test_score_floor_gate(self) -> None:
        guard = RegressionGuard()
        exp = _make_experiment(
            winner="challenger",
            champion_score=0.90,
            challenger_score=0.80,
            champion_success=0.9,
            challenger_success=0.9,
        )
        report = guard.evaluate(exp)
        score_gate = next(g for g in report.gates if g.gate_name == "score_floor")
        assert score_gate.passed is False

    def test_champion_retention_gate(self) -> None:
        guard = RegressionGuard()
        champion_results = [
            {"task_id": f"t{i}", "success": True, "score": 0.9}
            for i in range(5)
        ]
        challenger_results = [
            {"task_id": "t0", "success": False, "score": 0.3},
            {"task_id": "t1", "success": False, "score": 0.3},
            {"task_id": "t2", "success": True, "score": 0.9},
            {"task_id": "t3", "success": True, "score": 0.9},
            {"task_id": "t4", "success": True, "score": 0.9},
        ]
        exp = _make_experiment(
            champion_results=champion_results,
            challenger_results=challenger_results,
            champion_success=1.0,
            challenger_success=0.6,
            champion_score=0.9,
            challenger_score=0.6,
        )
        report = guard.evaluate(exp)
        retention_gate = next(g for g in report.gates if g.gate_name == "champion_retention")
        assert retention_gate.passed is False

    def test_all_gate_results_present(self) -> None:
        guard = RegressionGuard()
        exp = _make_experiment()
        report = guard.evaluate(exp)
        gate_names = {g.gate_name for g in report.gates}
        expected = {
            "success_rate",
            "no_new_regressions",
            "score_floor",
            "champion_retention",
            "efficiency_budget",
            "prompt_size_budget",
            "required_fields",
            "forbidden_patterns",
        }
        assert expected <= gate_names

    def test_gate_values_populated(self) -> None:
        guard = RegressionGuard()
        exp = _make_experiment()
        report = guard.evaluate(exp)
        for g in report.gates:
            assert g.champion_value >= 0
            assert g.threshold >= 0
            assert isinstance(g.message, str)


def _planner_config(**overrides: object) -> dict:
    config = dict(DEFAULT_COMPONENT_CONFIGS["planner"])
    config.update(overrides)
    return config


class TestPromptSizeBudgetGate:
    def test_short_prompt_passes(self) -> None:
        guard = RegressionGuard()
        report = guard.evaluate_candidate(
            _make_experiment(), _planner_config(prompt_text="Do the thing.")
        )
        gate = next(g for g in report.gates if g.gate_name == "prompt_size_budget")
        assert gate.passed is True
        assert report.overall_passed is True

    def test_oversized_prompt_fails(self) -> None:
        guard = RegressionGuard()
        config = _planner_config(prompt_text="x" * 9001)
        report = guard.evaluate_candidate(_make_experiment(), config)
        gate = next(g for g in report.gates if g.gate_name == "prompt_size_budget")
        assert gate.passed is False
        assert "9001" in gate.message
        assert "8000" in gate.message
        assert report.overall_passed is False

    def test_custom_cap_respected(self) -> None:
        guard = RegressionGuard(prompt_max_chars=10)
        passing = guard.evaluate_candidate(_make_experiment(), {"prompt_text": "short"})
        failing = guard.evaluate_candidate(_make_experiment(), {"prompt_text": "way too long"})
        p_gate = next(g for g in passing.gates if g.gate_name == "prompt_size_budget")
        f_gate = next(g for g in failing.gates if g.gate_name == "prompt_size_budget")
        assert p_gate.passed is True
        assert f_gate.passed is False

    def test_missing_config_skips_gate(self) -> None:
        guard = RegressionGuard()
        report = guard.evaluate(_make_experiment())
        gate = next(g for g in report.gates if g.gate_name == "prompt_size_budget")
        assert gate.passed is True
        assert "No candidate config" in gate.message

    def test_non_string_prompt_text_fails(self) -> None:
        guard = RegressionGuard()
        report = guard.evaluate_candidate(_make_experiment(), {"prompt_text": 123})
        gate = next(g for g in report.gates if g.gate_name == "prompt_size_budget")
        assert gate.passed is False
        assert "int" in gate.message

    def test_config_without_prompt_text_passes(self) -> None:
        guard = RegressionGuard()
        report = guard.evaluate_candidate(_make_experiment(), {"temperature": 0.2})
        gate = next(g for g in report.gates if g.gate_name == "prompt_size_budget")
        assert gate.passed is True


class TestRequiredFieldsGate:
    def test_valid_planner_config_passes(self) -> None:
        guard = RegressionGuard()
        report = guard.evaluate_candidate(_make_experiment(), _planner_config())
        gate = next(g for g in report.gates if g.gate_name == "required_fields")
        assert gate.passed is True
        assert report.overall_passed is True

    def test_mutation_metadata_keys_tolerated(self) -> None:
        guard = RegressionGuard()
        config = _planner_config(mutation_hash="abc123", mutation_type="prompt_tweak")
        report = guard.evaluate_candidate(_make_experiment(), config)
        gate = next(g for g in report.gates if g.gate_name == "required_fields")
        assert gate.passed is True

    def test_missing_field_fails(self) -> None:
        guard = RegressionGuard()
        config = _planner_config()
        del config["review_iterations"]
        report = guard.evaluate_candidate(_make_experiment(), config)
        gate = next(g for g in report.gates if g.gate_name == "required_fields")
        assert gate.passed is False
        assert "review_iterations" in gate.message
        assert report.overall_passed is False

    def test_wrong_field_type_fails(self) -> None:
        guard = RegressionGuard()
        config = _planner_config(max_plans="five")
        report = guard.evaluate_candidate(_make_experiment(), config)
        gate = next(g for g in report.gates if g.gate_name == "required_fields")
        assert gate.passed is False
        assert "'max_plans'" in gate.message

    def test_unknown_component_kind_skips(self) -> None:
        guard = RegressionGuard()
        exp = _make_experiment()
        exp.component_kind = "widget"
        report = guard.evaluate_candidate(exp, {})
        gate = next(g for g in report.gates if g.gate_name == "required_fields")
        assert gate.passed is True
        assert "widget" in gate.message

    def test_injected_challenger_config_metric_is_used(self) -> None:
        guard = RegressionGuard()
        config = _planner_config()
        del config["max_plans"]
        exp = _make_experiment(extra_metrics={"challenger_config": config})
        report = guard.evaluate(exp)
        gate = next(g for g in report.gates if g.gate_name == "required_fields")
        assert gate.passed is False


class TestForbiddenPatternsGate:
    def test_clean_config_passes(self) -> None:
        guard = RegressionGuard()
        report = guard.evaluate_candidate(_make_experiment(), _planner_config())
        gate = next(g for g in report.gates if g.gate_name == "forbidden_patterns")
        assert gate.passed is True
        assert gate.challenger_value == 0.0

    def test_rm_rf_fails(self) -> None:
        guard = RegressionGuard()
        config = _planner_config(prompt_text="clean up first: rm -rf /tmp/cache")
        report = guard.evaluate_candidate(_make_experiment(), config)
        gate = next(g for g in report.gates if g.gate_name == "forbidden_patterns")
        assert gate.passed is False
        assert "rm -rf" in gate.message

    def test_os_system_fails(self) -> None:
        guard = RegressionGuard()
        config = _planner_config(prompt_text="use os.system('ls') to inspect")
        report = guard.evaluate_candidate(_make_experiment(), config)
        gate = next(g for g in report.gates if g.gate_name == "forbidden_patterns")
        assert gate.passed is False
        assert "os.system" in gate.message

    def test_case_insensitive_match(self) -> None:
        guard = RegressionGuard()
        config = _planner_config(prompt_text="RUN RM -RF EVERYTHING NOW")
        report = guard.evaluate_candidate(_make_experiment(), config)
        gate = next(g for g in report.gates if g.gate_name == "forbidden_patterns")
        assert gate.passed is False

    def test_api_key_token_fails(self) -> None:
        guard = RegressionGuard()
        config = _planner_config(prompt_text="key sk-a1b2c3d4e5f6g7h8i9j0k1l2 embedded")
        report = guard.evaluate_candidate(_make_experiment(), config)
        gate = next(g for g in report.gates if g.gate_name == "forbidden_patterns")
        assert gate.passed is False

    def test_generic_secret_assignment_fails(self) -> None:
        guard = RegressionGuard()
        config = _planner_config(prompt_text='api_key = "a1b2c3d4e5f6g7"')
        report = guard.evaluate_candidate(_make_experiment(), config)
        gate = next(g for g in report.gates if g.gate_name == "forbidden_patterns")
        assert gate.passed is False

    def test_findings_in_nested_values_detected(self) -> None:
        guard = RegressionGuard()
        config = _planner_config(extra={"deep": ["rm -rf ~"]})
        report = guard.evaluate_candidate(_make_experiment(), config)
        gate = next(g for g in report.gates if g.gate_name == "forbidden_patterns")
        assert gate.passed is False

    def test_custom_substrings_replace_defaults(self) -> None:
        guard = RegressionGuard(forbidden_substrings=("backdoor",))
        blocked_cfg = _planner_config(prompt_text="enable backdoor mode")
        clean_cfg = _planner_config(prompt_text="use os.system('x') freely")
        blocked = guard.evaluate_candidate(_make_experiment(), blocked_cfg)
        allowed = guard.evaluate_candidate(_make_experiment(), clean_cfg)
        b_gate = next(g for g in blocked.gates if g.gate_name == "forbidden_patterns")
        a_gate = next(g for g in allowed.gates if g.gate_name == "forbidden_patterns")
        assert b_gate.passed is False
        assert a_gate.passed is True

    def test_extra_user_regex_appended(self) -> None:
        guard = RegressionGuard(forbidden_regexes=(r"eval\s*\(",))
        config = _planner_config(prompt_text="call eval(payload)")
        report = guard.evaluate_candidate(_make_experiment(), config)
        gate = next(g for g in report.gates if g.gate_name == "forbidden_patterns")
        assert gate.passed is False


class TestCustomGates:
    def test_registered_gate_appears_and_can_pass(self) -> None:
        guard = RegressionGuard()
        guard.register_gate("no_placeholder_text", lambda exp: True)
        report = guard.evaluate(_make_experiment())
        gate = next(g for g in report.gates if g.gate_name == "no_placeholder_text")
        assert gate.passed is True
        assert report.overall_passed is True

    def test_bool_false_blocks_promotion(self) -> None:
        guard = RegressionGuard()
        guard.register_gate("always_no", lambda exp: False)
        report = guard.evaluate(_make_experiment())
        assert report.overall_passed is False
        assert "always_no" in report.explanation

    def test_none_verdict_counts_as_pass(self) -> None:
        guard = RegressionGuard()
        guard.register_gate("silent", lambda exp: None)
        report = guard.evaluate(_make_experiment())
        gate = next(g for g in report.gates if g.gate_name == "silent")
        assert gate.passed is True

    def test_gate_result_verdict_renamed(self) -> None:
        guard = RegressionGuard()

        def gate(exp: Experiment) -> GateResult:
            return GateResult(
                gate_name="ignored",
                passed=False,
                champion_value=1.0,
                challenger_value=0.0,
                threshold=1.0,
                message="custom detail",
            )

        guard.register_gate("strict_mode", gate)
        report = guard.evaluate(_make_experiment())
        result = next(g for g in report.gates if g.gate_name == "strict_mode")
        assert result.passed is False
        assert result.message == "custom detail"

    def test_raising_gate_blocks_instead_of_crashing(self) -> None:
        def boom(exp: Experiment) -> bool:
            raise RuntimeError("exploded")

        guard = RegressionGuard()
        guard.register_gate("boom", boom)
        report = guard.evaluate(_make_experiment())
        gate = next(g for g in report.gates if g.gate_name == "boom")
        assert gate.passed is False
        assert "RuntimeError" in gate.message
        assert report.overall_passed is False

    def test_raising_gate_blocks_should_promote(self) -> None:
        def boom(exp: Experiment) -> bool:
            raise RuntimeError("exploded")

        baseline_guard = RegressionGuard()
        assert baseline_guard.should_promote(_make_experiment()) is True

        hardened_guard = RegressionGuard()
        hardened_guard.register_gate("boom", boom)
        assert hardened_guard.should_promote(_make_experiment()) is False

    def test_duplicate_registration_raises(self) -> None:
        guard = RegressionGuard()
        guard.register_gate("dup", lambda exp: True)
        with pytest.raises(ValueError):
            guard.register_gate("dup", lambda exp: True)

    def test_invalid_registration_raises(self) -> None:
        guard = RegressionGuard()
        with pytest.raises(ValueError):
            guard.register_gate("", lambda exp: True)
        with pytest.raises(TypeError):
            guard.register_gate("not_callable", "nope")

    def test_unregister_removes_gate(self) -> None:
        guard = RegressionGuard()
        guard.register_gate("temp", lambda exp: False)
        guard.unregister_gate("temp")
        guard.unregister_gate("never_existed")
        report = guard.evaluate(_make_experiment())
        assert all(g.gate_name != "temp" for g in report.gates)
        assert report.overall_passed is True


class TestCombinedGates:
    def test_all_new_gates_fail_together(self) -> None:
        guard = RegressionGuard()
        config = _planner_config(prompt_text="rm -rf / " * 900)
        del config["max_plans"]
        config["review_iterations"] = "lots"
        report = guard.evaluate_candidate(_make_experiment(), config)
        failed = {g.gate_name for g in report.gates if not g.passed}
        assert {"prompt_size_budget", "required_fields", "forbidden_patterns"} <= failed
        assert report.overall_passed is False
        assert report.explanation.startswith("Failed gate:")
        legacy = {"success_rate", "no_new_regressions", "score_floor", "champion_retention",
                  "efficiency_budget"}
        assert all(g.passed for g in report.gates if g.gate_name in legacy)

    def test_full_clean_candidate_passes_everything(self) -> None:
        guard = RegressionGuard()
        guard.register_gate("sanity", lambda exp: True)
        report = guard.evaluate_candidate(_make_experiment(), _planner_config())
        assert report.overall_passed is True
        assert all(g.passed for g in report.gates)
        expected = {
            "success_rate",
            "no_new_regressions",
            "score_floor",
            "champion_retention",
            "efficiency_budget",
            "prompt_size_budget",
            "required_fields",
            "forbidden_patterns",
            "sanity",
        }
        assert {g.gate_name for g in report.gates} >= expected

    def test_default_builtin_gate_set_exact(self) -> None:
        guard = RegressionGuard()
        report = guard.evaluate(_make_experiment())
        assert {g.gate_name for g in report.gates} == {
            "success_rate",
            "no_new_regressions",
            "score_floor",
            "champion_retention",
            "efficiency_budget",
            "prompt_size_budget",
            "required_fields",
            "forbidden_patterns",
        }
