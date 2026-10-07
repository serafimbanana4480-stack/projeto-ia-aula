"""TeamLeader — base class for specialized agent leaders.

Each team leader declares capabilities and can delegate subtasks
to other agents via the MessageBus.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.agents.base import AgentBase


@dataclass
class TeamCapability:
    """Capability declaration for a team leader."""

    name: str
    description: str = ""
    primary: bool = True
    stacks: list[str] = field(default_factory=list)


class TeamLeader(AgentBase):
    """Extended agent base with capability declarations and delegation.

    Subclasses must define:
    - capabilities: list of TeamCapability
    - delegate(): async method for subtask delegation
    """

    capabilities: list[TeamCapability] = []
    delegation_timeout: float = 30.0

    def can_handle(self, task_type: str, stack: str = "") -> bool:
        """Check if this team leader can handle a task type.

        Args:
            task_type: Capability name to check.
            stack: Optional stack preference.

        Returns:
            True if this leader can handle the task.
        """
        for cap in self.capabilities:
            if cap.name == task_type:
                if not stack or not cap.stacks or stack in cap.stacks:
                    return True
        return False

    async def delegate(
        self,
        task_type: str,
        task_description: str,
        registry: dict[str, TeamLeader],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Delegate a subtask to another team leader.

        Args:
            task_type: Required capability.
            task_description: What needs to be done.
            registry: Team leader registry for lookup.
            timeout: Max wait time.

        Returns:
            Result dict with status and output.
        """

        # Find capable leader
        for name, leader in registry.items():
            if name != self.name and leader.can_handle(task_type):
                # In real implementation, this would call leader.run()
                return {
                    "status": "delegated",
                    "to": name,
                    "task": task_type,
                    "description": task_description,
                }

        return {
            "status": "failed",
            "error": f"No team leader found for {task_type}",
        }
