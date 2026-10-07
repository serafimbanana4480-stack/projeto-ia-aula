"""Create the tables that only ever existed in schemas.sql.

Revision ID: 007_schemas_sql_parity
Revises: 006_execution_envelope
Create Date: 2026-09-26

Why this exists
---------------
``backend/persistence/schemas.sql`` is the canonical schema (AGENTS.md rule 6)
and is what ``persistence.db.init_db`` executes on a fresh database. Until this
revision the Alembic chain never created eight of those tables, so
``alembic upgrade head`` on an empty database could not even finish: 006 does
``ALTER TABLE session_runs`` and no earlier revision had ever created it.

With this revision the two sources converge, and
``backend/tests/persistence/test_schema_parity.py`` asserts it (tables, columns
and indexes), so the next divergence fails CI instead of a human's afternoon.

Safety
------
Every statement is ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT
EXISTS``. Existing databases are already stamped at 006 by
``persistence.db._stamp_alembic`` and already have these tables from
``schemas.sql``, so applying this revision to them is a verified no-op rather
than a data-touching migration. Do not convert these to bare CREATE.

The column definitions below are copied verbatim from schemas.sql. That copy is
intentional: an Alembic revision must be an immutable snapshot, so it cannot
read schemas.sql at run time. The parity test is what keeps the copy honest.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "007_schemas_sql_parity"
down_revision = "006_execution_envelope"
branch_labels = None
depends_on = None

_TABLES: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS agent_states (
        id              TEXT PRIMARY KEY,
        agent_name      TEXT NOT NULL,
        session_id      TEXT NOT NULL,
        project_path    TEXT NOT NULL DEFAULT '',
        memory_tier     TEXT NOT NULL CHECK (memory_tier IN ('short_term', 'medium_term', 'long_term')),
        key             TEXT NOT NULL,
        value           TEXT NOT NULL DEFAULT '{}',
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
        access_count    INTEGER DEFAULT 0,
        importance_score REAL DEFAULT 0.5 CHECK (importance_score >= 0.0 AND importance_score <= 1.0),
        UNIQUE(agent_name, session_id, project_path, memory_tier, key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS git_commits (
        id              TEXT PRIMARY KEY,
        session_id      TEXT,
        project_id      TEXT,
        file_path       TEXT NOT NULL,
        commit_message  TEXT NOT NULL,
        commit_hash     TEXT,
        commit_type     TEXT,
        scope           TEXT,
        strategy        TEXT NOT NULL DEFAULT 'always',
        status          TEXT NOT NULL DEFAULT 'committed'
            CHECK (status IN ('committed', 'pending_review', 'failed', 'rejected')),
        diff_preview    TEXT,
        error           TEXT,
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS peer_review_requests (
        review_id      TEXT PRIMARY KEY,
        artifact_id    TEXT NOT NULL,
        artifact_type  TEXT NOT NULL
            CHECK (artifact_type IN ('code', 'design', 'test', 'config')),
        author_agent   TEXT NOT NULL,
        content_hash   TEXT NOT NULL,
        status         TEXT NOT NULL DEFAULT 'pending'
            CHECK (status IN ('pending', 'in_review', 'approved',
                              'changes_requested', 'rejected')),
        created_at     TEXT NOT NULL,
        updated_at     TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS peer_review_results (
        result_id       TEXT PRIMARY KEY,
        review_id       TEXT NOT NULL,
        reviewer_agent  TEXT NOT NULL,
        status          TEXT NOT NULL
            CHECK (status IN ('approved', 'changes_requested', 'rejected')),
        comments        TEXT NOT NULL DEFAULT '[]',
        criteria_scores TEXT NOT NULL DEFAULT '{}',
        created_at      TEXT NOT NULL,
        FOREIGN KEY (review_id)
            REFERENCES peer_review_requests(review_id)
            ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS persistent_memories (
        id              TEXT PRIMARY KEY,
        user_id         TEXT,
        session_id      TEXT,
        project_id      TEXT,
        content         TEXT NOT NULL,
        summary         TEXT,
        embedding_json  TEXT,
        memory_type     TEXT,
        tags            TEXT,
        source          TEXT,
        file_path       TEXT,
        language        TEXT,
        kind            TEXT DEFAULT 'semantic',
        related_memory_ids TEXT,
        importance      REAL,
        created_at      REAL,
        last_accessed_at REAL,
        access_count    INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS whiteboard_entries (
        entry_id         TEXT PRIMARY KEY,
        topic            TEXT NOT NULL,
        author_agent     TEXT NOT NULL,
        content          TEXT NOT NULL,
        timestamp        TEXT NOT NULL,
        importance       REAL NOT NULL DEFAULT 0.5
            CHECK (importance >= 0.0 AND importance <= 1.0),
        tags             TEXT NOT NULL DEFAULT '[]',
        related_entries  TEXT NOT NULL DEFAULT '[]',
        archived         INTEGER NOT NULL DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS whiteboard_entry_links (
        id              TEXT PRIMARY KEY,
        entry_id_1      TEXT NOT NULL,
        entry_id_2      TEXT NOT NULL,
        relation_type   TEXT NOT NULL DEFAULT 'related',
        created_at      TEXT NOT NULL,
        UNIQUE(entry_id_1, entry_id_2, relation_type)
    )
    """,
)

