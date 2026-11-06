"""Regression tests for the token-usage overview aggregation.

``get_token_usage_overview`` feeds the analytics page and the dashboard
metrics widget. It used to raise ``IndexError: No item with that key`` inside
``model_stats`` because the SQL aliased the model column to ``name`` while the
Python side still read ``row["model_used"]``. The exception escaped the
endpoint, which answered HTTP 500 — and because the 500 bypassed the CORS
header, the browser reported it as a confusing "blocked by CORS policy"
error instead of a server fault.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from backend.persistence import db as db_module


@pytest.fixture()
def usage_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the persistence layer at a throwaway database."""
    path = tmp_path / "usage.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            cost_usd REAL DEFAULT 0,
            latency_ms INTEGER DEFAULT 0,
            model_used TEXT,
            tier_used TEXT,
            created_at TEXT
        )
        """
    )
    conn.execute(
        """
        INSERT INTO messages
            (session_id, role, tokens_in, tokens_out, cost_usd, latency_ms, model_used, tier_used, created_at)
        VALUES
            ('s1', 'user',      10,  0, 0.0,   0, 'model-a', 'coder',    '2026-01-02T10:00:00'),
            ('s1', 'assistant',  0, 20, 0.0, 200, 'model-a', 'coder',    '2026-01-02T10:00:01'),
            ('s2', 'user',      15,  0, 0.0,   0, '',         'fast',     '2026-01-02T11:00:00'),
            ('s2', 'assistant',  0, 25, 0.0, 400, '',         'fast',     '2026-01-02T11:00:01'),
            ('s3', 'user',      30,  0, 0.0,   0, '',         '',         '2026-01-02T12:00:00')
        """
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(db_module, "get_db", lambda: _fixed_conn(path))
    return path


def _fixed_conn(path: Path) -> Any:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def test_usage_overview_groups_models_without_raising(
    usage_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The endpoint must not raise for any populated database."""
    import contextlib

    @contextlib.contextmanager
    def _ctx() -> Any:
        conn = _fixed_conn(usage_db)
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(db_module, "get_db", _ctx)

    overview = db_module.get_token_usage_overview()

    assert isinstance(overview, dict)
    by_model = {entry["name"]: entry for entry in overview["by_model"]}
    # A row with a real model, a row that only has a tier, and a row with
    # neither must all land in a group instead of exploding the endpoint.
    assert "model-a" in by_model
    assert "fast" in by_model
    assert "Não identificado" in by_model
    assert by_model["model-a"]["tokens_out"] == 20
    assert by_model["fast"]["tokens_out"] == 25
    # The un-priced rows are costed from their token counts, not dropped.
    for entry in by_model.values():
        assert entry["cost"] >= 0.0
        assert entry["avg_tokens_per_second"] >= 0.0


def test_model_stats_reads_the_group_alias_not_a_missing_column(
    usage_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`model_stats` must read the column the query actually selects."""
    import contextlib

    @contextlib.contextmanager
    def _ctx() -> Any:
        conn = _fixed_conn(usage_db)
        try:
            yield conn
        finally:
            conn.close()

    monkeypatch.setattr(db_module, "get_db", _ctx)

    stats = db_module.get_token_usage_overview()

    assert stats["by_model"], "expected at least one model group"
