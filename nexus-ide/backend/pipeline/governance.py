"""Governance — autonomy levels, kill-switch, council, and immutable ledger.

Phase 10: Governanca e Seguranca
- AutonomyManager: 5 niveis de autonomia (Manual a Full)
- KillSwitch: congela acoes autonomas em <1s
- StateSnapshot: snapshots de estado global para rollback
- GovernanceCouncil: 3 auditores que podem vetar acoes
- ImmutableLedger: log append-only com hash chain SHA-256
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


# ============================================================================
# 10-01: Autonomy Levels
# ============================================================================

class AutonomyLevel(Enum):
    """Five levels of operational autonomy."""

    MANUAL = 0            # No autonomous actions — human approves everything
    SUPERVISED = 1        # Agent proposes, human approves before execution
    SEMI_AUTONOMOUS = 2   # Non-destructive tasks auto, human approves deploy/critical
    AUTONOMOUS = 3        # Everything except production deploy
    FULL = 4              # Full autonomy (dev/staging only)

    @property
    def label(self) -> str:
        labels = {
            0: "Manual",
            1: "Supervised",
            2: "Semi-Autonomous",
            3: "Autonomous",
            4: "Full",
        }
        return labels[self.value]

    @property
    def allows_code_gen(self) -> bool:
        return self.value >= AutonomyLevel.SEMI_AUTONOMOUS.value

    @property
    def allows_auto_deploy(self) -> bool:
        return self.value >= AutonomyLevel.AUTONOMOUS.value

    @property
    def allows_prod_deploy(self) -> bool:
        return self.value >= AutonomyLevel.FULL.value


# Action categories for permission checking
NON_DESTRUCTIVE_ACTIONS = {
    "code_generation", "test_generation", "documentation",
    "code_review", "research", "analysis", "refactoring",
}
DESTRUCTIVE_ACTIONS = {
    "deploy", "delete", "drop_table", "truncate",
    "rm_file", "force_push", "schema_migration",
}
CRITICAL_ACTIONS = {
    "production_deploy", "user_data_delete", "config_change",
    "security_policy_change", "kill_switch_deactivate",
}


class AutonomyManager:
    """Manages autonomy levels and permission checks."""

    def __init__(self, default_level: AutonomyLevel = AutonomyLevel.SEMI_AUTONOMOUS) -> None:
        self._global_level = default_level
        self._role_overrides: dict[str, AutonomyLevel] = {}
        self._action_overrides: dict[str, AutonomyLevel] = {}

    @property
    def level(self) -> AutonomyLevel:
        return self._global_level

    def set_level(self, level: AutonomyLevel) -> None:
        old = self._global_level
        self._global_level = level
        logger.info("Autonomy level changed: %s -> %s", old.label, level.label)

    def set_role_override(self, role: str, level: AutonomyLevel) -> None:
        self._role_overrides[role] = level

    def set_action_override(self, action: str, min_level: AutonomyLevel) -> None:
        self._action_overrides[action] = min_level

    def check_permission(self, action: str, role: str = "",
                         environment: str = "staging") -> bool:
        """Check if an action is allowed at current autonomy level.

        Args:
            action: The action being attempted.
            role: Agent role (for role-specific overrides).
            environment: staging or production.

        Returns:
            True if action is permitted.
        """
        effective_level = self._global_level

        # Apply role override if set
        if role in self._role_overrides:
            effective_level = self._role_overrides[role]

        # Apply action override if set
        if action in self._action_overrides:
            required = self._action_overrides[action]
            return effective_level.value >= required.value

        # Production deploy requires FULL or explicit override
        if environment == "production" and action == "deploy":
            return effective_level.allows_prod_deploy

        # Critical actions require AUTONOMOUS
        if action in CRITICAL_ACTIONS:
            return effective_level.value >= AutonomyLevel.AUTONOMOUS.value

        # Destructive actions require SEMI_AUTONOMOUS
        if action in DESTRUCTIVE_ACTIONS:
            return effective_level.value >= AutonomyLevel.SEMI_AUTONOMOUS.value

        # Non-destructive actions allowed from SUPERVISED
        if action in NON_DESTRUCTIVE_ACTIONS:
            return effective_level.value >= AutonomyLevel.SUPERVISED.value

        # Unknown actions: require SEMI_AUTONOMOUS
        return effective_level.value >= AutonomyLevel.SEMI_AUTONOMOUS.value

    def get_effective_level(self, role: str = "") -> AutonomyLevel:
        """Get effective autonomy level considering role overrides."""
        if role in self._role_overrides:
            return self._role_overrides[role]
        return self._global_level

    def to_dict(self) -> dict[str, Any]:
        return {
            "global_level": self._global_level.label,
            "global_level_value": self._global_level.value,
            "role_overrides": {k: v.label for k, v in self._role_overrides.items()},
            "action_overrides": {k: v.label for k, v in self._action_overrides.items()},
        }


# ============================================================================
# 10-02: Kill Switch and State Snapshots
# ============================================================================

class KillSwitch:
    """Global kill-switch that freezes all autonomous actions.

    Thread-safe singleton that can be activated to immediately halt
    all autonomous operations.
    """

    _instance: KillSwitch | None = None
    _lock = threading.Lock()

    def __new__(cls) -> KillSwitch:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._activated = False
                    cls._instance._activated_at: str = ""
                    cls._instance._reason: str = ""
                    cls._instance._activation_count = 0
        return cls._instance

    @property
    def is_active(self) -> bool:
        return self._activated

    def activate(self, reason: str = "Manual intervention") -> str:
        """Activate the kill-switch. Returns activation timestamp."""
        self._activated = True
        self._activated_at = datetime.now(timezone.utc).isoformat()
        self._reason = reason
        self._activation_count += 1
        logger.warning("KILL-SWITCH ACTIVATED: %s", reason)
        return self._activated_at

    def deactivate(self, auth_token: str = "") -> bool:
        """Deactivate the kill-switch. Requires authorization.

        In production, auth_token would be validated against a
        secure authorization system.
        """
        if not auth_token:
            logger.warning("Kill-switch deactivation requires auth token")
            return False

        self._activated = False
        logger.info("KILL-SWITCH DEACTIVATED (count: %d)", self._activation_count)
        return True

    def get_status(self) -> dict[str, Any]:
        return {
            "active": self._activated,
            "activated_at": self._activated_at,
            "reason": self._reason,
            "activation_count": self._activation_count,
        }


@dataclass
class StateSnapshot:
    """A point-in-time snapshot of system state."""

    snapshot_id: str
    timestamp: str
    autonomy_level: str
    active_agents: list[str]
    pending_tasks: int
    workflows_in_progress: list[str]
    kill_switch_active: bool
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "autonomy_level": self.autonomy_level,
            "active_agents": self.active_agents,
            "pending_tasks": self.pending_tasks,
            "workflows_in_progress": self.workflows_in_progress,
            "kill_switch_active": self.kill_switch_active,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StateSnapshot:
        return cls(
            snapshot_id=data["snapshot_id"],
            timestamp=data["timestamp"],
            autonomy_level=data["autonomy_level"],
            active_agents=data["active_agents"],
            pending_tasks=data["pending_tasks"],
            workflows_in_progress=data["workflows_in_progress"],
            kill_switch_active=data.get("kill_switch_active", False),
            metadata=data.get("metadata", {}),
        )


class SnapshotStore:
    """Manages state snapshots with 30-day retention."""

    RETENTION_DAYS = 30

    def __init__(self, storage_dir: str = "./snapshots") -> None:
        self._dir = Path(storage_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, StateSnapshot] = {}

    def capture(self, autonomy_level: str, active_agents: list[str],
                pending_tasks: int, workflows: list[str],
                kill_switch_active: bool = False,
                metadata: dict[str, Any] | None = None) -> StateSnapshot:
        """Capture current system state as a snapshot."""
        now = datetime.now(timezone.utc)
        snapshot_id = f"snap-{now.strftime('%Y%m%d-%H%M%S')}"

        snapshot = StateSnapshot(
            snapshot_id=snapshot_id,
            timestamp=now.isoformat(),
            autonomy_level=autonomy_level,
            active_agents=list(active_agents),
            pending_tasks=pending_tasks,
            workflows_in_progress=list(workflows),
            kill_switch_active=kill_switch_active,
            metadata=metadata or {},
        )

        self._save(snapshot)
        self._cache[snapshot_id] = snapshot
        logger.info("Snapshot captured: %s", snapshot_id)
        return snapshot

    def restore(self, snapshot_id: str) -> StateSnapshot | None:
        """Retrieve a snapshot for restoration."""
        if snapshot_id in self._cache:
            return self._cache[snapshot_id]

        path = self._dir / f"{snapshot_id}.json"
        if not path.exists():
            return None

        data = json.loads(path.read_text(encoding="utf-8"))
        return StateSnapshot.from_dict(data)

    def list_snapshots(self, limit: int = 50) -> list[dict[str, str]]:
        """List available snapshots."""
        files = sorted(self._dir.glob("snap-*.json"), reverse=True)
        result: list[dict[str, str]] = []
        for f in files[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                result.append({
                    "snapshot_id": data["snapshot_id"],
                    "timestamp": data["timestamp"],
                })
            except Exception:
                continue
        return result

    def prune_old(self) -> int:
        """Remove snapshots older than RETENTION_DAYS."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.RETENTION_DAYS)
        removed = 0

        for f in self._dir.glob("snap-*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                ts = datetime.fromisoformat(data["timestamp"])
                if ts < cutoff:
                    f.unlink()
                    removed += 1
                    self._cache.pop(data.get("snapshot_id", ""), None)
            except Exception:
                continue

        logger.info("Pruned %d old snapshots", removed)
        return removed

    def _save(self, snapshot: StateSnapshot) -> None:
        path = self._dir / f"{snapshot.snapshot_id}.json"
        path.write_text(json.dumps(snapshot.to_dict(), indent=2, default=str),
                       encoding="utf-8")


# ============================================================================
# 10-03: Governance Council
# ============================================================================

@dataclass
class AuditDecision:
    """Result of a governance audit."""

    action_id: str
    action: str
    agent_id: str
    timestamp: str
    security_vote: str = "approve"  # approve, deny, abstain
    compliance_vote: str = "approve"
    ethics_vote: str = "approve"
    security_reason: str = ""
    compliance_reason: str = ""
    ethics_reason: str = ""
    vetoed: bool = False
    veto_reason: str = ""

    @property
    def approve_count(self) -> int:
        return sum(1 for v in [self.security_vote, self.compliance_vote, self.ethics_vote]
                  if v == "approve")

    @property
    def deny_count(self) -> int:
        return sum(1 for v in [self.security_vote, self.compliance_vote, self.ethics_vote]
                  if v == "deny")


class AuditorAgent:
    """Base auditor agent that evaluates actions."""

    def __init__(self, name: str, rules: list[str] | None = None) -> None:
        self.name = name
        self._rules = rules or []

    def audit(self, action: str, agent_id: str, context: dict[str, Any] | None = None) -> tuple[str, str]:
        """Evaluate an action. Returns (vote, reason).

        Subclasses should override with specific logic.
        """
        return "approve", "No specific rules violated"


class SecurityAuditor(AuditorAgent):
    """Audits actions for security risks."""

    BLOCKED_ACTIONS = {"rm_file", "drop_table", "truncate", "force_push"}
    WARN_ACTIONS = {"deploy", "schema_migration"}

    def audit(self, action: str, agent_id: str, context: dict[str, Any] | None = None) -> tuple[str, str]:
        if action in self.BLOCKED_ACTIONS:
            return "deny", f"Action '{action}' blocked by security policy"

        if action in self.WARN_ACTIONS:
            env = (context or {}).get("environment", "staging")
            if env == "production":
                return "deny", f"Production {action} requires explicit approval"
            return "approve", f"{action} allowed in {env} with monitoring"

        return "approve", "No security concerns"


class ComplianceAuditor(AuditorAgent):
    """Audits actions for policy compliance."""

    def audit(self, action: str, agent_id: str, context: dict[str, Any] | None = None) -> tuple[str, str]:
        level = (context or {}).get("autonomy_level", 2)

        if action in CRITICAL_ACTIONS and level < 3:
            return "deny", f"Critical action '{action}' requires level 3+ autonomy"

        if action in DESTRUCTIVE_ACTIONS and level < 2:
            return "deny", f"Destructive action '{action}' requires level 2+ autonomy"

        return "approve", "Compliant with current policy"


class EthicsAuditor(AuditorAgent):
    """Audits actions for ethical considerations."""

    ETHICAL_CONCERNS = {
        "user_data_delete": "Deleting user data requires human confirmation",
        "production_deploy": "Production changes should be reviewed",
    }

    def audit(self, action: str, agent_id: str, context: dict[str, Any] | None = None) -> tuple[str, str]:
        if action in self.ETHICAL_CONCERNS:
            level = (context or {}).get("autonomy_level", 2)
            if level < 4:
                return "deny", self.ETHICAL_CONCERNS[action]

        return "approve", "No ethical concerns"


class GovernanceCouncil:
    """Council of 3 auditors that can veto autonomous actions."""

    VETO_THRESHOLD = 2  # 2/3 votes to veto

    def __init__(self) -> None:
        self._security = SecurityAuditor("SecurityAuditor")
        self._compliance = ComplianceAuditor("ComplianceAuditor")
        self._ethics = EthicsAuditor("EthicsAuditor")
        self._decisions: list[AuditDecision] = []

    def audit(self, action: str, agent_id: str, context: dict[str, Any] | None = None,
              timeout: float = 5.0) -> AuditDecision:
        """Submit an action for audit by all 3 council members.

        Args:
            action: Action being audited.
            agent_id: ID of the agent performing the action.
            context: Additional context for auditors.
            timeout: Max time to wait for each auditor (seconds).

        Returns:
            AuditDecision with all votes.
        """
        decision = AuditDecision(
            action_id=f"audit-{int(time.time() * 1000)}",
            action=action,
            agent_id=agent_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        # Security audit
        try:
            vote, reason = self._security.audit(action, agent_id, context)
            decision.security_vote = vote
            decision.security_reason = reason
        except Exception as exc:
            logger.error("Security audit failed: %s", exc)
            decision.security_vote = "abstain"

        # Compliance audit
        try:
            vote, reason = self._compliance.audit(action, agent_id, context)
            decision.compliance_vote = vote
            decision.compliance_reason = reason
        except Exception as exc:
            logger.error("Compliance audit failed: %s", exc)
            decision.compliance_vote = "abstain"

        # Ethics audit
        try:
            vote, reason = self._ethics.audit(action, agent_id, context)
            decision.ethics_vote = vote
            decision.ethics_reason = reason
        except Exception as exc:
            logger.error("Ethics audit failed: %s", exc)
            decision.ethics_vote = "abstain"

        # Check veto threshold
        if decision.deny_count >= self.VETO_THRESHOLD:
            decision.vetoed = True
            decision.veto_reason = (
                f"Vetoed by {decision.deny_count}/{self.VETO_THRESHOLD} auditors"
            )
            logger.warning("Action VETOED: %s by %s", action, agent_id)

        self._decisions.append(decision)
        return decision

    def is_action_allowed(self, action: str, agent_id: str,
                          context: dict[str, Any] | None = None) -> bool:
        """Quick check: is this action allowed?"""
        decision = self.audit(action, agent_id, context)
        return not decision.vetoed

    def get_decision_history(self, limit: int = 50) -> list[AuditDecision]:
        return self._decisions[-limit:]


# ============================================================================
# 10-04: Immutable Ledger
# ============================================================================

@dataclass
class LedgerEntry:
    """A single entry in the immutable audit ledger."""

    entry_id: str
    entry_type: str  # DECISION, CODE_GENERATED, TEST_EXECUTED, COMMAND_RUN, DEPLOY, ROLLBACK
    agent_id: str
    action: str
    timestamp: str
    data: dict[str, Any] = field(default_factory=dict)
    previous_hash: str = ""
    hash: str = ""

    def compute_hash(self) -> str:
        """Compute SHA-256 hash of this entry."""
        content = json.dumps({
            "entry_id": self.entry_id,
            "entry_type": self.entry_type,
            "agent_id": self.agent_id,
            "action": self.action,
            "timestamp": self.timestamp,
            "data": self.data,
            "previous_hash": self.previous_hash,
        }, sort_keys=True, default=str)
        return hashlib.sha256(content.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": self.entry_id,
            "entry_type": self.entry_type,
            "agent_id": self.agent_id,
            "action": self.action,
            "timestamp": self.timestamp,
            "data": self.data,
            "previous_hash": self.previous_hash,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LedgerEntry:
        return cls(
            entry_id=data["entry_id"],
            entry_type=data["entry_type"],
            agent_id=data["agent_id"],
            action=data["action"],
            timestamp=data["timestamp"],
            data=data.get("data", {}),
            previous_hash=data.get("previous_hash", ""),
            hash=data.get("hash", ""),
        )


class ImmutableLedger:
    """Append-only audit ledger with SHA-256 hash chain.

    Every entry links to the previous entry's hash, creating an
    immutable chain. Any tampering is detectable via verify().
    """

    def __init__(self, storage_path: str = "./audit_ledger.jsonl") -> None:
        self._path = Path(storage_path)
        self._entries: list[LedgerEntry] = []
        self._index: dict[str, int] = {}  # entry_id -> position
        self._load()

    def append(self, entry_type: str, agent_id: str, action: str,
               data: dict[str, Any] | None = None) -> LedgerEntry:
        """Append a new entry to the ledger.

        Args:
            entry_type: Type of entry (DECISION, CODE_GENERATED, etc.)
            agent_id: Agent that performed the action.
            action: Description of the action.
            data: Additional contextual data.

        Returns:
            The created LedgerEntry.
        """
        entry_id = f"ledger-{len(self._entries):06d}-{int(time.time())}"

        previous_hash = ""
        if self._entries:
            previous_hash = self._entries[-1].hash

        entry = LedgerEntry(
            entry_id=entry_id,
            entry_type=entry_type,
            agent_id=agent_id,
            action=action,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data or {},
            previous_hash=previous_hash,
        )
        entry.hash = entry.compute_hash()

        self._entries.append(entry)
        self._index[entry_id] = len(self._entries) - 1
        self._persist(entry)

        logger.debug("Ledger entry appended: %s [%s]", entry_id, entry_type)
        return entry

    def verify(self) -> tuple[bool, str]:
        """Verify the integrity of the entire hash chain.

        Returns:
            (is_valid, message) tuple.
        """
        if not self._entries:
            return True, "Ledger is empty"

        for i, entry in enumerate(self._entries):
            # Verify hash
            computed = entry.compute_hash()
            if computed != entry.hash:
                return False, f"Hash mismatch at entry {i} ({entry.entry_id})"

            # Verify chain link
            if i > 0:
                if entry.previous_hash != self._entries[i - 1].hash:
                    return False, f"Chain broken at entry {i} ({entry.entry_id})"

        return True, "Ledger integrity verified"

    def query(self, entry_type: str | None = None, agent_id: str | None = None,
              start_time: str | None = None, end_time: str | None = None,
              limit: int = 100) -> list[LedgerEntry]:
        """Query ledger entries with filters.

        All filters are optional and combined with AND.
        """
        results: list[LedgerEntry] = []

        for entry in self._entries:
            if entry_type and entry.entry_type != entry_type:
                continue
            if agent_id and entry.agent_id != agent_id:
                continue
            if start_time and entry.timestamp < start_time:
                continue
            if end_time and entry.timestamp > end_time:
                continue
            results.append(entry)

        return results[-limit:]

    def export_report(self, start_time: str = "", end_time: str = "") -> dict[str, Any]:
        """Generate an audit report for a time range."""
        entries = self.query(start_time=start_time, end_time=end_time, limit=10000)

        type_counts: dict[str, int] = {}
        agent_counts: dict[str, int] = {}

        for entry in entries:
            type_counts[entry.entry_type] = type_counts.get(entry.entry_type, 0) + 1
            agent_counts[entry.agent_id] = agent_counts.get(entry.agent_id, 0) + 1

        return {
            "total_entries": len(entries),
            "time_range": {"start": start_time, "end": end_time},
            "entry_types": type_counts,
            "agent_activity": agent_counts,
            "chain_valid": self.verify()[0],
        }

    def get_entry_count(self) -> int:
        return len(self._entries)

    def _persist(self, entry: LedgerEntry) -> None:
        """Append entry to JSONL file."""
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict(), default=str) + "\n")

    def _load(self) -> None:
        """Load existing entries from JSONL file."""
        if not self._path.exists():
            return

        try:
            with open(self._path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        entry = LedgerEntry.from_dict(data)
                        self._entries.append(entry)
                        self._index[entry.entry_id] = len(self._entries) - 1
                    except Exception:
                        continue
        except Exception as exc:
            logger.warning("Failed to load ledger: %s", exc)

        if self._entries:
            logger.info("Loaded %d ledger entries", len(self._entries))