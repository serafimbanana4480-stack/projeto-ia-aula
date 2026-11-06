"""The SQLite lock retry of ``get_db`` must work — and must not leak the pool.

Regression background
---------------------
``get_db`` used to catch ``sqlite3.OperationalError`` inside a generator based
context manager and tried to retry by yielding a second time. ``contextlib``
refuses that: it raises ``RuntimeError("generator didn't stop after
throw()")``. So:

* the caller never saw the real ``sqlite3.OperationalError("database is
  locked")`` — every ``except sqlite3.OperationalError`` handler in the
  codebase was dead code;
* the connection was closed and never returned to the pool, and
  ``_created_count`` was never decremented, so the pool leaked until it died
  with ``TimeoutError("Connection pool exhausted after 30s")`` while its
  queue was empty.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from backend.persistence import db


class _LockingConnection:
    """A connection whose ``LOCK_TEST`` statements fail with a lock error.

    Every other attribute is delegated to the wrapped connection, so the
    object behaves like the connection it wraps.
    """

    def __init__(self, connection: sqlite3.Connection, *, fail_forever: bool = True) -> None:
        self._connection = connection
        self._fail_forever = fail_forever
        self.attempts = 0

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        if "LOCK_TEST" in sql:
            self.attempts += 1
            if self._fail_forever or self.attempts == 1:
                raise sqlite3.OperationalError("database is locked")
        return self._connection.execute(sql, parameters)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._connection, name)


class _StubPool:
    """A pool stub that hands out one prepared connection."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.returned: list[sqlite3.Connection] = []

    def get_connection(self) -> sqlite3.Connection:
        return self.connection

    def return_connection(self, connection: sqlite3.Connection) -> None:
        self.returned.append(connection)


def test_get_db_propagates_the_real_locked_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The caller must see ``sqlite3.OperationalError``, not a RuntimeError."""
    raw = sqlite3.connect(":memory:")
    locked = _LockingConnection(raw)
    pool = _StubPool(locked)  # type: ignore[arg-type]
    monkeypatch.setattr(db, "get_connection_pool", lambda: pool)  # type: ignore[arg-type]

    with (
        pytest.raises(sqlite3.OperationalError, match="database is locked"),
        db.get_db() as conn,
    ):
        conn.execute("SELECT 1 /* LOCK_TEST */")

    # The connection is released even though the statement failed.
    assert pool.returned == [locked]
    raw.close()


def test_get_db_retries_after_a_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """A statement that hits a lock is re-run instead of failing the caller."""
    raw = sqlite3.connect(":memory:")
    # Only the first attempt fails: the second one goes through.
    flaky = _LockingConnection(raw, fail_forever=False)
    pool = _StubPool(flaky)  # type: ignore[arg-type]
    monkeypatch.setattr(db, "get_connection_pool", lambda: pool)  # type: ignore[arg-type]

    with db.get_db() as conn:
        conn.execute("SELECT 1 /* LOCK_TEST */")

    assert flaky.attempts == 2, "the statement must be re-run after a lock"
    assert pool.returned == [flaky]
    raw.close()


def test_pool_count_is_not_leaked_by_a_locked_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing statement must not cost the pool a connection."""
    db.close_pool()
    pool = db.get_connection_pool()
    real_create = db.SQLiteConnectionPool._create_connection

    def _create_locked(self: db.SQLiteConnectionPool) -> Any:
        return _LockingConnection(real_create(self))

    monkeypatch.setattr(db.SQLiteConnectionPool, "_create_connection", _create_locked)

    with (
        pytest.raises(sqlite3.OperationalError, match="database is locked"),
        db.get_db() as conn,
    ):
        conn.execute("SELECT 1 /* LOCK_TEST */")

    # The connection went back to the pool instead of being closed and lost.
    assert pool._created_count == 1
    assert pool._pool.qsize() == 1

    # A second user reuses it: no new connection is created.
    with db.get_db() as conn:
        conn.execute("SELECT 1")

    assert pool._created_count == 1
    assert pool._pool.qsize() == 1
    db.close_pool()
