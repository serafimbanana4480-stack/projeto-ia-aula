"""The runtime schema is canonical; the legacy Alembic chain must be compatible.

`backend/persistence/schemas.sql` is canonical (AGENTS.md rule 6) and is what
`persistence.db.init_db` executes. Alembic is not used by the app. Its legacy
chain may lack newer additive runtime tables, but anything it does create must
still exist in the canonical schema. These tests prevent the compatibility
chain from defining objects that the runtime cannot provide.

History: `alembic upgrade head` on an empty database used to fail outright --
006 did `ALTER TABLE session_runs` and no revision had ever created that table.
The 8 tables that only existed in schemas.sql were unreachable from the chain,
and the chain and runtime schema had drifted across tables, columns and indexes.

A third shape is compared as well: the schema the *running* database has. It
contains objects that only ever appeared at runtime -- the session garbage
collector's `status`/`expired_at` columns and the `structured_logs` /
`usage_ledger` tables -- so comparing only Alembic with schemas.sql could not
see that drift.

Everything here builds throwaway databases under tmp_path. The developer
database in backend data/ is never opened.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.persistence.db import SCHEMA_PATH
from backend.tests.persistence._helpers import (
    ALEMBIC_INI,
    REPO_ROOT,
    snapshot,
)

INFRA_TABLES = {"alembic_version", "sqlite_sequence"}

#: The objects the running database has but the schema file used to lack,
#: verbatim from the live database. The session soft-delete columns were
#: added at runtime by `persistence.db._ensure_session_gc_schema` (an ALTER
#: TABLE), `structured_logs` was created on demand by
#: `backend/observability/log_store.py` and `usage_ledger` by
#: `backend/llm/cost_governor.py`.
_LIVE_ONLY_SQL = """
CREATE TABLE IF NOT EXISTS structured_logs (
    id          TEXT PRIMARY KEY,
    timestamp   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    level       TEXT NOT NULL,
    message     TEXT NOT NULL,
    agent       TEXT,
    session_id  TEXT,
    task_id     TEXT,
    extra_json  TEXT,
    correlation_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_logs_session ON structured_logs(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_agent ON structured_logs(agent, timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_level ON structured_logs(level, timestamp);
CREATE INDEX IF NOT EXISTS idx_logs_time ON structured_logs(timestamp DESC);

CREATE TABLE IF NOT EXISTS usage_ledger (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    day TEXT NOT NULL,
    provider TEXT DEFAULT '',
    model TEXT DEFAULT '',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    session_id TEXT DEFAULT '',
    run_id TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_usage_ledger_day ON usage_ledger(day);
CREATE INDEX IF NOT EXISTS idx_usage_ledger_run ON usage_ledger(run_id);
"""

#: The Alembic head. Bumped whenever a revision is added to the chain.
ALEMBIC_HEAD = "010_session_gc_and_observability"


def _build_via_alembic(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(REPO_ROOT / "backend" / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")


def _build_via_schemas_sql(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def _build_live_shaped(db_path: Path) -> None:
    """Build the schema the running database has.

    The canonical schema plus the objects the running database only ever got
    at runtime. When the schema file is missing one of them, this database
    has it and the comparison fails -- which is exactly the drift the parity
    test could not see before.
    """
    _build_via_schemas_sql(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(sessions)")}
        if "status" not in columns:
            conn.execute(
                "ALTER TABLE sessions ADD COLUMN status TEXT "
                "NOT NULL DEFAULT 'active' "
                "CHECK (status IN ('active', 'idle', 'expired'))"
            )
        if "expired_at" not in columns:
            conn.execute("ALTER TABLE sessions ADD COLUMN expired_at TEXT")
        conn.executescript(_LIVE_ONLY_SQL)
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def parity(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """Build every schema once; the upgrade chain is slow enough to share."""
    tmp = tmp_path_factory.mktemp("schema_parity")
    alembic_db = tmp / "alembic.db"
    schemas_db = tmp / "schemas.db"
    live_db = tmp / "live.db"
    _build_via_alembic(alembic_db)
    _build_via_schemas_sql(schemas_db)
    _build_live_shaped(live_db)
    return {
        "alembic": snapshot(alembic_db),
        "schemas": snapshot(schemas_db),
        "live": snapshot(live_db),
    }


def test_alembic_upgrade_head_succeeds_on_a_fresh_database(tmp_path: Path) -> None:
    """Regression: this raised `no such table: session_runs` at revision 006."""
    db_path = tmp_path / "fresh.db"

    _build_via_alembic(db_path)

    assert db_path.exists()
    conn = sqlite3.connect(str(db_path))
    try:
        stamped = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        conn.close()
    assert stamped is not None
    assert stamped[0] == ALEMBIC_HEAD


def test_tables_match(parity: dict[str, object]) -> None:
    alembic_tables: set[str] = parity["alembic"]["tables"]  # type: ignore[assignment]
    schema_tables: set[str] = parity["schemas"]["tables"]  # type: ignore[assignment]
    only_alembic = alembic_tables - schema_tables
    assert not only_alembic, (
        "legacy migration tables missing from canonical schemas.sql: "
        f"{sorted(only_alembic)}"
    )


def test_columns_match(parity: dict[str, object]) -> None:
    alembic_cols: dict[str, set[str]] = parity["alembic"]["columns"]  # type: ignore[assignment]
    schema_cols: dict[str, set[str]] = parity["schemas"]["columns"]  # type: ignore[assignment]
    drift = {
        table: sorted(alembic_cols[table] - schema_cols[table])
        for table in sorted(alembic_cols)
        if table in schema_cols and alembic_cols[table] - schema_cols[table]
    }
    assert not drift, f"legacy migration columns missing from canonical schemas.sql: {drift}"


def test_indexes_match(parity: dict[str, object]) -> None:
    only_alembic = parity["alembic"]["indexes"] - parity["schemas"]["indexes"]
    assert not only_alembic, f"indexes only created by the migration chain: {sorted(only_alembic)}"


def test_live_shaped_tables_match(parity: dict[str, object]) -> None:
    """The schema file must contain every table the running database has."""
    live_tables: set[str] = parity["live"]["tables"]  # type: ignore[assignment]
    schema_tables: set[str] = parity["schemas"]["tables"]  # type: ignore[assignment]
    only_live = live_tables - schema_tables
    assert not only_live, f"tables the running database has but schemas.sql lacks: {sorted(only_live)}"


def test_live_shaped_columns_match(parity: dict[str, object]) -> None:
    """The schema file must contain every column the running database has."""
    live_cols: dict[str, set[str]] = parity["live"]["columns"]  # type: ignore[assignment]
    schema_cols: dict[str, set[str]] = parity["schemas"]["columns"]  # type: ignore[assignment]
    drift = {
        table: sorted(live_cols[table] - schema_cols[table])
        for table in sorted(live_cols)
        if live_cols[table] - schema_cols[table]
    }
    assert not drift, f"columns the running database has but schemas.sql lacks: {drift}"


def test_live_shaped_indexes_match(parity: dict[str, object]) -> None:
    """The schema file must contain every index the running database has."""
    only_live = parity["live"]["indexes"] - parity["schemas"]["indexes"]
    assert not only_live, f"indexes the running database has but schemas.sql lacks: {sorted(only_live)}"


def test_tables_that_only_existed_in_schemas_sql_are_now_reachable() -> None:
    """The 8 tables the chain never created. Named explicitly on purpose.

    Guards the specific regression rather than relying on the parity tests
    above, so the failure message says which table went missing.
    """
    versions_dir = REPO_ROOT / "backend" / "migrations" / "versions"
    chain_sql = "\n".join(p.read_text(encoding="utf-8") for p in versions_dir.glob("*.py"))
    for table in (
        "agent_states",
        "git_commits",
        "peer_review_requests",
        "peer_review_results",
        "persistent_memories",
        "session_runs",
        "whiteboard_entries",
        "whiteboard_entry_links",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in chain_sql, (
            f"{table} is in schemas.sql but no migration creates it"
        )


def test_production_stamped_database_upgrades_are_a_no_op(tmp_path: Path) -> None:
    """A runtime-built schema can be upgraded without changing its data/schema.

    `persistence.db.init_db` applies schemas.sql and then stamps head. Simulate
    an older 006 stamp to verify that the compatibility chain safely converges.
    """
    db_path = tmp_path / "production.db"

    # Reproduce init_db: schemas.sql, then stamp at the pre-007 head, then
    # upgrade -- exactly what a database created before this fix would see.
    _build_via_schemas_sql(db_path)
    from alembic import command
    from alembic.config import Config

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.stamp(config, "006_execution_envelope")

    before = snapshot(db_path)
    command.upgrade(config, "head")
    after = snapshot(db_path)

    assert after == before, "upgrading a schemas.sql-built database changed its schema"
