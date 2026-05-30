"""Task Spawner tool - allows agents to dynamically spawn new tasks in the orchestrator.

This is a core autonomy feature. If an agent realizes that the current task 
requires additional steps (e.g., refactoring before implementation), 
it can spawn new tasks that the orchestrator will then schedule.
"""

from __future__ import annotations

import logging
from typing import Any, get_args

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

async def spawn_task(
    name: str,
    description: str,
    agent: str = "CODER",
    priority: str = "medium",
    context: str = "",
    parent_id: str | None = None,
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    """Spawn a new task dynamically in the active orchestration run.

    Args:
        name: Short, descriptive name for the task.
        description: Detailed instructions for the task.
        agent: Agent type to execute the task (CODER, ANALYZER, etc).
        priority: Task priority (low, medium, high, critical).
        context: Additional context to provide to the agent.
        parent_id: Optional ID of the parent task/phase.
        depends_on: Optional list of task IDs this task depends on.

    Returns:
        Dict with the spawned task_id or an error.
    """
    logger.info("Spawning dynamic task: %s (agent=%s)", name, agent)

    # Validate agent is in the allowed list
    from backend.models.api import AgentName

    valid_agents = list(get_args(AgentName))
    if agent not in valid_agents:
        error_msg = f"Invalid agent '{agent}'. Must be one of: {valid_agents}"
        logger.error(error_msg)
        return {
            "status": "error",
            "error": error_msg,
            "task_name": name,
        }

    # Return structured spawn request that the OrchestrationEngine will intercept
    # from the tool result event and inject into the dependency graph.
    return {
        "status": "spawned",
        "task_name": name,
        "agent": agent,
        "priority": priority,
        "description": description,
        "context": context,
        "parent_id": parent_id,
        "depends_on": depends_on or [],
    }

register_tool(
    ToolSpec(
        name="spawn_task",
        description=(
            "Dynamically spawn a new task in the current orchestration run. "
            "Use this if you realize the current objective requires additional "
            "steps that were not in the original plan."
        ),
        schema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Short, descriptive name for the task",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed instructions for the agent",
                },
                "agent": {
                    "type": "string",
                    "enum": ["ARCHITECT", "RESEARCHER", "CODER", "ANALYZER", "DEBUGGER", "DOCUMENTER", "OPTIMIZER", "REFACTOR_PERFORMANCE", "REFACTOR_CLEAN"],
                    "description": "Agent type to execute the task",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "medium", "high", "critical"],
                    "description": "Task priority level",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context for the agent",
                },
                "parent_id": {
                    "type": "string",
                    "description": "Optional ID of the parent task/phase",
                },
                "depends_on": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of task IDs this task depends on",
                },
            },
            "required": ["name", "description"],
        },
        handler=spawn_task,
    )
)
