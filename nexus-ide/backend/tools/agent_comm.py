"""Inter-agent communication tool with A2A protocol integration.

Allows one agent to consult another agent for specialized input.
For example, CODER can consult ARCHITECT for design advice, or
DEBUGGER can consult CODER for implementation details.

All inter-agent communication is wrapped in A2AMessage for traceability,
validation, and audit purposes.
"""

from __future__ import annotations

import logging
import uuid
import asyncio
from typing import Any

from backend.contracts.a2a import A2AMessage, TaskType, MessagePriority
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

# Valid agent names that can be consulted
_CONSULTABLE_AGENTS = {
    "ARCHITECT", "RESEARCHER", "CODER", "ANALYZER",
    "DEBUGGER", "DOCUMENTER", "OPTIMIZER", "MICRO",
}

# Map agent names to A2A task types
_AGENT_TO_TASK_TYPE = {
    "ARCHITECT": TaskType.PLANNING,
    "RESEARCHER": TaskType.RESEARCH,
    "CODER": TaskType.CODING,
    "ANALYZER": TaskType.ANALYSIS,
    "DEBUGGER": TaskType.DEBUGGING,
    "DOCUMENTER": TaskType.DOCUMENTATION,
    "OPTIMIZER": TaskType.OPTIMIZATION,
    "MICRO": TaskType.GENERAL,
}


async def consult_agent(
    agent: str = "CODER",
    question: str = "",
    source_agent: str = "UNKNOWN",
    session_id: str = "consult-sub",
    priority: str = "medium",
    context: str = "",
    timeout_seconds: int = 60,
    project_path: str = "",
) -> dict[str, Any]:
    """Consult another agent for specialized input via A2A protocol.

    This creates a sub-invocation of the target agent with the given question
    and returns the response as context for the calling agent. The communication
    is wrapped in an A2AMessage for traceability and validation.

    Args:
        agent: Name of the agent to consult (e.g. "ARCHITECT", "RESEARCHER").
        question: The question or task to ask the consulted agent.
        source_agent: Name of the agent making the consultation.
        session_id: Session ID for context tracking.
        priority: Message priority (critical, high, medium, low).

    Returns:
        Dict with the consulted agent's response and A2A metadata.
    """
    agent_upper = agent.upper().strip()
    source_upper = source_agent.upper().strip()

    if agent_upper not in _CONSULTABLE_AGENTS:
        return {
            "error": f"Unknown agent: {agent}. Valid agents: {sorted(_CONSULTABLE_AGENTS)}",
        }

    if not question.strip():
        return {"error": "Question cannot be empty."}

    # Build A2A message for traceability
    try:
        priority_enum = MessagePriority(priority.lower())
    except ValueError:
        priority_enum = MessagePriority.MEDIUM

    task_type = _AGENT_TO_TASK_TYPE.get(agent_upper, TaskType.GENERAL)

    a2a_msg = A2AMessage(
        message_id=uuid.uuid4().hex[:16],
        correlation_id=uuid.uuid4().hex[:16],
        source_agent=source_upper,
        target_agent=agent_upper,
        priority=priority_enum,
        task_type=task_type,
        context_hash=uuid.uuid4().hex[:12],
        payload={"question": question, "session_id": session_id},
        requires_validation=False,
    )

    logger.info(
        "A2A: %s → %s (task=%s, priority=%s, msg_id=%s, timeout=%ds)",
        source_upper, agent_upper, task_type.value, priority_enum.value, a2a_msg.message_id, timeout_seconds,
    )

    try:
        from backend.orchestrator.registry import build_default_registry, resolve
        from backend.agents.base import AgentRequest
        from backend.config.settings import get_settings

        # Reuse the shared LLM client from the FastAPI app state when available,
        # otherwise create one via the factory.
        client = None
        try:
            from backend.orchestrator.main import app
            if hasattr(app.state, "llm_client"):
                client = app.state.llm_client
        except (ImportError, AttributeError) as exc:
            logger.debug("Could not reuse shared LLM client, will create new one: %s", exc)

        if client is None:
            from backend.llm import create_llm_client
            client = create_llm_client()

        # Get the target agent from the registry
        registry = build_default_registry()
        target_agent = resolve(registry, agent_upper)  # type: ignore[arg-type]

        # Build a request for the sub-agent, passing through context
        extra_context: dict[str, Any] = {"a2a_message_id": a2a_msg.message_id}
        if context:
            extra_context["consultation_context"] = context

        sub_request = AgentRequest(
            session_id=session_id,
            query=question,
            client=client,
            project_path=project_path,
            context=extra_context,
        )

        # Run the sub-agent with timeout and collect the response
        parts: list[str] = []

        async def _collect() -> list[str]:
            collected: list[str] = []
            async for token in target_agent.run(sub_request):
                collected.append(token)
            return collected

        try:
            parts = await asyncio.wait_for(_collect(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            logger.warning(
                "A2A consultation timed out | %s → %s | timeout=%ds | msg_id=%s",
                source_upper, agent_upper, timeout_seconds, a2a_msg.message_id,
            )
            return {
                "error": f"Consultation with {agent_upper} timed out after {timeout_seconds}s",
                "agent": agent_upper,
                "a2a_message_id": a2a_msg.message_id,
                "a2a_correlation_id": a2a_msg.correlation_id,
            }

        response_text = "".join(parts)

        # Only close the client if we created it (not the shared one)
        if not hasattr(client, "_shared") and hasattr(client, "aclose"):
            # We created this client — close it
            try:
                await client.aclose()
            except Exception as exc:
                logger.debug("Failed to close temporary LLM client: %s", exc)

        if not response_text.strip():
            return {
                "agent": agent_upper,
                "response": f"[{agent_upper} returned no output]",
                "a2a_message_id": a2a_msg.message_id,
                "a2a_correlation_id": a2a_msg.correlation_id,
            }

        return {
            "agent": agent_upper,
            "response": response_text[:5000],  # Cap response length
            "a2a_message_id": a2a_msg.message_id,
            "a2a_correlation_id": a2a_msg.correlation_id,
            "a2a_task_type": task_type.value,
        }

    except Exception as exc:
        logger.exception("consult_agent failed: %s", exc)
        return {
            "error": f"Failed to consult {agent_upper}: {exc}",
            "a2a_message_id": a2a_msg.message_id,
        }


register_tool(
    ToolSpec(
        name="consult_agent",
        description=(
            "Consult another specialized agent for input via A2A protocol. "
            "Use this when you need expertise from a different perspective. "
            "For example, consult ARCHITECT for design advice, "
            "RESEARCHER for information lookup, or DEBUGGER for error analysis. "
            "All communications are tracked with A2A message IDs for traceability."
        ),
        schema={
            "type": "object",
            "properties": {
                "agent": {
                    "type": "string",
                    "enum": sorted(_CONSULTABLE_AGENTS),
                    "description": "Name of the agent to consult",
                },
                "question": {
                    "type": "string",
                    "description": "The question or task for the consulted agent",
                },
                "source_agent": {
                    "type": "string",
                    "description": "Name of the calling agent (for A2A traceability)",
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID for context tracking",
                },
                "priority": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low"],
                    "description": "Message priority level",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context to pass to the consulted agent",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "default": 60,
                    "description": "Maximum time to wait for the consulted agent response",
                },
            },
            "required": ["agent", "question"],
        },
        handler=consult_agent,
    )
)
