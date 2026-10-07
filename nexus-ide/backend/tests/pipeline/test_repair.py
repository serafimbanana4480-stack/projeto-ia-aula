"""Tests for RepairAgent and RepairLoop."""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from backend.pipeline.repair import (
    FailureReport,
    RepairAgent,
    RepairAttempt,
    RepairLoop,
    RepairState,
    RepairTicket,
)
from backend.pipeline.test_generator import FailureType
from backend.pipeline.test_generator import TestResult as TR
from backend.pipeline.test_generator import TestSuiteReport as TSR


class TestFailureReport:
    def test_to_dict(self) -> None:
        report = FailureReport(
            story_id="story-1",
            failure_type=FailureType.ASSERTION,
            error_message="assert failed",
            source_path="app.py",
        )
        d = report.to_dict()
        assert d["story_id"] == "story-1"
        assert d["failure_type"] == "assertion"


class TestRepairTicket:
    def test_initial_state(self) -> None:
        ticket = RepairTicket(story_id="story-1", max_attempts=3)
        assert ticket.state == RepairState.PENDING
        assert ticket.can_retry
        assert ticket.current_attempt == 0

    def test_can_retry_false_after_resolve(self) -> None:
        ticket = RepairTicket(max_attempts=3)
        ticket.state = RepairState.RESOLVED
        assert not ticket.can_retry

    def test_can_retry_false_after_max(self) -> None:
        ticket = RepairTicket(max_attempts=2)
        ticket.attempts = [
            RepairAttempt(attempt_number=1, state=RepairState.TESTING),
            RepairAttempt(attempt_number=2, state=RepairState.TESTING),
        ]
        assert not ticket.can_retry

    def test_to_dict(self) -> None:
        ticket = RepairTicket(story_id="s1", max_attempts=5)
        d = ticket.to_dict()
        assert d["story_id"] == "s1"
        assert d["max_attempts"] == 5
        assert d["can_retry"]


class TestRepairAgent:
    def test_extract_diff_from_markdown(self) -> None:
        agent = RepairAgent()
        content = "Some text\n```diff\n--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-x\n+y\n```\nMore text"
        diff = agent._extract_diff(content)
        assert diff.startswith("--- a/file.py")
        assert "+y" in diff

    def test_extract_diff_raw(self) -> None:
        agent = RepairAgent()
        content = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-x\n+y"
        diff = agent._extract_diff(content)
        assert diff.startswith("---")

    def test_extract_diff_none(self) -> None:
        agent = RepairAgent()
        assert agent._extract_diff("no diff here") == ""

    def test_apply_patch_simple(self, tmp_path: Path) -> None:
        source = tmp_path / "file.py"
        source.write_text("line1\nline2\nline3")

        patch = """--- a/file.py
+++ b/file.py
@@ -1,3 +1,3 @@
 line1
-line2
+modified
 line3
"""
        assert RepairAgent.apply_patch(patch, source)
        content = source.read_text()
        assert "modified" in content
        assert "line2" not in content

    def test_apply_patch_invalid(self, tmp_path: Path) -> None:
        source = tmp_path / "file.py"
        source.write_text("content")
        # Invalid patch format
        assert not RepairAgent.apply_patch("not a diff", source)


class TestRepairLoop:
    def test_locate_source_from_traceback(self, tmp_path: Path) -> None:
        source = tmp_path / "app.py"
        source.write_text("code")
        failure = FailureReport(
            traceback=f'File "{source}"\n  line 5\n  x = 1',
        )
        found = RepairLoop._locate_source_file(tmp_path, failure)
        assert found == source

    def test_locate_source_from_test_name(self, tmp_path: Path) -> None:
        source = tmp_path / "module.py"
        source.write_text("code")
        failure = FailureReport(test_name="test_module")
        found = RepairLoop._locate_source_file(tmp_path, failure)
        assert found == source

    def test_locate_source_not_found(self, tmp_path: Path) -> None:
        failure = FailureReport(test_name="nonexistent")
        found = RepairLoop._locate_source_file(tmp_path, failure)
        assert found is None

    def test_extract_context(self) -> None:
        source = "\n".join(f"line {i}" for i in range(1, 51))
        failure = FailureReport(traceback="  line 25")
        context = RepairLoop._extract_context(source, failure.traceback, radius=5)
        assert "line 20" in context
        assert "line 25" in context
        assert "line 30" in context
        # Should not contain lines outside radius
        assert "line 1" not in context
        assert "line 50" not in context

    def test_extract_context_no_traceback(self) -> None:
        source = "\n".join(f"line {i}" for i in range(1, 11))
        context = RepairLoop._extract_context(source, "", radius=3)
        assert "line 1" in context
        assert "line 4" in context

    @pytest.mark.asyncio
    async def test_repair_no_failures(self, tmp_path: Path) -> None:
        loop = RepairLoop(
            repair_agent=RepairAgent(),
            test_runner=MagicMock(),
        )
        report = TSR(passed=5, total=5)
        ticket = await loop.repair(tmp_path, report)
        assert ticket.state == RepairState.RESOLVED
        assert len(ticket.attempts) == 0

    @pytest.mark.asyncio
    async def test_repair_max_attempts_enforced(self, tmp_path: Path) -> None:
        runner = MagicMock()
        # Always return failures
        runner.run.return_value = TSR(
            total=1,
            passed=0,
            failed=1,
            results=[TR(test_name="t1", status="failed")],
        )
        loop = RepairLoop(
            repair_agent=RepairAgent(),
            test_runner=runner,
            max_attempts=2,
        )
        report = TSR(
            total=1,
            passed=0,
            failed=1,
            results=[
                TR(
                    test_name="t1",
                    status="failed",
                    failure_type=FailureType.ASSERTION,
                    error_message="assert 1==2",
                ),
            ],
        )
        ticket = await loop.repair(tmp_path, report, story_id="story-1")
        assert ticket.state == RepairState.ESCALATED
        assert ticket.current_attempt == 2
        assert "Max attempts" in ticket.escalation_reason
