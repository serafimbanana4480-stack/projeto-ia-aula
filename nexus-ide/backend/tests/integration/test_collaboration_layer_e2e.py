"""End-to-end tests for the NEXUS IDE collaboration layer.

Covers:
  - FileLockManager (exclusive/shared locks, timeouts, deadlock detection)
  - SharedMemory (whiteboard CRUD, search, links, archive)
  - PeerReviewSystem (submission, required reviewers, review rules)
  - API surface via FastAPI TestClient
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.core.file_locks import DeadlockError, FileLockManager, LockError
from backend.core.peer_review import PeerReviewSystem, ReviewComment, get_peer_review_system
from backend.core.shared_memory import SharedMemory, get_shared_memory
from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app
from backend.persistence.db import init_db


# ──────────────────────────────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset all singletons before each test."""
    from backend.persistence.db import close_pool
    close_pool()
    monkeypatch.setattr(FileLockManager, "_instance", None)
    monkeypatch.setattr(SharedMemory, "_instance", None)
    monkeypatch.setattr(SharedMemory, "_initialized", False)
    monkeypatch.setattr(PeerReviewSystem, "_instance", None)
    monkeypatch.setattr(PeerReviewSystem, "_initialized", False)


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """FastAPI TestClient with temp DB."""
    db_file = tmp_path / "test_nexus_api.db"
    monkeypatch.setattr("backend.persistence.db.DB_PATH", db_file)
    init_db()
    token = create_access_token({"sub": "test-user", "email": "test@test.com"})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temporary project directory."""
    proj = tmp_path / "test_project"
    proj.mkdir()
    (proj / "test_file.txt").write_text("original content", encoding="utf-8")
    return proj


# ──────────────────────────────────────────────────────────────────────────────
# File Locks — Direct API
# ──────────────────────────────────────────────────────────────────────────────


class TestFileLocksDirect:
    """Test FileLockManager in isolation."""

    @pytest.mark.asyncio
    async def test_two_agents_write_same_file_one_waits(self, tmp_path: Path, monkeypatch):
        """Two agents trying to write the same file simultaneously — verify one waits."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        manager = FileLockManager()
        test_file = str((tmp_path / "shared.txt").resolve())
        results: list[str] = []
        lock = asyncio.Lock()

        async def agent_a():
            lid = await manager.acquire_write_lock(test_file, "agent-A", timeout=5.0)
            async with lock:
                results.append("A-acquired")
            await asyncio.sleep(0.3)  # hold the lock
            manager.release_lock(test_file, "agent-A")
            async with lock:
                results.append("A-released")

        async def agent_b():
            await asyncio.sleep(0.05)  # ensure A acquires first
            async with lock:
                results.append("B-before-acquire")
            lid = await manager.acquire_write_lock(test_file, "agent-B", timeout=5.0)
            async with lock:
                results.append("B-acquired")
            manager.release_lock(test_file, "agent-B")

        await asyncio.gather(agent_a(), agent_b())

        # Verify ordering: A acquires, B tries, A releases, B acquires
        assert results.index("A-acquired") < results.index("B-before-acquire")
        assert results.index("A-released") < results.index("B-acquired")

    @pytest.mark.asyncio
    async def test_multiple_agents_read_same_file(self, tmp_path: Path, monkeypatch):
        """Multiple agents reading the same file simultaneously — verify all can read."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        manager = FileLockManager()
        test_file = str((tmp_path / "shared.txt").resolve())
        acquired: list[str] = []
        lock = asyncio.Lock()

        async def reader(agent_name: str):
            lid = await manager.acquire_read_lock(test_file, agent_name, timeout=2.0)
            async with lock:
                acquired.append(agent_name)
            await asyncio.sleep(0.1)
            manager.release_lock(test_file, agent_name)

        await asyncio.gather(
            reader("agent-1"), reader("agent-2"), reader("agent-3")
        )

        assert len(acquired) == 3
        assert set(acquired) == {"agent-1", "agent-2", "agent-3"}

    @pytest.mark.asyncio
    async def test_lock_timeout_expires(self, tmp_path: Path, monkeypatch):
        """Lock timeout — verify lock expires after timeout."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        manager = FileLockManager()
        test_file = str((tmp_path / "timeout.txt").resolve())

        # Acquire with very short timeout
        await manager.acquire_write_lock(test_file, "agent-X", timeout=0.2)
        assert manager.is_locked(test_file) is True

        # Wait for expiry
        await asyncio.sleep(0.35)
        manager._prune_expired()
        assert manager.is_locked(test_file) is False

    @pytest.mark.asyncio
    async def test_lock_wait_timeout_raises(self, tmp_path: Path, monkeypatch):
        """Waiting longer than timeout raises LockError."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        manager = FileLockManager()
        test_file = str((tmp_path / "blocked.txt").resolve())

        # Hold lock for a long time
        await manager.acquire_write_lock(test_file, "holder", timeout=60.0)

        with pytest.raises(LockError, match="Timeout acquiring"):
            await manager.acquire_write_lock(test_file, "waiter", timeout=0.1)

        manager.release_lock(test_file, "holder")

    @pytest.mark.asyncio
    async def test_deadlock_detection(self, tmp_path: Path, monkeypatch):
        """Deadlock detection — create a scenario that would deadlock and verify it's detected."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        manager = FileLockManager()
        file_a = str((tmp_path / "file_a.txt").resolve())
        file_b = str((tmp_path / "file_b.txt").resolve())

        # Seed both files so normalisation works
        Path(file_a).write_text("a")
        Path(file_b).write_text("b")

        # Manually inject a wait-for cycle:
        # agent-1 holds file_a, waits for file_b
        # agent-2 holds file_b, waits for file_a
        await manager.acquire_write_lock(file_a, "agent-1", timeout=60.0)
        await manager.acquire_write_lock(file_b, "agent-2", timeout=60.0)

        # Manually populate wait graph to simulate the cycle
        manager._wait_graph["agent-1"].add(file_b)
        manager._wait_graph["agent-2"].add(file_a)

        deadlocked = manager.detect_deadlock()
        assert "agent-1" in deadlocked
        assert "agent-2" in deadlocked

        # Now try to acquire from one of the deadlocked agents — should raise
        with pytest.raises(DeadlockError, match="Deadlock detected"):
            await manager.acquire_write_lock(file_b, "agent-1", timeout=0.5)

        manager.release_lock(file_a, "agent-1")
        manager.release_lock(file_b, "agent-2")


