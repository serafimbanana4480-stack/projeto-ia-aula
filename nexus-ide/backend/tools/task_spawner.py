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
    definition_of_done: str = "",
    context: str = "",
    parent_id: str | None = None,
    depends_on: list[str] | None = None,
    session_id: str = "",
    project_path: str = "",
    autonomous: bool = True,
    sentinel_enforced: bool = False,
    allowed_tools: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Spawn a new task dynamically in the active orchestration run.

    Args:
        name: Short, descriptive name for the task.
        description: Detailed instructions for the task.
        agent: Agent type to execute the task (CODER, ANALYZER, etc).
        priority: Task priority (low, medium, high, critical).
        definition_of_done: Checkable condition that says the task is finished.
            Required by the spawn policy: without it the delegation is denied
            and the primary agent keeps the work.
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

    # The spawn policy decides whether delegating is actually better than
    # doing the work inline. Consulting it here is what keeps the tool result
    # honest: before this, the policy could decline the delegation while this
    # tool still told the model "status: spawned" for a subagent that never
    # started (audit 2026-08-16, P10). The model cannot be honest with the
    # user if its own tools lie to it.
    decision_reason = ""
    try:
        from backend.runtime.spawn_policy import (
            SpawnPolicy,
            SpawnVerdict,
            SubagentProposal,
        )
        from backend.runtime.spawn_registry import get_policy

        policy = get_policy(session_id) or SpawnPolicy()
        proposal = SubagentProposal(
            name=name,
            objective=description or "",
            definition_of_done=str(definition_of_done or context or ""),
            estimated_seconds=float(
                os.environ.get("NEXUS_SPAWN_ESTIMATED_SECONDS", "120") or 120
            ),
            requires_deep_exploration=True,
        )
        decision = policy.evaluate(proposal)
        decision_reason = decision.reason
        if decision.verdict is not SpawnVerdict.SPAWN:
            logger.info(
                "spawn_task declined by policy | task=%s | verdict=%s | reason=%s",
                name,
                decision.verdict.value,
                decision.reason,
            )
            return {
                "status": "denied" if decision.verdict is SpawnVerdict.PRIMARY_AGENT_ONLY else "queued",
                "spawned": False,
                "background": False,
                "task_name": name,
                "agent": agent,
                "priority": priority,
                "description": description,
                "context": context,
                "parent_id": parent_id,
                "depends_on": depends_on or [],
                "verdict": decision.verdict.value,
                "reason": decision.reason,
                "failed_conditions": list(decision.failed_conditions),
                "message": (
                    "A delegação NÃO foi criada: "
                    f"{decision.reason}. Trata isto tu próprio agora e não "
                    "digas ao utilizador que um sub-agente ficou a trabalhar."
                ),
            }
    except ImportError:  # pragma: no cover - runtime without the phase-3 policy
        logger.debug("Spawn policy unavailable; falling back to lifecycle check")

    result: dict[str, Any] = {
        "task_name": name,
        "agent": agent,
        "priority": priority,
        "description": description,
        "context": context,
        "parent_id": parent_id,
        "depends_on": depends_on or [],
    }
    if decision_reason:
        result["reason"] = decision_reason

    # In normal chat there is no active OrchestrationEngine to intercept the
    # old declarative result. Attach it to the real lifecycle manager so the
    # principal can answer immediately while the specialist continues in the
    # background and remains visible in Agent Instances.
    instance_id: str | None = None
    attach_error = ""
    try:
        from backend.orchestrator.main import app

        lifecycle = getattr(app.state, "agent_lifecycle", None)
        if lifecycle is None:
            attach_error = "não há gestor de ciclo de vida de agentes ativo"
        else:
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
                    "_sentinel_enforced": sentinel_enforced,
                    **(
                        {"_allowed_tools": tuple(allowed_tools)}
                        if allowed_tools is not None
                        else {}
                    ),
                },
                mission_id=session_id,
                parent_task_id=parent_id or "",
                token_budget=background_tokens,
                time_budget_seconds=background_budget,
            )
    except Exception as exc:  # pragma: no cover - runtime fallback
        attach_error = str(exc)
        logger.warning("Could not attach spawned task to agent lifecycle: %s", exc)

    if not instance_id:
        # No instance means no subagent. Saying "spawned" here is exactly the
        # lie the audit caught; report the truth so the model does the work.
        result.update(
            {
                "status": "not_started",
                "spawned": False,
                "background": False,
                "error": (
                    "O sub-agente NÃO arrancou"
                    + (f": {attach_error}" if attach_error else ".")
                    + " Executa a tarefa tu próprio e não afirmes que há "
                    "trabalho a decorrer em background."
                ),
            }
        )
        return result

    result.update(
        {
            "status": "spawned",
            "spawned": True,
            "background": True,
            "instance_id": instance_id,
            "message": f"{agent} continua em background; a conversa principal permanece livre.",
        }
    )

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
                "definition_of_done": {
                    "type": "string",
                    "description": (
                        "Checkable condition that proves the delegated task is "
                        "finished (e.g. 'os testes de scoring passam'). Required: "
                        "without it the spawn policy denies the delegation."
                    ),
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
            "required": ["name", "description", "definition_of_done"],
        },
        handler=spawn_task,
    )
)
