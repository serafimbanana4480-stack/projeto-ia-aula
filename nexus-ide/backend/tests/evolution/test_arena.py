"""Tests for the Arena (FASE 5)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.evolution.arena import Arena
from backend.evolution.registry import (
    ChampionRegistry,
    ExperimentStatus,
)


@pytest.fixture
def temp_arena(tmp_path: Path) -> Arena:
    """Arena with temp registry."""
    registry = ChampionRegistry(db_path=tmp_path / "test_evolution.db")
    return Arena(registry, allow_simulation=True)


class TestArenaSimulation:
    def test_simulate_without_runner(self, temp_arena: Arena) -> None:
        """Arena can simulate experiments without a real runner."""
        temp_arena._registry.register_champion("planner", "v1", {"prompt": "v1"})
        temp_arena._registry.create_challenger("planner", "v2", {"prompt": "v2"}, "v1")

        result = temp_arena.run_experiment("planner", "v2", ["task1", "task2"])
        assert result.status != ExperimentStatus.RUNNING  # should be completed or regression
        assert result.experiment_id.startswith("exp-")
        assert result.champion_version == "v1"
        assert result.challenger_version == "v2"
        assert result.metrics.get("simulated") is True

    def test_simulate_without_allow_simulation_raises(self, tmp_path: Path) -> None:
        """Arena without allow_simulation raises when no runner is set."""
        registry = ChampionRegistry(db_path=tmp_path / "test_evolution.db")
        arena = Arena(registry, allow_simulation=False)
        arena._registry.register_champion("planner", "v1", {"prompt": "v1"})
        arena._registry.create_challenger("planner", "v2", {"prompt": "v2"}, "v1")

        with pytest.raises(RuntimeError, match="No benchmark runner set"):
            arena.run_experiment("planner", "v2", ["task1"])

    def test_simulate_experiment_persisted(
        self, temp_arena: Arena, tmp_path: Path
    ) -> None:
        """Simulated experiments are persisted to the DB."""
        temp_arena._registry.register_champion("planner", "v1", {"prompt": "v1"})
        temp_arena._registry.create_challenger("planner", "v2", {"prompt": "v2"}, "v1")

        result = temp_arena.run_experiment("planner", "v2", ["task1"])
        assert temp_arena._persist_experiment  # exists

        # Reload from DB
        experiments = temp_arena.list_experiments("planner")
        assert any(e.experiment_id == result.experiment_id for e in experiments)

    def test_list_experiments_all_kinds(self, temp_arena: Arena) -> None:
        """list_experiments returns across all component kinds when None."""
        temp_arena._registry.register_champion("planner", "v1", {})
        temp_arena._registry.register_champion("coder", "v1", {})
        temp_arena._registry.create_challenger("planner", "v2", {}, "v1")
        temp_arena._registry.create_challenger("coder", "v2", {}, "v1")

        temp_arena.run_experiment("planner", "v2", ["t1"])
        temp_arena.run_experiment("coder", "v2", ["t2"])

        all_exps = temp_arena.list_experiments()
        assert len(all_exps) >= 2


class TestBenchmarkRunner:
    def test_arena_with_custom_runner(self, tmp_path: Path) -> None:
        """Arena works with a custom benchmark runner."""
        registry = ChampionRegistry(db_path=tmp_path / "test_evolution.db")

        class TestRunner:
            def __init__(self):
                self.call_count = 0

            def run(self, component_kind, version, tasks):
                self.call_count += 1
                results = []
                for t in tasks:
                    results.append({
                        "task_id": t["task_id"],
                        "success": True,
                        "score": 0.9 if version.version == "v2" else 0.7,
                        "metrics": {},
                        "error": None,
                    })
                return results

        runner = TestRunner()
        arena = Arena(registry)
        arena.set_runner(runner)

        registry.register_champion("prompt", "v1", {"prompt_text": "v1"})
        registry.create_challenger("prompt", "v2", {"prompt_text": "v2"}, "v1")

        result = arena.run_experiment("prompt", "v2", ["task_a", "task_b"])
        assert result.winner == "challenger"
        assert runner.call_count == 2  # champion + challenger

    def test_arena_champion_wins(self, tmp_path: Path) -> None:
        """When champion has higher score, winner is 'champion'."""
        registry = ChampionRegistry(db_path=tmp_path / "test_evolution.db")

        class TestRunner:
            def run(self, component_kind, version, tasks):
                results = []
                for t in tasks:
                    results.append({
                        "task_id": t["task_id"],
                        "success": True,
                        "score": 0.6 if version.version == "v2" else 0.95,
                        "metrics": {},
                        "error": None,
                    })
                return results

        arena = Arena(registry)
        arena.set_runner(TestRunner())
        registry.register_champion("prompt", "v1", {})
        registry.create_challenger("prompt", "v2", {}, "v1")

        result = arena.run_experiment("prompt", "v2", ["task_a"])
        assert result.winner == "champion"

    def test_arena_detects_regression(self, tmp_path: Path) -> None:
        """Arena detects regression when challenger fails on champion-solved tasks."""
        registry = ChampionRegistry(db_path=tmp_path / "test_evolution.db")

        class TestRunner:
            def run(self, component_kind, version, tasks):
                results = []
                for t in tasks:
                    if version.version == "v1":
                        # Champion succeeds on all
                        results.append({"task_id": t["task_id"], "success": True, "score": 0.9, "metrics": {}, "error": None})
                    else:
                        # Challenger fails on one
                        success = t["task_id"] != "fail_task"
                        results.append({
                            "task_id": t["task_id"],
                            "success": success,
                            "score": 0.5 if not success else 0.9,
                            "metrics": {},
                            "error": "failed" if not success else None,
                        })
                return results

        arena = Arena(registry)
        arena.set_runner(TestRunner())
        registry.register_champion("prompt", "v1", {})
        registry.create_challenger("prompt", "v2", {}, "v1")

        result = arena.run_experiment("prompt", "v2", ["ok_task", "fail_task"])
        assert result.regression_detected is True
        assert result.status == ExperimentStatus.REGRESSION
