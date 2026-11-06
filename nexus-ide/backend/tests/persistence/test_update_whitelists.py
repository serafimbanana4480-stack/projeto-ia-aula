"""The update whitelists must name the columns the tables really have.

``update_user`` whitelisted ``role`` and ``preferences`` and
``update_email_account`` whitelisted seven columns that do not exist: both
updates were silently no-ops. The scheduled-task status update had no
whitelist at all and interpolated the key straight into the SQL.
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.persistence import db


def _columns(table: str) -> set[str]:
    with db.get_db() as conn:
        return {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})")}


def test_update_user_whitelist_matches_the_schema() -> None:
    """Every whitelisted user column exists, and every mutable one is listed."""
    columns = _columns("users")

    assert db.USER_UPDATE_ALLOWED_COLS.issubset(columns), (
        f"unknown columns whitelisted: {sorted(db.USER_UPDATE_ALLOWED_COLS - columns)}"
    )
    mutable = columns - {"id", "password_hash", "created_at"}
    assert mutable.issubset(db.USER_UPDATE_ALLOWED_COLS), (
        f"mutable columns missing from the whitelist: {sorted(mutable - db.USER_UPDATE_ALLOWED_COLS)}"
    )

    # And the whitelist really writes: the old one dropped every field.
    user = db.create_user("alice", "alice@example.com", "hash", "Alice")
    updated = db.update_user(user["id"], full_name="Alice Updated")
    assert updated is not None
    assert updated["full_name"] == "Alice Updated"


def test_update_email_account_whitelist_matches_the_schema() -> None:
    """Every whitelisted email-account column exists, and vice versa."""
    columns = _columns("email_accounts")

    assert db.EMAIL_ACCOUNT_UPDATE_ALLOWED_COLS.issubset(columns), (
        f"unknown columns whitelisted: "
        f"{sorted(db.EMAIL_ACCOUNT_UPDATE_ALLOWED_COLS - columns)}"
    )
    mutable = columns - {"id", "user_id", "created_at"}
    assert mutable.issubset(db.EMAIL_ACCOUNT_UPDATE_ALLOWED_COLS), (
        f"mutable columns missing from the whitelist: "
        f"{sorted(mutable - db.EMAIL_ACCOUNT_UPDATE_ALLOWED_COLS)}"
    )

    # And the whitelist really writes: the old one dropped every field.
    user = db.create_user("bob", "bob@example.com", "hash", "Bob")
    account = db.create_email_account(
        user["id"], "Work", "imap.example.com", 993, "bob", "secret"
    )
    updated = db.update_email_account(account["id"], label="Personal")
    assert updated is not None
    assert updated["label"] == "Personal"


def test_change_statistics_returns_zero_not_null() -> None:
    """An empty table must report ``0`` lines written, not ``None``."""
    stats = db.get_change_statistics()

    assert stats["lines_written"] == 0
    assert isinstance(stats["lines_written"], int)
    assert stats["total_changes"] == 0
    assert stats["files_modified"] == 0


def test_scheduled_task_status_update_ignores_unknown_columns() -> None:
    """An unknown column must be ignored, not interpolated into the SQL."""
    db.save_scheduled_task({"task_id": "task-1", "name": "probe", "status": "pending"})

    db.update_scheduled_task_status(
        "task-1",
        "running",
        retry_count=2,
        not_a_column="boom",
    )

    with db.get_db() as conn:
        row = conn.execute(
            "SELECT status, retry_count FROM scheduled_tasks WHERE id = ?", ("task-1",)
        ).fetchone()
    assert row is not None
    assert row["status"] == "running"
    assert row["retry_count"] == 2


def test_scheduled_task_status_update_keeps_the_status_when_a_field_fails() -> None:
    """A failure must not lose the status write, and must not be silent."""
    db.save_scheduled_task({"task_id": "task-2", "name": "probe", "status": "pending"})

    # A value sqlite3 cannot bind: the extra-field write fails. The failure
    # is visible to the caller, and the status write survives it.
    with pytest.raises(sqlite3.Error):
        db.update_scheduled_task_status("task-2", "running", retry_count=object())

    with db.get_db() as conn:
        row = conn.execute(
            "SELECT status FROM scheduled_tasks WHERE id = ?", ("task-2",)
        ).fetchone()
    assert row is not None
    assert row["status"] == "running"
