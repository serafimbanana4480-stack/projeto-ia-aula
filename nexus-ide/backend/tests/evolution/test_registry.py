"""Tests for the ChampionRegistry (FASE 6)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.evolution.registry import (
    ChampionRegistry,
    ComponentStatus,
    _safe_json,
)


@pytest.fixture
def temp_registry(tmp_path: Path) -> ChampionRegistry:
    """Fresh ChampionRegistry on a temp SQLite file."""
    return ChampionRegistry(db_path=tmp_path / "test_evolution.db")


class TestChampionRegistry:
    def test_register_champion(self, temp_registry: ChampionRegistry) -> None:
        """Register initial champion for a component."""
        v = temp_registry.register_champion(
            "planner", "v1", {"prompt": "test"}, "Initial"
        )
        assert v.status == ComponentStatus.CHAMPION
        assert v.version == "v1"
        assert v.config == {"prompt": "test"}

    def test_register_demotes_existing_champion(self, temp_registry: ChampionRegistry) -> None:
        """Registering a new champion demotes the previous one to archived."""
        temp_registry.register_champion("planner", "v1", {"prompt": "v1"})
        temp_registry.register_champion("planner", "v2", {"prompt": "v2"})

        v1 = temp_registry.get_version("planner", "v1")
        v2 = temp_registry.get_champion("planner")
        assert v1.status == ComponentStatus.ARCHIVED
        assert v2.status == ComponentStatus.CHAMPION
        assert v2.version == "v2"

    def test_get_champion_none(self, temp_registry: ChampionRegistry) -> None:
        """No champion returns None before registration."""
        assert temp_registry.get_champion("planner") is None

    def test_create_challenger(self, temp_registry: ChampionRegistry) -> None:
        """Create a challenger from a champion."""
        temp_registry.register_champion("planner", "v1", {"prompt": "v1"})
        c = temp_registry.create_challenger("planner", "v2", {"prompt": "v2"}, "v1")
        assert c.status == ComponentStatus.CHALLENGER
        assert c.parent_version == "v1"

    def test_promote_challenger(self, temp_registry: ChampionRegistry) -> None:
        """Promote a challenger to champion."""
        temp_registry.register_champion("planner", "v1", {"prompt": "v1"})
        temp_registry.create_challenger("planner", "v2", {"prompt": "v2"}, "v1")
        temp_registry.promote("planner", "v2")

        champ = temp_registry.get_champion("planner")
        assert champ.version == "v2"
        old = temp_registry.get_version("planner", "v1")
        assert old.status == ComponentStatus.ARCHIVED

    def test_reject_challenger(self, temp_registry: ChampionRegistry) -> None:
        """Reject a challenger."""
        temp_registry.register_champion("planner", "v1", {"prompt": "v1"})
        temp_registry.create_challenger("planner", "v2", {"prompt": "v2"}, "v1")
        temp_registry.reject("planner", "v2", reason="failed tests")

        v2 = temp_registry.get_version("planner", "v2")
        assert v2.status == ComponentStatus.REJECTED

    def test_archive_version(self, temp_registry: ChampionRegistry) -> None:
        """Archive a version."""
        temp_registry.register_champion("planner", "v1", {"prompt": "v1"})
        temp_registry.create_challenger("planner", "v2", {"prompt": "v2"}, "v1")
        temp_registry.archive("planner", "v2")

        v2 = temp_registry.get_version("planner", "v2")
        assert v2.status == ComponentStatus.ARCHIVED

    def test_list_versions(self, temp_registry: ChampionRegistry) -> None:
        """List all versions for a component."""
        temp_registry.register_champion("planner", "v1", {})
        temp_registry.create_challenger("planner", "v2", {}, "v1")
        all_versions = temp_registry.list_versions("planner")
        assert len(all_versions) == 2

    def test_list_versions_filtered_by_status(self, temp_registry: ChampionRegistry) -> None:
        """List versions filtered by status."""
        temp_registry.register_champion("planner", "v1", {})
        temp_registry.create_challenger("planner", "v2", {}, "v1")
        temp_registry.create_challenger("planner", "v3", {}, "v1")

        champions = temp_registry.list_versions("planner", status=ComponentStatus.CHAMPION.value)
        assert len(champions) == 1
        assert champions[0].version == "v1"

        challengers = temp_registry.list_versions("planner", status=ComponentStatus.CHALLENGER.value)
        assert len(challengers) == 2

    def test_next_version(self, temp_registry: ChampionRegistry) -> None:
        """next_version generates sequential version strings."""
        assert temp_registry.next_version("planner") == "v1"
        temp_registry.register_champion("planner", "v1", {})
        assert temp_registry.next_version("planner") == "v2"
        temp_registry.create_challenger("planner", "v2", {}, "v1")
        assert temp_registry.next_version("planner") == "v3"

    def test_update_metrics(self, temp_registry: ChampionRegistry) -> None:
        """Update metrics for a version."""
        temp_registry.register_champion("planner", "v1", {})
        temp_registry.update_metrics("planner", "v1", {"success_rate": 0.85})
        v = temp_registry.get_champion("planner")
        assert v.metrics["success_rate"] == 0.85

    def test_update_metrics_merges(self, temp_registry: ChampionRegistry) -> None:
        """Metrics merge with existing values."""
        temp_registry.register_champion("planner", "v1", {})
        temp_registry.update_metrics("planner", "v1", {"a": 1})
        temp_registry.update_metrics("planner", "v1", {"b": 2})
        v = temp_registry.get_champion("planner")
        assert v.metrics["a"] == 1
        assert v.metrics["b"] == 2

    def test_list_all_kinds(self, temp_registry: ChampionRegistry) -> None:
        """list_all_kinds returns all component kinds."""
        temp_registry.register_champion("planner", "v1", {})
        temp_registry.register_champion("coder", "v1", {})
        kinds = temp_registry.list_all_kinds()
        assert "planner" in kinds
        assert "coder" in kinds

    def test_version_id(self, temp_registry: ChampionRegistry) -> None:
        """ComponentVersion id property combines kind and version."""
        v = temp_registry.register_champion("planner", "v1", {})
        assert v.id == "planner:v1"

    def test_safe_json_handles_none(self) -> None:
        """_safe_json returns empty dict on None/empty."""
        assert _safe_json(None) == {}
        assert _safe_json("") == {}
        assert _safe_json('{"a": 1}') == {"a": 1}
        assert _safe_json("invalid") == {}


class TestVersionTree:
    def test_version_tree(self, temp_registry: ChampionRegistry) -> None:
        """get_version_tree returns versions grouped by component kind."""
        temp_registry.register_champion("planner", "v1", {"a": 1}, "Initial")
        temp_registry.create_challenger("planner", "v2", {"a": 2}, "v1", "Mutation")
        tree = temp_registry.get_version_tree()
        assert "planner" in tree
        assert len(tree["planner"]) == 2
        assert tree["planner"][0]["version"] in ("v1", "v2")
        assert any(v["version"] == "v1" for v in tree["planner"])
        assert any(v["version"] == "v2" for v in tree["planner"])
