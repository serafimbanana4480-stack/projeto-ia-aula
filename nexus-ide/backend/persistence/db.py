"""SQLite database layer for NEXUS IDE.

Connection pooling with WAL mode. Thread-safe connection management.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from functools import wraps
from pathlib import Path
from queue import Empty, Queue
from typing import Any, TypeVar, cast

logger = logging.getLogger(__name__)

#: Type variable for the lock-retry helpers (the retried call returns
#: whatever the underlying statement returns).
_T = TypeVar("_T")

# Import cache for performance optimization
from backend.redis_cache import (  # noqa: E402
    SHORT_TTL,
    sync_cache_invalidate_pattern,
    sync_cache_result,
)

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

    return wrapper


DB_PATH = Path(
    os.environ.get("NEXUS_DB_PATH")
    or Path(__file__).resolve().parent.parent.parent / "data" / "nexus.db"
).expanduser().resolve()
SCHEMA_PATH = Path(__file__).resolve().parent / "schemas.sql"

# Connection pool settings
MAX_POOL_SIZE = 10
POOL_TIMEOUT = 30  # seconds
MAX_POOL_OVERFLOW = 20


class SQLiteConnectionPool:
    """A simple thread-safe connection pool for SQLite."""

    def __init__(
        self,
        db_path: Path,
        max_size: int = MAX_POOL_SIZE,
        timeout: int = POOL_TIMEOUT,
        max_overflow: int = MAX_POOL_OVERFLOW,
    ):
        """Initialize the connection pool.

        Args:
            db_path: Path to the SQLite database file.
            max_size: Maximum number of connections in the pool.
            timeout: Timeout in seconds when waiting for a connection.
        """
        self.db_path = db_path
        self.max_size = max_size
        self.timeout = timeout
        self.max_overflow = max(0, max_overflow)
        self._pool: Queue[sqlite3.Connection] = Queue(maxsize=max_size)
        self._lock = threading.Lock()
        self._created_count = 0
        self._overflow_connections: set[int] = set()

    def _create_connection(self) -> sqlite3.Connection:
        """Create a new database connection with proper settings."""
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        # FULL keeps WAL-backed session/checkpoint writes durable across a
        # process crash or power loss. The small fsync cost is preferable for
        # long-running agent work where losing the last checkpoint is costly.
        conn.execute("PRAGMA synchronous = FULL")
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
                    self._created_count += 1
                return self._create_connection()
        except Empty:
            logger.debug("Connection pool empty, will create new connection if under limit")

        # Pool is empty — create a new connection immediately if under limit.
        with self._lock:
            if self._created_count < self.max_size:
                self._created_count += 1
                logger.debug("Creating new connection (total: %d)", self._created_count)
                return self._create_connection()

            # Background monitoring and request handling share this pool. Do
            # not block the caller while all pooled connections are briefly in
            # use: an async request can hold the event loop while waiting and
            # prevent the task that would release a connection from running.
            # Overflow connections are short-lived and are closed on return.
            if len(self._overflow_connections) < self.max_overflow:
                conn = self._create_connection()
                self._overflow_connections.add(id(conn))
                logger.warning(
                    "Connection pool at capacity; using overflow connection (%d/%d)",
                    len(self._overflow_connections),
                    self.max_overflow,
                )
                return conn

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
                    self._created_count += 1
                return self._create_connection()
        except Empty:
            raise TimeoutError(f"Connection pool exhausted after {self.timeout}s") from None

    def return_connection(self, conn: sqlite3.Connection) -> None:
        """Return a connection to the pool.

        Args:
            conn: The connection to return.
        """
        with self._lock:
            is_overflow = id(conn) in self._overflow_connections
            if is_overflow:
                self._overflow_connections.remove(id(conn))

        if is_overflow:
            try:
                conn.rollback()
            except sqlite3.Error as exc:
                logger.warning("Rollback failed when closing overflow connection: %s", exc)
            try:
                conn.close()
            except sqlite3.Error as exc:
                logger.warning("Failed to close overflow connection: %s", exc)
            return

        try:
            # Rollback any uncommitted changes
            try:
                conn.rollback()
            except sqlite3.Error as exc:
                logger.warning("Rollback failed when returning connection: %s", exc)
            # Try to put the connection back in the pool
            self._pool.put_nowait(conn)
        except Exception:
            # Pool is full, close the connection
            try:
                conn.close()
                with self._lock:
                    self._created_count -= 1
                    logger.debug("Closing excess connection (total: %d)", self._created_count)
            except sqlite3.Error as exc:
                logger.warning("Failed to close excess connection: %s", exc)

    def close_all(self) -> None:
        """Close all connections in the pool."""
        while not self._pool.empty():
            try:
                conn = self._pool.get_nowait()
                conn.close()
            except Empty:
                break
            except sqlite3.Error as exc:
                logger.warning("Failed to close pooled connection: %s", exc)
        with self._lock:
            self._created_count = 0
            self._overflow_connections.clear()
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


# Git auto-commit schema snippet for migration
_GIT_COMMIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS git_commits (
    id              TEXT PRIMARY KEY,
    session_id      TEXT,
    project_id      TEXT,
    file_path       TEXT NOT NULL,
    commit_message  TEXT NOT NULL,
    commit_hash     TEXT,
    commit_type     TEXT,
    scope           TEXT,
    strategy        TEXT NOT NULL DEFAULT 'always',
    status          TEXT NOT NULL DEFAULT 'committed'
        CHECK (status IN ('committed', 'pending_review', 'failed', 'rejected')),
    diff_preview    TEXT,
    error           TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX IF NOT EXISTS idx_git_commits_session ON git_commits(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_git_commits_project ON git_commits(project_id);
CREATE INDEX IF NOT EXISTS idx_git_commits_status ON git_commits(status);
CREATE INDEX IF NOT EXISTS idx_git_commits_hash ON git_commits(commit_hash);
CREATE INDEX IF NOT EXISTS idx_git_commits_created ON git_commits(created_at DESC);
"""


def _ensure_git_commits_table() -> None:
    """Ensure the git_commits table exists in the database (idempotent migration)."""
    try:
        with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
            conn.executescript(_GIT_COMMIT_SCHEMA)
            conn.commit()
    except Exception as e:
        logger.warning("Failed to ensure git_commits table: %s", e)


def _ensure_message_cost_column() -> None:
    """Repair databases created from older/stamped schemas."""
    try:
        with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info(messages)").fetchall()
            }
            if columns and "cost_usd" not in columns:
                conn.execute(
                    "ALTER TABLE messages ADD COLUMN cost_usd REAL DEFAULT 0.0"
                )
                conn.commit()
                logger.info("Added missing messages.cost_usd compatibility column")
    except Exception as exc:
        logger.exception("Failed to ensure messages.cost_usd column")
        raise RuntimeError("Messages schema readiness failed") from exc


def _ensure_message_run_link_column() -> None:
    """Add the nullable run link before schemas.sql creates its index."""
    try:
        with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
            columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(messages)").fetchall()
            }
            if columns and "run_id" not in columns:
                conn.execute("ALTER TABLE messages ADD COLUMN run_id TEXT")
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to ensure messages.run_id column")
        raise RuntimeError("Messages run-link schema readiness failed") from exc


def _ensure_current_schema() -> None:
    """Create any tables added since an existing database was first made."""
    try:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
            whiteboard_columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(whiteboard_entries)").fetchall()
            }
            if whiteboard_columns and "user_id" not in whiteboard_columns:
                # The previous whiteboard schema was global. Keep old rows
                # ownerless; authenticated reads will only return scoped rows.
                conn.execute(
                    "ALTER TABLE whiteboard_entries ADD COLUMN user_id TEXT NOT NULL DEFAULT ''"
                )
            conn.executescript(schema)
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to ensure current database schema")
        raise RuntimeError("Database schema readiness failed") from exc


_SESSION_COMPAT_COLUMNS: tuple[tuple[str, str], ...] = (
    ("user_id", "TEXT"),
    ("project_id", "TEXT"),
    ("title", "TEXT"),
    ("mode", "TEXT"),
    ("started_at", "TEXT"),
    ("last_active_at", "TEXT"),
    ("context_json", "TEXT"),
)


def _ensure_session_compatibility_schema() -> None:
    """Repair legacy sessions before schemas.sql creates dependent indexes."""
    try:
        with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
            columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(sessions)")}
            if columns:
                for name, column_type in _SESSION_COMPAT_COLUMNS:
                    if name not in columns:
                        conn.execute(f"ALTER TABLE sessions ADD COLUMN {name} {column_type}")
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to ensure sessions compatibility schema")
        raise RuntimeError("Sessions schema readiness failed") from exc


_EXECUTION_ENVELOPE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("goal_id", "TEXT"),
    ("mission_id", "TEXT"),
    ("correlation_id", "TEXT"),
    ("mode", "TEXT"),
    ("execution_state", "TEXT"),
    ("provider", "TEXT"),
    ("model", "TEXT"),
    ("error_category", "TEXT"),
    ("retry_after", "INTEGER"),
    ("evidence_json", "TEXT"),
)


def _ensure_execution_envelope_schema() -> None:
    """Repair untracked/partially stamped databases before run persistence."""
    try:
        with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
            columns = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(session_runs)").fetchall()
            }
            if columns:
                for name, column_type in _EXECUTION_ENVELOPE_COLUMNS:
                    if name not in columns:
                        conn.execute(
                            f"ALTER TABLE session_runs ADD COLUMN {name} {column_type}"
                        )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_session_runs_session_updated "
                    "ON session_runs(session_id, updated_at)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_session_runs_correlation_updated "
                    "ON session_runs(correlation_id, updated_at)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_session_runs_mission_updated "
                    "ON session_runs(mission_id, updated_at)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_session_runs_goal_updated "
                    "ON session_runs(goal_id, updated_at)"
                )
            conn.commit()
    except Exception as exc:
        logger.exception("Failed to ensure execution envelope schema")
        raise RuntimeError("Execution envelope schema readiness failed") from exc


def init_db(run_migrations: bool = True) -> None:
    """Initialize the database and make its schema ready before use."""
    global _SESSION_GC_SCHEMA_MIGRATED

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    is_fresh_db = not DB_PATH.exists()
    # The session-GC columns are checked against the database that is being
    # initialized, so the "already migrated" shortcut must not survive a
    # change of DB_PATH (tests point it at a fresh file every time).
    _SESSION_GC_SCHEMA_MIGRATED = False

    if is_fresh_db:
        logger.info("Fresh database, applying initial schema")
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
            conn.executescript(schema)
            conn.commit()
        _ensure_execution_envelope_schema()
        _ensure_session_gc_schema()
        logger.info("DB initialized at %s", DB_PATH)
        _seed_default_user()
        _seed_default_rbac()
        _stamp_alembic()
    else:
        # Compatibility repairs must precede schema/index execution, migrations,
        # and all seed work. Older session_runs tables lack envelope columns
        # referenced by the current schemas.sql indexes.
        _ensure_execution_envelope_schema()
        _ensure_session_compatibility_schema()
        _ensure_message_cost_column()
        _ensure_message_run_link_column()
        _ensure_current_schema()
        _ensure_execution_envelope_schema()
        _ensure_git_commits_table()
        _ensure_session_gc_schema()
        if run_migrations:
            _run_alembic_migrations()
            _ensure_execution_envelope_schema()
            _ensure_session_gc_schema()
        _seed_default_user()
        _seed_default_rbac()


    # Stale-run recovery is performed by the startup lifespan immediately
    # after this function returns, once structured logging is available.



def _seed_default_user() -> None:
    """Create a default admin user if the users table is empty.

    Credentials come from the ``NEXUS_DEFAULT_EMAIL`` and
    ``NEXUS_DEFAULT_PASSWORD`` environment variables. If either is
    not set, seeding is skipped — no known-password admin account
    is created.
    """
    import os

    import bcrypt

    email = os.environ.get("NEXUS_DEFAULT_EMAIL", "")
    password = os.environ.get("NEXUS_DEFAULT_PASSWORD", "")
    if not email or not password:
        logger.info(
            "NEXUS_DEFAULT_EMAIL/NEXUS_DEFAULT_PASSWORD not set — "
            "skipping default user seed"
        )
        return

    try:
        with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
            if row and row[0] > 0:
                logger.debug("Users already exist, skipping default user seed")
                return

        password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

        uid = _new_id()
        with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
            conn.execute(
                "INSERT INTO users (id, username, email, password_hash, full_name) "
                "VALUES (?, ?, ?, ?, ?)",
                (uid, "admin", email, password_hash, "Admin"),
            )
            conn.commit()

        logger.info("Default admin user created (email=%s)", email)
    except Exception as exc:
        logger.warning("Failed to seed default user: %s", exc)


def ensure_dev_default_user() -> dict | None:
    """Ensure a development default user exists when there are no users yet.

    Credentials come from ``NEXUS_DEFAULT_EMAIL`` /
    ``NEXUS_DEFAULT_PASSWORD`` environment variables. If either is
    not set, returns ``None`` — no known-password admin account is created.
    """
    import os

    default_email = os.environ.get("NEXUS_DEFAULT_EMAIL", "")
    default_password = os.environ.get("NEXUS_DEFAULT_PASSWORD", "")
    if not default_email or not default_password:
        return None

    try:
        with sqlite3.connect(str(DB_PATH)) as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM users").fetchone()
            if row and row[0] > 0:
                existing = conn.execute("SELECT * FROM users WHERE email = ?", (default_email,)).fetchone()
                if existing:
                    user = dict(existing)
                    user.pop("password_hash", None)
                    return user
                return None

        _seed_default_user()
        with sqlite3.connect(str(DB_PATH)) as conn:
            existing = conn.execute("SELECT * FROM users WHERE email = ?", (default_email,)).fetchone()
            if existing:
                user = dict(existing)
                user.pop("password_hash", None)
                return user
    except Exception as exc:
        logger.warning("Failed to ensure dev default user: %s", exc)
        return None


