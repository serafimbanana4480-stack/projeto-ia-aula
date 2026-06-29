"""Add cost_usd column to messages table for token cost tracking

Revision ID: 005_add_token_tracking
Revises: 004_email_config
Create Date: 2025-01-12

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "005_add_token_tracking"
down_revision = "004_email_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add cost_usd column to messages table
    op.execute(
        "ALTER TABLE messages ADD COLUMN cost_usd REAL DEFAULT 0.0"
    )


def downgrade() -> None:
    # SQLite does not support DROP COLUMN natively in older versions.
    # To downgrade, recreate the table without the column.
    op.execute("""
        CREATE TABLE IF NOT EXISTS messages_backup (
            id            TEXT PRIMARY KEY,
            session_id    TEXT NOT NULL,
            role          TEXT NOT NULL CHECK (role IN ('user','assistant','system','tool','thinking')),
            content       TEXT NOT NULL,
            tier_used     TEXT,
            model_used    TEXT,
            tools_used_json TEXT,
            tokens_in     INTEGER DEFAULT 0,
            tokens_out    INTEGER DEFAULT 0,
            latency_ms    INTEGER DEFAULT 0,
            created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)
    op.execute("""
        INSERT INTO messages_backup
        SELECT id, session_id, role, content, tier_used, model_used,
               tools_used_json, tokens_in, tokens_out, latency_ms, created_at
        FROM messages
    """)
    op.execute("DROP TABLE messages")
    op.execute("ALTER TABLE messages_backup RENAME TO messages")
    # Recreate indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_session_only ON messages(session_id)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_model ON messages(model_used)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_tier ON messages(tier_used)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC)")
