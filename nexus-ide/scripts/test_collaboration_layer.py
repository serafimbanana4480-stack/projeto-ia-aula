#!/usr/bin/env python3
"""Standalone end-to-end test runner for the NEXUS IDE collaboration layer.

Produces a detailed report covering File Locks, Shared Memory, and Peer Review.
Usage:
    python scripts/test_collaboration_layer.py [--report-path REPORT.md]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Must set up temp DB before importing backend modules
_temp_db = Path(tempfile.gettempdir()) / "nexus_collaboration_test.db"

# Patch DB_PATH globally for this script
import backend.persistence.db as _db_mod

_db_mod.DB_PATH = _temp_db
_db_mod.init_db()

from backend.core.file_locks import DeadlockError, FileLockManager, LockError
from backend.core.peer_review import PeerReviewSystem, ReviewComment, get_peer_review_system
from backend.core.shared_memory import SharedMemory, get_shared_memory


# ──────────────────────────────────────────────────────────────────────────────
# Report accumulator
# ──────────────────────────────────────────────────────────────────────────────


class TestReport:
    def __init__(self) -> None:
        self.rows: list[dict[str, str]] = []
        self.issues: list[str] = []
        self.race_conditions: list[str] = []

    def add(self, category: str, test: str, result: str, issue: str = "—") -> None:
        self.rows.append({"category": category, "test": test, "result": result, "issue": issue})
        if result == "FAIL":
            self.issues.append(f"[{category}] {test}: {issue}")

    def markdown(self) -> str:
        lines: list[str] = []
        lines.append("# NEXUS IDE Collaboration Layer — End-to-End Test Report")
        lines.append(f"\n**Generated:** {datetime.now(UTC).isoformat()}")
        lines.append(f"**Database:** {_temp_db}")
        lines.append("\n---\n")

        lines.append("## Test Results\n")
        lines.append("| Category | Test Case | Result | Issues |")
        lines.append("|----------|-----------|--------|--------|")
        for r in self.rows:
            lines.append(f"| {r['category']} | {r['test']} | {r['result']} | {r['issue']} |")

        total = len(self.rows)
        passed = sum(1 for r in self.rows if r["result"] == "PASS")
        lines.append(f"\n**Summary:** {passed}/{total} passed")

        lines.append("\n---\n")
        lines.append("## Does the Collaboration Layer Work?\n")
        if passed == total:
            lines.append("✅ **Yes.** All components function correctly under normal and stress conditions.")
        elif passed >= total * 0.8:
            lines.append("⚠️ **Mostly.** Core features work, but some edge cases or integrations need attention.")
        else:
            lines.append("❌ **No.** Critical failures detected; the collaboration layer is not production-ready.")

        lines.append("\n---\n")
        lines.append("## Race Conditions Found\n")
        if self.race_conditions:
            for rc in self.race_conditions:
                lines.append(f"- {rc}")
        else:
            lines.append("No race conditions were surfaced during this test run.")

        lines.append("\n---\n")
        lines.append("## Recommendations\n")
        lines.extend(self._recommendations())
        return "\n".join(lines)

    def _recommendations(self) -> list[str]:
        recs: list[str] = []
        if any(r["result"] == "FAIL" for r in self.rows):
            recs.append("1. **Fix failing tests** before deploying to production.")
        recs.append("2. **Increase lock timeout defaults** if agents frequently operate on slow filesystems.")
        recs.append("3. **Add Prometheus metrics** for lock wait times, deadlock counts, and whiteboard QPS.")
        recs.append("4. **Expose `/api/whiteboard/link`** endpoint so clients can create entry links via REST.")
        recs.append("5. **Run the race-condition stress tests under `pytest-xdist`** with higher parallelism.")
        recs.append("6. **Add SQLite transaction retries** (`busy_timeout` is 5s but retry logic is absent).")
        recs.append("7. **Validate that `changes_requested` reviews trigger auto-correction** in end-to-end flows.")
        return recs


REPORT = TestReport()


# ──────────────────────────────────────────────────────────────────────────────
# File Lock Tests
# ──────────────────────────────────────────────────────────────────────────────


async def _test_two_agents_write_same_file():
    manager = FileLockManager()
    test_file = str(_temp_db.parent / "shared_write.txt")
    Path(test_file).write_text("x")
    results: list[str] = []
    lock = asyncio.Lock()

    async def agent_a():
        await manager.acquire_write_lock(test_file, "agent-A", timeout=5.0)
        async with lock:
            results.append("A-acquired")
        await asyncio.sleep(0.25)
        manager.release_lock(test_file, "agent-A")
        async with lock:
            results.append("A-released")

    async def agent_b():
        await asyncio.sleep(0.05)
        async with lock:
            results.append("B-before")
        await manager.acquire_write_lock(test_file, "agent-B", timeout=5.0)
        async with lock:
            results.append("B-acquired")
        manager.release_lock(test_file, "agent-B")

    await asyncio.gather(agent_a(), agent_b())
    ok = (
        results.index("A-acquired") < results.index("B-before")
        and results.index("A-released") < results.index("B-acquired")
    )
    REPORT.add(
        "File Locks",
        "Two agents write same file — one waits",
        "PASS" if ok else "FAIL",
        "" if ok else f"Unexpected ordering: {results}",
    )


async def _test_multiple_agents_read():
    manager = FileLockManager()
    test_file = str(_temp_db.parent / "shared_read.txt")
    Path(test_file).write_text("x")
    acquired: list[str] = []
    lock = asyncio.Lock()

    async def reader(name: str):
        await manager.acquire_read_lock(test_file, name, timeout=2.0)
        async with lock:
            acquired.append(name)
        await asyncio.sleep(0.1)
        manager.release_lock(test_file, name)

    await asyncio.gather(reader("r1"), reader("r2"), reader("r3"))
    ok = len(acquired) == 3
    REPORT.add(
        "File Locks",
        "Multiple agents read same file simultaneously",
        "PASS" if ok else "FAIL",
        "" if ok else f"Only {len(acquired)} readers acquired",
    )


async def _test_lock_timeout():
    manager = FileLockManager()
    test_file = str(_temp_db.parent / "timeout.txt")
    Path(test_file).write_text("x")
    await manager.acquire_write_lock(test_file, "agent-X", timeout=0.15)
    locked_before = manager.is_locked(test_file)
    await asyncio.sleep(0.35)
    manager._prune_expired()
    locked_after = manager.is_locked(test_file)
    ok = locked_before and not locked_after
    REPORT.add(
        "File Locks",
        "Lock expires after timeout",
        "PASS" if ok else "FAIL",
        "" if ok else f"Before={locked_before}, After={locked_after}",
    )


async def _test_lock_wait_timeout():
    manager = FileLockManager()
    test_file = str(_temp_db.parent / "blocked.txt")
    Path(test_file).write_text("x")
    await manager.acquire_write_lock(test_file, "holder", timeout=60.0)
    try:
        await manager.acquire_write_lock(test_file, "waiter", timeout=0.1)
        ok = False
        msg = "No timeout raised"
    except LockError as e:
        ok = "Timeout acquiring" in str(e)
        msg = "" if ok else f"Wrong exception: {e}"
    manager.release_lock(test_file, "holder")
    REPORT.add(
        "File Locks",
        "Lock wait timeout raises LockError",
        "PASS" if ok else "FAIL",
        msg,
    )


async def _test_deadlock_detection():
    manager = FileLockManager()
    fa = str(_temp_db.parent / "dead_a.txt")
    fb = str(_temp_db.parent / "dead_b.txt")
    Path(fa).write_text("a")
    Path(fb).write_text("b")
    await manager.acquire_write_lock(fa, "agent-1", timeout=60.0)
    await manager.acquire_write_lock(fb, "agent-2", timeout=60.0)
    manager._wait_graph["agent-1"].add(fb)
    manager._wait_graph["agent-2"].add(fa)
    deadlocked = manager.detect_deadlock()
    has_cycle = "agent-1" in deadlocked and "agent-2" in deadlocked
    try:
        await manager.acquire_write_lock(fb, "agent-1", timeout=0.5)
        raised = False
    except DeadlockError:
        raised = True
    manager.release_lock(fa, "agent-1")
    manager.release_lock(fb, "agent-2")
    ok = has_cycle and raised
    REPORT.add(
        "File Locks",
        "Deadlock detection — cycle detected and raises DeadlockError",
        "PASS" if ok else "FAIL",
        "" if ok else f"has_cycle={has_cycle}, raised={raised}",
    )


async def run_file_lock_tests():
    await _test_two_agents_write_same_file()
    await _test_multiple_agents_read()
    await _test_lock_timeout()
    await _test_lock_wait_timeout()
    await _test_deadlock_detection()


# ──────────────────────────────────────────────────────────────────────────────
# Shared Memory Tests
# ──────────────────────────────────────────────────────────────────────────────


async def _test_shm_write_three_agents():
    shm = get_shared_memory()
    e1 = await shm.write_entry("CODER", "code.change", "Fixed null pointer")
    e2 = await shm.write_entry("ANALYZER", "review.note", "Looks good")
    e3 = await shm.write_entry("BUG_HUNTER_STATIC", "bug.found", "Race condition in locks")
    ok = {e.author_agent for e in await shm.read_entries(limit=10)} == {
        "CODER",
        "ANALYZER",
        "BUG_HUNTER_STATIC",
    }
    REPORT.add(
        "Shared Memory",
        "Write entries from 3 different agents",
        "PASS" if ok else "FAIL",
        "" if ok else "Not all agents present",
    )


async def _test_shm_filters():
    shm = get_shared_memory()
    await shm.write_entry("CODER", "code.change", "fix 1", tags=["api"])
    await shm.write_entry("CODER", "code.change", "fix 2", tags=["ui"])
    await shm.write_entry("ANALYZER", "bug.discovery", "found issue", tags=["security"])
    ok_topic = len(await shm.read_entries(topic="code.change")) == 2
    ok_agent = len(await shm.read_entries(agent="ANALYZER")) == 1
    ok_tag = len(await shm.read_entries(tags=["security"])) == 1
    ok = ok_topic and ok_agent and ok_tag
    REPORT.add(
        "Shared Memory",
        "Read entries with filters (topic, agent, tags)",
        "PASS" if ok else "FAIL",
        "" if ok else f"topic={ok_topic}, agent={ok_agent}, tag={ok_tag}",
    )


async def _test_shm_search():
    shm = get_shared_memory()
    await shm.write_entry("CODER", "auth.refactor", "Refactored JWT handling")
    await shm.write_entry("ANALYZER", "db.optimisation", "Added indexes on users")
    r1 = await shm.search_entries("JWT")
    r2 = await shm.search_entries("indexes")
    ok = len(r1) == 1 and r1[0].topic == "auth.refactor" and len(r2) == 1
    REPORT.add(
        "Shared Memory",
        "Search entries",
        "PASS" if ok else "FAIL",
        "" if ok else f"JWT results={len(r1)}, indexes results={len(r2)}",
    )


async def _test_shm_link_and_thread():
    shm = get_shared_memory()
    e1 = await shm.write_entry("CODER", "code.change", "Initial implementation")
    e2 = await shm.write_entry("CODER", "code.change", "Follow-up fix")
    e3 = await shm.write_entry("ANALYZER", "review.note", "Approved")
    ok_link1 = await shm.link_entries(e1.entry_id, e2.entry_id, "follow_up") is True
    ok_link2 = await shm.link_entries(e1.entry_id, e3.entry_id, "review") is True
    ok_dup = await shm.link_entries(e1.entry_id, e2.entry_id, "follow_up") is False
    thread = await shm.get_thread(e1.entry_id)
    ids = {e.entry_id for e in thread}
    ok_thread = {e1.entry_id, e2.entry_id, e3.entry_id}.issubset(ids)
    ok = ok_link1 and ok_link2 and ok_dup and ok_thread
    REPORT.add(
        "Shared Memory",
        "Link related entries and get thread",
        "PASS" if ok else "FAIL",
        "" if ok else f"link1={ok_link1}, link2={ok_link2}, dup={ok_dup}, thread={ok_thread}",
    )


async def _test_shm_archive():
    shm = get_shared_memory()
    old_ts = (datetime.now(UTC) - timedelta(days=40)).isoformat()
    await shm.write_entry("CODER", "code.change", "Old change", importance=0.1)
    with _db_mod.get_db() as conn:
        conn.execute("UPDATE whiteboard_entries SET timestamp = ?", (old_ts,))
    await shm.write_entry("CODER", "code.change", "Recent change", importance=0.1)
    archived = await shm.archive_old_entries(days=30, max_importance=0.3)
    remaining = await shm.read_entries(topic="code.change")
    ok = archived == 1 and len(remaining) == 1 and remaining[0].content == "Recent change"
    REPORT.add(
        "Shared Memory",
        "Archive old entries",
        "PASS" if ok else "FAIL",
        "" if ok else f"archived={archived}, remaining={len(remaining)}",
    )


async def run_shared_memory_tests():
    await _test_shm_write_three_agents()
    await _test_shm_filters()
    await _test_shm_search()
    await _test_shm_link_and_thread()
    await _test_shm_archive()


# ──────────────────────────────────────────────────────────────────────────────
# Peer Review Tests
# ──────────────────────────────────────────────────────────────────────────────


async def _test_pr_submit():
    prs = get_peer_review_system()
    review = await prs.submit_for_review(
        artifact_id="api.py", artifact_type="code", author_agent="CODER", content="def hello(): pass"
    )
    ok = review.review_id and review.status == "pending"
    REPORT.add(
        "Peer Review",
        "Submit a code snippet for review",
        "PASS" if ok else "FAIL",
        "" if ok else "Missing review_id or wrong status",
    )


async def _test_pr_required_reviewers():
    prs = get_peer_review_system()
    await prs.submit_for_review("x.py", "code", "CODER", "x")
    required = prs.get_required_reviewers("CODER")
    ok = "ANALYZER" in required and "BUG_HUNTER_STATIC" in required
    REPORT.add(
        "Peer Review",
        "Required reviewers are assigned for CODER",
        "PASS" if ok else "FAIL",
        "" if ok else f"Required={required}",
    )


async def _test_pr_review_rules():
    prs = get_peer_review_system()
    coder = prs.get_required_reviewers("CODER")
    arch = prs.get_required_reviewers("ARCHITECT_DESIGN")
    ok = coder == ["ANALYZER", "BUG_HUNTER_STATIC"] and arch == ["ARCHITECT_COMPLEXITY"]
    REPORT.add(
        "Peer Review",
        "Review rules: CODER → ANALYZER + BUG_HUNTER_STATIC",
        "PASS" if ok else "FAIL",
        "" if ok else f"CODER={coder}, ARCHITECT_DESIGN={arch}",
    )


async def _test_pr_status_flow():
    prs = get_peer_review_system()
    review = await prs.submit_for_review("y.py", "code", "CODER", "y")
    await prs.conduct_review(review.review_id, "ANALYZER", "approved")
    s1 = (await prs.get_review_request(review.review_id)).status
    await prs.conduct_review(review.review_id, "BUG_HUNTER_STATIC", "approved")
    s2 = (await prs.get_review_request(review.review_id)).status
    ok = s1 == "in_review" and s2 == "approved"
    REPORT.add(
        "Peer Review",
        "Status stays in_review until all required reviewers approve",
        "PASS" if ok else "FAIL",
        "" if ok else f"After 1 reviewer={s1}, After 2 reviewers={s2}",
    )


async def run_peer_review_tests():
    await _test_pr_submit()
    await _test_pr_required_reviewers()
    await _test_pr_review_rules()
    await _test_pr_status_flow()


# ──────────────────────────────────────────────────────────────────────────────
# Race-condition stress tests
# ──────────────────────────────────────────────────────────────────────────────


async def _test_concurrent_shm_writes():
    shm = get_shared_memory()
    errors: list[str] = []
    entry_ids: list[str] = []
    lock = asyncio.Lock()

    async def writer(agent: str, idx: int):
        try:
            e = await shm.write_entry(agent, "stress.test", f"entry-{idx}", tags=["stress"])
            async with lock:
                entry_ids.append(e.entry_id)
        except Exception as e:
            async with lock:
                errors.append(str(e))

    await asyncio.gather(*[writer(f"agent-{i % 3}", i) for i in range(30)])

    ok = not errors and len(entry_ids) == 30
    if not ok:
        REPORT.race_conditions.append(
            "SharedMemory: concurrent writes from 30 coroutines" + (f" — errors: {errors[:3]}" if errors else "")
        )
    REPORT.add(
        "Race Conditions",
        "30 concurrent whiteboard writes",
        "PASS" if ok else "FAIL",
        "" if ok else f"errors={len(errors)}, entries={len(entry_ids)}",
    )


async def _test_concurrent_pr_submissions():
    prs = get_peer_review_system()
    review_ids: list[str] = []
    errors: list[str] = []
    lock = asyncio.Lock()

    async def submit(idx: int):
        try:
            r = await prs.submit_for_review(f"f{idx}.py", "code", "CODER", f"def f{idx}(): pass")
            async with lock:
                review_ids.append(r.review_id)
        except Exception as e:
            async with lock:
                errors.append(str(e))

    await asyncio.gather(*[submit(i) for i in range(20)])

    ok = not errors and len(review_ids) == 20 and len(set(review_ids)) == 20
    if not ok:
        REPORT.race_conditions.append(
            "PeerReview: concurrent submissions from 20 coroutines" + (f" — errors: {errors[:3]}" if errors else "")
        )
    REPORT.add(
        "Race Conditions",
        "20 concurrent review submissions",
        "PASS" if ok else "FAIL",
        "" if ok else f"errors={len(errors)}, ids={len(review_ids)}, unique={len(set(review_ids))}",
    )


async def run_race_condition_tests():
    await _test_concurrent_shm_writes()
    await _test_concurrent_pr_submissions()


# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run collaboration layer E2E tests")
    parser.add_argument("--report-path", default="COLLABORATION_TEST_REPORT.md", help="Output markdown report path")
    args = parser.parse_args()

    print("[RUN] Running File Lock tests...")
    await run_file_lock_tests()

    print("[RUN] Running Shared Memory tests...")
    await run_shared_memory_tests()

    print("[RUN] Running Peer Review tests...")
    await run_peer_review_tests()

    print("[RUN] Running Race Condition stress tests...")
    await run_race_condition_tests()

    md = REPORT.markdown()
    Path(args.report_path).write_text(md, encoding="utf-8")
    print(f"\n[DONE] Report written to: {args.report_path}")
    print(f"   Results: {sum(1 for r in REPORT.rows if r['result'] == 'PASS')}/{len(REPORT.rows)} passed")


if __name__ == "__main__":
    asyncio.run(main())