def _seed_default_rbac() -> None:
    """Create default roles, permissions and assign admin role to the default user.

    Idempotent: safe to run multiple times.
    """
    import os

    admin_email = os.environ.get("NEXUS_DEFAULT_EMAIL", "")
    try:
        with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
            conn.executescript("""
                INSERT OR IGNORE INTO roles (id, name, description) VALUES
                    ('role_admin',    'admin',    'Full system access'),
                    ('role_user',     'user',     'Standard authenticated user'),
                    ('role_readonly', 'readonly', 'Read-only access to non-sensitive data');

                INSERT OR IGNORE INTO permissions (id, name, description, resource, action) VALUES
                    ('perm_admin_all',       'admin_all',        'All admin operations',     'admin',    '*'),
                    ('perm_chat_write',      'chat_write',       'Send chat messages',       'chat',     'write'),
                    ('perm_files_read',      'files_read',       'Read project files',       'files',    'read'),
                    ('perm_files_write',     'files_write',      'Write project files',      'files',    'write'),
                    ('perm_projects_read',   'projects_read',    'List/view projects',       'projects', 'read'),
                    ('perm_projects_write',  'projects_write',   'Create/edit projects',     'projects', 'write'),
                    ('perm_system_read',     'system_read',      'Read system status',       'system',   'read'),
                    ('perm_agents_read',     'agents_read',      'View agent status',        'agents',   'read');

                INSERT OR IGNORE INTO role_permissions (id, role_id, permission_id) VALUES
                    ('rp_001', 'role_admin',    'perm_admin_all'),
                    ('rp_002', 'role_admin',    'perm_chat_write'),
                    ('rp_003', 'role_admin',    'perm_files_read'),
                    ('rp_004', 'role_admin',    'perm_files_write'),
                    ('rp_005', 'role_admin',    'perm_projects_read'),
                    ('rp_006', 'role_admin',    'perm_projects_write'),
                    ('rp_007', 'role_admin',    'perm_system_read'),
                    ('rp_008', 'role_admin',    'perm_agents_read'),
                    ('rp_009', 'role_user',     'perm_chat_write'),
                    ('rp_010', 'role_user',     'perm_files_read'),
                    ('rp_011', 'role_user',     'perm_projects_read'),
                    ('rp_012', 'role_readonly', 'perm_projects_read'),
                    ('rp_013', 'role_readonly', 'perm_system_read');
            """)
            conn.commit()
    except Exception as exc:
        logger.warning("Failed to seed default RBAC: %s", exc)
        return

    # Assign admin role to the default user (if created via env vars)
    if admin_email:
        try:
            with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
                conn.execute(
                    """INSERT OR IGNORE INTO user_roles (id, user_id, role_id)
                       SELECT 'ur_admin_001', u.id, 'role_admin'
                         FROM users u
                        WHERE u.email = ?
                        LIMIT 1""",
                    (admin_email,),
                )
                conn.commit()
        except Exception as exc:
            logger.warning("Failed to assign admin role: %s", exc)


# Alembic is deliberately not a hard dependency (it is absent from
# nexus-ide/pyproject.toml and uv.lock), so a `uv sync --frozen` environment has
# no `alembic`/`sqlalchemy`. That environment must still be able to run the test
# suite and start the app: persistence/schemas.sql remains the primary schema
# authority and Alembic is only a stamp/migration convenience. A missing
# Alembic is therefore a WARNING, while every other Alembic failure still
# raises -- silently ignoring a migration that genuinely failed to apply is
# worse than not starting.
ALEMBIC_UNAVAILABLE_MESSAGE = (
    "Alembic is not installed; schema stamp/migrations skipped. "
    "Install 'alembic' and 'sqlalchemy' (see nexus-ide/pyproject.toml) "
    "to enable migrations."
)


def _alembic_available() -> bool:
    """Return whether Alembic is installed, letting a broken install raise.

    Absence and breakage are two different facts and are decided two different
    ways:

    * ``importlib.util.find_spec`` answers *is it installed?* without executing
      any of it.  Only a genuine absence returns ``False`` (a WARNING, and the
      app starts on ``persistence/schemas.sql``).
    * a **present** install is then actually imported.  A version-mismatched
      Alembic raises ``ImportError`` from that import
      (``cannot import name 'Encoding' from 'sqlalchemy'``), and ``ImportError``
      is exactly what a broken install looks like, so it must never be folded
      into the "not installed" answer: warning there would start the app on a
      stale schema, which the note above calls out as worse than not starting.

    Any exception raised here propagates.  Both callers invoke this function
    inside their migration ``try`` block, so the caller sees the documented
    ``RuntimeError("Database migration ...")`` with the real import failure
    chained as ``__cause__`` rather than a bare ``ImportError``.
    """
    import importlib
    import importlib.util

    if importlib.util.find_spec("alembic") is None:
        return False

    # Present: prove it actually imports instead of guessing from its presence.
    importlib.import_module("alembic")
    importlib.import_module("alembic.config")
    importlib.import_module("alembic.command")
    return True


def _alembic_config() -> Any:
    """Build an Alembic ``Config`` that works from any working directory.

    ``backend/alembic.ini`` carries a *relative* ``script_location =
    backend/migrations``. Alembic resolves that against the current working
    directory, so ``init_db()`` only worked when the process happened to run
    from the repository root: from anywhere else it died with
    ``CommandError: Path doesn't exist: backend\\migrations``.

    The absolute migrations directory is therefore written back into the
    config before the command runs. ``%`` is escaped because ConfigParser
    would otherwise treat it as an interpolation marker.
    """
    from alembic.config import Config

    alembic_dir = Path(__file__).resolve().parent.parent / "migrations"
    alembic_ini = Path(__file__).resolve().parent.parent / "alembic.ini"
    if not alembic_dir.exists() or not alembic_ini.exists():
        raise RuntimeError("Alembic configuration is unavailable")
    config = Config(str(alembic_ini))
    config.set_main_option("script_location", str(alembic_dir).replace("%", "%%"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{DB_PATH}")
    return config


def _stamp_alembic(revision: str = "head") -> None:
    """Stamp the database with ``revision`` (the Alembic head by default)."""
    try:
        # Inside the try on purpose: a present-but-unimportable Alembic must
        # surface as the same documented RuntimeError as a failed stamp, not as
        # a raw ImportError leaking past this function's contract.
        if not _alembic_available():
            logger.warning(ALEMBIC_UNAVAILABLE_MESSAGE)
            return
        from alembic import command

        logger.info("Stamping database with revision %s", revision)
        config = _alembic_config()
        command.stamp(config, revision)
        logger.info("Database stamped successfully")
    except Exception as exc:
        logger.exception("Failed to stamp database with Alembic")
        raise RuntimeError("Database migration stamp failed") from exc


#: The objects every revision creates, in chain order (oldest first). A
#: database that contains all of them is at (or past) that revision, which is
#: what an untracked database has to be stamped with.
_ALEMBIC_REVISION_MARKERS: tuple[tuple[str, tuple[str, ...], tuple[tuple[str, str], ...]], ...] = (
    (
        "001_initial",
        (
            "projects",
            "sessions",
            "messages",
            "tool_executions",
            "routing_decisions",
            "proposed_changes",
        ),
        (),
    ),
    (
        "002_add_rbac",
        ("users", "roles", "permissions", "user_roles", "role_permissions"),
        (),
    ),
    ("003_user_profile", ("user_profiles", "user_routines", "user_memories"), ()),
    ("004_email_config", ("email_accounts",), ()),
    ("005_add_token_tracking", (), (("messages", "cost_usd"),)),
    ("006_execution_envelope", ("session_runs",), ()),
    (
        "007_schemas_sql_parity",
        (
            "agent_states",
            "git_commits",
            "peer_review_requests",
            "peer_review_results",
            "persistent_memories",
            "whiteboard_entries",
            "whiteboard_entry_links",
        ),
        (),
    ),
    ("008_message_run_link", (), (("messages", "run_id"),)),
    (
        "008_run_state",
        ("run_state", "run_checkpoints", "run_side_effects", "run_dead_letters"),
        (),
    ),
    (
        "009_todos_scheduled_tasks",
        ("todos", "scheduled_tasks"),
        (("sessions", "user_id"),),
    ),
    (
        "010_session_gc_and_observability",
        ("structured_logs", "usage_ledger"),
        (("sessions", "status"), ("sessions", "expired_at")),
    ),
)


def _detect_alembic_revision(conn: sqlite3.Connection) -> str | None:
    """Return the revision whose schema the database already has.

    Used to adopt an untracked database: it was built from ``schemas.sql``
    (or by an older release) and therefore matches one of the revisions, but
    nothing ever wrote ``alembic_version`` for it. Without this, the next
    ``alembic upgrade head`` replayed the whole chain and died at revision
    005 with "duplicate column name: cost_usd".

    The chain is walked in order and stops at the first revision whose
    objects are missing: that revision is the one the database still has to
    be migrated, so the database is stamped at its predecessor.
    """
    tables = {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    matched: str | None = None
    for revision, required_tables, required_columns in _ALEMBIC_REVISION_MARKERS:
        if not all(table in tables for table in required_tables):
            break
        satisfied = True
        for table, column in required_columns:
            if table not in tables:
                satisfied = False
                break
            columns = {
                str(row[1])
                for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if column not in columns:
                satisfied = False
                break
        if not satisfied:
            break
        matched = revision
    return matched


def _run_alembic_migrations() -> None:
    """Run pending Alembic migrations on an existing database."""
    with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
        tracked = conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name='alembic_version'"
        ).fetchone()
        if tracked is None:
            # An untracked database is not "pre-Alembic", it is a database
            # whose schema was never recorded. Adopt it: stamp the revision
            # its schema already matches so the *remaining* migrations apply
            # instead of the whole chain being replayed.
            revision = _detect_alembic_revision(conn)
            if revision is None:
                # Nothing recognisable: repairing it is the compatibility
                # schema path's job, and replaying the chain would be unsafe.
                logger.info("Untracked database repaired without Alembic replay")
                return
            logger.info("Adopting untracked database at revision %s", revision)
            _stamp_alembic(revision)

    try:
        # Same contract as _stamp_alembic: absence warns, breakage raises the
        # documented RuntimeError.
        if not _alembic_available():
            logger.warning(ALEMBIC_UNAVAILABLE_MESSAGE)
            return

        from alembic import command

        logger.info("Running database migrations")
        config = _alembic_config()
        command.upgrade(config, "head")
        logger.info("Migrations completed successfully")
    except Exception as exc:
        logger.exception("Failed to run migrations")
        raise RuntimeError("Database migration failed") from exc




def close_pool() -> None:
    """Close all connections in the connection pool.

    Call this when shutting down the application.
    """
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.close_all()
        _connection_pool = None
        logger.info("Connection pool closed")


# ───── SQLITE LOCK HANDLING ──────────────────────────────────────────────

#: How many times a statement is attempted when SQLite reports a transient
#: lock ("database is locked" / "database is busy"). The statement never ran,
#: so running it again is safe.
DB_LOCK_ATTEMPTS = 3

#: Seconds to wait before the first lock retry. The wait grows linearly with
#: the attempt number, so a lock that clears quickly costs almost nothing.
DB_LOCK_RETRY_DELAY = 0.05


def _is_transient_lock_error(exc: BaseException) -> bool:
    """Return whether ``exc`` is a transient SQLite lock/busy failure.

    ``sqlite3.OperationalError`` covers a lot of unrelated problems ("no such
    table", "attempt to write a readonly database", ...). Only the lock/busy
    family is worth retrying: the statement did not run, so running it again
    is safe. Everything else is a real error and must reach the caller.
    """
    if not isinstance(exc, sqlite3.OperationalError):
        return False
    text = str(exc).lower()
    return "locked" in text or "busy" in text


def _safe_rollback(connection: sqlite3.Connection) -> None:
    """Roll back ``connection`` without ever raising."""
    try:
        connection.rollback()
    except sqlite3.Error:
        logger.debug("Rollback failed while releasing a connection", exc_info=True)


class _LockRetryingConnection:
    """A ``sqlite3.Connection`` stand-in that retries transient lock errors.

    Why this exists
    ---------------
    ``get_db`` used to catch ``sqlite3.OperationalError`` inside a generator
    based context manager and tried to "retry" by yielding a second time.
    ``contextlib`` refuses that: it raises
    ``RuntimeError("generator didn't stop after throw()")``, so the caller
    never saw the real ``sqlite3.OperationalError("database is locked")`` and
    every ``except sqlite3.OperationalError`` handler in the codebase was
    dead code. The connection was also closed and never returned to the pool,
    which leaked the pool until it died with
    ``TimeoutError("Connection pool exhausted after 30s")``.

    A context manager cannot re-run the caller's block, so the retry has to
    live one level down, on the statement that actually failed. This wrapper
    re-runs *that statement* while SQLite reports a lock and lets every other
    error through untouched.

    Every attribute that is not overridden here is delegated to the wrapped
    connection, so the object behaves like the connection it wraps.
    """

    __slots__ = ("_connection", "_attempts", "_delay")

    #: The wrapped connection. Declared for the type checker; the value is
    #: installed in ``__init__``.
    _connection: sqlite3.Connection
    _attempts: int
    _delay: float

    #: Attribute names owned by the wrapper itself (everything else is
    #: forwarded to the wrapped connection).
    _OWN_ATTRIBUTES = frozenset({"_connection", "_attempts", "_delay"})

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        attempts: int = DB_LOCK_ATTEMPTS,
        delay: float = DB_LOCK_RETRY_DELAY,
    ) -> None:
        object.__setattr__(self, "_connection", connection)
        object.__setattr__(self, "_attempts", max(1, int(attempts)))
        object.__setattr__(self, "_delay", max(0.0, float(delay)))

    # ── delegation ─────────────────────────────────────────────────────

    def __getattr__(self, name: str) -> Any:
        # ``__getattr__`` only runs for attributes the wrapper does not have.
        # Guard the slot lookup so a half-initialised wrapper cannot recurse.
        if name == "_connection":
            raise AttributeError(name)
        return getattr(self._connection, name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._OWN_ATTRIBUTES:
            object.__setattr__(self, name, value)
        else:
            setattr(self._connection, name, value)

    # ── retried statements ─────────────────────────────────────────────

    def execute(self, sql: str, parameters: Any = ()) -> sqlite3.Cursor:
        """Run one statement, retrying it while SQLite reports a lock."""
        return self._run_with_lock_retry(lambda: self._connection.execute(sql, parameters))

    def executemany(self, sql: str, parameters: Any) -> sqlite3.Cursor:
        """Run one statement for every parameter set, retrying on a lock."""
        return self._run_with_lock_retry(lambda: self._connection.executemany(sql, parameters))

    def _run_with_lock_retry(self, operation: Callable[[], _T]) -> _T:
        """Run ``operation``, re-running it while SQLite reports a lock.

        The original :class:`sqlite3.OperationalError` is re-raised once the
        attempts are exhausted, so the caller sees the real failure.
        """
        attempt = 0
        while True:
            try:
                return operation()
            except sqlite3.OperationalError as exc:
                attempt += 1
                if attempt >= self._attempts or not _is_transient_lock_error(exc):
                    raise
                logger.debug("Retrying statement after a SQLite lock error: %s", exc)
                time.sleep(self._delay * attempt)


def _commit_with_lock_retry(
    connection: sqlite3.Connection,
    *,
    attempts: int = DB_LOCK_ATTEMPTS,
    delay: float = DB_LOCK_RETRY_DELAY,
) -> None:
    """Commit ``connection``, retrying while SQLite reports a lock."""
    attempt = 0
    while True:
        try:
            connection.commit()
            return
        except sqlite3.OperationalError as exc:
            attempt += 1
            if attempt >= attempts or not _is_transient_lock_error(exc):
                raise
            logger.debug("Retrying commit after a SQLite lock error: %s", exc)
            time.sleep(delay * attempt)


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    """Context manager yielding a sqlite connection from the pool.

    Uses the connection pool for better performance instead of creating
    a new connection every time.

    Lock handling
    -------------
    SQLite can still fail a statement with ``database is locked`` when the
    busy timeout expires (Windows holds WAL locks briefly after a previous
    connection closes). The yielded connection re-runs a statement that hit
    such a lock (:class:`_LockRetryingConnection`); when the retries are
    exhausted the original :class:`sqlite3.OperationalError` propagates to
    the caller unchanged.

    The connection is returned to the pool on *every* path — success, error
    and cancellation — so a failing statement can never leak pool capacity.
    """
    pool = get_connection_pool()
    connection = pool.get_connection()
    try:
        yield cast(
            "sqlite3.Connection",
            _LockRetryingConnection(
                connection,
                attempts=DB_LOCK_ATTEMPTS,
                delay=DB_LOCK_RETRY_DELAY,
            ),
        )
        _commit_with_lock_retry(connection, attempts=DB_LOCK_ATTEMPTS, delay=DB_LOCK_RETRY_DELAY)
    except Exception:
        _safe_rollback(connection)
        raise
    finally:
        pool.return_connection(connection)


# ───── PROJECTS ─────────────────────────────────────────────────────────


def get_auth_refresh_exchange(refresh_jti: str) -> dict[str, Any] | None:
    """Return a persisted idempotent refresh exchange, if one exists."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT refresh_jti, idempotency_key_hash, response_ciphertext, expires_at "
            "FROM auth_refresh_exchanges WHERE refresh_jti = ?",
            (refresh_jti,),
        ).fetchone()
    return dict(row) if row else None


def save_auth_refresh_exchange(
    refresh_jti: str,
    idempotency_key_hash: str,
    response_ciphertext: str,
    expires_at: float,
) -> None:
    """Persist one encrypted refresh result, atomically claiming its old JTI."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM auth_refresh_exchanges WHERE expires_at <= ?",
            (time.time(),),
        )
        conn.execute(
            "INSERT INTO auth_refresh_exchanges "
            "(refresh_jti, idempotency_key_hash, response_ciphertext, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (refresh_jti, idempotency_key_hash, response_ciphertext, expires_at),
        )


def save_auth_revocation(revocation_type: str, credential_hash: str, expires_at: float) -> None:
    """Persist a hashed token or session revocation until its credential expires."""
    if revocation_type not in {"token", "session"}:
        raise ValueError("Unsupported auth revocation type")
    with get_db() as conn:
        conn.execute(
            "DELETE FROM auth_revocations WHERE expires_at <= ?",
            (time.time(),),
        )
        conn.execute(
            "INSERT INTO auth_revocations (revocation_type, credential_hash, expires_at) "
            "VALUES (?, ?, ?) "
            "ON CONFLICT(revocation_type, credential_hash) DO UPDATE SET "
            "expires_at = MAX(auth_revocations.expires_at, excluded.expires_at)",
            (revocation_type, credential_hash, expires_at),
        )


def is_auth_revoked(revocation_type: str, credential_hash: str) -> bool:
    """Check a hashed token or session revocation in persistent storage."""
    if revocation_type not in {"token", "session"}:
        raise ValueError("Unsupported auth revocation type")
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM auth_revocations "
            "WHERE revocation_type = ? AND credential_hash = ? AND expires_at > ?",
            (revocation_type, credential_hash, time.time()),
        ).fetchone()
    return row is not None


@sync_cache_invalidate_pattern("project:*")
def create_project(
    name: str,
    path: str,
    description: str = "",
    mode: str = "auto",
    preferred_model: str | None = None,
    trust: bool = False,
) -> dict:
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM projects WHERE path = ?",
            (path,),
        ).fetchone()
        if existing:
            updated_at = _now_iso()
            conn.execute(
                """UPDATE projects SET name = ?, description = ?, mode = ?, preferred_model = ?, trust = ?, updated_at = ? WHERE path = ?""",
                (name, description, mode, preferred_model, 1 if trust else 0, updated_at, path),
            )
            row = conn.execute("SELECT * FROM projects WHERE path = ?", (path,)).fetchone()
            return dict(row) if row else None
        pid = _new_id()
        conn.execute(
            """INSERT INTO projects (id, name, path, description, mode, preferred_model, trust) VALUES (?, ?, ?, ?, ?, ?, ?)""",
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
        projects = [dict(r) for r in rows]
        seen: dict[str, dict] = {}
        for project in projects:
            path = project["path"]
            if path not in seen:
                seen[path] = project
        return list(seen.values())


def count_active_sessions() -> int:
    """Count the sessions that are still live (soft-deleted ones excluded)."""
    _ensure_session_gc_schema()
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM sessions "
            "WHERE status IS NULL OR status != 'expired'"
        ).fetchone()
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
    # Whitelist allowed columns to prevent SQL injection
    ALLOWED_COLS = {"name", "path", "description", "mode", "preferred_model", "trust", "updated_at"}
    safe_fields = {k: v for k, v in fields.items() if k in ALLOWED_COLS}
    if not safe_fields:
        return get_project(project_id)
    cols = ", ".join(f"{k} = ?" for k in safe_fields)
    with get_db() as conn:
        conn.execute(f"UPDATE projects SET {cols} WHERE id = ?", (*safe_fields.values(), project_id))
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
    user_id: str | None = None,
) -> dict:
    sid = session_id or _new_id()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, user_id, project_id, title, mode) VALUES (?, ?, ?, ?, ?)",
            (sid, user_id, project_id, title, mode),
        )
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
    return dict(row) if row else None


