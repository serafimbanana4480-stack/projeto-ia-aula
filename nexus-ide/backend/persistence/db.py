"""SQLite database layer for NEXUS IDE.

Connection pooling with WAL mode. Thread-safe connection management.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from queue import Empty, Queue
from typing import Any

logger = logging.getLogger(__name__)

# Import cache for performance optimization
try:
    from backend.cache import (
        sync_cache_result,
        sync_cache_invalidate_pattern,
        SHORT_TTL,
    )
except ImportError:
    # Fallback for when cache is not available
    SHORT_TTL = 300  # Default TTL in seconds

    def sync_cache_result(key_prefix: str, ttl: int = 300, serialize: bool = True):
        def decorator(func):
            return func
        return decorator

    def sync_cache_invalidate_pattern(pattern: str):
        def decorator(func):
            return func
        return decorator

    logger.warning("Redis cache not available, running without caching")

# Query performance monitoring
SLOW_QUERY_THRESHOLD_MS = 100  # Log queries slower than 100ms


def monitor_query_performance(func: Callable) -> Callable:
    """Decorator to monitor and log slow database queries."""

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start_time = time.perf_counter()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            elapsed_ms = (time.perf_counter() - start_time) * 1000
            if elapsed_ms > SLOW_QUERY_THRESHOLD_MS:
                logger.warning(
                    "Slow query detected: %s took %.2fms",
                    func.__name__,
                    elapsed_ms,
                )
            elif logger.isEnabledFor(logging.DEBUG):
                logger.debug(
                    "Query %s took %.2fms",
                    func.__name__,
                    elapsed_ms,
                )

    return wrapper

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "nexus.db"
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas.sql"

# Connection pool settings
MAX_POOL_SIZE = 10
POOL_TIMEOUT = 30  # seconds


class SQLiteConnectionPool:
    """A simple thread-safe connection pool for SQLite."""

    def __init__(self, db_path: Path, max_size: int = MAX_POOL_SIZE, timeout: int = POOL_TIMEOUT):
        """Initialize the connection pool.

        Args:
            db_path: Path to the SQLite database file.
            max_size: Maximum number of connections in the pool.
            timeout: Timeout in seconds when waiting for a connection.
        """
        self.db_path = db_path
        self.max_size = max_size
        self.timeout = timeout
        self._pool: Queue[sqlite3.Connection] = Queue(maxsize=max_size)
        self._lock = threading.Lock()
        self._created_count = 0

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with proper settings."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")  # 5 second timeout for locks
        return conn

    def get_connection(self) -> sqlite3.Connection:
        """Get a connection from the pool.

        Returns:
            A SQLite connection object.

        Raises:
            TimeoutError: If no connection is available within the timeout period.
        """
        # Fast-path: try to grab an existing connection without blocking.
        # This avoids a 30-second wait when the pool is empty (common in
        # tests because init_db() creates standalone connections).
        try:
            conn = self._pool.get(block=False)
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                logger.warning("Dead connection found, creating new one")
                conn.close()
                with self._lock:
                    self._created_count -= 1
                return self._create_connection()
        except Empty:
            pass

        # Pool is empty — create a new connection immediately if under limit.
        with self._lock:
            if self._created_count < self.max_size:
                self._created_count += 1
                logger.debug("Creating new connection (total: %d)", self._created_count)
                return self._create_connection()

        # Pool is at max capacity; block and wait for one to be returned.
        try:
            conn = self._pool.get(block=True, timeout=self.timeout)
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.Error:
                logger.warning("Dead connection found, creating new one")
                conn.close()
                with self._lock:
                    self._created_count -= 1
                return self._create_connection()
        except Empty:
            raise TimeoutError(f"Connection pool exhausted after {self.timeout}s")

    def return_connection(self, conn: sqlite3.Connection) -> None:
        """Return a connection to the pool.

        Args:
            conn: The connection to return.
        """
        try:
            # Rollback any uncommitted changes
            try:
                conn.rollback()
            except sqlite3.Error:
                pass
            # Try to put the connection back in the pool
            self._pool.put_nowait(conn)
        except Exception:
            # Pool is full, close the connection
            try:
                conn.close()
                with self._lock:
                    self._created_count -= 1
                    logger.debug("Closing excess connection (total: %d)", self._created_count)
            except sqlite3.Error:
                pass

    def close_all(self) -> None:
        """Close all connections in the pool."""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Empty:
                break
            except sqlite3.Error:
                pass
        with self._lock:
            self._created_count = 0
        logger.info("All connections closed")


# Global connection pool instance
_connection_pool: SQLiteConnectionPool | None = None
_pool_lock = threading.Lock()


def get_connection_pool() -> SQLiteConnectionPool:
    """Get the global connection pool instance.

    Returns:
        The SQLiteConnectionPool instance.
    """
    global _connection_pool
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                _connection_pool = SQLiteConnectionPool(DB_PATH)
                logger.info("Connection pool initialized")
    return _connection_pool


def _now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _new_id() -> str:
    return uuid.uuid4().hex[:16]


def init_db(run_migrations: bool = False) -> None:
    """Initialize the database with migration support.

    Creates directory and applies schema if needed.
    Uses Alembic for schema management if available.

    Args:
        run_migrations: If True, always run alembic migrations on existing DB.
            Defaults to False for fast startup — migrations are skipped unless
            the DB is fresh or this flag is set.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Check if this is a fresh database (no alembic_version table)
    is_fresh_db = not DB_PATH.exists()

    if is_fresh_db:
        # Fresh database: apply the initial schema from SQL file
        logger.info("Fresh database, applying initial schema")
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        with sqlite3.connect(str(DB_PATH)) as conn:
            conn.executescript(schema)
            conn.commit()
        logger.info("DB initialized at %s", DB_PATH)

        # Try to stamp with alembic if available
        _stamp_alembic()
    elif run_migrations:
        _run_alembic_migrations()
    else:
        # Existing database: fast-path skip — only check if schema is present
        try:
            with sqlite3.connect(str(DB_PATH)) as conn:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='alembic_version'"
                ).fetchone()
                if row is None:
                    logger.debug("No alembic_version table found, skipping migrations")
                else:
                    logger.debug("Alembic tracked DB found, migrations skipped (use run_migrations=True to force)")
        except Exception:
            logger.debug("Alembic check failed, continuing", exc_info=True)


