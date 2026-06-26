"""IntegrationPlanner — cross-system integration planning."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class IntegrationStatus(str, Enum):
    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    TESTING = "testing"
    COMPLETED = "completed"
    BLOCKED = "blocked"


@dataclass
class IntegrationPlan:
    """A plan for integrating two systems."""

    plan_id: str
    name: str
    source_system: str
    target_system: str
    integration_type: str  # api, event, file, database
    protocol: str
    data_mapping: list[dict[str, Any]] = field(default_factory=list)
    error_handling: str = "retry with exponential backoff"
    status: IntegrationStatus = IntegrationStatus.PLANNED
    dependencies: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    test_strategy: str = ""


class IntegrationPlanner:
    """Plans and tracks cross-system integrations."""

    def __init__(self) -> None:
        self._plans: dict[str, IntegrationPlan] = {}

    def create_plan(
        self,
        name: str,
        source_system: str,
        target_system: str,
        integration_type: str,
        protocol: str,
    ) -> IntegrationPlan:
        plan = IntegrationPlan(
            plan_id=f"int-{uuid.uuid4().hex[:8]}",
            name=name,
            source_system=source_system,
            target_system=target_system,
            integration_type=integration_type,
            protocol=protocol,
        )
        self._plans[plan.plan_id] = plan
        return plan

    def add_data_mapping(self, plan_id: str, source_field: str, target_field: str, transform: str = "") -> bool:
        plan = self._plans.get(plan_id)
        if not plan:
            return False
        plan.data_mapping.append({
            "source": source_field,
            "target": target_field,
            "transform": transform,
        })
        return True

    def update_status(self, plan_id: str, status: IntegrationStatus) -> Optional[IntegrationPlan]:
        plan = self._plans.get(plan_id)
        if plan:
            plan.status = status
        return plan

    def get_plan(self, plan_id: str) -> Optional[IntegrationPlan]:
        return self._plans.get(plan_id)

    def list_plans(self, status: IntegrationStatus | None = None) -> list[IntegrationPlan]:
        plans = list(self._plans.values())
        if status:
            plans = [p for p in plans if p.status == status]
        return plans

    def get_by_system(self, system_name: str) -> list[IntegrationPlan]:
        return [
            p for p in self._plans.values()
            if p.source_system == system_name or p.target_system == system_name
        ]

    def stats(self) -> dict[str, Any]:
        by_status = {s.value: 0 for s in IntegrationStatus}
        for p in self._plans.values():
            by_status[p.status.value] += 1
        return {
            "total": len(self._plans),
            "by_status": by_status,
            "completed": by_status[IntegrationStatus.COMPLETED.value],
        }
