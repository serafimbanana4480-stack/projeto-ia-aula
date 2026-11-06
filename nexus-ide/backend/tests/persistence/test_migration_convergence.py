"""The migration chain and ``init_db`` must converge with the runtime schema.

Three defects are pinned here:

* ``init_db()`` only worked from the repository root, because
  ``backend/alembic.ini`` carries a *relative* ``script_location``.
* revision 005 did a bare ``ALTER TABLE messages ADD COLUMN cost_usd`` and
  died with "duplicate column name" on a database built from
  ``schemas.sql`` — which is exactly the database ``init_db`` creates.
* an untracked database (one that was never stamped) was skipped instead of
  adopted, so the next ``alembic upgrade head`` replayed the whole chain.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from backend.persistence import db
from backend.persistence.db import SCHEMA_PATH
from backend.tests.persistence._helpers import (
    alembic_version,
    build_via_schemas_sql,
    table_names,
    upgrade_to,
)


def test_init_db_works_from_any_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``init_db()`` must not depend on the current working directory."""
    db_file = tmp_path / "any_cwd.db"
    monkeypatch.setattr(db, "DB_PATH", db_file)
    # An absolute schema path: the file location must not depend on the CWD
    # either (another test leaves a relative one behind).
    monkeypatch.setattr(db, "SCHEMA_PATH", SCHEMA_PATH)
    db.close_pool()

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)

    db.init_db()

    assert db_file.exists()
    assert alembic_version(db_file) is not None, "the database must be stamped"
    assert "sessions" in table_names(db_file)
    db.close_pool()


def test_migration_005_is_idempotent_on_a_schemas_built_db(tmp_path: Path) -> None:
    """Revision 005 must be a no-op when ``cost_usd`` already exists."""
    db_path = tmp_path / "schemas_built.db"
    build_via_schemas_sql(db_path)

    # Before the fix this raised:
    #   sqlite3.OperationalError: duplicate column name: cost_usd
    upgrade_to(db_path, "005_add_token_tracking")

    conn = sqlite3.connect(str(db_path))
    try:
        columns = [
            str(row[1]) for row in conn.execute("PRAGMA table_info(messages)").fetchall()
        ]
    finally:
        conn.close()
    assert "cost_usd" in columns
    assert columns.count("cost_usd") == 1


def test_untracked_database_is_stamped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A database that was never stamped must be adopted, not skipped."""
    db_path = tmp_path / "untracked.db"
    build_via_schemas_sql(db_path)
    assert alembic_version(db_path) is None, "the fixture must start untracked"

    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.close_pool()

    db._run_alembic_migrations()

    version = alembic_version(db_path)
    assert version is not None, "an untracked database must be stamped"
    assert version == "010_session_gc_and_observability"

    # And the stamp is usable: a later upgrade does not replay the chain.
    upgrade_to(db_path, "head")
    assert alembic_version(db_path) == "010_session_gc_and_observability"
    db.close_pool()


def test_untracked_database_is_stamped_at_the_revision_its_schema_matches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An older untracked database is stamped at the revision it matches."""
    db_path = tmp_path / "older_untracked.db"
    build_via_schemas_sql(db_path)
    # An older release knew neither the todo tables nor the session
    # soft-delete columns: its schema matches revision 008_run_state.
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DROP TABLE todos")
        conn.execute("DROP TABLE scheduled_tasks")
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(db, "DB_PATH", db_path)
    db.close_pool()

    db._run_alembic_migrations()

    # The missing revisions are applied on top of the stamp.
    assert alembic_version(db_path) == "010_session_gc_and_observability"
    tables = table_names(db_path)
    assert "todos" in tables
    assert "scheduled_tasks" in tables
    db.close_pool()