def _stamp_alembic() -> None:
    """Stamp a fresh database with the current alembic head."""
    try:
        from alembic.config import Config
        from alembic import command

        alembic_dir = Path(__file__).resolve().parent.parent / "migrations"
        alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"

        if alembic_dir.exists() and alembic_ini.exists():
            logger.info("Stamping database with initial migration")
            config = Config(str(alembic_ini))
            config.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")
            command.stamp(config, "head")
            logger.info("Database stamped successfully")
    except ImportError:
        logger.warning("Alembic not available, skipping migration stamp")
    except Exception as e:
        logger.warning("Failed to stamp database with Alembic: %s", e)


def _run_alembic_migrations() -> None:
    """Run alembic migrations on an existing database."""
    try:
        from alembic.config import Config
        from alembic import command

        alembic_dir = Path(__file__).resolve().parent.parent / "migrations"
        alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"

        if alembic_dir.exists() and alembic_ini.exists():
            logger.info("Running database migrations")
            config = Config(str(alembic_ini))
            config.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")
            command.upgrade(config, "head")
            logger.info("Migrations completed successfully")
    except ImportError:
        logger.warning("Alembic not available, skipping migrations")
    except Exception as e:
        logger.warning("Failed to run migrations: %s", e)


def close_pool() -> None:
    """Close all connections in the connection pool.

    Call this when shutting down the application.
    """
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.close_all()
        _connection_pool = None
        logger.info("Connection pool closed")


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Context manager yielding a sqlite connection from the pool.

    Uses the connection pool for better performance instead of creating
    a new connection every time.
    """
    pool = get_connection_pool()
    conn = pool.get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.return_connection(conn)


# ───── PROJECTS ─────────────────────────────────────────────────────────


@sync_cache_invalidate_pattern("project:*")
def create_project(
    name: str,
    path: str,
    description: str = "",
    mode: str = "auto",
    preferred_model: str | None = None,
    trust: bool = False,
) -> dict:
    pid = _new_id()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO projects (id, name, path, description, mode, preferred_model, trust)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (pid, name, path, description, mode, preferred_model, 1 if trust else 0),
        )
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    return dict(row) if row else None


@sync_cache_result("project:", ttl=SHORT_TTL)
def get_project(project_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return dict(row) if row else None


@monitor_query_performance
def list_projects() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [dict(r) for r in rows]


def count_active_sessions() -> int:
    with get_db() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()
        return int(row["count"] if row else 0)


def get_project_by_path(project_path: str) -> dict | None:
    """Get project by its path. Used for trust verification."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM projects WHERE path = ?",
            (project_path,),
        ).fetchone()
        return dict(row) if row else None


