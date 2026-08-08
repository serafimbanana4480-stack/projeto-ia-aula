"""Tests for the RollbackManager (FASE 9)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.evolution.registry import ChampionRegistry, ComponentStatus
from backend.evolution.rollback import RollbackEvent, RollbackManager


@pytest.fixture
def temp_registry(tmp_path: Path) -> ChampionRegistry:
    return ChampionRegistry(db_path=tmp_path / "test_evolution.db")


@pytest.fixture
def rollback(temp_registry: ChampionRegistry) -> RollbackManager:
    return RollbackManager(temp_registry)


class TestEvaluateHealth:
    def test_healthy_champion_no_rollback(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """Champion with good metrics doesn't trigger rollback."""
        temp_registry.register_champion("prompt", "v1", {"prompt_text": "old"})
        temp_registry.promote("prompt", "v1")

        metrics = {"success_rate": 0.95, "avg_score": 0.90, "total_tasks": 50}
        should_rollback, reason = rollback.evaluate_health("prompt", metrics)
        assert should_rollback is False
        assert "healthy" in reason.lower() or "insufficient" in reason.lower()

    def test_success_rate_drop_triggers_rollback(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """Success rate drop below threshold triggers rollback."""
        temp_registry.register_champion("coder", "v1", {})
        temp_registry.promote("coder", "v1")

        # Set champion baseline
        temp_registry.update_metrics("coder", "v1", {"success_rate": 0.95, "avg_score": 0.90})

        metrics = {"success_rate": 0.70, "avg_score": 0.90, "total_tasks": 50}
        should_rollback, reason = rollback.evaluate_health("coder", metrics)
        assert should_rollback is True
        assert "success rate" in reason.lower()

    def test_score_drop_triggers_rollback(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """Score drop below threshold triggers rollback."""
        temp_registry.register_champion("coder", "v1", {})
        temp_registry.promote("coder", "v1")
        temp_registry.update_metrics("coder", "v1", {"success_rate": 0.95, "avg_score": 0.90})

        metrics = {"success_rate": 0.95, "avg_score": 0.50, "total_tasks": 50}
        should_rollback, reason = rollback.evaluate_health("coder", metrics)
        assert should_rollback is True
        assert "score" in reason.lower()

    def test_insufficient_tasks_no_rollback(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """Insufficient task count prevents rollback."""
        temp_registry.register_champion("coder", "v1", {})
        temp_registry.promote("coder", "v1")
        temp_registry.update_metrics("coder", "v1", {"success_rate": 0.95, "avg_score": 0.90})

        metrics = {"success_rate": 0.70, "avg_score": 0.50, "total_tasks": 5}
        should_rollback, reason = rollback.evaluate_health("coder", metrics)
        assert should_rollback is False
        assert "insufficient" in reason.lower()


class TestShouldRollback:
    def test_no_champion(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """No champion → no rollback."""
        should, reason = rollback.should_rollback("nonexistent", {"total_tasks": 50})
        assert should is False

    def test_no_previous_champion(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """Champion exists but no previous version → no rollback."""
        temp_registry.register_champion("coder", "v1", {})

        metrics = {"success_rate": 0.70, "avg_score": 0.50, "total_tasks": 50}
        should, reason = rollback.should_rollback("coder", metrics)
        assert should is False
        assert "previous" in reason.lower()

    def test_rollback_when_degraded(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """Rollback triggered when champion is degraded and previous exists."""
        # Create v1 champion
        temp_registry.register_champion("coder", "v1", {"prompt": "old"})
        temp_registry.update_metrics("coder", "v1", {"success_rate": 0.95, "avg_score": 0.90})

        # Create v2 champion (v1 gets archived)
        temp_registry.register_champion("coder", "v2", {"prompt": "new"})
        temp_registry.update_metrics("coder", "v2", {"success_rate": 0.95, "avg_score": 0.90})

        # Now v2 is champion, v1 is archived. Feed degraded metrics.
        metrics = {"success_rate": 0.70, "avg_score": 0.50, "total_tasks": 50}
        should, reason = rollback.should_rollback("coder", metrics)
        assert should is True


class TestExecuteRollback:
    def test_execute_rollback_restores_previous(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """execute_rollback archives current champion and restores previous."""
        temp_registry.register_champion("prompt", "v1", {"text": "old"})
        temp_registry.register_champion("prompt", "v2", {"text": "new"})

        event = rollback.execute_rollback("prompt", reason="degraded performance")

        assert event is not None
        assert event.component_kind == "prompt"
        assert event.from_version == "v2"
        assert event.to_version == "v1"
        assert "degraded" in event.reason

        # Verify v2 is now archived, v1 is champion
        champ = temp_registry.get_champion("prompt")
        assert champ is not None
        assert champ.version == "v1"
        assert champ.status == ComponentStatus.CHAMPION

    def test_execute_rollback_no_champion(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """Rollback with no champion returns None."""
        result = rollback.execute_rollback("nonexistent", reason="nope")
        assert result is None

    def test_execute_rollback_no_previous(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """Rollback with no previous champion returns None."""
        temp_registry.register_champion("coder", "v1", {})
        result = rollback.execute_rollback("coder", reason="nope")
        assert result is None

    def test_rollback_event_is_dataclass(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """RollbackEvent has all expected fields."""
        temp_registry.register_champion("coder", "v1", {})
        temp_registry.register_champion("coder", "v2", {})

        event = rollback.execute_rollback("coder", reason="test")
        assert event is not None
        assert isinstance(event, RollbackEvent)
        assert hasattr(event, "component_kind")
        assert hasattr(event, "from_version")
        assert hasattr(event, "to_version")
        assert hasattr(event, "reason")
        assert hasattr(event, "timestamp")
        assert hasattr(event, "metrics_before")
        assert hasattr(event, "metrics_after")


class TestRollbackHistory:
    def test_get_rollback_history_empty(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """No rollbacks → empty history."""
        history = rollback.get_rollback_history("all")
        assert history == []

    def test_get_rollback_history_records_events(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """Rollback events are persisted and retrievable."""
        temp_registry.register_champion("prompt", "v1", {})
        temp_registry.register_champion("prompt", "v2", {})

        rollback.execute_rollback("prompt", reason="test rollback")

        history = rollback.get_rollback_history("all")
        assert len(history) >= 1
        assert history[0]["event_type"] == "rolled_back"
        assert history[0]["component_kind"] == "prompt"

    def test_get_rollback_history_filtered_by_component(self, rollback: RollbackManager, temp_registry: ChampionRegistry) -> None:
        """History can be filtered by component kind."""
        temp_registry.register_champion("prompt", "v1", {})
        temp_registry.register_champion("prompt", "v2", {})
        temp_registry.register_champion("coder", "v1", {})
        temp_registry.register_champion("coder", "v2", {})

        rollback.execute_rollback("prompt", reason="prompt rollback")
        rollback.execute_rollback("coder", reason="coder rollback")

        prompt_history = rollback.get_rollback_history("prompt")
        assert len(prompt_history) == 1
        assert prompt_history[0]["component_kind"] == "prompt"