def create_subagent_execution(
    *, parent_session_id: str, parent_run_id: str, task_id: str, user_id: str,
    agent: str, objective: str, model: str = "",
) -> dict[str, Any]:
    """Create a child session/run and its parent link in one transaction."""
    if not all((parent_session_id, parent_run_id, task_id, user_id)):
        raise ValueError("A subagent requires a parent run, task and authenticated owner")
    with get_db() as conn:
        parent = conn.execute(
            """SELECT s.project_id FROM sessions s JOIN session_runs r ON r.session_id = s.id
               WHERE s.id = ? AND s.user_id = ? AND r.id = ?""",
            (parent_session_id, user_id, parent_run_id),
        ).fetchone()
        if parent is None:
            raise ValueError("Parent session or run is not owned by this user")
        existing = conn.execute(
            "SELECT * FROM subagent_executions WHERE parent_run_id = ? AND task_id = ?",
            (parent_run_id, task_id),
        ).fetchone()
        if existing is not None:
            return dict(existing)
        child_session_id = f"child-{uuid.uuid4().hex}"
        child_run_id = f"childrun-{uuid.uuid4().hex}"
        conn.execute(
            "INSERT INTO sessions (id, user_id, project_id, title, mode) VALUES (?, ?, ?, ?, ?)",
            (child_session_id, user_id, parent["project_id"], agent[:200], "__subagent__"),
        )
        conn.execute(
            """INSERT INTO session_runs (id, session_id, status, agent, phase, prompt, model)
               VALUES (?, ?, 'running', ?, 'delegated', ?, ?)""",
            (child_run_id, child_session_id, agent, objective, model),
        )
        conn.execute(
            """INSERT INTO subagent_executions
               (parent_session_id, parent_run_id, task_id, child_session_id, child_run_id)
               VALUES (?, ?, ?, ?, ?)""",
            (parent_session_id, parent_run_id, task_id, child_session_id, child_run_id),
        )
        conn.execute(
            "INSERT INTO messages (id, session_id, role, content, run_id) VALUES (?, ?, 'user', ?, ?)",
            (_new_id(), child_session_id, objective, child_run_id),
        )
        row = conn.execute(
            "SELECT * FROM subagent_executions WHERE parent_run_id = ? AND task_id = ?",
            (parent_run_id, task_id),
        ).fetchone()
        return dict(row)


