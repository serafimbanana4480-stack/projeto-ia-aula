"""Carry the session soft-delete columns and the runtime-only tables into
the migration chain.

Revision ID: 010_session_gc_and_observability
Revises: 009_todos_scheduled_tasks
Create Date: 2026-10-21

Why this exists
---------------
Three objects existed in the live database but not in ``schemas.sql`` and not
in the Alembic chain:

* ``sessions.status`` and ``sessions.expired_at`` — the soft-delete marker
  the session garbage collector writes. They were added at runtime by
  ``persistence.db._ensure_session_gc_schema`` with an ``ALTER TABLE``, so a
  database built from the schema file did not have them at all.
* ``structured_logs`` — the durable observability log, created on demand by
  ``backend/observability/log_store.py``.
* ``usage_ledger`` — the durable LLM spend ledger, created on demand by
  ``backend/llm/cost_governor.py``.

Because the schema parity test only compared the Alembic chain with
``schemas.sql``, that drift was invisible: both sources agreed with each
other and both disagreed with the running database. The parity test now also
compares a freshly built live-shaped schema, and this revision closes the
gap.

Safety
------
Every statement is idempotent: the two columns are added behind a
``PRAGMA table_info`` guard (the same pattern as 006/008/009) and the two
tables are created with ``IF NOT EXISTS``. Applying this revision to a
database that already has the objects is a verified no-op, which is what
``test_production_stamped_database_upgrades_are_a_no_op`` asserts.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "010_session_gc_and_observability"
down_revision = "009_todos_scheduled_tasks"
branch_labels = None
depends_on = None

# The session soft-delete columns. Verbatim from backend/persistence/schemas.sql.
_SESSION_COLUMNS: tuple[tuple[str, str], ...] = (
    (
        "status",
        "TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'idle', 'expired'))",
    ),
    ("expired_at", "TEXT"),
)

# Verbatim from backend/persistence/schemas.sql (and from the runtime
# modules that create these tables on demand).
_TABLES: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS structured_logs (
        id          TEXT PRIMARY KEY,
        timestamp   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        level       TEXT NOT NULL,
        message     TEXT NOT NULL,
        agent       TEXT,
        session_id  TEXT,
        task_id     TEXT,
        extra_json  TEXT,
        correlation_id TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS usage_ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        day TEXT NOT NULL,
        provider TEXT DEFAULT '',
        model TEXT DEFAULT '',
        input_tokens INTEGER DEFAULT 0,
        output_tokens INTEGER DEFAULT 0,
        cost_usd REAL DEFAULT 0.0,
        session_id TEXT DEFAULT '',
        run_id TEXT DEFAULT ''
    )
    """,
)

# Verbatim from backend/persistence/schemas.sql.
_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_logs_session ON structured_logs(session_id, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_logs_agent ON structured_logs(agent, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_logs_level ON structured_logs(level, timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_logs_time ON structured_logs(timestamp DESC)",
    "CREATE INDEX IF NOT EXISTS idx_usage_ledger_day ON usage_ledger(day)",
    "CREATE INDEX IF NOT EXISTS idx_usage_ledger_run ON usage_ledger(run_id)",
)


def _existing_sessions_columns() -> set[str]:
    bind = op.get_bind()
    return {
        str(row[1])
        for row in bind.exec_driver_sql("PRAGMA table_info(sessions)").fetchall()
    }


def upgrade() -> None:
    """Create the two runtime-only tables and add the session columns."""
    for statement in _TABLES:
        op.execute(statement)

    existing = _existing_sessions_columns()
    if existing:
        for name, column_type in _SESSION_COLUMNS:
            if name not in existing:
                op.execute(f"ALTER TABLE sessions ADD COLUMN {name} {column_type}")

    for statement in _INDEXES:
        op.execute(statement)


def downgrade() -> None:
    # Deliberately a no-op. structured_logs and usage_ledger are written by
    # live runtimes and the session columns hold the garbage collector's
    # soft-delete state; dropping them (or the columns) to "undo" a revision
    # that only ever created missing objects would destroy runtime state, and
    # SQLite column drops vary by version. Alembic requires a downgrade() to
    # exist; refusing to destroy data is the point.
    pass
