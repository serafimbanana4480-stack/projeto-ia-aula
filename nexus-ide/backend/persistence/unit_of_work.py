"""Unit of Work pattern for the NEXUS IDE persistence layer.

A thin async wrapper around the synchronous SQLite connection pool exposed
by :mod:`backend.persistence.db`. The UnitOfWork holds a single connection
for the lifetime of an ``async with`` block, begins a transaction on entry,
commits on clean exit, and rolls back on exception. The connection is always
returned to the pool on exit, even when an error is raised.

The existing :func:`backend.persistence.db.get_db` and friends are not
modified — this module is purely additive.

Typical usage::

    async with get_unit_of_work() as uow:
        await uow.execute(
            "INSERT INTO projects (id, name, path) VALUES (?, ?, ?)",
            (pid, name, path),
        )
        project = await uow.fetch_one(
            "SELECT * FROM projects WHERE id = ?", (pid,)
        )
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sqlite3
from types import TracebackType
from typing import Any

from backend.persistence import db

logger = logging.getLogger(__name__)


class UnitOfWork:
    """Async context manager wrapping a single SQLite connection in a transaction.

    The transaction is opened implicitly on ``__aenter__`` and finalised on
    ``__aexit__``. The underlying connection is always returned to the pool
    when the block exits, regardless of outcome.
    """

    def __init__(self, pool: db.SQLiteConnectionPool | None = None) -> None:
        """Create a UnitOfWork.

        Args:
            pool: Optional custom connection pool. When ``None`` the global
                pool from :mod:`backend.persistence.db` is used.
        """
        self._pool: db.SQLiteConnectionPool = pool if pool is not None else db.get_connection_pool()
        self._conn: sqlite3.Connection | None = None
        self._finalised: bool = False

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    async def __aenter__(self) -> UnitOfWork:
        """Acquire a connection and start a transaction."""
        if self._conn is not None:
            raise RuntimeError("UnitOfWork is already active")
        self._conn = await asyncio.to_thread(self._pool.get_connection)
        # SQLite defaults to "autocommit" at the Python driver level; emit an
        # explicit BEGIN so subsequent statements are part of one transaction.
        try:
            await asyncio.to_thread(self._conn.execute, "BEGIN")
        except sqlite3.Error:
            # If we cannot start a transaction, release the connection and
            # re-raise so the caller sees a clean failure.
            try:
                await asyncio.to_thread(self._pool.return_connection, self._conn)
            finally:
                self._conn = None
            raise
        self._finalised = False
        logger.debug("UnitOfWork: transaction begun")
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Commit on success, rollback on exception, then return the connection."""
        if self._conn is None or self._finalised:
            return
        conn = self._conn
        try:
            if exc_type is None:
                try:
                    await asyncio.to_thread(conn.commit)
                    logger.debug("UnitOfWork: transaction committed")
                except sqlite3.Error as commit_exc:
                    logger.warning("UnitOfWork: commit failed: %s", commit_exc)
                    with contextlib.suppress(sqlite3.Error):
                        await asyncio.to_thread(conn.rollback)
            else:
                try:
                    await asyncio.to_thread(conn.rollback)
                    logger.debug("UnitOfWork: transaction rolled back due to %s", exc_type.__name__)
                except sqlite3.Error as rollback_exc:
                    logger.warning("UnitOfWork: rollback failed: %s", rollback_exc)
        finally:
            try:
                await asyncio.to_thread(self._pool.return_connection, conn)
            except Exception as release_exc:  # pragma: no cover - defensive
                logger.warning("UnitOfWork: failed to return connection to pool: %s", release_exc)
            self._conn = None
            self._finalised = True

    # ------------------------------------------------------------------
    # Transaction control
    # ------------------------------------------------------------------

    async def transaction(self) -> UnitOfWork:
        """Return ``self`` to support explicit ``async with`` chaining.

        The transaction is already opened in ``__aenter__``; this method
        exists for API symmetry and to allow call sites such as::

            async with get_unit_of_work() as uow:
                async with await uow.transaction():
                    ...
        """
        return self

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_connection(self) -> sqlite3.Connection:
        conn = self._conn
        if conn is None:
            raise RuntimeError(
                "UnitOfWork must be used as an async context manager (no active connection)"
            )
        return conn

    # ------------------------------------------------------------------
    # Statement execution
    # ------------------------------------------------------------------

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        """Execute a single statement.

        Returns the statement's ``lastrowid`` when available (e.g. INSERTs)
        and falls back to ``rowcount`` otherwise (UPDATE/DELETE). The
        transaction is committed when the surrounding ``async with`` block
        exits cleanly, not after each call.
        """
        conn = self._require_connection()
        cursor = await asyncio.to_thread(conn.execute, sql, params)
        # ``lastrowid`` is None for statements that do not produce a row id.
        if cursor.lastrowid is not None:
            return int(cursor.lastrowid)
        return int(cursor.rowcount or 0)

    async def executemany(self, sql: str, params_list: list[tuple[Any, ...]]) -> int:
        """Execute a parameterised statement once per parameter tuple.

        Returns the total ``rowcount`` across all invocations.
        """
        if not params_list:
            return 0
        conn = self._require_connection()
        cursor = await asyncio.to_thread(conn.executemany, sql, params_list)
        return int(cursor.rowcount or 0)

    async def fetch_one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        """Execute a query and return a single row as a dict (or ``None``)."""
        conn = self._require_connection()
        cursor = await asyncio.to_thread(conn.execute, sql, params)
        row = await asyncio.to_thread(cursor.fetchone)
        if row is None:
            return None
        return dict(row)

    async def fetch_all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        """Execute a query and return all rows as a list of dicts."""
        conn = self._require_connection()
        cursor = await asyncio.to_thread(conn.execute, sql, params)
        rows = await asyncio.to_thread(cursor.fetchall)
        return [dict(row) for row in rows]


def get_unit_of_work() -> UnitOfWork:
    """Factory returning a fresh :class:`UnitOfWork`.

    Intended to be used with ``async with``::

        async with get_unit_of_work() as uow:
            await uow.execute(...)

    The factory is stateless; each invocation produces a new UoW bound to
    the global connection pool (unless a custom pool is supplied via
    :class:`UnitOfWork` directly).
    """
    return UnitOfWork()
