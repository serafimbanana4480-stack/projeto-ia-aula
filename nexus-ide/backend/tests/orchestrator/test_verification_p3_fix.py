"""P3 fix: when test_runner fails to execute (no pytest), the verification
must return ok=False, not ok=True.

The defect (audit 2026-08-16, P3): ``run_tests`` returning ``ran=False``
or an error was treated as a green verification in some paths.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from backend.orchestrator.routes.chat_primary import _verify
from backend.runtime.primary import VerificationResult


class TestVerificationP3Fix:
    @pytest.mark.asyncio
    async def test_run_tests_not_run_returns_ok_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When the test runner reports it could not execute, verification
        must return ok=False."""
        monkeypatch.setattr(
            "backend.orchestrator.routes.chat_primary.execute_tool",
            AsyncMock(return_value={
                "status": "not_run",
                "ran": False,
                "executed": False,
                "ok": True,
                "error": "pytest not installed",
            }),
        )

        result = await _verify(
            type("FakeReq", (), {"changed_files": (), "forced": True})(),
            session_id="t-p3",
            project_path="/tmp/project",
        )
        assert isinstance(result, VerificationResult)
        assert result.ok is False, (
            "verification must be red when the runner could not execute"
        )
        assert result.ran is True

    @pytest.mark.asyncio
    async def test_run_tests_exception_returns_ok_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When execute_tool raises, verification must return ok=False."""
        monkeypatch.setattr(
            "backend.orchestrator.routes.chat_primary.execute_tool",
            AsyncMock(side_effect=RuntimeError("pytest not installed")),
        )

        result = await _verify(
            type("FakeReq", (), {"changed_files": ("a.py",), "forced": True})(),
            session_id="t-p3-exc",
            project_path="/tmp/project",
        )
        assert isinstance(result, VerificationResult)
        assert result.ok is False, (
            "verification must be red when the runner raises"
        )

    @pytest.mark.asyncio
    async def test_run_tests_zero_executed_returns_ok_false(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When pytest reports success but executed zero tests, verification
        must return ok=False to prevent a false-green (P3)."""
        monkeypatch.setattr(
            "backend.orchestrator.routes.chat_primary.execute_tool",
            AsyncMock(return_value={
                "status": "passed",
                "ran": True,
                "executed": False,
                "ok": True,
                "passed": 0,
                "failed": 0,
                "errors": 0,
                "total": 0,
            }),
        )

        result = await _verify(
            type("FakeReq", (), {"changed_files": ("a.py",), "forced": True})(),
            session_id="t-p3-zero",
            project_path="/tmp/project",
        )
        assert isinstance(result, VerificationResult)
        assert result.ok is False, (
            "verification must be red when zero tests were executed despite ran=True"
        )
        assert result.ran is True
