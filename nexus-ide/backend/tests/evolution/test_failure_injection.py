"""FASE 14: Failure injection and recovery tests.

Tests that the Evolution Engine handles failures gracefully:

- Arena without benchmark runner (RuntimeError)
- Arena with simulation but no champion (ValueError)
- Rollback triggers on health degradation
- Rollback preserves previous champion on healthy state
- FailureMiner with empty lake
- FailureMiner classifies known error patterns
- RegressionGuard edge cases (simulation rejection, regression rejection)
- Engine handles missing components gracefully
"""
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.evolution.arena import Arena, Experiment, ExperimentStatus
from backend.evolution.engine import EvolutionConfig, EvolutionEngine
from backend.evolution.failure_miner import FailureCategory, FailureMiner
from backend.evolution.registry import ChampionRegistry
from backend.evolution.regression_guard import RegressionGuard
from backend.evolution.rollback import RollbackManager
from backend.experience.lake import TraceLake
from backend.experience.models import (
    ExperienceTrace,
    ModelInfo,
    TaskCategory,
    TraceResult,
)


@pytest.fixture
def empty_engine(tmp_path: Path):
    """Engine with empty trace lake and registry."""
    registry = ChampionRegistry(db_path=tmp_path / "empty_registry.db")
    lake = TraceLake(tmp_path / "empty_lake.db")
    engine = EvolutionEngine(
        registry=registry,
        failure_miner=FailureMiner(lake),
    )
    engine._failure_miner._lake = lake
    return engine, tmp_path


class TestArenaFailureInjection:
    """Test Arena resilience to missing runners, missing champions."""

    def test_arena_requires_runner_when_not_simulating(self, empty_engine):
        """Arena must raise RuntimeError when no runner set and simulation off."""
        engine, _ = empty_engine
        engine.bootstrap_defaults()
        engine._registry.create_challenger(
            component_kind="planner",
            version="v2",
            config={"temperature": 0.0},
            parent_version="v1",
        )

        arena = Arena(engine._registry, allow_simulation=False)

        with pytest.raises(RuntimeError, match="No benchmark runner"):
            arena.run_experiment(
                component_kind="planner",
                challenger_version="v2",
                task_ids=["task_01"],
            )

    def test_arena_allows_simulation_when_enabled(self, empty_engine):
        """Arena with simulation must produce experiments without a runner."""
        engine, _ = empty_engine
        engine.bootstrap_defaults()
        engine._registry.create_challenger(
            component_kind="planner",
            version="v2",
            config={"temperature": 0.0},
            parent_version="v1",
        )

        arena = Arena(engine._registry, allow_simulation=True)

        experiment = arena.run_experiment(
            component_kind="planner",
            challenger_version="v2",
            task_ids=["task_01"],
        )

        assert experiment is not None
        assert experiment.status is not None

    def test_arena_champion_not_found_raises(self, empty_engine):
        """Arena must raise when no champion exists for the component."""
        engine, _ = empty_engine

        arena = Arena(engine._registry, allow_simulation=False)

        with pytest.raises(ValueError, match="No champion"):
            arena.run_experiment(
                component_kind="planner",
                challenger_version="v1",
                task_ids=[],
            )


