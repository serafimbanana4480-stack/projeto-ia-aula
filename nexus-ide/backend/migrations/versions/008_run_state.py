"""Create the run-coordinator tables (Fase 1a).

Revision ID: 008_run_state
Revises: 008_message_run_link
Create Date: 2026-10-10

``backend/runtime/run_coordinator.py`` needs four tables that the chain never
created: ``run_state``, ``run_checkpoints``, ``run_side_effects`` and
``run_dead_letters``. ``backend/persistence/schemas.sql`` is the canonical
schema and already defines them (``persistence.db._ensure_current_schema``
applies it on every ``init_db``), so this revision only has to bring the
Alembic route to the same place.

Safety
-----
Every statement is ``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT
EXISTS``. A database built from ``schemas.sql`` and stamped at the previous
head already has all four tables and their indexes, so applying this revision
to it is a verified no-op — exactly what
``backend/tests/persistence/test_schema_parity.py::
test_production_stamped_database_upgrades_are_a_no_op`` asserts. Do not
convert these to bare ``CREATE`` statements.

The column definitions are copied verbatim from schemas.sql. That copy is
intentional: an Alembic revision is an immutable snapshot and cannot read
schemas.sql at run time. The parity test is what keeps the copy honest.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "008_run_state"
down_revision = "008_message_run_link"
branch_labels = None
depends_on = None

# Verbatim from backend/persistence/schemas.sql. Foreign keys are declared here
# exactly as there: run_checkpoints and run_side_effects cascade away with
# their run, while run_dead_letters deliberately has none because a parked
# failure outlives the run that produced it.
_TABLES: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS run_state (
        run_id                 TEXT PRIMARY KEY,
        project_id             TEXT NOT NULL DEFAULT '',
        user_id                TEXT NOT NULL DEFAULT '',
        session_id             TEXT NOT NULL DEFAULT '',
        goal                   TEXT NOT NULL DEFAULT '',
        requirements_json      TEXT NOT NULL DEFAULT '[]',
        constraints_json       TEXT NOT NULL DEFAULT '[]',
        definition_of_done_json TEXT NOT NULL DEFAULT '[]',
        state                  TEXT NOT NULL DEFAULT 'created'
            CHECK (state IN ('created','planning','running','waiting_tool','waiting_approval',
                             'verifying','recovering','paused','completed','failed','cancelled','expired')),
        plan_json              TEXT,
        current_task_id        TEXT,
        retry_count            INTEGER NOT NULL DEFAULT 0,
        budget_json            TEXT NOT NULL DEFAULT '{}',
        provider_json          TEXT NOT NULL DEFAULT '{}',
        memory_refs_json       TEXT NOT NULL DEFAULT '[]',
        artifacts_json         TEXT NOT NULL DEFAULT '[]',
        changed_files_json     TEXT NOT NULL DEFAULT '[]',
        dod_results_json       TEXT,
        usage_tokens           INTEGER NOT NULL DEFAULT 0,
        usage_cost_usd         REAL NOT NULL DEFAULT 0.0,
        usage_tool_calls       INTEGER NOT NULL DEFAULT 0,
        usage_retries          INTEGER NOT NULL DEFAULT 0,
        usage_browser_actions  INTEGER NOT NULL DEFAULT 0,
        usage_subagents        INTEGER NOT NULL DEFAULT 0,
        usage_runtime_seconds  REAL NOT NULL DEFAULT 0.0,
        usage_provider_calls   INTEGER NOT NULL DEFAULT 0,
        created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        heartbeat_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        stop_reason            TEXT NOT NULL DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_checkpoints (
        checkpoint_id  TEXT PRIMARY KEY,
        run_id         TEXT NOT NULL,
        phase          TEXT NOT NULL
            CHECK (phase IN ('after_planning','before_side_effect','after_side_effect','after_task',
                             'before_verification','after_verification','pause','provider_failover','heartbeat')),
        payload_json   TEXT NOT NULL DEFAULT '{}',
        created_at     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        FOREIGN KEY (run_id) REFERENCES run_state(run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_side_effects (
        id              INTEGER PRIMARY KEY,
        run_id          TEXT NOT NULL,
        idempotency_key TEXT NOT NULL,
        kind            TEXT NOT NULL DEFAULT '',
        result_digest   TEXT NOT NULL DEFAULT '',
        created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE (run_id, idempotency_key),
        FOREIGN KEY (run_id) REFERENCES run_state(run_id) ON DELETE CASCADE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS run_dead_letters (
        id                   TEXT PRIMARY KEY,
        run_id               TEXT NOT NULL DEFAULT '',
        task_id              TEXT NOT NULL DEFAULT '',
        error_class          TEXT NOT NULL DEFAULT '',
        sanitized_traceback  TEXT NOT NULL DEFAULT '',
        attempts             INTEGER NOT NULL DEFAULT 0,
        last_tool            TEXT,
        last_provider        TEXT,
        last_evidence_json   TEXT NOT NULL DEFAULT '{}',
        recoverability       TEXT NOT NULL DEFAULT 'unknown',
        retry_after          TEXT,
        state                TEXT NOT NULL DEFAULT 'open'
            CHECK (state IN ('open','retrying','requeued','replanned','abandoned','escalated')),
        note                 TEXT NOT NULL DEFAULT '',
        created_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        updated_at           TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
    )
    """,
)

# Verbatim from backend/persistence/schemas.sql; the parity test fails if these
# drift from the schema file.
_INDEXES: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS idx_run_state_session ON run_state(session_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_run_state_project ON run_state(project_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_run_state_user ON run_state(user_id, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_run_state_state ON run_state(state, updated_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_run_checkpoints_run_created "
    "ON run_checkpoints(run_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_run_checkpoints_run_phase "
    "ON run_checkpoints(run_id, phase, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_run_side_effects_run "
    "ON run_side_effects(run_id, idempotency_key)",
    "CREATE INDEX IF NOT EXISTS idx_run_dead_letters_run ON run_dead_letters(run_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_run_dead_letters_state "
    "ON run_dead_letters(state, created_at DESC)",
)


def upgrade() -> None:
    for statement in _TABLES:
        op.execute(statement)
    for statement in _INDEXES:
        op.execute(statement)


def downgrade() -> None:
    # Deliberately a no-op. These tables hold durable run state: checkpoints
    # are what a crashed run is restored from, side effects are the idempotency
    # ledger that keeps a replayed action from happening twice, and dead letters
    # are the failure evidence a human needs. Dropping four tables to "undo" a
    # revision that only ever created missing ones would destroy that evidence,
    # so the revision refuses to run backwards instead.
    pass
