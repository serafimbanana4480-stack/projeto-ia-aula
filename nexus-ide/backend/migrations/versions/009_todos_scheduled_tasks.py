"""Create the todo / scheduled-task tables and add sessions.user_id.

Revision ID: 009_todos_scheduled_tasks
Revises: 008_run_state
Create Date: 2026-10-10

Why this exists
---------------
``todos``, ``scheduled_tasks`` and ``sessions.user_id`` are canonical in
``backend/persistence/schemas.sql`` (AGENTS.md rule 6) and are what
``persistence.db.init_db`` provisions at runtime, but no Alembic revision ever
created them. The drift is historical, not recent: these objects predate the
parity effort and were simply never carried into the chain. 007 reconciled an
earlier batch of eight schemas.sql-only tables and 008 added the run-coordinator
tables, which left the two autonomous-task queue tables and the multi-tenant
``sessions.user_id`` column unaccounted for -- so ``alembic upgrade head`` still
diverged from a fresh ``schemas.sql`` database.

This revision closes that last gap. ``backend/tests/persistence/
test_schema_parity.py`` and ``tools/ci/schema_parity.py`` assert the converged
schema; the second migration revision that reproduces the same tables is
intentionally absent (008 owns the run_* tables, this one owns the task queue).

Safety
------
Every statement is idempotent so applying it to a database already built from
``schemas.sql`` (and stamped at the previous head) is a verified no-op rather
than a data-touching migration:

* ``todos`` / ``scheduled_tasks`` are ``CREATE TABLE IF NOT EXISTS``.
* ``sessions.user_id`` is added with a ``PRAGMA table_info`` guard (the same
  pattern as 006/008), so the ``ALTER TABLE`` runs only when the column is
  genuinely missing -- never twice.
* all six indexes are ``CREATE INDEX IF NOT EXISTS``.

This is exactly what ``test_production_stamped_database_upgrades_are_a_no_op``
asserts. Do not convert these to bare ``CREATE``/``ALTER`` statements.

The column and index definitions are copied verbatim from schemas.sql. That
copy is intentional: an Alembic revision is an immutable snapshot and cannot
read schemas.sql at run time. The parity test is what keeps the copy honest.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "009_todos_scheduled_tasks"
down_revision = "008_run_state"
branch_labels = None
depends_on = None

# Verbatim from backend/persistence/schemas.sql. Neither table declares a
# foreign key there: todos.session_id and the scheduled_tasks rows are written
# by the agent runtimes, which keep their referential bookkeeping in-process.
_TABLES: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS todos (
        id              TEXT PRIMARY KEY,
        session_id      TEXT NOT NULL,
        content         TEXT NOT NULL,
        priority        TEXT NOT NULL DEFAULT 'normal'
            CHECK (priority IN ('low', 'normal', 'high')),
        status          TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'in_progress', 'completed', 'cancelled')),
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS scheduled_tasks (
        id              TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        task_type       TEXT NOT NULL DEFAULT 'monitoring',
        priority        TEXT NOT NULL DEFAULT 'normal',
        status          TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending','scheduled','running','completed',
                              'failed','cancelled','retrying','waiting')),
        handler         TEXT,
        parameters_json TEXT NOT NULL DEFAULT '{}',
        dependencies_json TEXT NOT NULL DEFAULT '[]',
        retry_count     INTEGER DEFAULT 0,
        max_retries     INTEGER DEFAULT 3,
        timeout         INTEGER DEFAULT 300,
        interval        INTEGER,
        auto_retry      INTEGER DEFAULT 1,
        result_json     TEXT,
        error           TEXT,
        execution_time  REAL DEFAULT 0.0,
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        scheduled_at    TEXT,
        started_at      TEXT,
        completed_at    TEXT,
        source          TEXT NOT NULL DEFAULT 'custom',
        metadata_json   TEXT NOT NULL DEFAULT '{}'
    )
    """,
)

# sessions.user_id exists in schemas.sql but not in 001_initial_schema, so on a
# chain-built database it is added here; on a schemas.sql-built database the
# guard below makes the ALTER a no-op. Verbatim type from schemas.sql.
_SESSIONS_COLUMNS: tuple[tuple[str, str], ...] = (
    ("user_id", "TEXT"),
)

# Verbatim from backend/persistence/schemas.sql; the parity test fails if these
# drift from the schema file. idx_sessions_user_active depends on sessions.user_id,
# so the guarded ALTER above must run before these are created -- it does.
_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_todos_session ON todos(session_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_todos_session_status ON todos(session_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_status ON scheduled_tasks(status)",
    "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_source ON scheduled_tasks(source)",
    "CREATE INDEX IF NOT EXISTS idx_scheduled_tasks_handler ON scheduled_tasks(handler)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user_active "
    "ON sessions(user_id, last_active_at DESC)",
)


def _existing_sessions_columns() -> set[str]:
    bind = op.get_bind()
    return {
        str(row[1])
        for row in bind.exec_driver_sql("PRAGMA table_info(sessions)").fetchall()
    }


def upgrade() -> None:
    """Create the two task tables and add sessions.user_id, all idempotently."""
    for statement in _TABLES:
        op.execute(statement)

    # Must precede idx_sessions_user_active; guarded so a re-run is a no-op.
    existing = _existing_sessions_columns()
    for name, column_type in _SESSIONS_COLUMNS:
        if name not in existing:
            op.execute(f"ALTER TABLE sessions ADD COLUMN {name} {column_type}")

    for statement in _INDEXES:
        op.execute(statement)


def downgrade() -> None:
    # Deliberately a no-op. todos and scheduled_tasks are the durable
    # autonomous-task queue read by live runtimes, and sessions.user_id is the
    # multi-tenant owner of live sessions; dropping them (or the column) to
    # "undo" a revision that only ever created missing objects would destroy
    # runtime state, and SQLite column drops vary by version. Alembic requires
    # downgrade() to exist; refusing to destroy data is the point.
    pass
