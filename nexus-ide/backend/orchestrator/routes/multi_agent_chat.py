
"""Multi-Agent Chat endpoint.

Provides POST /api/chat/multi for orchestrated conversations between
multiple AI agents. Each agent responds in sequence, building upon
previous responses, creating a true collaborative AI discussion.

Events streamed:
- routing: which agents will participate
- agent_started: agent begins thinking
- agent_message: agent's response to the conversation
- agent_finished: agent completed
- done: conversation complete
"""

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from backend.models.api import StreamEvent

logger = logging.getLogger(__name__)
router = APIRouter()


class MultiAgentChatRequest(BaseModel):
    """Request for multi-agent collaborative chat."""
    message: str
    session_id: str = "multi-agent-session"
    max_turns: int = 6
    agents: list[str] | None = None  # Optional: specific agents to involve


def _sse(event: StreamEvent) -> str:
    """Serialise a StreamEvent as one SSE frame."""
    return f"data: {event.model_dump_json()}\n\n"


# Default agent sequences by task type.  In production these can be loaded from config.
CONVERSATION_SEQUENCES = {
    "architecture": ["ROUTER", "ARCHITECT", "RESEARCHER", "ARCHITECT", "CODER", "OPTIMIZER"],
    "debugging": ["ROUTER", "DEBUGGER", "ANALYZER", "DEBUGGER", "CODER", "DOCUMENTER"],
    "feature": ["ROUTER", "ARCHITECT", "RESEARCHER", "CODER", "ANALYZER", "DOCUMENTER"],
    "optimization": ["ROUTER", "ANALYZER", "OPTIMIZER", "CODER", "ANALYZER", "DOCUMENTER"],
    "default": ["ROUTER", "RESEARCHER", "ARCHITECT", "CODER", "DEBUGGER", "DOCUMENTER"],
}


def _detect_task_type(message: str) -> str:
    """Detect conversation type from user message."""
    content = message.lower()
    keywords = {
        "architecture": ["architecture", "design", "structure", "system", "arquitetura", "estrutura"],
        "debugging": ["bug", "error", "fix", "debug", "erro", "corrigir", "debugar"],
        "optimization": ["optimize", "speed", "fast", "performance", "otimizar", "lento"],
        "feature": ["feature", "implement", "add", "nova", "funcionalidade"],
    }
    for task_type, words in keywords.items():
        if any(word in content for word in words):
            return task_type
    return "default"


async def _generate_agent_response(agent: str, context: str, ollama) -> str:
    """Generate a contextual response from an agent using the real Ollama backend."""
    try:
        messages = [
            {"role": "system", "content": f"You are the {agent} agent in a multi-agent AI system. Respond concisely in Portuguese or English."},
            {"role": "user", "content": context},
        ]
        response = await ollama.chat_complete("qwen2.5:7b", messages)
        return response.strip()
    except Exception as e:
        logger.error(f"Ollama failed for {agent}: {e}")
        raise RuntimeError(f"Agent {agent} could not generate a response: upstream LLM unavailable") from e


@router.post("/chat/multi")
async def multi_agent_chat(req: MultiAgentChatRequest, request: Request) -> StreamingResponse:
    """Stream a collaborative multi-agent conversation.

    Agents discuss the user's request in sequence, building upon each
    other's insights to produce a comprehensive solution.
    """
    ollama = request.app.state.ollama
    event_bus = request.app.state.event_bus

    async def event_stream() -> AsyncIterator[str]:
        # 1. Determine task type and agent sequence
        task_type = _detect_task_type(req.message)
        agent_sequence = req.agents or CONVERSATION_SEQUENCES.get(task_type, CONVERSATION_SEQUENCES["default"])
        agent_sequence = agent_sequence[:req.max_turns]

        yield _sse(StreamEvent(
            type="routing",
            routing={
                "primary_agent": agent_sequence[0] if agent_sequence else "ROUTER",
                "secondary_agents": agent_sequence[1:] if len(agent_sequence) > 1 else [],
                "routing_confidence": 0.95,
                "routing_reason": f"multi-agent:{task_type}",
                "thinking_mode": "deep",
                "context_needed": "high",
                "task_type": task_type,
            },
        ))

        # 2. Build conversation context
        conversation_context = f"User request: {req.message}\n\n"
        agent_responses: list[tuple[str, str]] = []

        # 3. Each agent responds in sequence
        for idx, agent_name in enumerate(agent_sequence):
            yield _sse(StreamEvent(type="agent_started", agent=agent_name))

            # Build prompt with previous context
            if agent_responses:
                conversation_context += "Previous discussion:\n"
                for prev_agent, prev_response in agent_responses:
                    conversation_context += f"{prev_agent}: {prev_response}\n"
                conversation_context += f"\nNow {agent_name}, based on the above, provide your expert input:\n"
            else:
                conversation_context += f"{agent_name}, analyze this request and provide your expert input:\n"

            # Generate response
            response_text = await _generate_agent_response(agent_name, conversation_context, ollama)
            agent_responses.append((agent_name, response_text))

            # Stream tokens
            for token in response_text:
                yield _sse(StreamEvent(
                    type="token",
                    agent=agent_name,
                    content=token,
                ))

            yield _sse(StreamEvent(
                type="agent_message",
                agent=agent_name,
                content=response_text,
            ))

            yield _sse(StreamEvent(type="agent_finished", agent=agent_name))

            # Publish to event bus for other consumers (dashboard, etc.)
            if event_bus:
                from backend.observability.events import Event
                await event_bus.publish(Event(
                    type="agent.conversation",
                    agent=agent_name,
                    payload={
                        "message": response_text,
                        "session_id": req.session_id,
                        "turn": idx + 1,
                        "total_turns": len(agent_sequence),
                        "task_type": task_type,
                    },
                ))

            # Small delay between agents for natural flow
            await __import__('asyncio').sleep(0.3)

        # 4. Final synthesis
        yield _sse(StreamEvent(
            type="synthesis",
            content=f"Conversa multi-agente completada. {len(agent_sequence)} agentes colaboraram na análise do pedido.",
        ))

        yield _sse(StreamEvent(type="done"))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/chat/multi/stream")
async def multi_agent_chat_stream(request: Request) -> StreamingResponse:
    """SSE stream of all multi-agent conversations happening in real-time.

    Connects to the EventBus and streams agent conversation events
    as they happen across the system.
    """
    event_bus = request.app.state.event_bus

    async def event_generator() -> AsyncIterator[str]:
        # Send initial connection event
        yield f"data: {json.dumps({'type': 'connected', 'message': 'Listening to multi-agent conversations'})}\n\n"

        if event_bus and hasattr(event_bus, 'subscribe'):
            async for event in event_bus.subscribe("agent.conversation"):
                sse_data = {
                    "type": "agent_message",
                    "agent": event.agent,
                    "content": event.payload.get("message", ""),
                    "session_id": event.payload.get("session_id", ""),
                    "turn": event.payload.get("turn", 0),
                    "total_turns": event.payload.get("total_turns", 0),
                    "task_type": event.payload.get("task_type", "unknown"),
                    "timestamp": event.timestamp.isoformat() if hasattr(event, 'timestamp') else datetime.now(UTC).isoformat(),
                }
                yield f"data: {json.dumps(sse_data)}\n\n"
        else:
            # Event bus not available — return error and close stream
            yield f"data: {json.dumps({'type': 'error', 'content': 'Event bus not initialized'})}\n\n"
            return

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
