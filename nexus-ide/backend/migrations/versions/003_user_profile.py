"""Add user profile, routines and persistent memories tables

Revision ID: 003_user_profile
Revises: 002_add_rbac
Create Date: 2025-01-12

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "003_user_profile"
down_revision = "002_add_rbac"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id              TEXT PRIMARY KEY,
            preferences_json     TEXT NOT NULL DEFAULT '{}',
            routines_json        TEXT NOT NULL DEFAULT '[]',
            favorite_projects_json TEXT NOT NULL DEFAULT '[]',
            learned_facts_json   TEXT NOT NULL DEFAULT '[]',
            evolution_summary    TEXT NOT NULL DEFAULT '',
            created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_routines (
            id              TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL,
            name            TEXT NOT NULL,
            description     TEXT,
            schedule_cron   TEXT,
            last_executed   TEXT,
            execution_count INTEGER DEFAULT 0,
            success_count   INTEGER DEFAULT 0,
            active          INTEGER DEFAULT 1,
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS user_memories (
            id              TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL,
            content         TEXT NOT NULL,
            memory_type     TEXT NOT NULL CHECK (memory_type IN ('preference','fact','routine','insight')),
            importance      REAL DEFAULT 0.5,
            created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            access_count    INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    op.execute("CREATE INDEX IF NOT EXISTS idx_user_routines_user ON user_routines(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_memories_user ON user_memories(user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_user_memories_type ON user_memories(memory_type)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_memories_importance ON user_memories(importance DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_user_memories_created ON user_memories(created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_user_memories_created")
    op.execute("DROP INDEX IF EXISTS idx_user_memories_importance")
    op.execute("DROP INDEX IF EXISTS idx_user_memories_type")
    op.execute("DROP INDEX IF EXISTS idx_user_memories_user")
    op.execute("DROP INDEX IF EXISTS idx_user_routines_user")
    op.execute("DROP TABLE IF EXISTS user_memories")
    op.execute("DROP TABLE IF EXISTS user_routines")
    op.execute("DROP TABLE IF EXISTS user_profiles")
