"""Link persisted chat messages to their durable execution run.

Revision ID: 008_message_run_link
Revises: 007_schemas_sql_parity
Create Date: 2026-09-27

The nullable link is populated by new PRIMARY chat writes. Existing messages
remain valid with a NULL run_id and can still use the legacy text-match fallback
while their original run journal is available.
"""

from __future__ import annotations

from alembic import op

revision = "008_message_run_link"
down_revision = "007_schemas_sql_parity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = {
        str(row[0])
        for row in bind.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "messages" not in tables:
        return

    columns = {
        str(row[1]) for row in bind.exec_driver_sql("PRAGMA table_info(messages)").fetchall()
    }
    if "run_id" not in columns:
        op.execute("ALTER TABLE messages ADD COLUMN run_id TEXT")
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_run_id ON messages(run_id)")


def downgrade() -> None:
    # Keep the nullable column and index: removing the link would discard
    # recovery evidence from live databases and SQLite column drops vary by version.
    pass