# ──────────────────────────────────────────────────────────────────────────────
# File Locks — API Endpoints
# ──────────────────────────────────────────────────────────────────────────────


class TestFileLocksAPI:
    """Test file locking behaviour through the REST API."""

    @pytest.mark.asyncio
    async def test_parallel_writes_via_api(self, client: TestClient, tmp_project: Path, monkeypatch):
        """Write to same file from two parallel async requests via /api/files/write.

        Using httpx.AsyncClient avoids blocking the shared TestClient event loop
        across threads, which previously caused hangs/timeouts on Windows.
        """
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_project.parent / "api_test.db")
        init_db()

        # Trust the project so writes are allowed — mock DB lookup to avoid Redis cache
        def _fake_get_project_by_path(path: str):
            return {"name": "api_test", "path": str(tmp_project), "trust": True}

        monkeypatch.setattr(
            "backend.persistence.db.get_project_by_path", _fake_get_project_by_path
        )

        target = str(tmp_project / "test_file.txt")
        Path(target).write_text("original", encoding="utf-8")

        import httpx
        from backend.orchestrator.main import app

        token = create_access_token({"sub": "test-user", "email": "test@test.com"})
        async with httpx.AsyncClient(
            app=app, base_url="http://testserver", headers={"Authorization": f"Bearer {token}"}
        ) as ac:

            async def writer(content: str):
                return await ac.post(
                    "/api/files/write",
                    json={
                        "path": "test_file.txt",
                        "content": content,
                        "project_path": str(tmp_project),
                        "session_id": "sess-123",
                    },
                )

            resp_a, resp_b = await asyncio.gather(
                writer("CONTENT-A"), writer("CONTENT-B")
            )

        responses = [
            {"status": resp_a.status_code, "json": resp_a.json()},
            {"status": resp_b.status_code, "json": resp_b.json()},
        ]

        # Both requests should succeed (one waits, then overwrites)
        for r in responses:
            assert r["status"] == 200, f"Unexpected status: {r}"

        # Final content must be exactly one of the two (no corruption)
        final = Path(target).read_text(encoding="utf-8")
        assert final in ("CONTENT-A", "CONTENT-B"), f"Corrupted content: {final!r}"


# ──────────────────────────────────────────────────────────────────────────────
# Shared Memory — Direct API
# ──────────────────────────────────────────────────────────────────────────────