def finish_subagent_execution(
    *, child_session_id: str, child_run_id: str, status: str, output: str = "", error: str = "",
) -> None:
    """Persist a child's observed result or failure without changing its parent."""
    if status not in {"completed", "failed", "cancelled", "interrupted"}:
        raise ValueError("Invalid child run status")
    now = _now_iso()
    with get_db() as conn:
        cursor = conn.execute(
            """UPDATE session_runs SET status = ?, phase = ?, error = ?,
               updated_at = ?, finished_at = ? WHERE id = ? AND session_id = ?""",
            (status, status, error or None, now, now, child_run_id, child_session_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Child run no longer exists")
        if output and not conn.execute(
            "SELECT 1 FROM messages WHERE session_id = ? AND run_id = ? AND role = 'assistant'",
            (child_session_id, child_run_id),
        ).fetchone():
            conn.execute(
                """INSERT INTO messages (id, session_id, role, content, run_id)
                   VALUES (?, ?, 'assistant', ?, ?)""",
                (_new_id(), child_session_id, output, child_run_id),
            )
        conn.execute("UPDATE sessions SET last_active_at = ? WHERE id = ?", (now, child_session_id))


def get_subagent_execution(child_session_id: str, user_id: str) -> dict[str, Any] | None:
    """Return the child link only when both conversations belong to the caller."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT e.*, r.status, r.error, r.agent, r.model
               FROM subagent_executions e
               JOIN sessions p ON p.id = e.parent_session_id
               JOIN sessions c ON c.id = e.child_session_id
               JOIN session_runs r ON r.id = e.child_run_id
               WHERE e.child_session_id = ? AND p.user_id = ? AND c.user_id = ?""",
            (child_session_id, user_id, user_id),
        ).fetchone()
        return dict(row) if row else None


@sync_cache_result("session:", ttl=SHORT_TTL)
def get_session(session_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return dict(row) if row else None


def get_session_for_user(session_id: str, user_id: str) -> dict | None:
    """Return a session only when it is owned by the authenticated user."""
    if not session_id or not user_id:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM sessions WHERE id = ? AND user_id = ?",
            (session_id, user_id),
        ).fetchone()
    return dict(row) if row else None


@monitor_query_performance
def list_sessions(
    project_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = None,
) -> list[dict]:
    """List the live sessions, newest activity first.

    Soft-deleted sessions (``status = 'expired'``) are excluded: the garbage
    collector expired them on purpose and the listing must not show them as
    ordinary conversations.
    """
    _ensure_session_gc_schema()
    with get_db() as conn:
        clauses: list[str] = [
            "(status IS NULL OR status != 'expired')",
            "(mode IS NULL OR mode != '__subagent__')",
        ]
        params: list[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        where = f" WHERE {' AND '.join(clauses)}"
        params.extend((limit, offset))
        rows = conn.execute(
            "SELECT * FROM sessions" + where
            + " ORDER BY last_active_at DESC, id DESC LIMIT ? OFFSET ?",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


def session_belongs_to_user(session_id: str, user_id: str) -> bool:
    """Check session ownership without returning private session contents."""
    if not session_id or not user_id:
        return False
    with get_db() as conn:
        row = conn.execute(
            "SELECT 1 FROM sessions WHERE id = ? AND user_id = ? LIMIT 1",
            (session_id, user_id),
        ).fetchone()
    return row is not None


def touch_session(session_id: str) -> None:
    with get_db() as conn:
        conn.execute(
            "UPDATE sessions SET last_active_at = ? WHERE id = ?", (_now_iso(), session_id)
        )


def _invalidate_session_cache(session_id: str | None = None) -> None:
    """Invalidate the Redis cache for a session (best-effort, silent)."""
    try:
        from backend.redis_cache import get_sync_cache

        cache = get_sync_cache()
        if session_id:
            with suppress(Exception):
                cache.delete(f"session:{session_id}")
        # Also bust the list cache
        with suppress(Exception):
            cache.delete_pattern("session:*")
    except Exception:
        pass


def update_session(
    session_id: str,
    *,
    title: str | None = None,
    mode: str | None = None,
    user_id: str | None = None,
) -> dict | None:
    """Update mutable fields on a session. Returns the updated row."""
    fields: list[str] = []
    values: list[Any] = []
    if title is not None:
        fields.append("title = ?")
        values.append(title[:120])
    if mode is not None:
        fields.append("mode = ?")
        values.append(mode)
    if not fields:
        row = get_session(session_id)
        if user_id is not None and (row is None or row.get("user_id") != user_id):
            return None
        return row
    fields.append("last_active_at = ?")
    values.append(_now_iso())
    values.append(session_id)
    owner_filter = " AND user_id = ?" if user_id is not None else ""
    if user_id is not None:
        values.append(user_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE sessions SET {', '.join(fields)} WHERE id = ?{owner_filter}",
            values,
        )
        select_sql = "SELECT * FROM sessions WHERE id = ?" + owner_filter
        select_params: tuple[Any, ...] = (session_id, user_id) if user_id is not None else (session_id,)
        row = conn.execute(select_sql, select_params).fetchone()
    _invalidate_session_cache(session_id)
    return dict(row) if row else None


def delete_session(session_id: str, *, user_id: str | None = None) -> bool:
    """Delete a session and all its messages. Returns True if the session existed."""
    with get_db() as conn:
        owner_filter = " AND user_id = ?" if user_id is not None else ""
        params: tuple[Any, ...] = (session_id, user_id) if user_id is not None else (session_id,)
        cursor = conn.execute(
            "DELETE FROM sessions WHERE id = ?" + owner_filter,
            params,
        )
    deleted = cursor.rowcount > 0
    if deleted:
        _invalidate_session_cache(session_id)
    return deleted


def get_session_message_count(session_id: str) -> int:
    """Return the number of messages in a session (for the session list)."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
    return int(row["cnt"]) if row else 0


def count_sessions(project_id: str | None = None, *, user_id: str | None = None) -> int:
    """Count the live sessions without loading the complete history into the API.

    Uses the same filter as :func:`list_sessions`, so the count always agrees
    with the listing.
    """
    _ensure_session_gc_schema()
    with get_db() as conn:
        clauses: list[str] = [
            "(status IS NULL OR status != 'expired')",
            "(mode IS NULL OR mode != '__subagent__')",
        ]
        params: list[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        where = f" WHERE {' AND '.join(clauses)}"
        row = conn.execute(
            "SELECT COUNT(*) AS cnt FROM sessions" + where,
            params,
        ).fetchone()
    return int(row["cnt"]) if row else 0


def _session_display_status(session: Mapping[str, Any]) -> str:
    """Return the status shown for one session row.

    A soft-deleted session keeps the status the garbage collector wrote:
    ``expired``. Reporting it as ``idle``/``closed`` would make a deleted
    conversation look like a live one. Every other session reports its live
    liveness, derived from ``last_active_at``:

    * ``active`` — last activity within the last 5 minutes
    * ``idle``   — last activity 5 min to 24 h ago
    * ``closed`` — last activity more than 24 h ago
    """
    persisted = session.get("status")
    if persisted == "expired":
        return "expired"
    now = datetime.now(UTC)
    last = session.get("last_active_at")
    if not last:
        return "closed"
    try:
        last_dt = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=UTC)
        age = now - last_dt
    except (TypeError, ValueError):
        return "closed"
    if age < timedelta(minutes=5):
        return "active"
    if age < timedelta(hours=24):
        return "idle"
    return "closed"


def _decorate_session_rows(sessions: list[dict]) -> list[dict]:
    for session in sessions:
        try:
            session["message_count"] = get_session_message_count(session["id"])
        except Exception:
            session["message_count"] = 0
        session["status"] = _session_display_status(session)
    return sessions


def list_sessions_with_counts(
    project_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
    user_id: str | None = None,
) -> list[dict]:
    """Same as ``list_sessions`` but with a ``message_count`` and ``status`` column attached.

    ``status`` is the persisted soft-delete marker when the session was
    expired, and otherwise derived from ``last_active_at``:
      * ``active``  — last activity within the last 5 minutes
      * ``idle``    — last activity 5 min to 24 h ago
      * ``closed``  — last activity more than 24 h ago
    """
    sessions = list_sessions(
        project_id=project_id, limit=limit, offset=offset, user_id=user_id
    )
    return _decorate_session_rows(sessions)


@monitor_query_performance
def search_sessions(
    query: str,
    *,
    project_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    user_id: str | None = None,
) -> tuple[list[dict], int]:
    """Search session titles, modes, and persisted message text.

    Message text currently uses SQLite's built-in LIKE so this remains
    compatible with existing databases and needs no schema migration. The
    result includes a short snippet and the kind of match for the UI.

    Soft-deleted sessions are excluded, exactly like in :func:`list_sessions`.
    """
    _ensure_session_gc_schema()
    needle = query.strip()[:200]
    if not needle:
        return [], 0
    escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{escaped.lower()}%"
    project_filter = " AND s.project_id = ?" if project_id else ""
    user_filter = " AND s.user_id = ?" if user_id is not None else ""
    base_sql = f"""
        FROM sessions s
        WHERE (
            lower(COALESCE(s.title, '')) LIKE ? ESCAPE '\\'
            OR lower(COALESCE(s.mode, '')) LIKE ? ESCAPE '\\'
            OR EXISTS (
                SELECT 1 FROM messages mm
                WHERE mm.session_id = s.id
                  AND lower(mm.content) LIKE ? ESCAPE '\\'
            )
        ){project_filter}{user_filter}
        AND (s.status IS NULL OR s.status != 'expired')
        AND (s.mode IS NULL OR s.mode != '__subagent__')
    """
    with get_db() as conn:
        count_params: tuple[Any, ...] = (pattern, pattern, pattern)
        if project_id:
            count_params += (project_id,)
        if user_id is not None:
            count_params += (user_id,)
        total_row = conn.execute(
            f"SELECT COUNT(*) AS cnt {base_sql}", count_params
        ).fetchone()
        total = int(total_row["cnt"]) if total_row else 0

        params: tuple[Any, ...] = (
            pattern,
            pattern,
            pattern,
            needle.lower(),
            pattern,
            pattern,
            pattern,
            pattern,
        )
        if project_id:
            params += (project_id,)
        if user_id is not None:
            params += (user_id,)
        params += (limit, offset)
        rows = conn.execute(
            f"""
            SELECT s.*,
                CASE
                    WHEN EXISTS (
                        SELECT 1 FROM messages mm
                        WHERE mm.session_id = s.id
                          AND lower(mm.content) LIKE ? ESCAPE '\\'
                    ) THEN 'message'
                    WHEN lower(COALESCE(s.title, '')) LIKE ? ESCAPE '\\' THEN 'title'
                    ELSE 'mode'
                END AS match_type,
                (
                    SELECT m.id FROM messages m
                    WHERE m.session_id = s.id
                      AND lower(m.content) LIKE ? ESCAPE '\\'
                    ORDER BY m.created_at DESC, m.rowid DESC LIMIT 1
                ) AS match_message_id,
                (
                    SELECT substr(
                        m.content,
                        max(instr(lower(m.content), ?) - 60, 1),
                        180
                    ) FROM messages m
                    WHERE m.session_id = s.id
                      AND lower(m.content) LIKE ? ESCAPE '\\'
                    ORDER BY m.created_at DESC, m.rowid DESC LIMIT 1
                ) AS snippet
            {base_sql}
            ORDER BY s.last_active_at DESC, s.id DESC
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
        # Keep the visible list's count/status fields consistent with the
        # normal session endpoint without exposing the matching message body.
        sessions = _decorate_session_rows([dict(row) for row in rows])
    return sessions, total


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
    cost_usd: float = 0.0,
    latency_ms: int = 0,
    run_id: str | None = None,
) -> dict:
    mid = _new_id()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO messages
               (id, session_id, role, content, tier_used, model_used, tools_used_json,
                tokens_in, tokens_out, cost_usd, latency_ms, run_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                cost_usd,
                latency_ms,
                run_id,
            ),
        )
        conn.execute(
            "UPDATE sessions SET last_active_at = ? WHERE id = ?",
            (_now_iso(), session_id),
        )
        row = conn.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
    return (
        dict(row)
        if row
        else {"id": mid, "session_id": session_id, "role": role, "content": content}
    )


@monitor_query_performance
def get_messages(session_id: str, limit: int = 200) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM messages
                WHERE session_id = ?
                  AND id IN (
                      SELECT id FROM messages
                       WHERE session_id = ?
                       ORDER BY created_at DESC, rowid DESC
                       LIMIT ?
                  )
                ORDER BY created_at ASC, rowid ASC""",
            (session_id, session_id, limit),
        ).fetchall()
        return _collapse_legacy_duplicate_messages([dict(row) for row in rows])


def _collapse_legacy_duplicate_messages(rows: list[dict]) -> list[dict]:
    """Collapse exact duplicate turns in returned history without changing SQLite.

    Old retries could write a user turn twice; a few also wrote the assistant
    answer twice under the same durable run id. Keep the first row's identity
    and timestamp so pagination and timeline links remain stable.
    """
    messages: list[dict] = []
    for row in rows:
        row.pop("_rowid", None)
        previous = messages[-1] if messages else None
        same_run_and_content = bool(
            previous
            and row.get("role") == previous.get("role")
            and row.get("content") == previous.get("content")
            and row.get("run_id") == previous.get("run_id")
        )
        duplicate_user = same_run_and_content and row.get("role") == "user"
        duplicate_assistant = (
            same_run_and_content
            and row.get("role") == "assistant"
            and bool(row.get("run_id"))
        )
        if (
            previous is not None
            and (duplicate_user or duplicate_assistant)
        ):
            # A history read reports one logical message without destructively
            # rewriting the user's stored transcript.
            first = previous
            merged = {**first, **row}
            merged["id"] = first.get("id")
            merged["created_at"] = first.get("created_at")
            messages[-1] = merged
            continue
        messages.append(row)
    return messages


@monitor_query_performance
def get_messages_page(
    session_id: str,
    *,
    limit: int = 100,
    before_id: str | None = None,
) -> tuple[list[dict], bool, str | None]:
    """Fetch one newest-first cursor page, returned in chronological order.

    ``before_id`` is an opaque message id from the prior page. The stable
    cursor resolves its timestamp and SQLite rowid so messages that share a
    timestamp cannot be skipped or repeated.
    """
    bounded_limit = max(1, min(int(limit), 500))
    with get_db() as conn:
        cursor_row: sqlite3.Row | None = None
        if before_id:
            cursor_row = conn.execute(
                "SELECT created_at, rowid AS _rowid FROM messages "
                "WHERE session_id = ? AND id = ?",
                (session_id, before_id),
            ).fetchone()
            if cursor_row is None:
                raise ValueError("Message cursor does not belong to this session")

        if cursor_row is None:
            rows = conn.execute(
                "SELECT *, rowid AS _rowid FROM messages WHERE session_id = ? "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (session_id, bounded_limit + 1),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT *, rowid AS _rowid FROM messages "
                "WHERE session_id = ? AND (created_at < ? "
                "OR (created_at = ? AND rowid < ?)) "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (
                    session_id,
                    cursor_row["created_at"],
                    cursor_row["created_at"],
                    cursor_row["_rowid"],
                    bounded_limit + 1,
                ),
            ).fetchall()

    has_more = len(rows) > bounded_limit
    page_rows = rows[:bounded_limit]
    next_cursor = str(page_rows[-1]["id"]) if has_more and page_rows else None
    messages = _collapse_legacy_duplicate_messages(
        [dict(row) for row in reversed(page_rows)]
    )
    return messages, has_more, next_cursor


def _session_run_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    raw_evidence = result.get("evidence_json")
    if raw_evidence:
        try:
            result["evidence"] = json.loads(raw_evidence)
        except (TypeError, json.JSONDecodeError):
            result["evidence"] = raw_evidence
    else:
        result["evidence"] = []
    return result


def upsert_session_run(
    run_id: str,
    session_id: str,
    *,
    status: str = "running",
    agent: str | None = None,
    phase: str = "starting",
    prompt: str | None = None,
    partial_output: str | None = None,
    checkpoint: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    error: str | None = None,
    finished: bool = False,
    goal_id: str | None = None,
    mission_id: str | None = None,
    correlation_id: str | None = None,
    mode: str | None = None,
    execution_state: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    error_category: str | None = None,
    retry_after: int | None = None,
    evidence: Any | None = None,
) -> dict[str, Any] | None:
    """Persist a durable checkpoint and its execution-envelope metadata."""
    now = _now_iso()
    finished_at = now if finished else None
    evidence_json = (
        json.dumps(evidence, ensure_ascii=False, default=str)
        if evidence is not None
        else None
    )
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO session_runs
                (id, session_id, status, agent, phase, prompt, partial_output,
                 checkpoint_json, usage_json, error, mission_id, correlation_id,
                 goal_id,
                 mode, execution_state, provider, model, error_category,
                 retry_after, evidence_json, started_at, updated_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                status = excluded.status,
                agent = COALESCE(excluded.agent, session_runs.agent),
                phase = excluded.phase,
                prompt = CASE WHEN excluded.prompt <> '' THEN excluded.prompt ELSE session_runs.prompt END,
                partial_output = excluded.partial_output,
                checkpoint_json = CASE WHEN ? THEN excluded.checkpoint_json ELSE session_runs.checkpoint_json END,
                usage_json = CASE WHEN ? THEN excluded.usage_json ELSE session_runs.usage_json END,
                error = excluded.error,
                goal_id = COALESCE(excluded.goal_id, session_runs.goal_id),
                mission_id = COALESCE(excluded.mission_id, session_runs.mission_id),
                correlation_id = COALESCE(excluded.correlation_id, session_runs.correlation_id),
                mode = COALESCE(excluded.mode, session_runs.mode),
                execution_state = COALESCE(excluded.execution_state, session_runs.execution_state),
                provider = COALESCE(excluded.provider, session_runs.provider),
                model = COALESCE(excluded.model, session_runs.model),
                error_category = COALESCE(excluded.error_category, session_runs.error_category),
                retry_after = COALESCE(excluded.retry_after, session_runs.retry_after),
                evidence_json = COALESCE(excluded.evidence_json, session_runs.evidence_json),
                updated_at = excluded.updated_at,
                finished_at = COALESCE(excluded.finished_at, session_runs.finished_at)
            """,
            (
                run_id,
                session_id,
                status,
                agent,
                phase,
                prompt or "",
                partial_output or "",
                json.dumps(checkpoint or {}, ensure_ascii=False),
                json.dumps(usage or {}, ensure_ascii=False),
                error,
                mission_id,
                correlation_id,
                goal_id,
                mode,
                execution_state,
                provider,
                model,
                error_category,
                retry_after,
                evidence_json,
                now,
                now,
                finished_at,
                checkpoint is not None,
                usage is not None,
            ),
        )
        row = conn.execute("SELECT * FROM session_runs WHERE id = ?", (run_id,)).fetchone()
    touch_session(session_id)
    return _session_run_row(row)


def get_session_run(run_id: str) -> dict[str, Any] | None:
    """Return a single durable run checkpoint, if it exists."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM session_runs WHERE id = ?", (run_id,)).fetchone()
    return _session_run_row(row)


def list_session_runs(
    session_id: str,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List recent runs for the session, newest first, from a bounded page."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM session_runs WHERE session_id = ? "
            "ORDER BY updated_at DESC, rowid DESC LIMIT ? OFFSET ?",
            (session_id, max(1, min(limit, 101)), max(0, int(offset))),
        ).fetchall()
        return [_session_run_row(row) for row in rows if row is not None]


def get_runs_by_correlation(correlation_id: str) -> list[dict[str, Any]]:
    """Return durable runs associated with one correlation identifier."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM session_runs WHERE correlation_id = ? "
            "ORDER BY updated_at DESC",
            (correlation_id,),
        ).fetchall()
    return [_session_run_row(row) for row in rows if row is not None]


def mark_run_terminal(
    run_id: str,
    *,
    status: str = "completed",
    execution_state: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    error_category: str | None = None,
    retry_after: int | None = None,
    evidence: Any | None = None,
    error: str | None = None,
) -> dict[str, Any] | None:
    """Atomically record terminal metadata and the completion timestamp."""
    terminal_statuses = {"completed", "failed", "cancelled", "interrupted"}
    terminal_execution_states = terminal_statuses | {"blocked"}
    if status not in terminal_statuses:
        raise ValueError(f"mark_run_terminal requires a terminal status, got {status!r}")
    if execution_state is not None and execution_state not in terminal_execution_states:
        raise ValueError(
            f"mark_run_terminal requires a terminal execution state, got {execution_state!r}"
        )
    terminal_state = execution_state or status
    now = _now_iso()
    evidence_json = (
        json.dumps(evidence, ensure_ascii=False, default=str)
        if evidence is not None
        else None
    )
    with get_db() as conn:
        conn.execute(
            """
            UPDATE session_runs
               SET status = ?,
                   execution_state = ?,
                   provider = COALESCE(?, provider),
                   model = COALESCE(?, model),
                   error_category = COALESCE(?, error_category),
                   retry_after = COALESCE(?, retry_after),
                   evidence_json = COALESCE(?, evidence_json),
                   error = COALESCE(?, error),
                   updated_at = ?,
                   finished_at = ?
             WHERE id = ?
            """,
            (
                status,
                terminal_state,
                provider,
                model,
                error_category,
                retry_after,
                evidence_json,
                error,
                now,
                now,
                run_id,
            ),
        )
        row = conn.execute("SELECT * FROM session_runs WHERE id = ?", (run_id,)).fetchone()
    return _session_run_row(row)


