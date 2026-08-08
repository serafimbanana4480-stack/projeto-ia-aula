"""Integration tests for the EvolutionEngine (FASE 17 - self-evolution)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.evolution.engine import EvolutionEngine
from backend.evolution.registry import ChampionRegistry, ComponentStatus


@pytest.fixture
def temp_engine(tmp_path: Path) -> EvolutionEngine:
    """EvolutionEngine with temp DBs."""
    registry = ChampionRegistry(db_path=tmp_path / "test_evolution.db")
    from backend.evolution.arena import Arena
    from backend.evolution.failure_miner import FailureMiner
    from backend.evolution.regression_guard import RegressionGuard
    from backend.evolution.rollback import RollbackManager
    from backend.experience.lake import TraceLake

    lake = TraceLake(tmp_path / "test_trace_lake.db")
    miner = FailureMiner(lake=lake, db_path=tmp_path / "test_evolution.db")
    arena = Arena(registry, allow_simulation=True)
    guard = RegressionGuard()
    rollback = RollbackManager(registry)

    return EvolutionEngine(
        registry=registry,
        arena=arena,
        failure_miner=miner,
        guard=guard,
        rollback=rollback,
    )


class TestEvolutionEngine:
    def test_bootstrap_defaults(self, temp_engine: EvolutionEngine) -> None:
        """bootstrap_defaults registers champions for all default components."""
        registered = temp_engine.bootstrap_defaults()
        assert len(registered) > 0
        for kind in registered:
            champ = temp_engine._registry.get_champion(kind)
            assert champ is not None
            assert champ.status == ComponentStatus.CHAMPION

    def test_bootstrap_idempotent(self, temp_engine: EvolutionEngine) -> None:
        """bootstrap_defaults doesn't re-register existing champions."""
        temp_engine.bootstrap_defaults()
        second = temp_engine.bootstrap_defaults()
        assert len(second) == 0

    def test_register_champion(self, temp_engine: EvolutionEngine) -> None:
        """Can manually register a champion."""
        v = temp_engine.register_champion("prompt", {"prompt_text": "test"})
        assert v.status.value == "champion"
        assert v.version == "v1"

    def test_get_state(self, temp_engine: EvolutionEngine) -> None:
        """get_state returns engine state dict."""
        temp_engine.bootstrap_defaults()
        state = temp_engine.get_state()
        assert "version_tree" in state
        assert "experiments" in state
        assert "failure_summary" in state
        assert "cycle_count" in state

    def test_set_benchmark_runner(self, temp_engine: EvolutionEngine) -> None:
        """set_benchmark_runner sets the arena runner."""

        class DummyRunner:
            def run(self, component_kind, version, tasks):
                return [{"task_id": "t1", "success": True, "score": 0.9}]

        temp_engine.set_benchmark_runner(DummyRunner())
        assert temp_engine._arena._runner is not None