class TestSharedMemoryDirect:
    """Test SharedMemory in isolation."""

    @pytest.mark.asyncio
    async def test_write_entries_from_three_agents(self, tmp_path: Path, monkeypatch):
        """Write entries from 3 different 'agents'."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        shm = get_shared_memory()
        e1 = await shm.write_entry("CODER", "code.change", "Fixed null pointer")
        e2 = await shm.write_entry("ANALYZER", "review.note", "Looks good")
        e3 = await shm.write_entry("BUG_HUNTER_STATIC", "bug.found", "Race condition in locks")

        assert e1.author_agent == "CODER"
        assert e2.author_agent == "ANALYZER"
        assert e3.author_agent == "BUG_HUNTER_STATIC"

        all_entries = await shm.read_entries(limit=10)
        assert len(all_entries) == 3

    @pytest.mark.asyncio
    async def test_read_entries_with_filters(self, tmp_path: Path, monkeypatch):
        """Read entries with filters (topic, agent, tags)."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        shm = get_shared_memory()
        await shm.write_entry("CODER", "code.change", "fix 1", tags=["api", "bugfix"])
        await shm.write_entry("CODER", "code.change", "fix 2", tags=["ui"])
        await shm.write_entry("ANALYZER", "bug.discovery", "found issue", tags=["security"])

        by_topic = await shm.read_entries(topic="code.change")
        assert len(by_topic) == 2

        by_agent = await shm.read_entries(agent="ANALYZER")
        assert len(by_agent) == 1
        assert by_agent[0].topic == "bug.discovery"

        by_tag = await shm.read_entries(tags=["security"])
        assert len(by_tag) == 1
        assert by_tag[0].author_agent == "ANALYZER"

    @pytest.mark.asyncio
    async def test_search_entries(self, tmp_path: Path, monkeypatch):
        """Search entries."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        shm = get_shared_memory()
        await shm.write_entry("CODER", "auth.refactor", "Refactored JWT handling")
        await shm.write_entry("ANALYZER", "db.optimisation", "Added indexes on users")

        results = await shm.search_entries("JWT")
        assert len(results) == 1
        assert results[0].topic == "auth.refactor"

        results = await shm.search_entries("indexes")
        assert len(results) == 1
        assert results[0].author_agent == "ANALYZER"

    @pytest.mark.asyncio
    async def test_link_entries_and_get_thread(self, tmp_path: Path, monkeypatch):
        """Link related entries and get thread."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        shm = get_shared_memory()
        e1 = await shm.write_entry("CODER", "code.change", "Initial implementation")
        e2 = await shm.write_entry("CODER", "code.change", "Follow-up fix")
        e3 = await shm.write_entry("ANALYZER", "review.note", "Approved")

        assert await shm.link_entries(e1.entry_id, e2.entry_id, "follow_up") is True
        assert await shm.link_entries(e1.entry_id, e3.entry_id, "review") is True
        # Duplicate should fail gracefully
        assert await shm.link_entries(e1.entry_id, e2.entry_id, "follow_up") is False

        thread = await shm.get_thread(e1.entry_id)
        entry_ids = {e.entry_id for e in thread}
        assert e1.entry_id in entry_ids
        assert e2.entry_id in entry_ids
        assert e3.entry_id in entry_ids

    @pytest.mark.asyncio
    async def test_archive_old_entries(self, tmp_path: Path, monkeypatch):
        """Archive old entries."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        shm = get_shared_memory()
        old_ts = (datetime.now(UTC) - timedelta(days=40)).isoformat()
        await shm.write_entry("CODER", "code.change", "Old change", importance=0.1)

        # Backdate the entry
        from backend.persistence.db import get_db

        with get_db() as conn:
            conn.execute("UPDATE whiteboard_entries SET timestamp = ?", (old_ts,))

        await shm.write_entry("CODER", "code.change", "Recent change", importance=0.1)

        archived = await shm.archive_old_entries(days=30, max_importance=0.3)
        assert archived == 1

        remaining = await shm.read_entries(topic="code.change")
        assert len(remaining) == 1
        assert remaining[0].content == "Recent change"


# ──────────────────────────────────────────────────────────────────────────────
# Shared Memory — API Endpoints
# ──────────────────────────────────────────────────────────────────────────────


class TestSharedMemoryAPI:
    """Test SharedMemory via REST endpoints."""

    def test_api_write_and_read(self, client: TestClient, tmp_path: Path, monkeypatch):
        """POST /api/whiteboard and GET /api/whiteboard."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "api.db")
        init_db()

        resp = client.post(
            "/api/whiteboard",
            json={
                "agent_name": "CODER",
                "topic": "code.change",
                "content": "Refactored auth module",
                "importance": 0.8,
                "tags": ["refactor", "auth"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["author_agent"] == "CODER"

        # Read back with filter
        resp = client.get("/api/whiteboard?topic=code.change")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["entries"][0]["content"] == "Refactored auth module"

    def test_api_search(self, client: TestClient, tmp_path: Path, monkeypatch):
        """GET /api/whiteboard/search."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "api.db")
        init_db()

        client.post(
            "/api/whiteboard",
            json={
                "agent_name": "CODER",
                "topic": "code.change",
                "content": "Fixed race condition in locks",
                "tags": ["concurrency"],
            },
        )

        resp = client.get("/api/whiteboard/search?q=race+condition")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert any("race" in e["content"].lower() for e in data["entries"])

    def test_api_thread(self, client: TestClient, tmp_path: Path, monkeypatch):
        """GET /api/whiteboard/thread/{entry_id}."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "api.db")
        init_db()

        r1 = client.post(
            "/api/whiteboard",
            json={
                "agent_name": "CODER",
                "topic": "code.change",
                "content": "Initial fix",
            },
        )
        r2 = client.post(
            "/api/whiteboard",
            json={
                "agent_name": "CODER",
                "topic": "code.change",
                "content": "Follow-up fix",
                "related_entries": [r1.json()["entry_id"]],
            },
        )

        # Thread from e2 follows related_entries backward to e1
        entry_id = r2.json()["entry_id"]
        resp = client.get(f"/api/whiteboard/thread/{entry_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        contents = {e["content"] for e in data["entries"]}
        assert contents == {"Initial fix", "Follow-up fix"}


# ──────────────────────────────────────────────────────────────────────────────
# Peer Review — Direct API
# ──────────────────────────────────────────────────────────────────────────────


class TestPeerReviewDirect:
    """Test PeerReviewSystem in isolation."""

    @pytest.mark.asyncio
    async def test_submit_code_snippet_for_review(self, tmp_path: Path, monkeypatch):
        """Submit a code snippet for review."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        prs = get_peer_review_system()
        review = await prs.submit_for_review(
            artifact_id="api.py",
            artifact_type="code",
            author_agent="CODER",
            content="def hello(): pass",
        )
        assert review.review_id
        assert review.status == "pending"

        status = await prs.get_review_status("api.py")
        assert status["artifact_id"] == "api.py"
        assert len(status["reviews"]) == 1

    @pytest.mark.asyncio
    async def test_required_reviewers_assigned(self, tmp_path: Path, monkeypatch):
        """Check if required reviewers are assigned."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        prs = get_peer_review_system()
        review = await prs.submit_for_review(
            artifact_id="api.py",
            artifact_type="code",
            author_agent="CODER",
            content="def hello(): pass",
        )

        required = prs.get_required_reviewers(review.author_agent)
        assert "ANALYZER" in required
        assert "BUG_HUNTER_STATIC" in required

    def test_review_rules_coder_requires_analyzer_and_bug_hunter(self, tmp_path: Path, monkeypatch):
        """Verify review rules: CODER → ANALYZER + BUG_HUNTER_STATIC."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        prs = get_peer_review_system()

        # CODER rule
        coder_reviewers = prs.get_required_reviewers("CODER")
        assert coder_reviewers == ["ANALYZER", "BUG_HUNTER_STATIC"]

        # ARCHITECT_DESIGN rule
        arch_reviewers = prs.get_required_reviewers("ARCHITECT_DESIGN")
        assert arch_reviewers == ["ARCHITECT_COMPLEXITY"]

        # Unknown author — no required reviewers
        assert prs.get_required_reviewers("UNKNOWN") == []

    @pytest.mark.asyncio
    async def test_review_status_after_all_required_approved(self, tmp_path: Path, monkeypatch):
        """Review stays 'in_review' until all required reviewers approve."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        prs = get_peer_review_system()
        review = await prs.submit_for_review(
            artifact_id="api.py", artifact_type="code", author_agent="CODER", content="x"
        )

        # Only one required reviewer approves
        await prs.conduct_review(review.review_id, "ANALYZER", "approved")
        updated = await prs.get_review_request(review.review_id)
        assert updated.status == "in_review"

        # Second required reviewer approves
        await prs.conduct_review(review.review_id, "BUG_HUNTER_STATIC", "approved")
        updated = await prs.get_review_request(review.review_id)
        assert updated.status == "approved"

    @pytest.mark.asyncio
    async def test_review_changes_requested_overrides_approved(self, tmp_path: Path, monkeypatch):
        """If any reviewer requests changes, status becomes 'changes_requested'."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        prs = get_peer_review_system()
        review = await prs.submit_for_review(
            artifact_id="api.py", artifact_type="code", author_agent="CODER", content="x"
        )

        await prs.conduct_review(review.review_id, "ANALYZER", "approved")
        await prs.conduct_review(
            review.review_id,
            "BUG_HUNTER_STATIC",
            "changes_requested",
            comments=[ReviewComment(message="Missing type hints")],
        )

        updated = await prs.get_review_request(review.review_id)
        assert updated.status == "changes_requested"


# ──────────────────────────────────────────────────────────────────────────────
# Peer Review — API Endpoints
# ──────────────────────────────────────────────────────────────────────────────


class TestPeerReviewAPI:
    """Test PeerReview via REST endpoints."""

    def test_api_submit_review(self, client: TestClient, tmp_path: Path, monkeypatch):
        """POST /api/reviews/submit."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "api.db")
        init_db()

        resp = client.post(
            "/api/reviews/submit",
            json={
                "artifact_id": "auth.py",
                "artifact_type": "code",
                "author_agent": "CODER",
                "content": "def login(): pass",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["artifact_id"] == "auth.py"

    def test_api_get_reviews(self, client: TestClient, tmp_path: Path, monkeypatch):
        """GET /api/reviews/{artifact_id}."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "api.db")
        init_db()

        client.post(
            "/api/reviews/submit",
            json={
                "artifact_id": "auth.py",
                "artifact_type": "code",
                "author_agent": "CODER",
                "content": "def login(): pass",
            },
        )

        resp = client.get("/api/reviews/auth.py")
        assert resp.status_code == 200
        data = resp.json()
        assert data["artifact_id"] == "auth.py"
        assert len(data["reviews"]) == 1


# ──────────────────────────────────────────────────────────────────────────────
# Concurrency / Race-condition probes
# ──────────────────────────────────────────────────────────────────────────────


class TestRaceConditions:
    """Stress tests to surface race conditions."""

    @pytest.mark.asyncio
    async def test_shared_memory_concurrent_writes(self, tmp_path: Path, monkeypatch):
        """Many coroutines writing to shared memory simultaneously."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        shm = get_shared_memory()
        errors: list[str] = []
        entry_ids: list[str] = []
        lock = asyncio.Lock()

        async def writer(agent: str, idx: int):
            try:
                entry = await shm.write_entry(
                    agent_name=agent,
                    topic="stress.test",
                    content=f"entry-{idx}",
                    tags=["stress"],
                )
                async with lock:
                    entry_ids.append(entry.entry_id)
            except Exception as e:
                async with lock:
                    errors.append(str(e))

        await asyncio.gather(*[writer(f"agent-{i % 3}", i) for i in range(30)])

        assert not errors, f"Errors during concurrent writes: {errors}"
        assert len(entry_ids) == 30

        # Verify all entries are readable
        entries = await shm.read_entries(topic="stress.test", limit=50)
        assert len(entries) == 30

    @pytest.mark.asyncio
    async def test_peer_review_concurrent_submissions(self, tmp_path: Path, monkeypatch):
        """Many coroutines submitting reviews simultaneously."""
        monkeypatch.setattr("backend.persistence.db.DB_PATH", tmp_path / "test.db")
        init_db()

        prs = get_peer_review_system()
        review_ids: list[str] = []
        errors: list[str] = []
        lock = asyncio.Lock()

        async def submit(idx: int):
            try:
                review = await prs.submit_for_review(
                    artifact_id=f"file_{idx}.py",
                    artifact_type="code",
                    author_agent="CODER",
                    content=f"def func{idx}(): pass",
                )
                async with lock:
                    review_ids.append(review.review_id)
            except Exception as e:
                async with lock:
                    errors.append(str(e))

        await asyncio.gather(*[submit(i) for i in range(20)])

        assert not errors, f"Errors during concurrent submissions: {errors}"
        assert len(review_ids) == 20
        assert len(set(review_ids)) == 20  # All unique
