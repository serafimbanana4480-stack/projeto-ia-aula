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

    # Canonical parity indexes (added 2026-09-26).
    # These 16 indexes exist in backend/persistence/schemas.sql but were never
    # created by the migration chain, so a database built with
    # `alembic upgrade head` was missing all of them. Verbatim from schemas.sql;
    # backend/tests/persistence/test_schema_parity.py fails if they drift.
    for _statement in (
        # projects
        "CREATE INDEX IF NOT EXISTS idx_projects_path ON projects(path)",
        "CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at DESC)",
        # sessions
        "CREATE INDEX IF NOT EXISTS idx_sessions_mode ON sessions(mode)",
        # messages
        "CREATE INDEX IF NOT EXISTS idx_messages_session_only ON messages(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_role ON messages(role)",
        "CREATE INDEX IF NOT EXISTS idx_messages_model ON messages(model_used)",
        "CREATE INDEX IF NOT EXISTS idx_messages_tier ON messages(tier_used)",
        "CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at DESC)",
        # tool_executions
        "CREATE INDEX IF NOT EXISTS idx_tool_executions_session_timestamp "
        "ON tool_executions(session_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_tool_name ON tool_executions(tool_name)",
        "CREATE INDEX IF NOT EXISTS idx_tool_success ON tool_executions(success)",
        # routing_decisions
        "CREATE INDEX IF NOT EXISTS idx_routing_tier ON routing_decisions(tier_chosen)",
        "CREATE INDEX IF NOT EXISTS idx_routing_created ON routing_decisions(created_at DESC)",
        # proposed_changes
        "CREATE INDEX IF NOT EXISTS idx_changes_project ON proposed_changes(project_id)",
        "CREATE INDEX IF NOT EXISTS idx_changes_file ON proposed_changes(file_path)",
        "CREATE INDEX IF NOT EXISTS idx_changes_operation ON proposed_changes(operation)",
    ):
        op.execute(_statement)


def downgrade() -> None:
    # Drop indexes
    for _statement in (
        "DROP INDEX IF EXISTS idx_changes_operation",
        "DROP INDEX IF EXISTS idx_changes_file",
        "DROP INDEX IF EXISTS idx_changes_project",
        "DROP INDEX IF EXISTS idx_routing_created",
        "DROP INDEX IF EXISTS idx_routing_tier",
        "DROP INDEX IF EXISTS idx_tool_success",
        "DROP INDEX IF EXISTS idx_tool_name",
        "DROP INDEX IF EXISTS idx_tool_executions_session_timestamp",
        "DROP INDEX IF EXISTS idx_messages_created",
        "DROP INDEX IF EXISTS idx_messages_tier",
        "DROP INDEX IF EXISTS idx_messages_model",
        "DROP INDEX IF EXISTS idx_messages_role",
        "DROP INDEX IF EXISTS idx_messages_session_only",
        "DROP INDEX IF EXISTS idx_sessions_mode",
        "DROP INDEX IF EXISTS idx_projects_updated",
        "DROP INDEX IF EXISTS idx_projects_path",
        "DROP INDEX IF EXISTS idx_changes_pending",
        "DROP INDEX IF EXISTS idx_changes_session",
        "DROP INDEX IF EXISTS idx_routing_session",
        "DROP INDEX IF EXISTS idx_tool_session",
        "DROP INDEX IF EXISTS idx_messages_session",
        "DROP INDEX IF EXISTS idx_sessions_active",
        "DROP INDEX IF EXISTS idx_sessions_project",
    ):
        op.execute(_statement)

    # Drop tables
    op.execute("DROP TABLE IF EXISTS proposed_changes")
    op.execute("DROP TABLE IF EXISTS routing_decisions")
    op.execute("DROP TABLE IF EXISTS tool_executions")
    op.execute("DROP TABLE IF EXISTS messages")
    op.execute("DROP TABLE IF EXISTS sessions")
    op.execute("DROP TABLE IF EXISTS projects")
