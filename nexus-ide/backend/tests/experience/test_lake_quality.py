"""Tests for TraceLake quality features: dedup, TTL archive, failure queries."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from backend.experience.lake import (
    _SCHEMA_SQL,
    SCHEMA_VERSION,
    TraceLake,
    classify_failure_text,
)
from backend.experience.models import ExperienceTrace, TaskCategory

OLD_TS = "2020-01-01T00:00:00+00:00"


def _trace(task_id: str, **kw: Any) -> ExperienceTrace:
    fields: dict[str, Any] = {
        "task_id": task_id,
        "prompt": kw.get("prompt", "Fix the failing test in auth.py"),
        "task_type": kw.get("task_type", "debugging"),
        "category": kw.get("category", TaskCategory.DEBUGGING),
    }
    if kw.get("timestamp"):
        fields["timestamp"] = kw["timestamp"]
    return ExperienceTrace(**fields)


@pytest.fixture
def lake(tmp_path: Path) -> TraceLake:
    return TraceLake(tmp_path / "lake_quality.db")


# ── Content-hash dedup ───────────────────────────────────────────────────────

class TestContentHashDedup:
    def test_identical_write_is_skipped(self, lake: TraceLake) -> None:
        trace = _trace("dup_1")
        assert lake.store_trace(trace) == "dup_1"
        assert lake.store_trace(trace) == "dup_1"
        assert lake.trace_count() == 1
        stats = lake.get_ingest_stats()
        assert stats["writes_total"] == 1
        assert stats["duplicates_skipped"] == 1

    def test_store_trace_with_stats(self, lake: TraceLake) -> None:
        trace = _trace("dup_2")
        first = lake.store_trace_with_stats(trace)
        second = lake.store_trace_with_stats(trace)
        assert first == {"task_id": "dup_2", "stored": True, "duplicate": False}
        assert second == {"task_id": "dup_2", "stored": False, "duplicate": True}

    def test_timestamp_only_difference_is_duplicate(self, lake: TraceLake) -> None:
        trace = _trace("dup_3", timestamp="2026-01-01T10:00:00+00:00")
        lake.store_trace(trace)
        replayed = _trace("dup_3", timestamp="2026-01-02T10:00:00+00:00")
        result = lake.store_trace_with_stats(replayed)
        assert result["duplicate"] is True
        assert lake.trace_count() == 1

    def test_mutated_payload_replaces(self, lake: TraceLake) -> None:
        trace = _trace("mut_1")
        lake.store_trace(trace)
        trace.result.success = False
        trace.result.error = "timeout after 30s"
        result = lake.store_trace_with_stats(trace)
        assert result["stored"] is True
        assert lake.trace_count() == 1
        stored = lake.get_trace("mut_1")
        assert stored is not None
        assert stored.result.error == "timeout after 30s"

    def test_dedupe_disabled_forces_replace(self, lake: TraceLake) -> None:
        trace = _trace("dup_4")
        lake.store_trace(trace)
        lake.store_trace(trace, dedupe=False)
        assert lake.trace_count() == 1
        assert lake.get_ingest_stats()["duplicates_skipped"] == 0

    def test_content_hash_stable_and_sensitive(self) -> None:
        a = _trace("h_1", timestamp="2026-01-01T00:00:00+00:00")
        b = _trace("h_1", timestamp="2099-12-31T00:00:00+00:00")
        c = _trace("h_1", prompt="Different prompt")
        assert a.compute_content_hash() == b.compute_content_hash()
        assert a.compute_content_hash() != c.compute_content_hash()

    def test_failure_classification_not_duplicated(self, lake: TraceLake) -> None:
        trace = _trace("fc_1")
        trace.result.success = False
        trace.result.error = "SyntaxError: invalid syntax"
        lake.store_trace(trace)
        lake.store_trace(trace)
        with sqlite3.connect(lake.db_path) as conn:
            rows = conn.execute(
                "SELECT failure_category FROM failure_categories WHERE task_id = 'fc_1'"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "incorrect_code"


# ── Retention / TTL cold archive ─────────────────────────────────────────────

class TestPurgeExpired:
    def _seed(self, lake: TraceLake) -> None:
        old = _trace("old_1", timestamp=OLD_TS)
        old.add_trajectory_entry(agent="DEBUGGER", action="run_test", duration_ms=50)
        old.result.success = False
        old.result.error = "SyntaxError: invalid syntax"
        lake.store_trace(old)

        fresh = _trace("new_1")
        fresh.result.success = True
        lake.store_trace(fresh)

    def test_expired_moves_to_archive(self, lake: TraceLake) -> None:
        self._seed(lake)
        report = lake.purge_expired(ttl_days=30)
        assert report["archived_traces"] == 1
        assert report["archived_trajectory_entries"] == 1
        assert report["archived_failure_classifications"] == 1
        assert report["ttl_days"] == 30
        assert lake.trace_count() == 1
        assert lake.get_trace("old_1") is None
        assert lake.get_trace("new_1") is not None
        assert lake.archived_trace_count() == 1

    def test_archive_preserves_full_record(self, lake: TraceLake) -> None:
        self._seed(lake)
        lake.purge_expired(ttl_days=1)
        archived = lake.list_archived()
        assert len(archived) == 1
        row = archived[0]
        assert row["task_id"] == "old_1"
        assert row["result_success"] == 0
        assert row["archived_at"]
        with sqlite3.connect(lake.db_path) as conn:
            conn.row_factory = sqlite3.Row
            raw = conn.execute(
                "SELECT raw_json FROM traces_archive WHERE task_id = 'old_1'"
            ).fetchone()
            traj = conn.execute(
                "SELECT agent, action FROM trajectory_entries_archive WHERE task_id = 'old_1'"
            ).fetchall()
            fc = conn.execute(
                "SELECT failure_category FROM failure_categories_archive WHERE task_id = 'old_1'"
            ).fetchone()
            live_traj = conn.execute(
                "SELECT COUNT(*) FROM trajectory_entries WHERE task_id = 'old_1'"
            ).fetchone()[0]
        assert json.loads(raw["raw_json"])["task_id"] == "old_1"
        assert len(traj) == 1 and traj[0]["agent"] == "DEBUGGER"
        assert fc["failure_category"] == "incorrect_code"
        assert live_traj == 0

    def test_second_purge_is_noop(self, lake: TraceLake) -> None:
        self._seed(lake)
        lake.purge_expired(ttl_days=30)
        report = lake.purge_expired(ttl_days=30)
        assert report["archived_traces"] == 0
        assert report["archived_trajectory_entries"] == 0
        assert lake.archived_trace_count() == 1

    def test_negative_ttl_raises(self, lake: TraceLake) -> None:
        with pytest.raises(ValueError, match="ttl_days"):
            lake.purge_expired(-1)


# ── Failure-category indexed queries ────────────────────────────────────────

class TestFailureCategoryQueries:
    def _seed(self, lake: TraceLake) -> None:
        for task_id, error in (
            ("syn_1", "SyntaxError: invalid syntax at line 3"),
            ("syn_2", "TypeError: unsupported operand"),
            ("tim_1", "timeout after 30s while running tests"),
        ):
            t = _trace(task_id)
            t.result.success = False
            t.result.error = error
            lake.store_trace(t)
        ok = _trace("ok_1")
        ok.result.success = True
        lake.store_trace(ok)

    def test_top_failures_ordering(self, lake: TraceLake) -> None:
        self._seed(lake)
        top = lake.top_failures()
        assert [r["failure_category"] for r in top] == ["incorrect_code", "timeout"]
        assert top[0]["failure_count"] == 2
        assert top[1]["failure_count"] == 1
        assert top[0]["last_seen"]
        assert "syn_1" in top[0]["sample_task_ids"]

    def test_top_failures_limit(self, lake: TraceLake) -> None:
        self._seed(lake)
        assert len(lake.top_failures(limit=1)) == 1

    def test_query_by_failure_category(self, lake: TraceLake) -> None:
        self._seed(lake)
        rows = lake.query_by_failure_category("incorrect_code")
        assert {r["task_id"] for r in rows} == {"syn_1", "syn_2"}
        assert all(r["result_success"] == 0 for r in rows)

    def test_query_by_failure_category_limit_and_empty(self, lake: TraceLake) -> None:
        self._seed(lake)
        assert len(lake.query_by_failure_category("incorrect_code", limit=1)) == 1
        assert lake.query_by_failure_category("regression") == []

    def test_classify_failure_text(self) -> None:
        assert classify_failure_text(None) == "unknown"
        assert classify_failure_text("") == "unknown"
        assert classify_failure_text("ModuleNotFoundError: no module named x") == (
            "dependency_problem"
        )
        assert classify_failure_text("random gibberish") == "unknown"

    def test_miner_style_roundtrip(self, lake: TraceLake) -> None:
        """Aggregations must be consumable by the evolution FailureMiner flow."""
        self._seed(lake)
        for priority in lake.top_failures(limit=5):
            affected = lake.query_by_failure_category(priority["failure_category"])
            assert len(affected) == priority["failure_count"]
            assert all("result_error" in r for r in affected)


# ── Schema / indexes / legacy migration ─────────────────────────────────────

class TestSchemaAndMigration:
    def test_indexes_created_idempotently(self, lake: TraceLake, tmp_path: Path) -> None:
        expected = {
            "idx_traces_content_hash",
            "idx_traces_success_ts",
            "idx_fc_cat",
            "idx_fc_task",
            "idx_arch_traces_ts",
            "idx_arch_traj_task",
        }
        with sqlite3.connect(lake.db_path) as conn:
            found = {
                r[0] for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                )
            }
        assert expected <= found
        reopened = TraceLake(lake.db_path)
        assert reopened.trace_count() == 0
        with sqlite3.connect(lake.db_path) as conn:
            version = conn.execute(
                "SELECT value FROM trace_lake_meta WHERE key='schema_version'"
            ).fetchone()
        assert int(version[0]) >= SCHEMA_VERSION

    def test_archive_columns_mirror_live_table(self, lake: TraceLake) -> None:
        with sqlite3.connect(lake.db_path) as conn:

            def cols(table: str) -> list[str]:
                return [r[1] for r in conn.execute(f"PRAGMA table_info({table})")]

        assert cols("traces_archive") == cols("traces") + ["archived_at", "ttl_days"]

    def test_legacy_db_gets_hash_backfilled(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        payload = _trace("legacy_1").to_dict()
        v1_schema = re.sub(
            r",\n\s*content_hash\s+TEXT", "", _SCHEMA_SQL
        )
        conn = sqlite3.connect(db)
        try:
            conn.executescript(v1_schema)
            conn.execute(
                "INSERT INTO traces (task_id, timestamp, prompt, task_type, raw_json)"
                " VALUES (?, ?, ?, ?, ?)",
                (
                    "legacy_1",
                    payload["timestamp"],
                    payload["prompt"],
                    payload["task_type"],
                    json.dumps(payload),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        lake = TraceLake(db)
        assert lake.trace_count() == 1

        with sqlite3.connect(db) as check:
            stored = check.execute(
                "SELECT content_hash FROM traces WHERE task_id = 'legacy_1'"
            ).fetchone()[0]
        assert stored == _trace("legacy_1").compute_content_hash()

        result = lake.store_trace_with_stats(_trace("legacy_1"))
        assert result["duplicate"] is True
        assert lake.trace_count() == 1
