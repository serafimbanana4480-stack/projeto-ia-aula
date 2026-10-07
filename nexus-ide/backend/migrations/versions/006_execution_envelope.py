"""Add correlated execution envelope fields to durable session runs.

Revision ID: 006_execution_envelope
Revises: 005_add_token_tracking
Create Date: 2026-08-08

Note (2026-09-26): this revision used to ALTER ``session_runs`` without ever
creating it, so ``alembic upgrade head`` on an empty database died with
``sqlite3.OperationalError: no such table: session_runs``. The table is
canonical in ``backend/persistence/schemas.sql`` and nothing in the chain
created it. It is now created here, IF NOT EXISTS, before the ALTERs:

* fresh database  -> CREATE runs here, the ALTERs below are no-ops (the
  columns are already in the definition), indexes are created.
* production DB   -> the table already exists (schemas.sql) and already has the
  envelope columns, so CREATE is a no-op and the ALTERs are no-ops.

``backend/tests/persistence/test_schema_parity.py`` asserts the resulting
schema equals a fresh ``schemas.sql`` database.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "006_execution_envelope"
down_revision = "005_add_token_tracking"
branch_labels = None
depends_on = None


_COLUMNS: tuple[tuple[str, str], ...] = (
    # goal_id belongs here. It is the first entry of
    # persistence.db._EXECUTION_ENVELOPE_COLUMNS and is present in schemas.sql,
    # so it is an envelope field -- but this revision never added it, and a
    # legacy pre-envelope table therefore could not receive the
    # idx_session_runs_goal_updated index below. Added 2026-09-26; the upgrade
    # skips it when the column is already there, so production is unaffected.
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

# Verbatim from backend/persistence/schemas.sql.
_CREATE_SESSION_RUNS = """
CREATE TABLE IF NOT EXISTS session_runs (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed', 'cancelled', 'interrupted')),
    agent           TEXT,
    phase           TEXT NOT NULL DEFAULT 'starting',
    prompt          TEXT NOT NULL DEFAULT '',
    partial_output  TEXT NOT NULL DEFAULT '',
    checkpoint_json TEXT NOT NULL DEFAULT '{}',
    usage_json      TEXT NOT NULL DEFAULT '{}',
    error           TEXT,
    goal_id         TEXT,
    mission_id      TEXT,
    correlation_id  TEXT,
    mode            TEXT,
    execution_state TEXT,
    provider        TEXT,
    model           TEXT,
    error_category  TEXT,
    retry_after     INTEGER,
    evidence_json   TEXT,
    started_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    finished_at     TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
)
"""

# All six session_runs indexes from schemas.sql, not just the three this
# revision originally created, so the Alembic path converges on the canonical
# schema instead of leaving a half-indexed table behind.
_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_session_runs_session "
    "ON session_runs(session_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_session_runs_active ON session_runs(status, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_session_runs_session_updated "
    "ON session_runs(session_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_session_runs_correlation_updated "
    "ON session_runs(correlation_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_session_runs_mission_updated "
    "ON session_runs(mission_id, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_session_runs_goal_updated "
    "ON session_runs(goal_id, updated_at)",
)


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    return {str(row[1]) for row in bind.exec_driver_sql("PRAGMA table_info(session_runs)").fetchall()}


def upgrade() -> None:
    """Add only missing columns so old SQLite fixtures remain readable."""
    # Must precede the ALTERs: on a fresh database the table does not exist yet.
    op.execute(_CREATE_SESSION_RUNS)

    existing = _existing_columns()
    for name, column_type in _COLUMNS:
        if name not in existing:
            op.execute(f"ALTER TABLE session_runs ADD COLUMN {name} {column_type}")

    for statement in _INDEXES:
        op.execute(statement)


def downgrade() -> None:
    """Remove indexes only; SQLite column removal is not portable enough."""
    for statement in reversed(_INDEXES):
        name = statement.split("IF NOT EXISTS ", 1)[1].split(" ", 1)[0]
        op.execute(f"DROP INDEX IF EXISTS {name}")