class TestRollbackFailureScenarios:
    """Test RollbackManager under failure and healthy conditions."""

    def test_rollback_no_champion_no_action(self, empty_engine):
        """Rollback check with no champion should be a no-op."""
        engine, _ = empty_engine
        engine._check_rollbacks()  # Should not raise

    def test_rollback_triggers_on_severe_drop(self, tmp_path):
        """Rollback triggers when success rate drops below 15% threshold."""
        registry = ChampionRegistry(db_path=tmp_path / "rollback_test.db")
        rollback = RollbackManager(registry)

        # Register v1 as initial champion with good metrics
        registry.register_champion(
            component_kind="planner",
            version="v1",
            config={"temperature": 0.0},
            changelog="initial champion",
        )
        registry.update_metrics("planner", "v1", {
            "success_rate": 0.95,
            "avg_score": 0.9,
            "num_benchmark_tasks": 10,
            "promoted_at": datetime.now(UTC).isoformat(),
        })

        # Create v2 as challenger, then promote it (archives v1)
        registry.create_challenger(
            component_kind="planner",
            version="v2",
            config={"temperature": 0.7},
            parent_version="v1",
            changelog="degraded version",
        )
        registry.promote("planner", "v2", changelog="promoted v2")
        # Set v2's champion metrics (baseline for comparison)
        registry.update_metrics("planner", "v2", {
            "success_rate": 0.95,
            "avg_score": 0.9,
            "num_benchmark_tasks": 10,
            "promoted_at": datetime.now(UTC).isoformat(),
        })

        # Current production metrics show degradation
        degraded_metrics = {
            "success_rate": 0.50,  # 47% drop from 0.95 — exceeds 15% threshold
            "avg_score": 0.4,
            "total_tasks": 50,  # Must be >= MIN_TASKS_FOR_ROLLBACK (10)
            "regression_rate": 0.05,
        }

        should_rb, reason = rollback.should_rollback("planner", degraded_metrics)
        assert should_rb is True, f"Expected rollback, got: {reason}"
        assert reason is not None
        assert len(reason) > 0

    def test_rollback_does_not_trigger_when_healthy(self, tmp_path):
        """Rollback should not trigger when metrics are healthy."""
        registry = ChampionRegistry(db_path=tmp_path / "healthy_test.db")
        rollback = RollbackManager(registry)

        registry.register_champion(
            component_kind="planner",
            version="v1",
            config={"temperature": 0.0},
            changelog="healthy champion",
        )
        registry.update_metrics("planner", "v1", {
            "success_rate": 0.95,
            "avg_score": 0.9,
            "num_benchmark_tasks": 10,
            "promoted_at": datetime.now(UTC).isoformat(),
        })

        healthy_metrics = {
            "success_rate": 0.93,
            "avg_score": 0.89,
            "total_tasks": 10,
            "regression_rate": 0.01,
        }
        should_rb, reason = rollback.should_rollback("planner", healthy_metrics)
        assert should_rb is False


class TestFailureMinerEdgeCases:
    """Test FailureMiner with edge cases."""

    def test_failure_miner_empty_lake(self, tmp_path):
        """FailureMiner with empty TraceLake returns empty priority list."""
        lake = TraceLake(tmp_path / "empty_lake.db")
        miner = FailureMiner(lake)

        priorities = miner.analyze_failures()
        assert priorities == []

    def test_failure_miner_classifies_known_errors(self, tmp_path):
        """FailureMiner classifies errors into proper categories."""
        lake = TraceLake(tmp_path / "mining_lake.db")
        miner = FailureMiner(lake)

        assert miner.classify_error("timeout after 60s") == FailureCategory.TIMEOUT
        assert miner.classify_error("runtime error: NameError") == FailureCategory.INCORRECT_CODE
        assert miner.classify_error("wrong tool used") == FailureCategory.TOOL_SELECTION_ERROR
        assert miner.classify_error("memory retrieval failed") == FailureCategory.MEMORY_RETRIEVAL_ERROR
        assert miner.classify_error("hallucinated API call") == FailureCategory.HALLUCINATED_API
        assert miner.classify_error("infinite loop detected") == FailureCategory.INFINITE_LOOP

    def test_failure_miner_unknown_error(self, tmp_path):
        """Unrecognized errors classify as UNKNOWN."""
        lake = TraceLake(tmp_path / "unknown_lake.db")
        miner = FailureMiner(lake)

        category = miner.classify_error("something completely unexpected happened xyz123")
        assert category == FailureCategory.UNKNOWN

    def test_failure_miner_stores_and_retrieves(self, tmp_path):
        """FailureMiner stores classifications to DB and retrieves them."""
        lake = TraceLake(tmp_path / "store_lake.db")
        miner = FailureMiner(lake)

        trace = ExperienceTrace(
            task_id="fail_001",
            prompt="Test task",
            category=TaskCategory.CODING,
            difficulty=0.5,
            model=ModelInfo(name="test", version="v1", temperature=0.0, tier="fast"),
        )
        trace.result = TraceResult(success=False, score=0.1, error="timeout")
        lake.store_trace(trace)

        priorities = miner.analyze_failures()
        miner.store_classifications(priorities)

        summary = miner.get_failure_summary()
        assert summary != {}