@sync_cache_invalidate_pattern("project:*")
def update_project(project_id: str, **fields: Any) -> dict | None:
    if not fields:
        return get_project(project_id)
    fields["updated_at"] = _now_iso()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_db() as conn:
        conn.execute(f"UPDATE projects SET {cols} WHERE id = ?", (*fields.values(), project_id))
    return get_project(project_id)


@sync_cache_invalidate_pattern("project:*")
def delete_project(project_id: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))


# ───── SESSIONS ─────────────────────────────────────────────────────────


def create_session(
    project_id: str | None = None,
    title: str = "Nova sessão",
    mode: str = "auto",
    session_id: str | None = None,
) -> dict:
    sid = session_id or _new_id()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, project_id, title, mode) VALUES (?, ?, ?, ?)",
            (sid, project_id, title, mode),
        )
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    return dict(row) if row else None


@sync_cache_result("session:", ttl=SHORT_TTL)
def get_session(session_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


@monitor_query_performance
def list_sessions(project_id: str | None = None, limit: int = 50) -> list[dict]:
    with get_db() as conn:
        if project_id:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE project_id = ? ORDER BY last_active_at DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY last_active_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def touch_session(session_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET last_active_at = ? WHERE id = ?", (_now_iso(), session_id)
        )


# ───── MESSAGES ─────────────────────────────────────────────────────────


def add_message(
    session_id: str,
    role: str,
    content: str,
    *,
    tier_used: str | None = None,
    model_used: str | None = None,
    tools_used: list | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    latency_ms: int = 0,
) -> dict:
    mid = _new_id()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO messages
               (id, session_id, role, content, tier_used, model_used, tools_used_json,
                tokens_in, tokens_out, latency_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                mid,
                session_id,
                role,
                content,
                tier_used,
                model_used,
                json.dumps(tools_used) if tools_used else None,
                tokens_in,
                tokens_out,
                latency_ms,
            ),
        )
        conn.execute(
            "UPDATE sessions SET last_active_at = ? WHERE id = ?",
            (_now_iso(), session_id),
        )
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
    return dict(row) if row else {"id": mid, "session_id": session_id, "role": role, "content": content}


@monitor_query_performance
def get_messages(session_id: str, limit: int = 200) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY created_at ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


@monitor_query_performance
def get_message_statistics() -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_messages,
                COUNT(DISTINCT session_id) AS sessions_with_messages,
                SUM(CASE WHEN role = 'user' THEN 1 ELSE 0 END) AS user_messages,
                SUM(CASE WHEN role = 'assistant' THEN 1 ELSE 0 END) AS assistant_messages,
                COALESCE(SUM(tokens_in), 0) AS tokens_in_total,
                COALESCE(SUM(tokens_out), 0) AS tokens_out_total,
                COALESCE(AVG(NULLIF(latency_ms, 0)), 0) AS avg_latency_ms,
                COALESCE(MAX(created_at), '') AS last_message_at
            FROM messages
            """
        ).fetchone()
        if not row:
            return {
                "total_messages": 0,
                "sessions_with_messages": 0,
                "user_messages": 0,
                "assistant_messages": 0,
                "tokens_in_total": 0,
                "tokens_out_total": 0,
                "avg_latency_ms": 0.0,
                "last_message_at": "",
            }
        return dict(row)


def count_pending_changes(session_id: str | None = None) -> int:
    with get_db() as conn:
        if session_id:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM proposed_changes WHERE applied = 0 AND session_id = ?",
                (session_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM proposed_changes WHERE applied = 0",
            ).fetchone()
        return int(row["count"] if row else 0)


# ───── TOOL EXECUTIONS ──────────────────────────────────────────────────


def log_tool_execution(
    session_id: str | None,
    tool_name: str,
    args: dict,
    result: Any,
    success: bool = True,
    error: str | None = None,
    duration_ms: int = 0,
) -> str:
    eid = _new_id()
    with get_db() as conn:
        # Ensure session exists to satisfy FK constraint
        if session_id:
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO sessions (id, title, mode) VALUES (?, ?, ?)",
                    (session_id, session_id, "auto"),
                )
            except Exception:
                logger.debug("Failed to ensure session for tool execution", exc_info=True)
        conn.execute(
            """INSERT INTO tool_executions
               (id, session_id, tool_name, args_json, result_json, success, error, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eid,
                session_id,
                tool_name,
                json.dumps(args, default=str),
                json.dumps(result, default=str) if result is not None else None,
                1 if success else 0,
                error,
                duration_ms,
            ),
        )
    return eid


# ───── ROUTING DECISIONS ────────────────────────────────────────────────


