"""Agent Bus tools exposed to agents via the ReAct tool registry.

These wrappers allow any agent to publish messages and subscribe to topics
through the standard ``execute_tool`` mechanism.
"""

from __future__ import annotations

import logging
from typing import Any

from backend.core.agent_bus import BusMessage, get_agent_bus
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


async def publish_bus_message(
    topic: str = "",
    payload: dict[str, Any] | None = None,
    source_agent: str = "UNKNOWN",
    target_agents: list[str] | None = None,
    priority: int = 3,
    ttl_seconds: int = 3600,
) -> dict[str, Any]:
    """Publish a message to the Agent Bus.

    Args:
        topic: Target topic, e.g. ``code.changes``.
        payload: JSON-serialisable dictionary with message content.
        source_agent: Name of the publishing agent.
        target_agents: Specific agents to target; empty = broadcast.
        priority: 1 (lowest) to 5 (highest).
        ttl_seconds: Retention time in persistence (default 3600).

    Returns:
        Dict with ``success`` and ``message_id``.
    """
    import uuid

    bus = get_agent_bus()
    msg = BusMessage(
        message_id=uuid.uuid4().hex[:16],
        topic=topic,
        source_agent=source_agent,
        target_agents=target_agents or [],
        payload=payload or {},
        priority=priority,
        ttl_seconds=ttl_seconds,
    )
    await bus.publish(topic, msg)
    return {
        "success": True,
        "message_id": msg.message_id,
        "topic": msg.topic,
        "source_agent": msg.source_agent,
    }


async def subscribe_bus_topic(
    topic: str = "",
    agent_name: str = "UNKNOWN",
) -> dict[str, Any]:
    """Subscribe an agent to a bus topic (returns a subscription handle).

    Args:
        topic: Topic to listen on.
        agent_name: Name of the subscribing agent (for logging).

    Returns:
        Dict with ``subscription_id`` and ``topic``.
    """
    import uuid

    bus = get_agent_bus()

    async def _default_handler(msg: Any) -> None:
        logger.info(
            "[%s] received bus message on %s from %s",
            agent_name,
            msg.topic,
            msg.source_agent,
        )

    sub = await bus.subscribe(topic, _default_handler)
    return {
        "success": True,
        "subscription_id": sub.subscription_id,
        "topic": sub.topic,
    }


register_tool(
    ToolSpec(
        name="publish_bus_message",
        description=(
            "Publish a message to the Agent Bus pub/sub system. "
            "Use this to notify other agents about code changes, test results, "
            "errors found, architecture proposals, review completions, or status updates. "
            "Messages persist for the specified TTL and can be replayed by late subscribers."
        ),
        schema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Target topic (e.g. code.changes, test.results, errors.found)",
                },
                "payload": {
                    "type": "object",
                    "description": "JSON-serialisable message content",
                },
                "source_agent": {
                    "type": "string",
                    "description": "Name of the publishing agent",
                },
                "target_agents": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Specific agents to target; omit or empty for broadcast",
                },
                "priority": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5,
                    "default": 3,
                    "description": "Message priority 1 (lowest) to 5 (highest)",
                },
                "ttl_seconds": {
                    "type": "integer",
                    "default": 3600,
                    "description": "How long to retain the message in persistence",
                },
            },
            "required": ["topic", "payload"],
        },
        handler=publish_bus_message,
    )
)

register_tool(
    ToolSpec(
        name="subscribe_bus_topic",
        description=(
            "Subscribe to an Agent Bus topic. This registers the agent to receive "
            "messages published on the given topic. For most use-cases agents use "
            "the in-built subscribe() method instead; this tool exists for dynamic "
            "runtime subscriptions."
        ),
        schema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "Topic to subscribe to",
                },
                "agent_name": {
                    "type": "string",
                    "description": "Name of the subscribing agent (for logging)",
                },
            },
            "required": ["topic"],
        },
        handler=subscribe_bus_topic,
    )
)