class TestRegressionGuardEdgeCases:
    """Test RegressionGuard edge cases."""

    def test_guard_rejects_simulated_results(self):
        """RegressionGuard must refuse promotion when metrics show simulation."""
        guard = RegressionGuard()

        experiment = Experiment(
            experiment_id="test-sim",
            component_kind="planner",
            champion_version="v1",
            challenger_version="v2",
            status=ExperimentStatus.COMPLETED,
            started_at=datetime.now(UTC).isoformat(),
            completed_at=datetime.now(UTC).isoformat(),
            winner="challenger",
            metrics={
                "champion_score": 0.8,
                "challenger_score": 0.9,
                "champion_success": 0.8,
                "challenger_success": 0.9,
                "num_tasks": 5,
                "simulated": True,
            },
        )

        assert guard.should_promote(experiment) is False

    def test_guard_rejects_on_regression_status(self):
        """Guard rejects when experiment status is REGRESSION."""
        guard = RegressionGuard()

        experiment = Experiment(
            experiment_id="test-reg",
            component_kind="planner",
            champion_version="v1",
            challenger_version="v2",
            status=ExperimentStatus.REGRESSION,
            started_at=datetime.now(UTC).isoformat(),
            completed_at=datetime.now(UTC).isoformat(),
            winner="champion",
            metrics={
                "champion_score": 0.8,
                "challenger_score": 0.5,
                "champion_success": 0.8,
                "challenger_success": 0.5,
            },
        )

        assert guard.should_promote(experiment) is False

    def test_guard_accepts_real_improvement(self):
        """Guard accepts when challenger wins all gates with real results."""
        guard = RegressionGuard()

        experiment = Experiment(
            experiment_id="test-pass",
            component_kind="planner",
            champion_version="v1",
            challenger_version="v2",
            status=ExperimentStatus.COMPLETED,
            started_at=datetime.now(UTC).isoformat(),
            completed_at=datetime.now(UTC).isoformat(),
            winner="challenger",
            metrics={
                "champion_score": 0.7,
                "challenger_score": 0.9,
                "champion_success": 0.7,
                "challenger_success": 0.9,
                "num_tasks": 5,
                "champion_results": [
                    {"task_id": f"t{i}", "success": True, "score": 0.7,
                     "tokens_input": 100, "tokens_output": 50}
                    for i in range(5)
                ],
                "challenger_results": [
                    {"task_id": f"t{i}", "success": True, "score": 0.9,
                     "tokens_input": 100, "tokens_output": 50}
                    for i in range(5)
                ],
            },
        )

        assert guard.should_promote(experiment) is True


class TestEngineFailureInjection:
    """Test EvolutionEngine handling of failure conditions."""

    def test_evolve_without_failures(self, empty_engine):
        """Engine with no failures should complete without crashing."""
        engine, _ = empty_engine
        engine.bootstrap_defaults()

        config = EvolutionConfig(max_cycles=1)
        result = engine.evolve(config=config)

        assert result is not None
        assert result.cycle == 1

    def test_engine_state_always_queryable(self, empty_engine):
        """Engine state is always queryable for dashboard, even on empty state."""
        engine, _ = empty_engine

        state = engine.get_state()
        assert "version_tree" in state
        assert "experiments" in state
        assert "failure_summary" in state
        assert "rollbacks" in state
        assert "cycle_count" in state

    def test_engine_handles_missing_components(self, empty_engine):
        """Engine handles evolution of components with no evolver gracefully."""
        engine, _ = empty_engine
        engine.bootstrap_defaults()

        config = EvolutionConfig(
            max_cycles=1,
            components_to_evolve=["planner"],
            candidates_per_cycle=3,
        )

        result = engine.evolve(config=config)
        assert result is not None


class TestFailureInjectionSummary:
    """Verify that failure injection scenarios produce expected behavior."""

    def test_all_gates_evaluated(self):
        """RegressionGuard.evaluate returns all 5 gates."""
        guard = RegressionGuard()

        experiment = Experiment(
            experiment_id="gate-test",
            component_kind="planner",
            champion_version="v1",
            challenger_version="v2",
            status=ExperimentStatus.COMPLETED,
            started_at=datetime.now(UTC).isoformat(),
            completed_at=datetime.now(UTC).isoformat(),
            winner="challenger",
            metrics={
                "champion_score": 0.7,
                "challenger_score": 0.9,
                "champion_success": 0.7,
                "challenger_success": 0.9,
                "num_tasks": 5,
                "champion_results": [
                    {"task_id": f"t{i}", "success": True, "score": 0.7,
                     "tokens_input": 100, "tokens_output": 50}
                    for i in range(5)
                ],
                "challenger_results": [
                    {"task_id": f"t{i}", "success": True, "score": 0.9,
                     "tokens_input": 100, "tokens_output": 50}
                    for i in range(5)
                ],
            },
        )

        report = guard.evaluate(experiment)
        gate_names = {g.gate_name for g in report.gates}
        assert {
            "success_rate", "no_new_regressions", "score_floor",
            "champion_retention", "efficiency_budget",
        } <= gate_names
