"""Initial schema

Revision ID: 001_initial
Revises:
Create Date: 2025-01-12

"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Apply PRAGMA settings
    op.execute("PRAGMA journal_mode = WAL")
    op.execute("PRAGMA synchronous = NORMAL")
    op.execute("PRAGMA foreign_keys = ON")

    # Create projects table
    op.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id            TEXT PRIMARY KEY,
            name          TEXT NOT NULL,
            path          TEXT NOT NULL,
            description   TEXT,
            mode          TEXT DEFAULT 'auto',
            preferred_model TEXT,
            trust         INTEGER DEFAULT 0,
            created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    # Create sessions table
    op.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id            TEXT PRIMARY KEY,
            project_id    TEXT,
            title         TEXT,
            mode          TEXT DEFAULT 'auto',
            started_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            last_active_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            context_json  TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        )
    """)

    # Create indexes for sessions
    op.execute("CREATE INDEX IF NOT EXISTS idx_sessions_project ON sessions(project_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(last_active_at DESC)")

    # Create messages table
    op.execute("""
        CREATE TABLE IF NOT EXISTS messages (
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

    # Create indexes for messages
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at)"
    )

    # Create tool_executions table
    op.execute("""
        CREATE TABLE IF NOT EXISTS tool_executions (
            id            TEXT PRIMARY KEY,
            session_id    TEXT,
            tool_name     TEXT NOT NULL,
            args_json     TEXT,
            result_json   TEXT,
            success       INTEGER DEFAULT 1,
            error         TEXT,
            duration_ms   INTEGER DEFAULT 0,
            created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)

    # Create indexes for tool_executions
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_tool_session ON tool_executions(session_id, created_at)"
    )

    # Create routing_decisions table
    op.execute("""
        CREATE TABLE IF NOT EXISTS routing_decisions (
            id            TEXT PRIMARY KEY,
            session_id    TEXT,
            user_input    TEXT NOT NULL,
            tier_chosen   TEXT NOT NULL,
            reason        TEXT,
            confidence    REAL,
            word_count    INTEGER,
            decision_ms   INTEGER DEFAULT 0,
            created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
        )
    """)

    # Create indexes for routing_decisions
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_routing_session ON routing_decisions(session_id, created_at)"
    )

    # Create proposed_changes table
    op.execute("""
        CREATE TABLE IF NOT EXISTS proposed_changes (
            id            TEXT PRIMARY KEY,
            session_id    TEXT NOT NULL,
            project_id    TEXT,
            file_path     TEXT NOT NULL,
            operation     TEXT NOT NULL CHECK (operation IN ('create','modify','delete')),
            diff          TEXT,
            new_content   TEXT,
            applied       INTEGER DEFAULT 0,
            applied_at    TEXT,
            created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
        )
    """)

    # Create indexes for proposed_changes
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_changes_session ON proposed_changes(session_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_changes_pending ON proposed_changes(applied) WHERE applied = 0"
    )


def downgrade() -> None:
    # Drop indexes
    op.execute("DROP INDEX IF EXISTS idx_changes_pending")
    op.execute("DROP INDEX IF EXISTS idx_changes_session")
    op.execute("DROP INDEX IF EXISTS idx_routing_session")
    op.execute("DROP INDEX IF EXISTS idx_tool_session")
    op.execute("DROP INDEX IF EXISTS idx_messages_session")
    op.execute("DROP INDEX IF EXISTS idx_sessions_active")
    op.execute("DROP INDEX IF EXISTS idx_sessions_project")

    # Drop tables
    op.execute("DROP TABLE IF EXISTS proposed_changes")
    op.execute("DROP TABLE IF EXISTS routing_decisions")
    op.execute("DROP TABLE IF EXISTS tool_executions")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS projects")
