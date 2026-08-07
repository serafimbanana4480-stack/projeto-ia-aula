import sqlite3
from pathlib import Path

import pytest

from backend.persistence import db


def test_init_db_seeds_default_dev_user_when_users_table_is_empty(tmp_path: Path):
    db_path = tmp_path / "nexus.db"
    db.DB_PATH = db_path
    db.SCHEMA_PATH = Path("backend/persistence/schemas.sql")

    with sqlite3.connect(db_path) as conn:
        schema_sql = db.SCHEMA_PATH.read_text(encoding="utf-8")
        conn.executescript(schema_sql)
        conn.commit()

    db.init_db()

    user = db.get_user_with_password("admin@nexus-ide.com")

    assert user is not None
    assert user["email"] == "admin@nexus-ide.com"


def test_init_db_repairs_existing_database_missing_current_tables(tmp_path: Path):
    """Existing pre-Alembic databases must gain tables required by live routes."""
    db_path = tmp_path / "legacy.db"
    db.close_pool()
    db.DB_PATH = db_path
    db.SCHEMA_PATH = Path("backend/persistence/schemas.sql")

    # A realistic legacy DB: it already exists, so the old init_db fast-path
    # skipped schemas.sql and left profile/RBAC routes crashing with HTTP 500.
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """CREATE TABLE users (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                is_active INTEGER DEFAULT 1
            )"""
        )
        conn.execute(
            "INSERT INTO users (id, username, email, password_hash) VALUES (?, ?, ?, ?)",
            ("legacy-user", "legacy", "legacy@example.test", "not-used"),
        )
        conn.commit()

    db.init_db()

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

    assert {
        "roles",
        "permissions",
        "user_roles",
        "role_permissions",
        "user_profiles",
        "user_routines",
        "user_memories",
        "email_accounts",
    }.issubset(tables)
