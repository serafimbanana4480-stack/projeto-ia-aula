"""Shared helpers for the persistence tests.

Everything here builds throwaway databases under ``tmp_path``. The developer
database in ``data/`` is never opened.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from backend.persistence.db import SCHEMA_PATH

REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "backend" / "alembic.ini"
ALEMBIC_DIR = REPO_ROOT / "backend" / "migrations"

INFRA_TABLES = {"alembic_version", "sqlite_sequence"}


def snapshot(db_path: Path) -> dict[str, Any]:
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


def build_via_schemas_sql(db_path: Path) -> None:
    """Build a database from the canonical schema file."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def alembic_config(db_path: Path) -> Any:
    """Return an Alembic config that resolves its scripts absolutely.

    ``backend/alembic.ini`` carries a relative ``script_location``; the tests
    set the absolute path so they do not depend on the current directory.
    """
    from alembic.config import Config

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    return config


def upgrade_to(db_path: Path, revision: str) -> None:
    """Run ``alembic upgrade <revision>`` against ``db_path``."""
    from alembic import command

    command.upgrade(alembic_config(db_path), revision)


def alembic_version(db_path: Path) -> str | None:
    """Return the revision recorded in ``alembic_version`` (None when untracked)."""
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    return str(row[0]) if row else None


def table_names(db_path: Path) -> set[str]:
    """Return the table names of a SQLite file."""
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            str(row[0])
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        conn.close()
