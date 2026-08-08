"""Tests for the RegressionGuard (FASE 8)."""
from __future__ import annotations

from backend.evolution.registry import Experiment, ExperimentStatus
from backend.evolution.regression_guard import RegressionGuard


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
        expected = {"success_rate", "no_new_regressions", "score_floor", "champion_retention", "efficiency_budget"}
        assert gate_names == expected

    def test_gate_values_populated(self) -> None:
        guard = RegressionGuard()
        exp = _make_experiment()
        report = guard.evaluate(exp)
        for g in report.gates:
            assert g.champion_value >= 0
            assert g.threshold >= 0
            assert isinstance(g.message, str)
