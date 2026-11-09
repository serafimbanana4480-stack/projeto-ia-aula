"""Add cost_usd column to messages table for token cost tracking

Revision ID: 005_add_token_tracking
Revises: 004_email_config
Create Date: 2025-01-12

Idempotency (2026-10-21)
-----------------------
``messages.cost_usd`` is part of ``backend/persistence/schemas.sql``, so a
database built from that file — which is exactly what
``persistence.db.init_db`` creates — already has the column. The bare
``ALTER TABLE messages ADD COLUMN cost_usd`` therefore died with
"duplicate column name: cost_usd" whenever the chain was replayed against
such a database. The column list is checked first, exactly like revisions
006/008/009 do.

The downgrade used to recreate ``messages`` without ``run_id``, silently
destroying the link between a message and the durable run that produced it
(added by revision 008_message_run_link). The column is preserved now, and
so is its index.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "005_add_token_tracking"
down_revision = "004_email_config"
branch_labels = None
depends_on = None


def _existing_columns() -> set[str]:
    bind = op.get_bind()
    return {
        str(row[1]) for row in bind.exec_driver_sql("PRAGMA table_info(messages)").fetchall()
    }


def upgrade() -> None:
    """Add messages.cost_usd when the column is not there yet."""
    bind = op.get_bind()
    tables = {
        str(row[0])
        for row in bind.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "messages" not in tables:
        return
    if "cost_usd" in _existing_columns():
        # Already present (schemas.sql, or a database that was stamped at a
        # later revision): nothing to do.
        return
    op.execute("ALTER TABLE messages ADD COLUMN cost_usd REAL DEFAULT 0.0")


def downgrade() -> None:
    """Recreate messages without cost_usd, keeping messages.run_id intact."""
    columns = _existing_columns()
    if not columns:
        return

    has_run_id = "run_id" in columns
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
            run_id        TEXT,
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)
    carried = "id, session_id, role, content, tier_used, model_used, " \
              "tools_used_json, tokens_in, tokens_out, latency_ms, created_at"
    if has_run_id:
        carried += ", run_id"
    op.execute(
        f"INSERT INTO messages_backup ({carried}) SELECT {carried} FROM messages"
    )
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
    op.execute("CREATE INDEX IF NOT EXISTS idx_messages_run_id ON messages(run_id)")
