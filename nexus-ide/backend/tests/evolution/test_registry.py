"""Tests for the ChampionRegistry (FASE 6)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

import pytest

from backend.evolution.registry import (
    ALLOWED_STATUS_TRANSITIONS,
    ChampionRegistry,
    ComponentStatus,
    Experiment,
    ExperimentStatus,
    _safe_json,
    bump_semantic_version,
    parse_semantic_version,
    semantic_bump_for_outcome,
    validate_transition,
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


def _seed_experimental(registry: ChampionRegistry, kind: str = "comp",
                       version: str = "exp") -> None:
    registry.import_versions([{
        "component_kind": kind,
        "version": version,
        "status": ComponentStatus.EXPERIMENTAL.value,
        "created_at": "2026-01-01T00:00:00+00:00",
    }])


class TestStatusTransitions:
    @pytest.mark.parametrize("current", list(ComponentStatus))
    @pytest.mark.parametrize("target", list(ComponentStatus))
    def test_transition_matrix(self, current: ComponentStatus,
                               target: ComponentStatus) -> None:
        """Every (current, target) pair behaves exactly as the map declares."""
        if target in ALLOWED_STATUS_TRANSITIONS[current]:
            validate_transition(current, target)
        else:
            with pytest.raises(ValueError, match="Illegal status transition"):
                validate_transition(current, target)

    def test_map_covers_all_statuses(self) -> None:
        """The transitions map has an entry for every lifecycle status."""
        assert set(ALLOWED_STATUS_TRANSITIONS) == set(ComponentStatus)

    def test_promote_champion_is_idempotent(self, temp_registry: ChampionRegistry) -> None:
        """Promoting the incumbent champion keeps it champion."""
        temp_registry.register_champion("planner", "v1", {})
        v = temp_registry.promote("planner", "v1")
        assert v.status == ComponentStatus.CHAMPION
        assert temp_registry.get_champion("planner").version == "v1"

    def test_reject_champion_raises(self, temp_registry: ChampionRegistry) -> None:
        """A champion cannot be rejected directly."""
        temp_registry.register_champion("planner", "v1", {})
        with pytest.raises(ValueError, match="champion.*rejected"):
            temp_registry.reject("planner", "v1")

    def test_archived_can_be_repromoted_rollback_flow(self, temp_registry: ChampionRegistry) -> None:
        """Demoted champions can be restored, as rollback does."""
        temp_registry.register_champion("planner", "v1", {})
        temp_registry.create_challenger("planner", "v2", {}, "v1")
        temp_registry.promote("planner", "v2")
        temp_registry.archive("planner", "v2")
        restored = temp_registry.promote("planner", "v1")
        assert restored.status == ComponentStatus.CHAMPION
        assert temp_registry.get_version("planner", "v2").status == ComponentStatus.ARCHIVED

    def test_retire_champion(self, temp_registry: ChampionRegistry) -> None:
        """retire() moves a champion to the terminal retired state."""
        temp_registry.register_champion("planner", "v1", {})
        retired = temp_registry.retire("planner", "v1", reason="superseded")
        assert retired.status == ComponentStatus.RETIRED
        assert "superseded" in retired.changelog
        assert temp_registry.get_champion("planner") is None

    def test_retired_cannot_be_promoted_directly(self, temp_registry: ChampionRegistry) -> None:
        """Retired versions require re-promotion via a fresh challenger."""
        temp_registry.register_champion("planner", "v1", {})
        temp_registry.retire("planner", "v1")
        with pytest.raises(ValueError, match="retired"):
            temp_registry.promote("planner", "v1")

    def test_retired_repromotion_via_fresh_challenger(self, temp_registry: ChampionRegistry) -> None:
        """The documented re-promotion path: challenger derived from retired wins."""
        temp_registry.register_champion("planner", "v1", {"a": 1})
        temp_registry.retire("planner", "v1")
        fresh = temp_registry.create_challenger("planner", "v1.1", {"a": 2}, "v1")
        promoted = temp_registry.promote("planner", "v1.1")
        assert fresh.status == ComponentStatus.CHALLENGER
        assert promoted.status == ComponentStatus.CHAMPION

    def test_rejected_is_terminal(self, temp_registry: ChampionRegistry) -> None:
        """Rejected versions cannot be re-promoted or re-rejected."""
        temp_registry.register_champion("planner", "v1", {})
        temp_registry.create_challenger("planner", "v2", {}, "v1")
        temp_registry.reject("planner", "v2")
        with pytest.raises(ValueError):
            temp_registry.reject("planner", "v2")
        with pytest.raises(ValueError):
            temp_registry.promote("planner", "v2")

    def test_set_status_validated(self, temp_registry: ChampionRegistry) -> None:
        """set_status enforces the map for legal and illegal moves."""
        _seed_experimental(temp_registry)
        v = temp_registry.set_status("comp", "exp", ComponentStatus.CHALLENGER)
        assert v.status == ComponentStatus.CHALLENGER
        with pytest.raises(ValueError):
            temp_registry.set_status("comp", "exp", ComponentStatus.RETIRED)

    def test_set_status_to_champion_demotes_incumbent(self, temp_registry: ChampionRegistry) -> None:
        """Experimental can take the crown directly; old champion is archived."""
        temp_registry.register_champion("planner", "v1", {})
        _seed_experimental(temp_registry, kind="planner", version="exp")
        champ = temp_registry.set_status("planner", "exp", ComponentStatus.CHAMPION)
        assert champ.status == ComponentStatus.CHAMPION
        assert temp_registry.get_version("planner", "v1").status == ComponentStatus.ARCHIVED

    def test_unknown_version_raises(self, temp_registry: ChampionRegistry) -> None:
        """All mutating operations raise ValueError for unknown versions."""
        with pytest.raises(ValueError, match="Unknown version"):
            temp_registry.promote("planner", "ghost")
        with pytest.raises(ValueError, match="Unknown version"):
            temp_registry.reject("planner", "ghost")
        with pytest.raises(ValueError, match="Unknown version"):
            temp_registry.archive("planner", "ghost")
        with pytest.raises(ValueError, match="Unknown version"):
            temp_registry.set_status("planner", "ghost", ComponentStatus.ARCHIVED)
        with pytest.raises(ValueError, match="Unknown version"):
            temp_registry.retire("planner", "ghost")


class TestSemanticVersioning:
    def test_parse_semantic_version(self) -> None:
        assert parse_semantic_version("1.2.3") == (1, 2, 3)
        assert parse_semantic_version("v1.2.3") == (1, 2, 3)
        assert parse_semantic_version("0.0.0") == (0, 0, 0)

    @pytest.mark.parametrize("bad", ["1.2", "1.2.3.4", "a.b.c", "", "v", "v1.x.z"])
    def test_parse_semantic_version_invalid(self, bad: str) -> None:
        with pytest.raises(ValueError, match="Not a semantic version"):
            parse_semantic_version(bad)

    def test_bump_semantic_version(self) -> None:
        assert bump_semantic_version("1.2.3", "major") == "2.0.0"
        assert bump_semantic_version("1.2.3", "minor") == "1.3.0"
        assert bump_semantic_version("1.2.3", "patch") == "1.2.4"
        assert bump_semantic_version("v1.2.3", "minor") == "v1.3.0"

    def test_bump_semantic_version_invalid_part(self) -> None:
        with pytest.raises(ValueError, match="Unknown bump part"):
            bump_semantic_version("1.2.3", "mega")

    @staticmethod
    def _experiment(**overrides: Any) -> Experiment:
        base: dict[str, Any] = {
            "experiment_id": "exp-1",
            "component_kind": "planner",
            "champion_version": "v1",
            "challenger_version": "v2",
            "status": ExperimentStatus.COMPLETED,
            "winner": "challenger",
            "regression_detected": False,
        }
        base.update(overrides)
        return Experiment(**base)

    def test_outcome_promoted_is_minor(self) -> None:
        exp = self._experiment(status=ExperimentStatus.PROMOTED)
        assert semantic_bump_for_outcome(exp) == "minor"

    def test_outcome_regression_is_patch(self) -> None:
        exp = self._experiment(status=ExperimentStatus.REGRESSION)
        assert semantic_bump_for_outcome(exp) == "patch"
        exp_flagged = self._experiment(regression_detected=True, status=ExperimentStatus.COMPLETED)
        assert semantic_bump_for_outcome(exp_flagged) == "patch"

    def test_outcome_champion_kept_or_tie_is_patch(self) -> None:
        kept = self._experiment(winner="champion", status=ExperimentStatus.COMPLETED)
        tie = self._experiment(winner="tie")
        rejected = self._experiment(
            winner=None, status=ExperimentStatus.REJECTED
        )
        assert semantic_bump_for_outcome(kept) == "patch"
        assert semantic_bump_for_outcome(tie) == "patch"
        assert semantic_bump_for_outcome(rejected) == "patch"

    @pytest.mark.parametrize("status", [ExperimentStatus.PENDING, ExperimentStatus.RUNNING])
    def test_outcome_incomplete_raises(self, status: ExperimentStatus) -> None:
        with pytest.raises(ValueError, match="not complete"):
            semantic_bump_for_outcome(self._experiment(status=status))

    def test_next_semantic_version_from_no_champion(self, temp_registry: ChampionRegistry) -> None:
        assert temp_registry.next_semantic_version("planner") == "0.1.0"
        assert temp_registry.next_semantic_version("planner", part="major") == "1.0.0"

    def test_next_semantic_version_from_non_semantic_champion(
        self, temp_registry: ChampionRegistry,
    ) -> None:
        temp_registry.register_champion("planner", "v7", {})
        assert temp_registry.next_semantic_version("planner") == "0.1.0"

    def test_next_semantic_version_from_semantic_champion(
        self, temp_registry: ChampionRegistry,
    ) -> None:
        temp_registry.register_champion("planner", "v1.2.3", {})
        assert temp_registry.next_semantic_version("planner", part="patch") == "v1.2.4"
        assert temp_registry.next_semantic_version("planner", part="minor") == "v1.3.0"
        assert temp_registry.next_semantic_version("planner", part="major") == "v2.0.0"


class TestExportImportRoundTrip:
    @staticmethod
    def _populate(registry: ChampionRegistry) -> None:
        registry.register_champion("planner", "v1", {"prompt": "p1"}, "initial release")
        registry.update_metrics("planner", "v1", {"success_rate": 0.9})
        c = registry.create_challenger("planner", "v2", {"prompt": "p2"}, "v1", "mutation A")
        registry.reject("planner", c.version, reason="failed gates")
        registry.create_challenger("planner", "v3", {"prompt": "p3"}, "v1", "mutation B")
        registry.promote("planner", "v3", changelog="won arena")
        registry.register_champion("coder", "v1", {"lang": "py"})
        _seed_experimental(registry, kind="coder", version="exp")

    @staticmethod
    def _snapshot(registry: ChampionRegistry) -> list[dict[str, object]]:
        rows = []
        for kind in sorted(registry.list_all_kinds()):
            for v in registry.list_versions(kind):
                rows.append({
                    "component_kind": v.component_kind,
                    "version": v.version,
                    "status": v.status.value,
                    "config": v.config,
                    "created_at": v.created_at,
                    "promoted_at": v.promoted_at,
                    "parent_version": v.parent_version,
                    "changelog": v.changelog,
                    "metrics": v.metrics,
                })
        return sorted(rows, key=lambda r: (str(r["component_kind"]), str(r["version"])))

    def test_round_trip_preserves_everything(
        self, temp_registry: ChampionRegistry, tmp_path: Path,
    ) -> None:
        self._populate(temp_registry)
        exported = temp_registry.export_versions()

        restored = ChampionRegistry(db_path=tmp_path / "restored.db")
        count = restored.import_versions(exported)
        assert count == 5
        assert self._snapshot(restored) == self._snapshot(temp_registry)
        assert restored.get_champion("planner").version == "v3"
        assert restored.get_version("planner", "v2").status == ComponentStatus.REJECTED
        assert restored.get_version("coder", "exp").status == ComponentStatus.EXPERIMENTAL

    def test_import_idempotent(self, temp_registry: ChampionRegistry, tmp_path: Path) -> None:
        self._populate(temp_registry)
        exported = temp_registry.export_versions()
        restored = ChampionRegistry(db_path=tmp_path / "restored.db")
        first = restored.import_versions(exported)
        second = restored.import_versions(exported)
        assert first == second == 5
        assert len(restored.list_all_kinds()) == 2
        assert len(restored.list_versions("planner")) == 3

    def test_export_filtered_by_kind(self, temp_registry: ChampionRegistry) -> None:
        self._populate(temp_registry)
        payload = json.loads(temp_registry.export_versions("coder"))
        assert {item["component_kind"] for item in payload} == {"coder"}

    def test_import_accepts_parsed_list(self, temp_registry: ChampionRegistry, tmp_path: Path) -> None:
        self._populate(temp_registry)
        items = json.loads(temp_registry.export_versions())
        restored = ChampionRegistry(db_path=tmp_path / "restored.db")
        assert restored.import_versions(items) == 5
        assert self._snapshot(restored) == self._snapshot(temp_registry)

    def test_import_unknown_status_raises(self, tmp_path: Path) -> None:
        registry = ChampionRegistry(db_path=tmp_path / "target.db")
        with pytest.raises(ValueError):
            registry.import_versions([{
                "component_kind": "x",
                "version": "v1",
                "status": "nonexistent",
                "created_at": "2026-01-01T00:00:00+00:00",
            }])


class TestHistoryOrdering:
    def test_history_is_chronological(self, temp_registry: ChampionRegistry) -> None:
        temp_registry.register_champion("planner", "v1", {})
        temp_registry.create_challenger("planner", "v2", {}, "v1")
        temp_registry.create_challenger("planner", "v3", {}, "v2")
        history = temp_registry.history("planner")
        assert [v.version for v in history] == ["v1", "v2", "v3"]

    def test_history_orders_by_created_at_even_if_inserted_out_of_order(
        self, temp_registry: ChampionRegistry,
    ) -> None:
        temp_registry.import_versions([
            {
                "component_kind": "planner",
                "version": "v3",
                "status": ComponentStatus.EXPERIMENTAL.value,
                "created_at": "2026-03-01T00:00:00+00:00",
            },
            {
                "component_kind": "planner",
                "version": "v1",
                "status": ComponentStatus.ARCHIVED.value,
                "created_at": "2026-01-01T00:00:00+00:00",
            },
            {
                "component_kind": "planner",
                "version": "v2",
                "status": ComponentStatus.CHALLENGER.value,
                "created_at": "2026-02-01T00:00:00+00:00",
            },
        ])
        history = temp_registry.history("planner")
        assert [v.version for v in history] == ["v1", "v2", "v3"]
        assert [v.created_at for v in history] == sorted(v.created_at for v in history)

    def test_history_includes_all_statuses_and_other_kinds_untouched(
        self, temp_registry: ChampionRegistry,
    ) -> None:
        temp_registry.register_champion("planner", "v1", {})
        temp_registry.create_challenger("planner", "v2", {}, "v1")
        temp_registry.reject("planner", "v2")
        temp_registry.register_champion("coder", "v1", {})
        history = temp_registry.history("planner")
        assert [v.version for v in history] == ["v1", "v2"]
        assert [v.status for v in history] == [
            ComponentStatus.CHAMPION,
            ComponentStatus.REJECTED,
        ]
        assert [v.version for v in temp_registry.history("coder")] == ["v1"]
        assert all(v.component_kind == "planner" for v in temp_registry.history("planner"))

    def test_history_empty_for_unknown_kind(self, temp_registry: ChampionRegistry) -> None:
        assert temp_registry.history("nope") == []


class TestThreadSafety:
    def test_concurrent_promotes_yield_single_champion(
        self, temp_registry: ChampionRegistry,
    ) -> None:
        """Concurrent promote() calls are serialized: exactly one champion survives."""
        temp_registry.register_champion("planner", "v1", {})
        challengers = [f"c{i}" for i in range(10)]
        for c in challengers:
            temp_registry.create_challenger("planner", c, {}, "v1")

        errors: list[Exception] = []
        barrier = threading.Barrier(len(challengers))

        def worker(version: str) -> None:
            try:
                barrier.wait(timeout=10)
                temp_registry.promote("planner", version)
            except Exception as exc:
                errors.append(exc)

        threads = [
            threading.Thread(target=worker, args=(c,), name=f"promote-{c}")
            for c in challengers
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not any(t.is_alive() for t in threads), "worker thread hung"

        assert errors == []
        champions = [
            v for v in temp_registry.list_versions("planner")
            if v.status == ComponentStatus.CHAMPION
        ]
        assert len(champions) == 1
        assert champions[0].version in challengers

    def test_lock_is_reentrant(self, temp_registry: ChampionRegistry) -> None:
        """Nested public mutations from the same thread do not deadlock."""
        temp_registry.register_champion("planner", "v1", {})
        temp_registry.create_challenger("planner", "v2", {}, "v1")
        with temp_registry._lock:
            temp_registry.promote("planner", "v2")
        assert temp_registry.get_champion("planner").version == "v2"
