"""Sandbox Audit — structured audit logging for all sandbox executions.

Logs every execution with agent identity, command hash, result, and
risk level to immutable JSON log files for forensic analysis.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.sandbox.auth import AgentIdentity
from backend.sandbox.types import SandboxResult

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    """A single audit log entry for a sandbox execution."""

    timestamp: str
    event_type: str
    audit_id: str
    agent_id: str
    role: str
    sandbox_id: str
    execution_id: str
    command_hash: str
    exit_code: int
    duration_ms: int
    risk_level: str
    token_jti: str | None
    dependencies_installed: list[str]
    policy_violations: list[str]


class AuditLogger:
    """Structured audit logger for sandbox executions."""

    def __init__(self, output_dir: Path | str | None = None) -> None:
        self._output_dir = Path(output_dir) if output_dir else Path("logs/audit")
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def _today_file(self) -> Path:
        """Get the log file path for today."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._output_dir / f"audit-{today}.jsonl"

    @staticmethod
    def _hash_command(code: str) -> str:
        """Create SHA-256 hash of code for audit trail."""
        return hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]

    def log_execution(
        self,
        identity: AgentIdentity | None,
        code: str,
        result: SandboxResult,
    ) -> str:
        """Log a sandbox execution to the audit trail.

        Args:
            identity: Agent identity (or None for anonymous).
            code: Executed code.
            result: Execution result.

        Returns:
            Audit entry ID.
        """
        audit_id = f"audit-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{result.execution_id}"

        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type="sandbox_execution",
            audit_id=audit_id,
            agent_id=identity.agent_id if identity else "anonymous",
            role=identity.role.value if identity else "unknown",
            sandbox_id=identity.sandbox_id if identity else "",
            execution_id=result.execution_id,
            command_hash=self._hash_command(code),
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            risk_level=result.risk_level.value if hasattr(result.risk_level, 'value') else str(result.risk_level),
            token_jti=identity.token_jti if identity else None,
            dependencies_installed=result.dependencies_installed,
            policy_violations=result.policy_violations,
        )

        # Append to daily JSONL file
        log_file = self._today_file()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(entry), ensure_ascii=False) + "\n")

        logger.debug("Audit logged: %s", audit_id)
        return audit_id

    def log_policy_violation(
        self,
        identity: AgentIdentity | None,
        code: str,
        reason: str,
    ) -> str:
        """Log a policy violation.

        Args:
            identity: Agent identity.
            code: Blocked code.
            reason: Violation reason.

        Returns:
            Audit entry ID.
        """
        audit_id = f"audit-violation-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "policy_violation",
            "audit_id": audit_id,
            "agent_id": identity.agent_id if identity else "anonymous",
            "role": identity.role.value if identity else "unknown",
            "command_hash": self._hash_command(code),
            "reason": reason,
            "severity": "critical" if "CRITICAL" in reason else "warning",
        }

        log_file = self._today_file()
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

        logger.warning("Policy violation logged: %s — %s", audit_id, reason)
        return audit_id

    def get_audit_trail(
        self,
        agent_id: str | None = None,
        since: datetime | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search audit logs by criteria.

        Args:
            agent_id: Filter by agent ID.
            since: Filter entries after this datetime.
            event_type: Filter by event type.

        Returns:
            List of matching audit entries.
        """
        results: list[dict[str, Any]] = []

        # Read all audit files
        for log_file in sorted(self._output_dir.glob("audit-*.jsonl")):
            with open(log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    # Apply filters
                    if agent_id and entry.get("agent_id") != agent_id:
                        continue
                    if event_type and entry.get("event_type") != event_type:
                        continue
                    if since:
                        entry_time = datetime.fromisoformat(
                            entry.get("timestamp", "").replace("Z", "+00:00")
                        )
                        if entry_time < since:
                            continue

                    results.append(entry)

        return results