def log_routing_decision(
    session_id: str | None,
    user_input: str,
    tier: str | None = None,
    tier_chosen: str | None = None,
    reason: str = "",
    confidence: float = 0.0,
    word_count: int = 0,
    decision_ms: int = 0,
) -> str:
    rid = _new_id()
    resolved_tier = tier_chosen or tier or "fast"
    with get_db() as conn:
        conn.execute(
            """INSERT INTO routing_decisions
               (id, session_id, user_input, tier_chosen, reason, confidence,
                word_count, decision_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                rid,
                session_id,
                user_input[:500],
                resolved_tier,
                reason,
                confidence,
                word_count,
                decision_ms,
            ),
        )
    return rid


def recent_routing_decisions(limit: int = 50) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM routing_decisions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ───── PROPOSED CHANGES ─────────────────────────────────────────────────


def propose_change(
    session_id: str,
    project_id: str | None,
    file_path: str,
    operation: str,
    diff: str = "",
    new_content: str = "",
) -> dict:
    cid = _new_id()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO proposed_changes
               (id, session_id, project_id, file_path, operation, diff, new_content)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (cid, session_id, project_id, file_path, operation, diff, new_content),
        )
    return get_change(cid)


def get_change(change_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM proposed_changes WHERE id = ?", (change_id,)).fetchone()
        return dict(row) if row else None


def get_change_statistics() -> dict[str, Any]:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total_changes,
                COUNT(DISTINCT file_path) AS files_modified,
                SUM(CASE
                        WHEN new_content IS NULL OR new_content = '' THEN 0
                        ELSE 1 + LENGTH(new_content) - LENGTH(REPLACE(new_content, char(10), ''))
                    END) AS lines_written
            FROM proposed_changes
            """
        ).fetchone()
        if not row:
            return {
                "total_changes": 0,
                "files_modified": 0,
                "lines_written": 0,
            }
        return dict(row)


def list_pending_changes(session_id: str | None = None) -> list[dict]:
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                "SELECT * FROM proposed_changes WHERE session_id = ? AND applied = 0 ORDER BY created_at DESC",
                (session_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM proposed_changes WHERE applied = 0 ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def mark_change_applied(change_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE proposed_changes SET applied = 1, applied_at = ? WHERE id = ?",
            (_now_iso(), change_id),
        )


# ───── USERS (AUTHENTICATION) ──────────────────────────────────────────────


def create_user(
    username: str, email: str, password_hash: str, full_name: str = ""
) -> dict:
    """Create a new user in the database."""
    uid = _new_id()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO users (id, username, email, password_hash, full_name)
               VALUES (?, ?, ?, ?, ?)""",
            (uid, username, email, password_hash, full_name),
        )
    return get_user(uid)


def get_user(user_id: str) -> dict | None:
    """Get a user by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if row:
            user_dict = dict(row)
            # Don't return password_hash
            user_dict.pop("password_hash", None)
            return user_dict
        return None


def get_user_by_email(email: str) -> dict | None:
    """Get a user by email address."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            user_dict = dict(row)
            # Don't return password_hash
            user_dict.pop("password_hash", None)
            return user_dict
        return None


def get_user_with_password(email: str) -> dict | None:
    """Get a user by email address including password hash (for authentication)."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        return dict(row) if row else None


def verify_user_password(email: str, password_hash: str) -> dict | None:
    """Verify user password by comparing hashes."""
    user = get_user_with_password(email)
    if user and user["password_hash"] == password_hash:
        # Remove password hash before returning
        user_dict = dict(user)
        user_dict.pop("password_hash", None)
        return user_dict
    return None


def update_user(user_id: str, **fields: Any) -> dict | None:
    """Update user fields."""
    if not fields:
        return get_user(user_id)
    fields["updated_at"] = _now_iso()
    # Don't allow updating password_hash through this method
    fields.pop("password_hash", None)
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_db() as conn:
        conn.execute(f"UPDATE users SET {cols} WHERE id = ?", (*fields.values(), user_id))
    return get_user(user_id)


def update_user_password(user_id: str, password_hash: str) -> None:
    """Update user password hash."""
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (password_hash, _now_iso(), user_id),
        )


# ───── RBAC (ROLES & PERMISSIONS) ───────────────────────────────────────────


def assign_role_to_user(user_id: str, role_id: str) -> None:
    """Assign a role to a user."""
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO user_roles (id, user_id, role_id) VALUES (?, ?, ?)",
            (_new_id(), user_id, role_id),
        )


