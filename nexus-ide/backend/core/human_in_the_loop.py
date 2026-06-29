from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_POLICY_PATH = Path(".nexus/human_in_the_loop/policy.json")
DEFAULT_ESCALATIONS_PATH = Path(".nexus/human_in_the_loop/escalations.json")


@dataclass
class EscalationPolicy:
    enabled: bool = True
    require_approval_for: set[str] = field(
        default_factory=lambda: {"architecture", "security", "database", "infrastructure"}
    )
    require_approval_above_confidence: float = 0.8
    escalation_channels: list[str] = field(default_factory=lambda: ["agent_bus", "notify"])
    max_auto_apply_iterations: int = 3
    rollback_on_human_reject: bool = True


class HumanInTheLoopManager:
    def __init__(
        self,
        base_path: Path | str = Path("."),
        policy_path: Path | str | None = None,
        escalations_path: Path | str | None = None,
    ):
        self.base_path = Path(base_path)
        self.policy_path = (
            Path(policy_path) if policy_path else self.base_path / DEFAULT_POLICY_PATH
        )
        self.escalations_path = (
            Path(escalations_path)
            if escalations_path
            else self.base_path / DEFAULT_ESCALATIONS_PATH
        )
        self._policy: EscalationPolicy | None = None
        self._escalations: dict[str, dict[str, Any]] = {}
        self._load_escalations()

    # ------------------------------------------------------------------
    # Policy CRUD
    # ------------------------------------------------------------------

    def load_policy(self) -> EscalationPolicy:
        if self._policy is not None:
            return self._policy
        if not self.policy_path.exists():
            self._policy = EscalationPolicy()
            self.save_policy(self._policy)
            logger.info("Default EscalationPolicy created at %s", self.policy_path)
            return self._policy
        try:
            raw = json.loads(self.policy_path.read_text(encoding="utf-8"))
            raw["require_approval_for"] = set(raw.get("require_approval_for", []))
            self._policy = EscalationPolicy(**raw)
            return self._policy
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error(
                "Failed to load policy from %s: %s. Using defaults.", self.policy_path, exc
            )
            self._policy = EscalationPolicy()
            return self._policy

    def save_policy(self, policy: EscalationPolicy) -> None:
        self.policy_path.parent.mkdir(parents=True, exist_ok=True)
        raw = {
            "enabled": policy.enabled,
            "require_approval_for": sorted(policy.require_approval_for),
            "require_approval_above_confidence": policy.require_approval_above_confidence,
            "escalation_channels": policy.escalation_channels,
            "max_auto_apply_iterations": policy.max_auto_apply_iterations,
            "rollback_on_human_reject": policy.rollback_on_human_reject,
        }
        self.policy_path.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
        self._policy = policy
        logger.info("EscalationPolicy saved to %s", self.policy_path)

    # ------------------------------------------------------------------
    # Escalation logic
    # ------------------------------------------------------------------

    def should_escalate(self, proposal: dict, category: str, confidence: float) -> bool:
        policy = self.load_policy()
        if not policy.enabled:
            return False
        if category in policy.require_approval_for:
            return True
        return confidence >= policy.require_approval_above_confidence

    def create_escalation_request(self, proposal_id: str, proposal: dict, reason: str) -> dict:
        self.load_policy()
        request_id = f"esc_{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
        record: dict[str, Any] = {
            "request_id": request_id,
            "proposal_id": proposal_id,
            "proposal": proposal,
            "reason": reason,
            "decision": "pending",
            "operator": None,
            "notes": "",
            "decided_at": None,
            "created_at": datetime.now(UTC).isoformat(),
            "resolution": None,
        }
        self._escalations[request_id] = record
        self._persist_escalations()
        logger.info("Escalation request %s created for proposal %s", request_id, proposal_id)
        return record

    def resolve_escalation(
        self, request_id: str, decision: str, operator: str, notes: str = ""
    ) -> dict:
        valid_decisions = {"approved", "rejected", "modified"}
        if decision not in valid_decisions:
            raise ValueError(
                f"Invalid decision '{decision}'. Must be one of: {sorted(valid_decisions)}"
            )
        if request_id not in self._escalations:
            raise KeyError(f"Escalation request '{request_id}' not found")
        record = self._escalations[request_id]
        if record["decision"] != "pending":
            raise ValueError(
                f"Escalation request '{request_id}' is already resolved as '{record['decision']}'"
            )
        policy = self.load_policy()
        record["decision"] = decision
        record["operator"] = operator
        record["notes"] = notes
        record["decided_at"] = datetime.now(UTC).isoformat()
        resolution: dict[str, Any] = {
            "request_id": request_id,
            "decision": decision,
            "operator": operator,
            "notes": notes,
            "rollback_triggered": False,
        }
        if decision == "rejected" and policy.rollback_on_human_reject:
            resolution["rollback_triggered"] = True
            record["resolution"] = "rollback"
            logger.info(
                "Rollback triggered for proposal %s due to human rejection", record["proposal_id"]
            )
        elif decision == "modified":
            record["resolution"] = "modified"
        else:
            record["resolution"] = decision
        self._persist_escalations()
        logger.info("Escalation request %s resolved: %s by %s", request_id, decision, operator)
        return resolution

    def list_pending(self) -> list[dict]:
        return [record for record in self._escalations.values() if record["decision"] == "pending"]

    # ------------------------------------------------------------------
    # Internal persistence helpers
    # ------------------------------------------------------------------

    def _load_escalations(self) -> None:
        if not self.escalations_path.exists():
            self._escalations = {}
            return
        try:
            self._escalations = json.loads(self.escalations_path.read_text(encoding="utf-8"))
            if not isinstance(self._escalations, dict):
                self._escalations = {}
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("Failed to load escalations from %s: %s", self.escalations_path, exc)
            self._escalations = {}

    def _persist_escalations(self) -> None:
        self.escalations_path.parent.mkdir(parents=True, exist_ok=True)
        self.escalations_path.write_text(
            json.dumps(self._escalations, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
