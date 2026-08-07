from __future__ import annotations

import sqlite3
from pathlib import Path

from backend.persistence.db import SQLiteConnectionPool


def test_pool_uses_short_lived_overflow_connections_when_saturated(tmp_path: Path) -> None:
    db_path = tmp_path / "pool.db"
    pool = SQLiteConnectionPool(db_path, max_size=1, timeout=0.05, max_overflow=1)

    pooled = pool.get_connection()
    overflow = pool.get_connection()

    assert isinstance(pooled, sqlite3.Connection)
    assert isinstance(overflow, sqlite3.Connection)
    assert pool._created_count == 1
    assert len(pool._overflow_connections) == 1

    pool.return_connection(overflow)
    pool.return_connection(pooled)

    assert len(pool._overflow_connections) == 0
    assert pool._pool.qsize() == 1


def test_pool_replaces_dead_connection_without_losing_capacity(tmp_path: Path) -> None:
    pool = SQLiteConnectionPool(tmp_path / "pool.db", max_size=1, timeout=0.05)
    conn = pool.get_connection()
    conn.close()

    replacement = pool.get_connection()
    try:
        assert pool._created_count == 1
        replacement.execute("SELECT 1")
    finally:
        pool.return_connection(replacement)