def remove_role_from_user(user_id: str, role_id: str) -> None:
    """Remove a role from a user."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM user_roles WHERE user_id = ? AND role_id = ?",
            (user_id, role_id),
        )


def get_user_roles(user_id: str) -> list[dict]:
    """Get all roles assigned to a user."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT r.* FROM roles r
               INNER JOIN user_roles ur ON r.id = ur.role_id
               WHERE ur.user_id = ?""",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_role_permissions(role_id: str) -> list[dict]:
    """Get all permissions for a role."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT p.* FROM permissions p
               INNER JOIN role_permissions rp ON p.id = rp.permission_id
               WHERE rp.role_id = ?""",
            (role_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_user_permissions(user_id: str) -> list[dict]:
    """Get all permissions for a user (through their roles)."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT DISTINCT p.* FROM permissions p
               INNER JOIN role_permissions rp ON p.id = rp.permission_id
               INNER JOIN user_roles ur ON rp.role_id = ur.role_id
               WHERE ur.user_id = ?""",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def user_has_permission(user_id: str, resource: str, action: str) -> bool:
    """Check if a user has a specific permission."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT 1 FROM permissions p
               INNER JOIN role_permissions rp ON p.id = rp.permission_id
               INNER JOIN user_roles ur ON rp.role_id = ur.role_id
               WHERE ur.user_id = ? AND p.resource = ? AND p.action = ?
               LIMIT 1""",
            (user_id, resource, action),
        ).fetchone()
        return row is not None


def create_role(name: str, description: str = "") -> dict:
    """Create a new role."""
    rid = f"role_{name.lower()}"
    with get_db() as conn:
        conn.execute(
            "INSERT INTO roles (id, name, description) VALUES (?, ?, ?)",
            (rid, name, description),
        )
    return {"id": rid, "name": name, "description": description}


def create_permission(name: str, resource: str, action: str, description: str = "") -> dict:
    """Create a new permission."""
    pid = f"perm_{resource}_{action}"
    with get_db() as conn:
        conn.execute(
            "INSERT INTO permissions (id, name, description, resource, action) VALUES (?, ?, ?, ?, ?)",
            (pid, name, description, resource, action),
        )
    return {"id": pid, "name": name, "description": description, "resource": resource, "action": action}


def assign_permission_to_role(role_id: str, permission_id: str) -> None:
    """Assign a permission to a role."""
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO role_permissions (id, role_id, permission_id) VALUES (?, ?, ?)",
            (_new_id(), role_id, permission_id),
        )


# ───── EMAIL ACCOUNTS ───────────────────────────────────────────────────


def create_email_account(
    user_id: str,
    label: str,
    host: str,
    port: int,
    username: str,
    password_encrypted: str,
    use_ssl: bool = True,
    active: bool = True,
) -> dict:
    """Create a new email account configuration."""
    eid = _new_id()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO email_accounts
               (id, user_id, label, host, port, username, password_encrypted, use_ssl, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eid,
                user_id,
                label,
                host,
                port,
                username,
                password_encrypted,
                1 if use_ssl else 0,
                1 if active else 0,
            ),
        )
    return get_email_account(eid)


def get_email_account(account_id: str) -> dict | None:
    """Get an email account by ID (excludes password)."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM email_accounts WHERE id = ?", (account_id,)).fetchone()
        if not row:
            return None
        account = dict(row)
        account.pop("password_encrypted", None)
        return account


def get_email_account_with_password(account_id: str) -> dict | None:
    """Get an email account by ID including encrypted password."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM email_accounts WHERE id = ?", (account_id,)).fetchone()
        return dict(row) if row else None


def list_email_accounts(user_id: str | None = None, active_only: bool = True) -> list[dict]:
    """List email accounts, optionally filtering by user and active status."""
    with get_db() as conn:
        query = "SELECT * FROM email_accounts WHERE 1=1"
        params: list[Any] = []
        if user_id:
            query += " AND user_id = ?"
            params.append(user_id)
        if active_only:
            query += " AND active = 1"
        query += " ORDER BY created_at DESC"
        rows = conn.execute(query, params).fetchall()
        result = []
        for row in rows:
            account = dict(row)
            account.pop("password_encrypted", None)
            result.append(account)
        return result


def update_email_account(account_id: str, **fields: Any) -> dict | None:
    """Update email account fields."""
    if not fields:
        return get_email_account(account_id)
    fields["updated_at"] = _now_iso()
    fields.pop("id", None)
    cols = ", ".join(f"{k} = ?" for k in fields)
    with get_db() as conn:
        conn.execute(f"UPDATE email_accounts SET {cols} WHERE id = ?", (*fields.values(), account_id))
    return get_email_account(account_id)


def delete_email_account(account_id: str) -> None:
    """Delete an email account."""
    with get_db() as conn:
        conn.execute("DELETE FROM email_accounts WHERE id = ?", (account_id,))