def interrupt_active_session_runs(
    session_id: str,
    *,
    except_run_id: str | None = None,
    reason: str = "Superseded by a newer request in the same session",
) -> int:
    """Close obsolete runs before starting a replacement chat request."""
    now = _now_iso()
    params: list[Any] = [reason, now, now, session_id]
    exclude = ""
    if except_run_id:
        exclude = " AND id <> ?"
        params.append(except_run_id)
    with get_db() as conn:
        cursor = conn.execute(
            f"""
            UPDATE session_runs
               SET status = 'interrupted',
                   execution_state = 'interrupted',
                   phase = 'superseded',
                   error = COALESCE(error, ?),
                   updated_at = ?,
                   finished_at = COALESCE(finished_at, ?)
             WHERE session_id = ?
               AND status = 'running'
               {exclude}
            """,
            params,
        )
        return int(cursor.rowcount or 0)


def recover_interrupted_runs(max_age_seconds: int = 120) -> list[dict[str, Any]]:
    """Atomically recover stale running rows left behind by a crashed process."""
    cutoff = (datetime.now(UTC) - timedelta(seconds=max_age_seconds)).isoformat()
    now = _now_iso()
    with get_db() as conn:
        recovered = conn.execute(
            """
            UPDATE session_runs
               SET status = 'interrupted',
                   execution_state = 'interrupted',
                   phase = 'process_restart',
                   error = COALESCE(error, 'Backend restarted before the run completed'),
                   finished_at = COALESCE(finished_at, ?),
                   updated_at = ?
             WHERE status = 'running' AND updated_at < ?
            RETURNING *
            """,
            (now, now, cutoff),
        ).fetchall()
    result = [_session_run_row(row) for row in recovered if row is not None]
    if result:
        logger.warning("Marked %d stale session run(s) as interrupted", len(result))
    return result


def mark_stale_session_runs(max_age_seconds: int = 120) -> int:
    """Backward-compatible count-returning stale-run recovery wrapper."""
    return len(recover_interrupted_runs(max_age_seconds))


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
                COALESCE(SUM(cost_usd), 0.0) AS cost_usd_total,
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
                "cost_usd_total": 0.0,
                "avg_latency_ms": 0.0,
                "last_message_at": "",
            }
        return dict(row)


