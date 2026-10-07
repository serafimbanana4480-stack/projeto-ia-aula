"""The Alembic chain and schemas.sql must produce the same schema.

`backend/persistence/schemas.sql` is canonical (AGENTS.md rule 6) and is what
`persistence.db.init_db` executes. The Alembic chain is the alternative route to
the same schema. These tests pin that equivalence so the two cannot drift again.

History: `alembic upgrade head` on an empty database used to fail outright --
006 did `ALTER TABLE session_runs` and no revision had ever created that table.
The 8 tables that only existed in schemas.sql were unreachable from the chain,
and the chain and runtime schema had drifted across tables, columns and indexes.

Everything here builds throwaway databases under tmp_path. The developer
database in backend data/ is never opened.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.persistence.db import SCHEMA_PATH

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "backend" / "alembic.ini"

INFRA_TABLES = {"alembic_version", "sqlite_sequence"}


def _snapshot(db_path: Path) -> dict[str, object]:
    """Return tables, per-table columns and index names for a SQLite file."""
    conn = sqlite3.connect(str(db_path))
    try:
        tables = {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        } - INFRA_TABLES
        columns = {
            table: {
                str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            for table in tables
        }
        indexes = {
            str(row[0])
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        }
    finally:
        conn.close()
    return {"tables": tables, "columns": columns, "indexes": indexes}


def _build_via_alembic(db_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "head")


def _build_via_schemas_sql(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def parity(tmp_path_factory: pytest.TempPathFactory) -> dict[str, object]:
    """Build both schemas once; the upgrade chain is slow enough to share."""
    tmp = tmp_path_factory.mktemp("schema_parity")
    alembic_db = tmp / "alembic.db"
    schemas_db = tmp / "schemas.db"
    _build_via_alembic(alembic_db)
    _build_via_schemas_sql(schemas_db)
    return {"alembic": _snapshot(alembic_db), "schemas": _snapshot(schemas_db)}


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
    assert stamped[0] == "008_message_run_link"


def test_tables_match(parity: dict[str, object]) -> None:
    assert parity["alembic"]["tables"] == parity["schemas"]["tables"], (
        "table set differs between `alembic upgrade head` and schemas.sql"
    )


def test_columns_match(parity: dict[str, object]) -> None:
    alembic_cols: dict[str, set[str]] = parity["alembic"]["columns"]  # type: ignore[assignment]
    schema_cols: dict[str, set[str]] = parity["schemas"]["columns"]  # type: ignore[assignment]
    drift = {
        table: {
            "only_in_alembic": sorted(alembic_cols[table] - schema_cols[table]),
            "only_in_schemas": sorted(schema_cols[table] - alembic_cols[table]),
        }
        for table in sorted(alembic_cols)
        if alembic_cols[table] != schema_cols[table]
    }
    assert not drift, f"column drift: {drift}"


def test_indexes_match(parity: dict[str, object]) -> None:
    only_alembic = parity["alembic"]["indexes"] - parity["schemas"]["indexes"]
    only_schemas = parity["schemas"]["indexes"] - parity["alembic"]["indexes"]
    assert not only_alembic, f"indexes only created by the migration chain: {sorted(only_alembic)}"
    assert not only_schemas, f"indexes only created by schemas.sql: {sorted(only_schemas)}"


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

    before = _snapshot(db_path)
    command.upgrade(config, "head")
    after = _snapshot(db_path)

    assert after == before, "upgrading a schemas.sql-built database changed its schema"
