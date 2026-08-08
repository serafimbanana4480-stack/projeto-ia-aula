"""Focused migration tests for old durable-run fixtures."""

import importlib
import sqlite3

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine


def test_pre_migration_session_runs_rows_survive_schema_readiness(tmp_path) -> None:

    db_path = tmp_path / "pre-migration.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (id TEXT PRIMARY KEY);
            INSERT INTO sessions (id) VALUES ('legacy-session');
            CREATE TABLE session_runs (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'running',
                agent TEXT,
                phase TEXT NOT NULL DEFAULT 'starting',
                prompt TEXT NOT NULL DEFAULT '',
                partial_output TEXT NOT NULL DEFAULT '',
                checkpoint_json TEXT NOT NULL DEFAULT '{}',
                usage_json TEXT NOT NULL DEFAULT '{}',
                error TEXT,
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                finished_at TEXT
            );
            INSERT INTO session_runs
                (id, session_id, status, started_at, updated_at)
            VALUES ('legacy-run', 'legacy-session', 'completed',
                    '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z');
            """
        )

    migration = importlib.import_module(
        "backend.migrations.versions.006_execution_envelope"
    )
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(Operations(context)):
            migration.upgrade()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(session_runs)")}
        legacy = conn.execute(
            "SELECT status FROM session_runs WHERE id = 'legacy-run'"
        ).fetchone()

    assert "execution_state" in columns
    assert "correlation_id" in columns
    assert "evidence_json" in columns
    assert legacy == ("completed",)