@monitor_query_performance
def get_token_usage_overview() -> dict[str, Any]:
    """Return persisted token usage for the dashboard metrics experience.

    Token accounting lives on ``messages``: prompt tokens are attached to the
    user message and generated tokens to the assistant message. Keeping this
    aggregation here makes the metrics page survive process restarts and lets
    it expose an honest all-time view instead of the 30-day in-memory window.
    """

    now = datetime.now(UTC)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    timeline_start = today_start - timedelta(days=29)

    def iso_start(value: datetime) -> str:
        # SQLite stores timestamps as UTC ISO strings with a ``Z`` suffix.
        return value.strftime("%Y-%m-%dT%H:%M:%S")

    def _compute_missing_costs(conn: sqlite3.Connection, start: str | None = None, model: str | None = None) -> float:
        """Compute cost from token counts for messages where cost_usd was never populated."""
        where = "WHERE cost_usd = 0 AND (tokens_in > 0 OR tokens_out > 0)"
        params: tuple[Any, ...] = ()
        if start:
            where += " AND created_at >= ?"
            params = (start,)
        if model:
            where += " AND model_used = ?"
            params = params + (model,)
        try:
            from backend.llm.multi_llm_manager import _compute_cost
        except ImportError:
            return 0.0
        rows = conn.execute(
            f"SELECT model_used, tokens_in, tokens_out FROM messages {where}",
            params,
        ).fetchall()
        total = 0.0
        for row in rows:
            total += _compute_cost(
                model=row["model_used"] or "",
                input_tokens=int(row["tokens_in"] or 0),
                output_tokens=int(row["tokens_out"] or 0),
                conservative_unknown=True,
            )
        return total

    #: The grouping key used by ``model_stats``. Kept as a single literal so
    #: the GROUP BY expression and the per-group cost lookup can never drift
    #: apart. They did once: the query aliased the key to ``name`` while the
    #: Python side still read a non-existent ``model_used`` column, which
    #: raised IndexError and 500'd the whole usage-overview endpoint.
    model_group_key = (
        "COALESCE(NULLIF(model_used, ''), NULLIF(tier_used, ''), 'Não identificado')"
    )

    def _compute_missing_costs_for_group(conn: sqlite3.Connection, group: str) -> float:
        """Compute the not-yet-priced cost of one model group.

        The group key is the same COALESCE expression the GROUP BY uses, so a
        row is counted against exactly the group it appears in. Rows whose
        ``cost_usd`` was never written are priced from their token counts.
        """
        try:
            from backend.llm.multi_llm_manager import _compute_cost
        except ImportError:
            return 0.0
        rows = conn.execute(
            f"""
            SELECT model_used, tokens_in, tokens_out
            FROM messages
            WHERE cost_usd = 0
              AND (tokens_in > 0 OR tokens_out > 0)
              AND {model_group_key} = ?
            """,
            (group,),
        ).fetchall()
        total = 0.0
        for row in rows:
            total += _compute_cost(
                model=row["model_used"] or "",
                input_tokens=int(row["tokens_in"] or 0),
                output_tokens=int(row["tokens_out"] or 0),
                conservative_unknown=True,
            )
        return total

    def period_stats(conn: sqlite3.Connection, start: str | None) -> dict[str, Any]:
        where = "WHERE created_at >= ?" if start else ""
        params: tuple[Any, ...] = (start,) if start else ()
        row = conn.execute(
            f"""
            SELECT
                COALESCE(SUM(COALESCE(tokens_in, 0) + COALESCE(tokens_out, 0)), 0) AS total_tokens,
                COALESCE(SUM(COALESCE(tokens_in, 0)), 0) AS tokens_in,
                COALESCE(SUM(COALESCE(tokens_out, 0)), 0) AS tokens_out,
                COUNT(CASE WHEN role = 'assistant' THEN 1 END) AS requests,
                COUNT(DISTINCT session_id) AS sessions,
                COALESCE(SUM(COALESCE(cost_usd, 0)), 0.0) AS cost,
                COALESCE(SUM(CASE WHEN role = 'assistant' THEN COALESCE(tokens_out, 0) ELSE 0 END), 0) AS generated_tokens,
                COALESCE(SUM(CASE WHEN role = 'assistant' AND latency_ms > 0 THEN latency_ms ELSE 0 END), 0) AS latency_ms
            FROM messages
            {where}
            """,
            params,
        ).fetchone()
        total = int(row["total_tokens"] or 0)
        generated = int(row["generated_tokens"] or 0)
        latency_ms = int(row["latency_ms"] or 0)
        return {
            "total_tokens": total,
            "tokens_in": int(row["tokens_in"] or 0),
            "tokens_out": int(row["tokens_out"] or 0),
            "requests": int(row["requests"] or 0),
            "sessions": int(row["sessions"] or 0),
            "cost": round(float(row["cost"] or 0.0) + _compute_missing_costs(conn, start), 6),
            "avg_tokens_per_second": round(generated / (latency_ms / 1000), 2) if latency_ms > 0 else 0.0,
        }

    def model_stats(conn: sqlite3.Connection) -> list[dict[str, Any]]:
        rows = conn.execute(
            f"""
            SELECT
                {model_group_key} AS name,
                COALESCE(SUM(COALESCE(tokens_in, 0) + COALESCE(tokens_out, 0)), 0) AS total_tokens,
                COALESCE(SUM(COALESCE(tokens_in, 0)), 0) AS tokens_in,
                COALESCE(SUM(COALESCE(tokens_out, 0)), 0) AS tokens_out,
                COUNT(CASE WHEN role = 'assistant' THEN 1 END) AS requests,
                COALESCE(SUM(CASE WHEN role = 'assistant' THEN COALESCE(tokens_out, 0) ELSE 0 END), 0) AS generated_tokens,
                COALESCE(SUM(CASE WHEN role = 'assistant' AND latency_ms > 0 THEN latency_ms ELSE 0 END), 0) AS latency_ms,
                COALESCE(SUM(COALESCE(cost_usd, 0)), 0.0) AS cost
            FROM messages
            GROUP BY name
            ORDER BY total_tokens DESC
            LIMIT 12
            """
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            latency_ms = int(row["latency_ms"] or 0)
            generated = int(row["generated_tokens"] or 0)
            model_name = str(row["name"])
            result.append(
                {
                    "name": model_name,
                    "total_tokens": int(row["total_tokens"] or 0),
                    "tokens_in": int(row["tokens_in"] or 0),
                    "tokens_out": int(row["tokens_out"] or 0),
                    "requests": int(row["requests"] or 0),
                    "cost": round(
                        float(row["cost"] or 0.0)
                        + _compute_missing_costs_for_group(conn, model_name),
                        6,
                    ),
                    "avg_tokens_per_second": round(generated / (latency_ms / 1000), 2) if latency_ms > 0 else 0.0,
                }
            )
        return result

    with get_db() as conn:
        timeline_rows = conn.execute(
            """
            SELECT
                substr(created_at, 1, 10) AS day,
                COALESCE(SUM(COALESCE(tokens_in, 0) + COALESCE(tokens_out, 0)), 0) AS total_tokens,
                COALESCE(SUM(COALESCE(tokens_in, 0)), 0) AS tokens_in,
                COALESCE(SUM(COALESCE(tokens_out, 0)), 0) AS tokens_out,
                COUNT(CASE WHEN role = 'assistant' THEN 1 END) AS requests,
                COALESCE(SUM(CASE WHEN role = 'assistant' THEN COALESCE(tokens_out, 0) ELSE 0 END), 0) AS generated_tokens,
                COALESCE(SUM(CASE WHEN role = 'assistant' AND latency_ms > 0 THEN latency_ms ELSE 0 END), 0) AS latency_ms
            FROM messages
            WHERE created_at >= ?
            GROUP BY day
            ORDER BY day ASC
            """,
            (iso_start(timeline_start),),
        ).fetchall()

        timeline: list[dict[str, Any]] = []
        for row in timeline_rows:
            latency_ms = int(row["latency_ms"] or 0)
            generated = int(row["generated_tokens"] or 0)
            timeline.append(
                {
                    "day": row["day"],
                    "total_tokens": int(row["total_tokens"] or 0),
                    "tokens_in": int(row["tokens_in"] or 0),
                    "tokens_out": int(row["tokens_out"] or 0),
                    "requests": int(row["requests"] or 0),
                    "avg_tokens_per_second": round(generated / (latency_ms / 1000), 2) if latency_ms > 0 else 0.0,
                }
            )

        return {
            "periods": {
                "today": period_stats(conn, iso_start(today_start)),
                "week": period_stats(conn, iso_start(week_start)),
                "month": period_stats(conn, iso_start(month_start)),
                "all": period_stats(conn, None),
            },
            "timeline": timeline,
            "by_model": model_stats(conn),
            "generated_at": time.time(),
            "currency": "USD",
        }


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
    """Record one tool execution.

    ``tool_executions.session_id`` is a *nullable* foreign key: an execution
    that belongs to no known session is stored with a NULL session id.

    It used to be "fixed" by inserting a placeholder ``sessions`` row for an
    unknown session id, which fabricated user-visible sessions (the live
    database had 26 of them) and made them show up in the session list and in
    ``count_active_sessions()``.
    """
    eid = _new_id()
    with get_db() as conn:
        resolved_session_id = session_id
        if session_id:
            known = conn.execute(
                "SELECT 1 FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if known is None:
                resolved_session_id = None
        conn.execute(
            """INSERT INTO tool_executions
               (id, session_id, tool_name, args_json, result_json, success, error, duration_ms)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                eid,
                resolved_session_id,
                tool_name,
                json.dumps(args, default=str),
                json.dumps(result, default=str) if result is not None else None,
                1 if success else 0,
                error,
                duration_ms,
            ),
        )
    return eid


def get_agent_activity(minutes: int = 30) -> list[dict[str, Any]]:
    """Summarise recent agent activity for the dashboard widget."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(m.tier_used, 'UNKNOWN') AS agent,
                   COUNT(*) AS tasks_completed,
                   SUM(CASE WHEN COALESCE(te.failed, 0) > 0 THEN 1 ELSE 0 END) AS tasks_failed,
                   AVG(COALESCE(m.latency_ms, 0)) AS avg_latency_ms,
                   MAX(m.created_at) AS last_activity,
                   MAX(
                       CASE WHEN EXISTS (
                           SELECT 1
                           FROM session_runs sr
                           WHERE sr.session_id = m.session_id
                             AND sr.status = 'running'
                             AND (sr.agent IS NULL OR UPPER(sr.agent) = UPPER(m.tier_used))
                       ) THEN 1 ELSE 0 END
                   ) AS has_active_run
            FROM messages m
            LEFT JOIN (
                SELECT session_id, COUNT(*) AS failed
                FROM tool_executions
                WHERE success = 0
                  AND created_at > datetime('now', printf('-%d minutes', ?))
                GROUP BY session_id
            ) te ON te.session_id = m.session_id
            WHERE m.role = 'assistant'
              AND m.tier_used IS NOT NULL
              AND m.created_at > datetime('now', printf('-%d minutes', ?))
            GROUP BY m.tier_used
            ORDER BY last_activity DESC
            LIMIT 15
            """,
            (minutes, minutes),
        ).fetchall()

    now = datetime.now(UTC)
    activity: list[dict[str, Any]] = []
    for row in rows:
        last = row["last_activity"] or ""
        # A recent assistant message is recent activity, not proof that work
        # is still running. Use the durable execution envelope as the source
        # of truth for the live status shown by the dashboard.
        status = "active" if int(row["has_active_run"] or 0) else "idle"
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
        except Exception:
            pass
        tasks_failed = int(row["tasks_failed"] or 0)
        if tasks_failed > 0 and status != "active":
            status = "error"
        activity.append(
            {
                "agent": row["agent"],
                "status": status,
                "tasks_completed": int(row["tasks_completed"] or 0),
                "tasks_failed": tasks_failed,
                "avg_latency_ms": float(row["avg_latency_ms"] or 0),
                "last_activity": last or now.isoformat(),
            }
        )
    # A live run has a session_runs row before it writes the assistant message.
    # The query above only sees agents that already answered, so the panel
    # showed "—" for the whole generation.
    cutoff = now - timedelta(minutes=minutes)
    with get_db() as conn:
        running_rows = conn.execute(
            """
            SELECT agent, MAX(updated_at) AS last_activity
            FROM session_runs
            WHERE LOWER(status) = 'running'
              AND agent IS NOT NULL
              AND TRIM(agent) <> ''
            GROUP BY agent
            """
        ).fetchall()
    by_name = {str(item["agent"]).upper(): item for item in activity}
    for row in running_rows:
        last = str(row["last_activity"] or "")
        try:
            last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            continue
        if last_dt < cutoff:
            continue
        name = str(row["agent"])
        current = by_name.get(name.upper())
        if current is not None:
            current["status"] = "active"
            continue
        entry = {
            "agent": name,
            "status": "active",
            "tasks_completed": 0,
            "tasks_failed": 0,
            "avg_latency_ms": 0.0,
            "last_activity": last or now.isoformat(),
        }
        activity.append(entry)
        by_name[name.upper()] = entry
    return activity


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
                COALESCE(SUM(CASE
                        WHEN new_content IS NULL OR new_content = '' THEN 0
                        ELSE 1 + LENGTH(new_content) - LENGTH(REPLACE(new_content, char(10), ''))
                    END), 0) AS lines_written
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


def create_user(username: str, email: str, password_hash: str, full_name: str = "") -> dict:
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


#: Columns ``update_user`` is allowed to write. It matches the real
#: ``users`` table: ``id``, ``password_hash`` and ``created_at`` are not
#: updatable. The previous whitelist also named ``role`` and
#: ``preferences``, which do not exist in the table, so those writes were
#: silently dropped (and would have raised "no such column" if they had not
#: been filtered out first).
USER_UPDATE_ALLOWED_COLS: frozenset[str] = frozenset(
    {"username", "email", "full_name", "is_active", "updated_at"}
)


def update_user(user_id: str, **fields: Any) -> dict | None:
    """Update user fields."""
    if not fields:
        return get_user(user_id)
    fields["updated_at"] = _now_iso()
    # Don't allow updating password_hash through this method
    fields.pop("password_hash", None)
    # Whitelist allowed columns
    safe_fields = {k: v for k, v in fields.items() if k in USER_UPDATE_ALLOWED_COLS}
    if not safe_fields:
        return get_user(user_id)
    cols = ", ".join(f"{k} = ?" for k in safe_fields)
    with get_db() as conn:
        conn.execute(f"UPDATE users SET {cols} WHERE id = ?", (*safe_fields.values(), user_id))
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
    return {
        "id": pid,
        "name": name,
        "description": description,
        "resource": resource,
        "action": action,
    }


def assign_permission_to_role(role_id: str, permission_id: str) -> None:
    """Assign a permission to a role."""
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO role_permissions (id, role_id, permission_id) VALUES (?, ?, ?)",
            (_new_id(), role_id, permission_id),
        )


# ───── GIT AUTO-COMMIT HISTORY ──────────────────────────────────────────


def record_git_commit(
    session_id: str | None,
    project_id: str | None,
    file_path: str,
    commit_message: str,
    commit_hash: str | None,
    commit_type: str = "chore",
    scope: str = "",
    strategy: str = "always",
    status: str = "committed",
    diff_preview: str = "",
    error: str | None = None,
) -> dict | None:
    """Record an auto-commit in the database history.

    Returns the recorded commit dict or None if db unavailable.
    """
    cid = _new_id()
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO git_commits
                   (id, session_id, project_id, file_path, commit_message, commit_hash,
                    commit_type, scope, strategy, status, diff_preview, error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    cid,
                    session_id,
                    project_id,
                    file_path,
                    commit_message,
                    commit_hash,
                    commit_type,
                    scope,
                    strategy,
                    status,
                    diff_preview[:1000],
                    error,
                ),
            )
            row = conn.execute("SELECT * FROM git_commits WHERE id = ?", (cid,)).fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.warning("Failed to record git commit: %s", e)
        return None


@monitor_query_performance
def get_git_commits(
    session_id: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Retrieve auto-commit history from the database."""
    conditions = []
    params: list[Any] = []
    if session_id:
        conditions.append("session_id = ?")
        params.append(session_id)
    if project_id:
        conditions.append("project_id = ?")
        params.append(project_id)
    if status:
        conditions.append("status = ?")
        params.append(status)
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    with get_db() as conn:
        rows = conn.execute(
            f"SELECT * FROM git_commits WHERE {where_clause} ORDER BY created_at DESC LIMIT ?",
            (*params, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def get_git_commit(commit_id: str) -> dict | None:
    """Get a single auto-commit record by ID."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM git_commits WHERE id = ?", (commit_id,)).fetchone()
        return dict(row) if row else None


def update_git_commit_status(
    commit_id: str, status: str, commit_hash: str | None = None
) -> dict | None:
    """Update the status of a git commit record."""
    with get_db() as conn:
        if commit_hash:
            conn.execute(
                "UPDATE git_commits SET status = ?, commit_hash = ? WHERE id = ?",
                (status, commit_hash, commit_id),
            )
        else:
            conn.execute(
                "UPDATE git_commits SET status = ? WHERE id = ?",
                (status, commit_id),
            )
    return get_git_commit(commit_id)


@monitor_query_performance
def get_git_commit_statistics(
    project_id: str | None = None, session_id: str | None = None
) -> dict[str, Any]:
    """Get statistics about auto-commits."""
    conditions = []
    params: list[Any] = []
    if project_id:
        conditions.append("project_id = ?")
        params.append(project_id)
    if session_id:
        conditions.append("session_id = ?")
        params.append(session_id)
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    with get_db() as conn:
        status_rows = conn.execute(
            f"SELECT status, COUNT(*) as count FROM git_commits WHERE {where_clause} GROUP BY status",
            params,
        ).fetchall()
        type_rows = conn.execute(
            f"SELECT commit_type, COUNT(*) as count FROM git_commits WHERE {where_clause} AND status = 'committed' GROUP BY commit_type",
            params,
        ).fetchall()
        recent_row = conn.execute(
            f"SELECT COUNT(*) as count FROM git_commits WHERE {where_clause} AND created_at > datetime('now', '-1 day')",
            params,
        ).fetchone()
        total_row = conn.execute(
            f"SELECT COUNT(*) as count FROM git_commits WHERE {where_clause}",
            params,
        ).fetchone()
        return {
            "total": total_row["count"] if total_row else 0,
            "last_24h": recent_row["count"] if recent_row else 0,
            "by_status": {r["status"]: r["count"] for r in status_rows},
            "by_type": {r["commit_type"]: r["count"] for r in type_rows},
        }


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


#: Columns ``update_email_account`` is allowed to write. It matches the real
#: ``email_accounts`` table (``label, host, port, username,
#: password_encrypted, use_ssl, active`` plus ``updated_at``). The previous
#: whitelist named seven columns that do not exist (``email``,
#: ``display_name``, ``imap_server``, ...) so every update was a no-op.
EMAIL_ACCOUNT_UPDATE_ALLOWED_COLS: frozenset[str] = frozenset(
    {
        "label",
        "host",
        "port",
        "username",
        "password_encrypted",
        "use_ssl",
        "active",
        "updated_at",
    }
)


def update_email_account(account_id: str, **fields: Any) -> dict | None:
    """Update email account fields."""
    if not fields:
        return get_email_account(account_id)
    fields["updated_at"] = _now_iso()
    fields.pop("id", None)
    # Whitelist allowed columns
    safe_fields = {
        k: v for k, v in fields.items() if k in EMAIL_ACCOUNT_UPDATE_ALLOWED_COLS
    }
    if not safe_fields:
        return get_email_account(account_id)
    cols = ", ".join(f"{k} = ?" for k in safe_fields)
    with get_db() as conn:
        conn.execute(
            f"UPDATE email_accounts SET {cols} WHERE id = ?", (*safe_fields.values(), account_id)
        )
    return get_email_account(account_id)


def delete_email_account(account_id: str) -> None:
    """Delete an email account."""
    with get_db() as conn:
        conn.execute("DELETE FROM email_accounts WHERE id = ?", (account_id,))


# ───── TODOS ───────────────────────────────────────────

_MAX_TODO_CONTENT_CHARS = 2000


def create_todo(
    session_id: str,
    content: str,
    priority: str = "normal",
) -> dict | None:
    """Create a todo item for a session."""
    tid = _new_id()
    now = _now_iso()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO todos (id, session_id, content, priority, status, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (tid, session_id, content, priority, "pending", now, now),
        )
        row = conn.execute("SELECT * FROM todos WHERE id = ?", (tid,)).fetchone()
    return dict(row) if row else None


def update_todo(
    todo_id: str,
    *,
    session_id: str | None = None,
    content: str | None = None,
    priority: str | None = None,
    status: str | None = None,
) -> dict | None:
    """Update mutable fields on a todo. Returns the updated row."""
    fields: list[str] = []
    values: list[Any] = []
    if content is not None:
        fields.append("content = ?")
        values.append(content[:_MAX_TODO_CONTENT_CHARS])
    if priority is not None:
        fields.append("priority = ?")
        values.append(priority)
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if not fields:
        return get_todo(todo_id)
    now = _now_iso()
    fields.append("updated_at = ?")
    values.append(now)
    values.append(todo_id)
    if session_id is not None:
        fields.append("session_id = ?")
        values.append(session_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE todos SET {', '.join(fields)} WHERE id = ?",
            values,
        )
    return get_todo(todo_id)


def delete_todo(todo_id: str, *, session_id: str | None = None) -> bool:
    """Delete a todo. Returns True if the row existed."""
    with get_db() as conn:
        params: tuple[Any, ...] = (todo_id,)
        if session_id is not None:
            params = (todo_id, session_id)
        cursor = conn.execute(
            "DELETE FROM todos WHERE id = ?"
            + (" AND session_id = ?" if session_id is not None else ""),
            params,
        )
    return cursor.rowcount > 0


def clear_session_todos(session_id: str) -> int:
    """Delete all todos for a session. Returns count deleted."""
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM todos WHERE session_id = ?", (session_id,)
        )
    return cursor.rowcount


def get_todo(todo_id: str) -> dict | None:
    """Return a single todo by id."""
    with get_db() as conn:
        row = conn.execute("SELECT * FROM todos WHERE id = ?", (todo_id,)).fetchone()
    return dict(row) if row else None


def get_session_todos_db(session_id: str) -> list[dict]:
    """Return all todos for a session, ordered by created_at ASC."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM todos WHERE session_id = ? ORDER BY created_at ASC",
            (session_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_todos_by_status(session_id: str, status: str) -> list[dict]:
    """Return todos for a session filtered by status."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM todos WHERE session_id = ? AND status = ? ORDER BY created_at ASC",
            (session_id, status),
        ).fetchall()
    return [dict(r) for r in rows]


# ───── SESSION LIFECYCLE (GARBAGE COLLECTION) ────────────────────────────


_SESSION_GC_SCHEMA_MIGRATED = False


def _ensure_session_gc_schema() -> None:
    """Add ``status`` and ``expired_at`` columns to the ``sessions`` table.

    Idempotent — safe to call multiple times.  Uses PRAGMA table_info to
    check column existence before ALTER TABLE so it works on SQLite.

    A short-lived raw connection is used on purpose: ``init_db`` calls this
    before the pool exists, and a pooled connection would pin the pool to
    whichever database was configured at that moment.
    """
    global _SESSION_GC_SCHEMA_MIGRATED
    if _SESSION_GC_SCHEMA_MIGRATED:
        return
    try:
        with sqlite3.connect(str(DB_PATH), timeout=30) as conn:
            existing = {
                str(row[1])
                for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
            }
            if not existing:
                # No sessions table yet: nothing to repair. The next
                # init_db() creates it with the columns already declared.
                _SESSION_GC_SCHEMA_MIGRATED = True
                return
            if "status" not in existing:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN status TEXT "
                    "NOT NULL DEFAULT 'active' "
                    "CHECK (status IN ('active', 'idle', 'expired'))"
                )
                logger.info("Added 'status' column to sessions table")
            if "expired_at" not in existing:
                conn.execute(
                    "ALTER TABLE sessions ADD COLUMN expired_at TEXT"
                )
                logger.info("Added 'expired_at' column to sessions table")
            conn.commit()
            _SESSION_GC_SCHEMA_MIGRATED = True
    except Exception as exc:
        logger.warning("Session GC schema migration failed: %s", exc)


def list_expired_sessions(ttl_hours: int = 24) -> list[dict]:
    """Return sessions whose ``last_active_at`` is older than ``ttl_hours``.

    Only includes sessions that are not already marked ``expired``.
    """
    _ensure_session_gc_schema()
    cutoff = _now_iso_minus_hours(ttl_hours)
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM sessions
               WHERE (status IS NULL OR status != 'expired')
                 AND last_active_at < ?
               ORDER BY last_active_at ASC""",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]


def _now_iso_minus_hours(hours: int) -> str:
    """Return an ISO-8601 string for ``now - hours``."""
    dt = datetime.now(UTC) - timedelta(hours=hours)
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def mark_session_expired(session_id: str) -> bool:
    """Mark a session as ``expired`` (soft-delete).

    Does **not** delete the session row, only sets ``status`` and
    ``expired_at``.  Returns ``True`` if the session was found.
    """
    _ensure_session_gc_schema()
    with get_db() as conn:
        cursor = conn.execute(
            "UPDATE sessions SET status = 'expired', expired_at = ? WHERE id = ?",
            (_now_iso(), session_id),
        )
    _invalidate_session_cache(session_id)
    return cursor.rowcount > 0


def delete_session_related_data(session_id: str) -> dict[str, int]:
    """Delete all data that belongs to a session.

    Covers the FK-referenced tables (messages, tool executions, routing
    decisions, proposed changes, git commits, agent states) and the todos:
    ``todos.session_id`` carries no foreign key, so the todo rows would
    otherwise be orphaned by the deletion.

    Returns a dict with counts of deleted rows per table.
    """
    counts: dict[str, int] = {}
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM messages WHERE session_id = ?", (session_id,)
        )
        counts["messages"] = cursor.rowcount
        cursor = conn.execute(
            "DELETE FROM tool_executions WHERE session_id = ?", (session_id,)
        )
        counts["tool_executions"] = cursor.rowcount
        cursor = conn.execute(
            "DELETE FROM routing_decisions WHERE session_id = ?", (session_id,)
        )
        counts["routing_decisions"] = cursor.rowcount
        cursor = conn.execute(
            "DELETE FROM proposed_changes WHERE session_id = ?", (session_id,)
        )
        counts["proposed_changes"] = cursor.rowcount
        cursor = conn.execute(
            "DELETE FROM git_commits WHERE session_id = ?", (session_id,)
        )
        counts["git_commits"] = cursor.rowcount
        cursor = conn.execute(
            "DELETE FROM agent_states WHERE session_id = ?", (session_id,)
        )
        counts["agent_states"] = cursor.rowcount
        cursor = conn.execute(
            "DELETE FROM todos WHERE session_id = ?", (session_id,)
        )
        counts["todos"] = cursor.rowcount
    _invalidate_session_cache(session_id)
    return counts


def hard_delete_expired_sessions(before_days: int = 7) -> list[str]:
    """Permanently delete session rows that have been ``expired`` for at
    least ``before_days`` days.

    Returns the list of deleted session IDs.
    """
    _ensure_session_gc_schema()
    cutoff = _now_iso_minus_hours(before_days * 24)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id FROM sessions WHERE status = 'expired' AND expired_at < ?",
            (cutoff,),
        ).fetchall()
        ids = [r["id"] for r in rows]
        for sid in ids:
            conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            _invalidate_session_cache(sid)
        return ids


def get_session_stats() -> dict[str, int]:
    """Return counters for session lifecycle stats.

    Returns:
        ``{"active": N, "expired": N, "total": N}``

    ``active`` counts exactly the sessions the session list shows (the
    soft-deleted ones are excluded), ``expired`` counts the soft-deleted
    sessions, and ``total`` is every session row, so ``active + expired ==
    total``. The list and the stats therefore always agree about the same
    rows instead of contradicting each other.
    """
    _ensure_session_gc_schema()
    with get_db() as conn:
        total_row = conn.execute("SELECT COUNT(*) AS c FROM sessions").fetchone()
        total = int(total_row["c"]) if total_row else 0
        active_row = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE status IS NULL OR status != 'expired'"
        ).fetchone()
        active = int(active_row["c"]) if active_row else 0
        expired_row = conn.execute(
            "SELECT COUNT(*) AS c FROM sessions WHERE status = 'expired'"
        ).fetchone()
        expired = int(expired_row["c"]) if expired_row else 0
    return {"active": active, "expired": expired, "total": total}


# ───── SCHEDULED TASKS ──────────────────────────────────────────


def save_scheduled_task(task_data: dict) -> None:
    """Persist a scheduled task (upsert by id).

    Expects a dict compatible with ``Task.to_dict()`` plus a ``source`` key.
    JSON columns (parameters_json, dependencies_json, metadata_json,
    result_json) are serialized automatically.
    """
    try:
        with get_db() as conn:
            conn.execute(
                """INSERT INTO scheduled_tasks
                   (id, name, task_type, priority, status, handler,
                    parameters_json, dependencies_json, retry_count, max_retries,
                    timeout, interval, auto_retry, result_json, error,
                    execution_time, created_at, updated_at, scheduled_at,
                    started_at, completed_at, source, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                       name = excluded.name,
                       task_type = excluded.task_type,
                       priority = excluded.priority,
                       status = excluded.status,
                       handler = excluded.handler,
                       parameters_json = excluded.parameters_json,
                       dependencies_json = excluded.dependencies_json,
                       retry_count = excluded.retry_count,
                       max_retries = excluded.max_retries,
                       timeout = excluded.timeout,
                       interval = excluded.interval,
                       auto_retry = excluded.auto_retry,
                       result_json = excluded.result_json,
                       error = excluded.error,
                       execution_time = excluded.execution_time,
                       updated_at = excluded.updated_at,
                       scheduled_at = excluded.scheduled_at,
                       started_at = excluded.started_at,
                       completed_at = excluded.completed_at,
                       source = excluded.source,
                       metadata_json = excluded.metadata_json
                """,
                (
                    task_data["task_id"],
                    task_data["name"],
                    task_data.get("task_type", "monitoring"),
                    task_data.get("priority", "normal"),
                    task_data.get("status", "pending"),
                    task_data.get("handler"),
                    json.dumps(task_data.get("parameters", {}))
                    if isinstance(task_data.get("parameters"), dict)
                    else task_data.get("parameters", "{}"),
                    json.dumps(task_data.get("dependencies", []))
                    if isinstance(task_data.get("dependencies"), (list, set))
                    else "[]",
                    task_data.get("retry_count", 0),
                    task_data.get("max_retries", 3),
                    task_data.get("timeout", 300),
                    task_data.get("interval"),
                    1 if task_data.get("auto_retry", True) else 0,
                    json.dumps(task_data.get("result"))
                    if task_data.get("result") is not None
                    else None,
                    task_data.get("error"),
                    task_data.get("execution_time", 0.0),
                    task_data.get("created_at", _now_iso()),
                    task_data.get("updated_at", _now_iso()),
                    task_data.get("scheduled_at"),
                    task_data.get("started_at"),
                    task_data.get("completed_at"),
                    task_data.get("source", "custom"),
                    json.dumps(task_data.get("metadata", {}))
                    if isinstance(task_data.get("metadata"), dict)
                    else task_data.get("metadata", "{}"),
                ),
            )
    except Exception as e:
        logger.warning("Failed to save scheduled task: %s", e)


def delete_scheduled_task(task_id: str) -> None:
    """Remove a scheduled task from the database."""
    try:
        with get_db() as conn:
            conn.execute("DELETE FROM scheduled_tasks WHERE id = ?", (task_id,))
    except Exception as e:
        logger.warning("Failed to delete scheduled task %s: %s", task_id, e)


def load_scheduled_tasks(source: str = "custom") -> list[dict]:
    """Load scheduled tasks from the database, filtered by source."""
    try:
        with get_db() as conn:
            rows = conn.execute(
                "SELECT * FROM scheduled_tasks WHERE source = ? AND status IN ('pending', 'scheduled', 'waiting', 'retrying') ORDER BY CASE priority WHEN 'critical' THEN 1 WHEN 'urgent' THEN 2 WHEN 'high' THEN 3 WHEN 'normal' THEN 4 WHEN 'low' THEN 5 END, created_at ASC",
                (source,),
            ).fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        logger.warning("Failed to load scheduled tasks: %s", e)
        return []


#: Columns ``update_scheduled_task_status`` may write besides ``status`` and
#: ``updated_at``. They match the real ``scheduled_tasks`` table; the column
#: names used to be interpolated straight into the SQL, so a caller passing
#: an unknown key crashed the whole update (and the swallowed exception also
#: lost the status change).
SCHEDULED_TASK_UPDATE_ALLOWED_COLS: frozenset[str] = frozenset(
    {
        "name",
        "task_type",
        "priority",
        "handler",
        "parameters_json",
        "dependencies_json",
        "retry_count",
        "max_retries",
        "timeout",
        "interval",
        "auto_retry",
        "result_json",
        "error",
        "execution_time",
        "scheduled_at",
        "started_at",
        "completed_at",
        "source",
        "metadata_json",
    }
)


def update_scheduled_task_status(task_id: str, status: str, **fields: Any) -> None:
    """Update the status (and optional fields) of a scheduled task.

    The status is written first, in its own transaction, so a later failure
    can never lose it. The extra fields are whitelisted: an unknown column is
    reported and ignored instead of being interpolated into the SQL. A real
    failure is re-raised so the caller sees it instead of it being swallowed.
    """
    with get_db() as conn:
        conn.execute(
            "UPDATE scheduled_tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status, _now_iso(), task_id),
        )

    sets: list[str] = []
    values: list[Any] = []
    for key, value in fields.items():
        if value is None:
            continue
        if key not in SCHEDULED_TASK_UPDATE_ALLOWED_COLS:
            logger.warning(
                "Ignoring unknown scheduled task column %r for task %s", key, task_id
            )
            continue
        sets.append(f"{key} = ?")
        values.append(value)
    if not sets:
        return

    values.append(task_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE scheduled_tasks SET {', '.join(sets)} WHERE id = ?",
            values,
        )


def prune_scheduled_tasks(
    max_age_days: int,
    *,
    dry_run: bool = False,
    db_path: str | Path | None = None,
) -> int:
    """Delete scheduled-task rows that finished before the retention window.

    Recurring tasks completed once per tick accumulate ~1440 rows/day, so the
    queue needs a TTL. Only *terminal* rows carrying a completion timestamp are
    candidates: a pending, scheduled, retrying or running row is live state, and
    a completed row younger than ``max_age_days`` is recent history that stays
    untouched. When ``completed_at`` is missing (legacy rows), ``updated_at`` is
    used so those rows age out as well instead of living forever.

    Returns the number of rows that were (or, with ``dry_run``, would be)
    deleted.
    """
    cutoff = _now_iso_minus_hours(max_age_days * 24)
    where = (
        "status IN ('completed', 'failed', 'cancelled') "
        "AND COALESCE(completed_at, updated_at) < ?"
    )
    with run_state_connection(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'scheduled_tasks'"
        ).fetchone()
        if exists is None:
            # A database that only carries the run-state tables (the run
            # coordinator can be pointed at its own file) has nothing to prune.
            logger.debug("scheduled_tasks table absent; nothing to prune")
            return 0
        row = conn.execute(
            f"SELECT COUNT(*) AS total FROM scheduled_tasks WHERE {where}",
            (cutoff,),
        ).fetchone()
        total = int(row["total"]) if row else 0
        if total and not dry_run:
            conn.execute(
                f"DELETE FROM scheduled_tasks WHERE {where}",
                (cutoff,),
            )
            logger.info(
                "Pruned %d scheduled task row(s) older than %d day(s)", total, max_age_days
            )
    return total


# ───── RUN STATE / RUN COORDINATOR (Fase 1a) ─────────────────────────────


# Copied verbatim from backend/persistence/schemas.sql. The schema file is the
# canonical source (AGENTS.md rule 6) and ``_ensure_current_schema`` applies it
# to every database ``init_db`` touches, so this copy exists only so a caller —
# mainly backend/runtime/run_coordinator.py against an explicit ``db_path`` —
# can make the run tables ready without replaying the whole schema.
_RUN_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_state (
    run_id                 TEXT PRIMARY KEY,
    project_id             TEXT NOT NULL DEFAULT '',
    user_id                TEXT NOT NULL DEFAULT '',
    session_id             TEXT NOT NULL DEFAULT '',
    goal                   TEXT NOT NULL DEFAULT '',
    requirements_json      TEXT NOT NULL DEFAULT '[]',
    constraints_json       TEXT NOT NULL DEFAULT '[]',
    definition_of_done_json TEXT NOT NULL DEFAULT '[]',
    state                  TEXT NOT NULL DEFAULT 'created'
        CHECK (state IN ('created','planning','running','waiting_tool','waiting_approval',
                         'verifying','recovering','paused','completed','failed','cancelled','expired')),
    plan_json              TEXT,
    current_task_id        TEXT,
    retry_count            INTEGER NOT NULL DEFAULT 0,
    budget_json            TEXT NOT NULL DEFAULT '{}',
    provider_json          TEXT NOT NULL DEFAULT '{}',
    memory_refs_json       TEXT NOT NULL DEFAULT '[]',
    artifacts_json         TEXT NOT NULL DEFAULT '[]',
    changed_files_json     TEXT NOT NULL DEFAULT '[]',
    dod_results_json       TEXT,
    usage_tokens           INTEGER NOT NULL DEFAULT 0,
    usage_cost_usd         REAL NOT NULL DEFAULT 0.0,
    usage_tool_calls       INTEGER NOT NULL DEFAULT 0,
    usage_retries          INTEGER NOT NULL DEFAULT 0,
    usage_browser_actions  INTEGER NOT NULL DEFAULT 0,
    usage_subagents        INTEGER NOT NULL DEFAULT 0,
    usage_runtime_seconds  REAL NOT NULL DEFAULT 0.0,
    usage_provider_calls   INTEGER NOT NULL DEFAULT 0,
    created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    heartbeat_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    stop_reason            TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_run_state_session ON run_state(session_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_state_project ON run_state(project_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_state_user ON run_state(user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_state_state ON run_state(state, updated_at DESC);

CREATE TABLE IF NOT EXISTS run_checkpoints (
    checkpoint_id  TEXT PRIMARY KEY,
    run_id         TEXT NOT NULL,
    phase          TEXT NOT NULL
        CHECK (phase IN ('after_planning','before_side_effect','after_side_effect','after_task',
                         'before_verification','after_verification','pause','provider_failover','heartbeat')),
    payload_json   TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    FOREIGN KEY (run_id) REFERENCES run_state(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_run_checkpoints_run_created ON run_checkpoints(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_checkpoints_run_phase ON run_checkpoints(run_id, phase, created_at DESC);

CREATE TABLE IF NOT EXISTS run_side_effects (
    id              INTEGER PRIMARY KEY,
    run_id          TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    kind            TEXT NOT NULL DEFAULT '',
    result_digest   TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE (run_id, idempotency_key),
    FOREIGN KEY (run_id) REFERENCES run_state(run_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_run_side_effects_run ON run_side_effects(run_id, idempotency_key);

CREATE TABLE IF NOT EXISTS run_dead_letters (
    id                   TEXT PRIMARY KEY,
    run_id               TEXT NOT NULL DEFAULT '',
    task_id              TEXT NOT NULL DEFAULT '',
    error_class          TEXT NOT NULL DEFAULT '',
    sanitized_traceback  TEXT NOT NULL DEFAULT '',
    attempts             INTEGER NOT NULL DEFAULT 0,
    last_tool            TEXT,
    last_provider        TEXT,
    last_evidence_json   TEXT NOT NULL DEFAULT '{}',
    recoverability       TEXT NOT NULL DEFAULT 'unknown',
    retry_after          TEXT,
    state                TEXT NOT NULL DEFAULT 'open'
        CHECK (state IN ('open','retrying','requeued','replanned','abandoned','escalated')),
    note                 TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS idx_run_dead_letters_run ON run_dead_letters(run_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_run_dead_letters_state ON run_dead_letters(state, created_at DESC);
"""


def ensure_run_state_schema(db_path: str | Path | None = None) -> None:
    """Create the run-coordinator tables in ``db_path`` (idempotent).

    Every statement is ``CREATE ... IF NOT EXISTS``, so calling this against an
    already-migrated database is a no-op. ``db_path`` defaults to ``DB_PATH``.
    """
    with run_state_connection(db_path) as conn:
        conn.executescript(_RUN_STATE_SCHEMA)


@contextmanager
def run_state_connection(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    """Yield a short-lived connection for run-state persistence.

    Same pragmas as ``SQLiteConnectionPool._create_connection`` (row factory,
    foreign keys, WAL, busy timeout) without going through the global pool: the
    run coordinator points at an explicit ``db_path`` (tests and sidecar
    databases), which the pool cannot express. Writes commit when the block
    exits normally and roll back when it raises.
    """
    target = Path(db_path) if db_path is not None else DB_PATH
    conn = sqlite3.connect(str(target), check_same_thread=False, timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        yield conn
        conn.commit()
    finally:
        conn.close()


def _json_text(value: Any) -> str:
    """Serialize a value the way the other JSON columns in this file do."""
    return json.dumps(value)


def create_run_row(
    *,
    run_id: str,
    project_id: str,
    user_id: str,
    session_id: str,
    goal: str,
    requirements: list[str],
    constraints: list[str],
    definition_of_done: list[str],
    state: str,
    plan: dict[str, Any] | None,
    budget: dict[str, Any],
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Insert one run row, returning it as stored (timestamps included)."""
    now = _now_iso()
    with run_state_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO run_state
               (run_id, project_id, user_id, session_id, goal, requirements_json,
                constraints_json, definition_of_done_json, state, plan_json,
                budget_json, created_at, updated_at, heartbeat_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_id,
                project_id,
                user_id,
                session_id,
                goal,
                _json_text(list(requirements)),
                _json_text(list(constraints)),
                _json_text(list(definition_of_done)),
                state,
                _json_text(plan) if plan is not None else None,
                _json_text(dict(budget)),
                now,
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM run_state WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else {}


def get_run_row(run_id: str, *, db_path: str | Path | None = None) -> dict[str, Any] | None:
    """Return one run row, or ``None`` when it does not exist."""
    with run_state_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM run_state WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


# Columns update_run_row may write. Anything else is a programming error, so it
# raises instead of silently ignoring the request.
_RUN_ROW_MUTABLE_COLUMNS = frozenset(
    {
        "state",
        "plan_json",
        "current_task_id",
        "retry_count",
        "budget_json",
        "provider_json",
        "memory_refs_json",
        "artifacts_json",
        "changed_files_json",
        "dod_results_json",
        "stop_reason",
        "heartbeat_at",
        "updated_at",
    }
)


def update_run_row(
    run_id: str,
    updates: Mapping[str, Any],
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Apply whitelisted column updates to one run, returning the fresh row.

    All columns of one call are written by a single UPDATE, so a progress write
    is atomic. Returns ``None`` when the run does not exist.
    """
    if not updates:
        return get_run_row(run_id, db_path=db_path)
    unknown = set(updates) - _RUN_ROW_MUTABLE_COLUMNS
    if unknown:
        raise ValueError(f"unknown run_state columns: {sorted(unknown)}")
    assignments = ", ".join(f"{column} = ?" for column in updates)
    values: list[Any] = [*updates.values(), run_id]
    with run_state_connection(db_path) as conn:
        conn.execute(
            f"UPDATE run_state SET {assignments} WHERE run_id = ?",
            values,
        )
        row = conn.execute("SELECT * FROM run_state WHERE run_id = ?", (run_id,)).fetchone()
    return dict(row) if row else None


def list_run_rows(
    *,
    project_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
    states: Sequence[str] | None = None,
    limit: int = 100,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return run rows, newest activity first, filtered by the given fields."""
    clauses: list[str] = []
    params: list[Any] = []
    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)
    if session_id:
        clauses.append("session_id = ?")
        params.append(session_id)
    if user_id:
        clauses.append("user_id = ?")
        params.append(user_id)
    if states:
        placeholders = ", ".join("?" for _ in states)
        clauses.append(f"state IN ({placeholders})")
        params.extend(states)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with run_state_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM run_state" + where + " ORDER BY updated_at DESC, run_id DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def insert_checkpoint_row(
    *,
    checkpoint_id: str,
    run_id: str,
    phase: str,
    payload_json: str,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Insert one checkpoint row, returning it as stored."""
    with run_state_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO run_checkpoints (checkpoint_id, run_id, phase, payload_json)
               VALUES (?, ?, ?, ?)""",
            (checkpoint_id, run_id, phase, payload_json),
        )
        row = conn.execute(
            "SELECT * FROM run_checkpoints WHERE checkpoint_id = ?",
            (checkpoint_id,),
        ).fetchone()
    return dict(row) if row else {}


def get_checkpoint_row(
    checkpoint_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return one checkpoint by id, or ``None`` when it does not exist."""
    with run_state_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM run_checkpoints WHERE checkpoint_id = ?",
            (checkpoint_id,),
        ).fetchone()
    return dict(row) if row else None


def latest_checkpoint_row(
    run_id: str,
    *,
    phase: str | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return the newest checkpoint of a run (optionally of one phase).

    Ordering is ``created_at DESC, checkpoint_id DESC``: two checkpoints written
    in the same millisecond still resolve deterministically.
    """
    clauses = ["run_id = ?"]
    params: list[Any] = [run_id]
    if phase:
        clauses.append("phase = ?")
        params.append(phase)
    params.append(1)
    with run_state_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM run_checkpoints WHERE "
            + " AND ".join(clauses)
            + " ORDER BY created_at DESC, checkpoint_id DESC LIMIT ?",
            params,
        ).fetchone()
    return dict(row) if row else None


def list_checkpoint_rows(
    run_id: str,
    *,
    limit: int = 50,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return a run's checkpoints, newest first."""
    with run_state_connection(db_path) as conn:
        rows = conn.execute(
            """SELECT * FROM run_checkpoints
               WHERE run_id = ?
               ORDER BY created_at DESC, checkpoint_id DESC
               LIMIT ?""",
            (run_id, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def get_side_effect_row(
    run_id: str,
    idempotency_key: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return the recorded side effect for a key, or ``None`` if unconfirmed."""
    with run_state_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM run_side_effects WHERE run_id = ? AND idempotency_key = ?",
            (run_id, idempotency_key),
        ).fetchone()
    return dict(row) if row else None


def insert_side_effect_row(
    run_id: str,
    idempotency_key: str,
    *,
    kind: str,
    result_digest: str,
    db_path: str | Path | None = None,
) -> bool:
    """Record a side effect idempotently.

    ``UNIQUE(run_id, idempotency_key)`` plus ``ON CONFLICT DO NOTHING`` makes a
    replayed call a no-op: the first writer wins and the stored digest is kept.
    Returns ``True`` when this call inserted the row.
    """
    with run_state_connection(db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO run_side_effects (run_id, idempotency_key, kind, result_digest)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (run_id, idempotency_key) DO NOTHING""",
            (run_id, idempotency_key, kind, result_digest),
        )
        inserted = cursor.rowcount == 1
    return inserted


# usage metric name -> run_state column that accumulates it.
_USAGE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("tokens", "usage_tokens"),
    ("cost_usd", "usage_cost_usd"),
    ("tool_calls", "usage_tool_calls"),
    ("retries", "usage_retries"),
    ("browser_actions", "usage_browser_actions"),
    ("subagents", "usage_subagents"),
    ("runtime_seconds", "usage_runtime_seconds"),
    ("provider_calls", "usage_provider_calls"),
)

_USAGE_SELECT = ", ".join(column for _, column in _USAGE_COLUMNS)


def record_usage_row(
    run_id: str,
    *,
    tokens: int = 0,
    cost_usd: float = 0.0,
    tool_calls: int = 0,
    retries: int = 0,
    browser_actions: int = 0,
    subagents: int = 0,
    runtime_seconds: float = 0.0,
    provider_calls: int = 0,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Accumulate usage for a run and return the running totals.

    A single ``INSERT ... ON CONFLICT DO UPDATE`` statement does the add, so two
    concurrent writers cannot lose each other's increment. Raises
    ``ValueError`` when the run does not exist rather than inserting an orphan
    usage row with a defaulted state.
    """
    increments: list[Any] = [
        int(tokens),
        float(cost_usd),
        int(tool_calls),
        int(retries),
        int(browser_actions),
        int(subagents),
        float(runtime_seconds),
        int(provider_calls),
    ]
    columns = ", ".join(column for _, column in _USAGE_COLUMNS)
    placeholders = ", ".join("?" for _ in _USAGE_COLUMNS)
    accumulations = ", ".join(
        f"{column} = {column} + excluded.{column}" for _, column in _USAGE_COLUMNS
    )
    with run_state_connection(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM run_state WHERE run_id = ?", (run_id,)
        ).fetchone()
        if exists is None:
            raise ValueError(f"unknown run_id: {run_id}")
        conn.execute(
            f"INSERT INTO run_state (run_id, {columns}) VALUES (?, {placeholders}) "
            f"ON CONFLICT (run_id) DO UPDATE SET {accumulations}",
            (run_id, *increments),
        )
        row = conn.execute(
            f"SELECT {_USAGE_SELECT} FROM run_state WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if row is None:  # pragma: no cover - the insert above just created it
        return {name: 0 for name, _ in _USAGE_COLUMNS}
    return {name: row[column] for name, column in _USAGE_COLUMNS}


def get_usage_row(
    run_id: str,
    *,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Return the accumulated usage totals for a run (zeros when unknown)."""
    with run_state_connection(db_path) as conn:
        row = conn.execute(
            f"SELECT {_USAGE_SELECT} FROM run_state WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if row is None:
        return {name: 0 for name, _ in _USAGE_COLUMNS}
    return {name: row[column] for name, column in _USAGE_COLUMNS}


def insert_dead_letter_row(
    *,
    entry_id: str,
    run_id: str,
    task_id: str,
    error_class: str,
    sanitized_traceback: str,
    attempts: int,
    last_tool: str,
    last_provider: str,
    last_evidence_json: str,
    recoverability: str,
    retry_after: str | None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    """Insert one dead-letter entry, returning it as stored."""
    with run_state_connection(db_path) as conn:
        conn.execute(
            """INSERT INTO run_dead_letters
               (id, run_id, task_id, error_class, sanitized_traceback, attempts,
                last_tool, last_provider, last_evidence_json, recoverability,
                retry_after, state)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
            (
                entry_id,
                run_id,
                task_id,
                error_class,
                sanitized_traceback,
                attempts,
                last_tool,
                last_provider,
                last_evidence_json,
                recoverability,
                retry_after,
            ),
        )
        row = conn.execute(
            "SELECT * FROM run_dead_letters WHERE id = ?",
            (entry_id,),
        ).fetchone()
    return dict(row) if row else {}


def list_dead_letter_rows(
    *,
    run_id: str | None = None,
    state: str | None = "open",
    limit: int = 100,
    db_path: str | Path | None = None,
) -> list[dict[str, Any]]:
    """Return dead-letter entries, newest first, optionally scoped to a run."""
    clauses: list[str] = []
    params: list[Any] = []
    if run_id:
        clauses.append("run_id = ?")
        params.append(run_id)
    if state:
        clauses.append("state = ?")
        params.append(state)
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with run_state_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM run_dead_letters" + where
            + " ORDER BY created_at DESC, id DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def update_dead_letter_row(
    entry_id: str,
    *,
    state: str,
    note: str,
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Move a dead-letter entry to a new state, appending ``note`` to its trail.

    Returns the updated row, or ``None`` when the entry does not exist.
    """
    with run_state_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM run_dead_letters WHERE id = ?",
            (entry_id,),
        ).fetchone()
        if row is None:
            return None
        existing_note = str(row["note"] or "")
        merged_note = f"{existing_note}\n{note}" if existing_note and note else (note or existing_note)
        conn.execute(
            "UPDATE run_dead_letters SET state = ?, note = ?, updated_at = ? WHERE id = ?",
            (state, merged_note, _now_iso(), entry_id),
        )
        updated = conn.execute(
            "SELECT * FROM run_dead_letters WHERE id = ?",
            (entry_id,),
        ).fetchone()
    return dict(updated) if updated else None


# Runs that own no more future work. prune_run_state_tables only deletes these,
# so a paused or still-running run is never dropped by retention.
_TERMINAL_RUN_STATES: tuple[str, ...] = ("completed", "failed", "cancelled", "expired")


def _count_and_delete(
    conn: sqlite3.Connection,
    table: str,
    where: str,
    params: Sequence[Any],
    *,
    dry_run: bool,
) -> int:
    """Count the rows matching ``where`` and delete them unless ``dry_run``."""
    row = conn.execute(
        f"SELECT COUNT(*) AS total FROM {table} WHERE {where}",
        tuple(params),
    ).fetchone()
    total = int(row["total"]) if row else 0
    if total and not dry_run:
        conn.execute(
            f"DELETE FROM {table} WHERE {where}",
            tuple(params),
        )
    return total


def prune_run_state_tables(
    *,
    runs_cutoff: str,
    checkpoints_cutoff: str,
    dead_letters_cutoff: str,
    dry_run: bool = False,
    db_path: str | Path | None = None,
) -> dict[str, int]:
    """Apply retention to the run-state tables.

    * runs         — terminal states whose ``updated_at`` is older than
      ``runs_cutoff``; their checkpoints, side effects and dead letters go with
      them (the foreign keys cascade).
    * checkpoints  — any checkpoint older than ``checkpoints_cutoff``, including
      those of runs that are still alive: checkpoints are history.
    * dead_letters — any entry older than ``dead_letters_cutoff`` (or belonging
      to a run that is being deleted).

    ``dry_run`` reports the counts without deleting. The developer database is
    only touched when ``db_path`` is ``None``.
    """
    with run_state_connection(db_path) as conn:
        run_rows = conn.execute(
            "SELECT run_id FROM run_state WHERE state IN (?, ?, ?, ?) AND updated_at < ?",
            (*_TERMINAL_RUN_STATES, runs_cutoff),
        ).fetchall()
        run_ids = [str(row["run_id"]) for row in run_rows]

        checkpoint_clauses = ["(created_at < ?)"]
        side_effect_clauses: list[str] = []
        dead_letter_clauses = ["(created_at < ?)"]
        checkpoint_params: list[Any] = [checkpoints_cutoff]
        dead_letter_params: list[Any] = [dead_letters_cutoff]
        if run_ids:
            placeholders = ", ".join("?" for _ in run_ids)
            checkpoint_clauses.append(f"run_id IN ({placeholders})")
            checkpoint_params.extend(run_ids)
            side_effect_clauses.append(f"run_id IN ({placeholders})")
            dead_letter_clauses.append(f"run_id IN ({placeholders})")
            dead_letter_params.extend(run_ids)

        checkpoint_where = " OR ".join(checkpoint_clauses)
        dead_letter_where = " OR ".join(dead_letter_clauses)
        # Side effects carry no timestamp of their own: they only age out with
        # the run they belong to.
        side_effect_where = " OR ".join(side_effect_clauses)

        counts = {
            "runs": 0,
            "checkpoints": _count_and_delete(
                conn,
                "run_checkpoints",
                checkpoint_where,
                checkpoint_params,
                dry_run=dry_run,
            ),
            "side_effects": _count_and_delete(
                conn,
                "run_side_effects",
                side_effect_where or "1 = 0",
                run_ids,
                dry_run=dry_run,
            ),
            "dead_letters": _count_and_delete(
                conn,
                "run_dead_letters",
                dead_letter_where,
                dead_letter_params,
                dry_run=dry_run,
            ),
        }
        counts["runs"] = _count_and_delete(
            conn,
            "run_state",
            "run_id IN (SELECT run_id FROM run_state WHERE state IN (?, ?, ?, ?) AND updated_at < ?)",
            (*_TERMINAL_RUN_STATES, runs_cutoff),
            dry_run=dry_run,
        )
    logger.debug("Run-state prune: %s (dry_run=%s)", counts, dry_run)
    return counts
