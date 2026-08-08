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



def test_init_db_repairs_pre_envelope_session_runs_before_current_schema(
    tmp_path, monkeypatch
) -> None:
    import backend.persistence.db as db

    db_path = tmp_path / "legacy-startup.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE sessions (id TEXT PRIMARY KEY);
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
            """
        )
    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.close_pool()
    db.init_db(run_migrations=False)

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(session_runs)")}
        index_names = {
            row[1] for row in conn.execute(
                "SELECT type, name FROM sqlite_master WHERE type = 'index'"
            )
        }
    assert "correlation_id" in columns
    assert "idx_session_runs_correlation_updated" in index_names

def test_stamped_head_repairs_missing_message_cost_column(tmp_path, monkeypatch) -> None:
    import backend.persistence.db as db

    db_path = tmp_path / "stamped-head.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(db.SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.execute("ALTER TABLE messages RENAME TO messages_full")
        conn.execute("DROP TABLE messages_full")
        conn.execute(
            """
            CREATE TABLE messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tier_used TEXT,
                model_used TEXT,
                tools_used_json TEXT,
                tokens_in INTEGER DEFAULT 0,
                tokens_out INTEGER DEFAULT 0,
                latency_ms INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        conn.execute(
            "INSERT INTO alembic_version (version_num) VALUES ('006_execution_envelope')"
        )
        conn.commit()

    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.close_pool()
    db.init_db()

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
    assert "cost_usd" in columns
