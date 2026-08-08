"""Add correlated execution envelope fields to durable session runs.

Revision ID: 006_execution_envelope
Revises: 005_add_token_tracking
Create Date: 2026-08-08

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "006_execution_envelope"
down_revision = "005_add_token_tracking"
branch_labels = None
depends_on = None


_COLUMNS: tuple[tuple[str, str], ...] = (
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


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    return {str(row[1]) for row in bind.exec_driver_sql("PRAGMA table_info(session_runs)").fetchall()}


def upgrade() -> None:
    """Add only missing columns so old SQLite fixtures remain readable."""
    existing = _existing_columns()
    for name, column_type in _COLUMNS:
        if name not in existing:
            op.execute(f"ALTER TABLE session_runs ADD COLUMN {name} {column_type}")

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_runs_session_updated "
        "ON session_runs(session_id, updated_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_runs_correlation_updated "
        "ON session_runs(correlation_id, updated_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_session_runs_mission_updated "
        "ON session_runs(mission_id, updated_at)"
    )


def downgrade() -> None:
    """Remove indexes only; SQLite column removal is not portable enough."""
    op.execute("DROP INDEX IF EXISTS idx_session_runs_session_updated")
    op.execute("DROP INDEX IF EXISTS idx_session_runs_correlation_updated")
    op.execute("DROP INDEX IF EXISTS idx_session_runs_mission_updated")
