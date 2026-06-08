"""Tests for the Shared Memory (whiteboard) system."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.core.shared_memory import SharedMemory, WhiteboardEntry, get_shared_memory


@pytest.fixture(autouse=True)
def reset_shared_memory_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset the SharedMemory singleton before each test."""
    monkeypatch.setattr(SharedMemory, "_instance", None)


class TestSharedMemory:
    def setup_method(self):
        from backend.persistence.db import close_pool
        close_pool()

    def test_write_and_read_entry(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db

        init_db()
        shm = get_shared_memory()
        entry = shm.write_entry(
            agent_name="CODER",
            topic="code.change",
            content="Fixed bug in api.py",
            importance=0.8,
            tags=["bugfix", "api"],
        )
        assert entry.entry_id
        assert entry.author_agent == "CODER"

        entries = shm.read_entries(topic="code.change")
        assert len(entries) == 1
        assert entries[0].content == "Fixed bug in api.py"

    def test_read_entries_with_filters(self, tmp_path, monkeypatch):
        # Clean tables to avoid test pollution
        import sqlite3
        from backend.persistence.db import DB_PATH
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("DELETE FROM whiteboard_entries")
        conn.execute("DELETE FROM whiteboard_entry_links")
        conn.commit()
        conn.close()
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db
        init_db()
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db

        init_db()
        shm = get_shared_memory()
        shm.write_entry("CODER", "code.change", "fix 1", tags=["api"])
        shm.write_entry("ANALYZER", "bug.discovery", "found issue", tags=["security"])
        shm.write_entry("CODER", "code.change", "fix 2", tags=["ui"])

        entries = shm.read_entries(topic="code.change")
        assert len(entries) == 2

        entries = shm.read_entries(agent="ANALYZER")
        assert len(entries) == 1
        assert entries[0].topic == "bug.discovery"

    def test_search_entries(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db

        init_db()
        shm = get_shared_memory()
        shm.write_entry("CODER", "code.change", "Refactored auth module")
        shm.write_entry("ANALYZER", "architecture.decision", "Use JWT tokens")

        results = shm.search_entries("auth")
        assert len(results) == 1
        assert results[0].author_agent == "CODER"

        results = shm.search_entries("JWT")
        assert len(results) == 1
        assert results[0].author_agent == "ANALYZER"

    def test_link_entries_and_get_thread(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db

        init_db()
        shm = get_shared_memory()
        e1 = shm.write_entry("CODER", "code.change", "Initial fix")
        e2 = shm.write_entry("CODER", "code.change", "Follow-up fix")
        e3 = shm.write_entry("ANALYZER", "review.note", "Looks good")

        assert shm.link_entries(e1.entry_id, e2.entry_id, "follow_up") is True
        assert shm.link_entries(e1.entry_id, e3.entry_id, "review") is True
        # Duplicate link should fail
        assert shm.link_entries(e1.entry_id, e2.entry_id, "follow_up") is False

        thread = shm.get_thread(e1.entry_id)
        entry_ids = {e.entry_id for e in thread}
        assert e1.entry_id in entry_ids
        assert e2.entry_id in entry_ids
        assert e3.entry_id in entry_ids

    def test_archive_old_entries(self, tmp_path, monkeypatch):
        # Clean tables to avoid test pollution
        import sqlite3
        from backend.persistence.db import DB_PATH
        conn = sqlite3.connect(str(DB_PATH))
        conn.execute("DELETE FROM whiteboard_entries")
        conn.execute("DELETE FROM whiteboard_entry_links")
        conn.commit()
        conn.close()
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db
        init_db()
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db

        init_db()
        shm = get_shared_memory()
        old_ts = (datetime.now(UTC) - timedelta(days=40)).isoformat()
        shm.write_entry("CODER", "code.change", "Old change", importance=0.1)

        # Manually backdate the entry
        from backend.persistence.db import get_db

        with get_db() as conn:
            conn.execute(
                "UPDATE whiteboard_entries SET timestamp = ?",
                (old_ts,),
            )

        shm.write_entry("CODER", "code.change", "Recent change", importance=0.1)
        archived = shm.archive_old_entries(days=30, max_importance=0.3)
        assert archived == 1

        entries = shm.read_entries(topic="code.change")
        assert len(entries) == 1
        assert entries[0].content == "Recent change"

    def test_get_thread_missing_entry(self, tmp_path, monkeypatch):
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        from backend.persistence.db import init_db

        init_db()
        shm = get_shared_memory()
        assert shm.get_thread("nonexistent") == []
