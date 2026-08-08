"""Task Spawner tool - allows agents to dynamically spawn new tasks in the orchestrator.

This is a core autonomy feature. If an agent realizes that the current task
requires additional steps (e.g., refactoring before implementation),
it can spawn new tasks that the orchestrator will then schedule.
"""

from __future__ import annotations

import logging
import os
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
    session_id: str = "",
    project_path: str = "",
    autonomous: bool = True,
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

    result: dict[str, Any] = {
        "status": "spawned",
        "task_name": name,
        "agent": agent,
        "priority": priority,
        "description": description,
        "context": context,
        "parent_id": parent_id,
        "depends_on": depends_on or [],
    }

    # In normal chat there is no active OrchestrationEngine to intercept the
    # old declarative result. Attach it to the real lifecycle manager so the
    # principal can answer immediately while the specialist continues in the
    # background and remains visible in Agent Instances.
    try:
        from backend.orchestrator.main import app

        lifecycle = getattr(app.state, "agent_lifecycle", None)
        if lifecycle is not None:
            try:
                background_budget = max(
                    60,
                    int(os.environ.get("NEXUS_BACKGROUND_AGENT_TIME_BUDGET_SECONDS", "7200")),
                )
            except ValueError:
                background_budget = 7200
            try:
                background_tokens = max(
                    1000,
                    int(os.environ.get("NEXUS_BACKGROUND_AGENT_TOKEN_BUDGET", "200000")),
                )
            except ValueError:
                background_tokens = 200000
            instance_id = await lifecycle.spawn(
                agent_type=agent,
                objective=description,
                context={
                    "project_path": project_path or ".",
                    "parent_context": context,
                    "depends_on": depends_on or [],
                    "autonomous": autonomous,
                },
                mission_id=session_id,
                parent_task_id=parent_id or "",
                token_budget=background_tokens,
                time_budget_seconds=background_budget,
            )
            result.update(
                {
                    "background": True,
                    "instance_id": instance_id,
                    "message": f"{agent} continua em background; a conversa principal permanece livre.",
                }
            )
    except Exception as exc:  # pragma: no cover - runtime fallback
        logger.warning("Could not attach spawned task to agent lifecycle: %s", exc)

    return result


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
                    "enum": [
                        "ARCHITECT",
                        "RESEARCHER",
                        "CODER",
                        "ANALYZER",
                        "DEBUGGER",
                        "DOCUMENTER",
                        "OPTIMIZER",
                        "REFACTOR_PERFORMANCE",
                        "REFACTOR_CLEAN",
                    ],
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