# Copied verbatim from schemas.sql; the parity test fails if these drift.
# session_runs is absent on purpose: 006 owns it (it has to, since 006 ALTERs it)
# and 006 also creates the three session_runs_* indexes it needs.
_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_agent_states_lookup "
    "ON agent_states(agent_name, session_id, project_path, memory_tier, key)",
    "CREATE INDEX IF NOT EXISTS idx_agent_states_agent ON agent_states(agent_name)",
    "CREATE INDEX IF NOT EXISTS idx_agent_states_tier ON agent_states(memory_tier)",
    "CREATE INDEX IF NOT EXISTS idx_agent_states_project ON agent_states(project_path)",
    "CREATE INDEX IF NOT EXISTS idx_agent_states_importance "
    "ON agent_states(importance_score DESC)",
    "CREATE INDEX IF NOT EXISTS idx_agent_states_agent_tier_updated "
    "ON agent_states(agent_name, memory_tier, updated_at)",
    "CREATE INDEX IF NOT EXISTS idx_git_commits_session ON git_commits(session_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_git_commits_project ON git_commits(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_git_commits_status ON git_commits(status)",
    "CREATE INDEX IF NOT EXISTS idx_git_commits_hash ON git_commits(commit_hash)",
    "CREATE INDEX IF NOT EXISTS idx_git_commits_created ON git_commits(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pr_artifact ON peer_review_requests(artifact_id)",
    "CREATE INDEX IF NOT EXISTS idx_pr_status ON peer_review_requests(status)",
    "CREATE INDEX IF NOT EXISTS idx_pr_results_review ON peer_review_results(review_id)",
    "CREATE INDEX IF NOT EXISTS idx_pm_user ON persistent_memories(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_pm_session ON persistent_memories(session_id)",
    "CREATE INDEX IF NOT EXISTS idx_pm_project ON persistent_memories(project_id)",
    "CREATE INDEX IF NOT EXISTS idx_pm_type ON persistent_memories(memory_type)",
    "CREATE INDEX IF NOT EXISTS idx_pm_source ON persistent_memories(source)",
    "CREATE INDEX IF NOT EXISTS idx_pm_accessed ON persistent_memories(last_accessed_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_pm_created ON persistent_memories(created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_wb_topic ON whiteboard_entries(topic)",
    "CREATE INDEX IF NOT EXISTS idx_wb_author ON whiteboard_entries(author_agent)",
    "CREATE INDEX IF NOT EXISTS idx_wb_timestamp ON whiteboard_entries(timestamp)",
    "CREATE INDEX IF NOT EXISTS idx_wb_archived ON whiteboard_entries(archived)",
    "CREATE INDEX IF NOT EXISTS idx_wb_links_1 ON whiteboard_entry_links(entry_id_1)",
    "CREATE INDEX IF NOT EXISTS idx_wb_links_2 ON whiteboard_entry_links(entry_id_2)",
)


def upgrade() -> None:
    for statement in _TABLES:
        op.execute(statement)
    for statement in _INDEXES:
        op.execute(statement)


def downgrade() -> None:
    # Deliberately a no-op. These tables are canonical in schemas.sql and are
    # read by live run persistence, so dropping them to "undo" a revision that
    # only ever created missing tables would destroy runtime state. Alembic
    # requires a downgrade() to exist; refusing to destroy data is the point.
    pass
