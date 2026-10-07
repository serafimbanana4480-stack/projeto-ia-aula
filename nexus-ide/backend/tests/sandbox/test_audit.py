"""Tests for AuditLogger structured logging."""
from __future__ import annotations

import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from backend.sandbox.audit import AuditLogger
from backend.sandbox.auth import AgentIdentity, Role
from backend.sandbox.executor import RiskLevel, SandboxResult


class TestAuditLogger:
    @pytest.fixture
    def logger(self) -> AuditLogger:
        tmpdir = tempfile.mkdtemp()
        return AuditLogger(output_dir=tmpdir)

    def test_log_execution(self, logger: AuditLogger) -> None:
        identity = AgentIdentity(
            agent_id="agent-1",
            role=Role.DEVELOPER,
            sandbox_id="sandbox-1",
            issued_at=datetime.now(UTC),
            expires_at=datetime.now(UTC),
            token_jti="jti-123",
        )
        result = SandboxResult(
            execution_id="exec-1",
            stdout="hello",
            stderr="",
            exit_code=0,
            timed_out=False,
            duration_ms=1500,
            risk_level=RiskLevel.SAFE,
            dependencies_installed=["requests"],
        )

        audit_id = logger.log_execution(identity, "print('hello')", result)
        assert audit_id.startswith("audit-")

        # Verify log file was written
        log_files = list(Path(logger._output_dir).glob("audit-*.jsonl"))
        assert len(log_files) == 1

        with open(log_files[0]) as f:
            entry = json.loads(f.readline())

        assert entry["event_type"] == "sandbox_execution"
        assert entry["agent_id"] == "agent-1"
        assert entry["role"] == "developer"
        assert entry["exit_code"] == 0
        assert entry["command_hash"] is not None
        assert entry["dependencies_installed"] == ["requests"]

    def test_log_policy_violation(self, logger: AuditLogger) -> None:
        audit_id = logger.log_policy_violation(
            None,
            "rm -rf /",
            "CRITICAL: Recursive root deletion",
        )
        assert audit_id.startswith("audit-violation-")

        log_files = list(Path(logger._output_dir).glob("audit-*.jsonl"))
        with open(log_files[0]) as f:
            entry = json.loads(f.readline())

        assert entry["event_type"] == "policy_violation"
        assert entry["severity"] == "critical"
        assert "root deletion" in entry["reason"]

    def test_get_audit_trail_by_agent(self, logger: AuditLogger) -> None:
        # Log two executions for different agents
        for agent_id in ["agent-a", "agent-b"]:
            identity = AgentIdentity(
                agent_id=agent_id,
                role=Role.DEVELOPER,
                sandbox_id="sandbox-1",
                issued_at=datetime.now(UTC),
                expires_at=datetime.now(UTC),
                token_jti=f"jti-{agent_id}",
            )
            result = SandboxResult(
                execution_id=f"exec-{agent_id}",
                stdout="",
                stderr="",
                exit_code=0,
                timed_out=False,
                duration_ms=100,
            )
            logger.log_execution(identity, "print('test')", result)

        # Query for agent-a only
        trail = logger.get_audit_trail(agent_id="agent-a")
        assert len(trail) == 1
        assert trail[0]["agent_id"] == "agent-a"

    def test_get_audit_trail_by_event_type(self, logger: AuditLogger) -> None:
        # Log different event types
        logger.log_policy_violation(None, "bad", "reason")

        result = SandboxResult(
            execution_id="exec-1", stdout="", stderr="",
            exit_code=0, timed_out=False, duration_ms=100,
        )
        logger.log_execution(None, "print('ok')", result)

        # Filter by event type
        violations = logger.get_audit_trail(event_type="policy_violation")
        assert len(violations) == 1
        assert violations[0]["event_type"] == "policy_violation"
