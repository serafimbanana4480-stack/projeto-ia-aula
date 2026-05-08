"""POST /api/chat — the Tier-1 end-to-end vertical.

Pipeline:

1. Sanitize input (prompt-injection defence, P0 rule).
2. Classify with :func:`fast_route`; fall back to :func:`route_with_model`.
3. Resolve the agent via the registry.
4. Stream tokens through the fallback chain.
5. Persist the exchange in the :class:`ContextStore` for future turns.

Every chunk sent to the client is a Pydantic :class:`StreamEvent` serialised
as a single SSE ``data:`` line terminated by two newlines. The client reads
until a ``{"type": "done"}`` event.
"""
from __future__ import annotations

import json
import logging
from typing import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from backend.agents.base import AgentRequest
from backend.models.api import ChatRequest, RoutingDecision, StreamEvent
from backend.orchestrator.fallback import invoke_with_fallback
from backend.orchestrator.registry import resolve
from backend.orchestrator.router import fast_route, route_with_model
from backend.tools.ollama_client import ChatMessage, OllamaError
from backend.tools.sanitizer import detect_injection

logger = logging.getLogger(__name__)
router = APIRouter()


def _sse(event: StreamEvent) -> str:
    """Serialise a :class:`StreamEvent` as one SSE frame."""
    return f"data: {event.model_dump_json()}\n\n"


@router.post("/chat")
async def chat(req: ChatRequest, request: Request) -> StreamingResponse:
    """Stream the agent response as Server-Sent Events.

    We deliberately always return ``200 OK`` even on upstream errors: the
    failure is delivered to the client as an ``error`` SSE event so the UI
    can render it gracefully. Returning 4xx/5xx would break the EventSource
    contract on most browsers.
    """
    ollama = request.app.state.ollama
    registry = request.app.state.registry
    context = request.app.state.context

    async def event_stream() -> AsyncIterator[str]:
        async for chunk in _run_pipeline(req, ollama, registry, context):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",  # nginx: disable response buffering
            "Connection": "keep-alive",
        },
    )


async def _run_pipeline(req, ollama, registry, context) -> AsyncIterator[str]:
    """The core chat pipeline, extracted for testability (keeps the route tiny)."""
    # 1. Sanitize.
    injection = detect_injection(req.message)
    if injection.detected:
        logger.info("Blocked potential prompt injection: %s", injection.pattern)
        yield _sse(StreamEvent(
            type="error",
            content=f"Request blocked: potential prompt injection ({injection.pattern}).",
        ))
        yield _sse(StreamEvent(type="done"))
        return

    # 2. Route.
    mode = (getattr(req, "mode", "agent") or "agent").lower()
    if mode == "plan":
        decision = RoutingDecision(
            primary_agent="ARCHITECT",
            routing_confidence=1.0,
            routing_reason="explicit-mode:plan",
            thinking_mode="deep",
            context_needed="high",
            task_type="planning",
        )
    elif mode == "debug":
        decision = RoutingDecision(
            primary_agent="DEBUGGER",
            routing_confidence=1.0,
            routing_reason="explicit-mode:debug",
            thinking_mode="iterative",
            context_needed="high",
            task_type="debugging",
        )
    elif mode == "ask":
        decision = RoutingDecision(
            primary_agent="MICRO",
            routing_confidence=1.0,
            routing_reason="explicit-mode:ask",
            thinking_mode="fast",
            context_needed="low",
            task_type="question",
        )
    else:
        decision = await _decide_route(req.message, ollama)
    yield _sse(StreamEvent(type="routing", routing=decision))

    # 3. Resolve agent + build per-agent request factory.
    history = await context.get_history(req.session_id)

    def make_invocation(agent_name: str):
        async def invoke() -> AsyncIterator[str]:
            agent = resolve(registry, agent_name)  # type: ignore[arg-type]
            agent_req = AgentRequest(
                session_id=req.session_id,
                query=req.message,
                client=ollama,
                history=history,
            )
            return agent.run(agent_req)
        return invoke

    # 4. Invoke with fallback.
    try:
        outcome, token_stream = await invoke_with_fallback(
            decision.primary_agent,
            lambda name: make_invocation(name)(),
        )
    except OllamaError as exc:
        logger.exception("All fallbacks exhausted: %s", exc)
        yield _sse(StreamEvent(type="error", content=f"Upstream unavailable: {exc}"))
        yield _sse(StreamEvent(type="done"))
        return

    yield _sse(StreamEvent(type="agent_started", agent=outcome.used_agent))  # type: ignore[arg-type]

    # 5. Stream tokens and accumulate full response for history.
    parts: list[str] = []
    try:
        async for token in token_stream:
            parts.append(token)
            yield _sse(StreamEvent(
                type="token",
                agent=outcome.used_agent,  # type: ignore[arg-type]
                content=token,
            ))
    except OllamaError as exc:
        logger.exception("Stream interrupted: %s", exc)
        yield _sse(StreamEvent(type="error", content=f"Stream interrupted: {exc}"))
        yield _sse(StreamEvent(type="done"))
        return

    # 6. Persist exchange.
    full = "".join(parts)
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    await context.append_message(req.session_id, ChatMessage(role="user", content=req.message, timestamp=now))
    await context.append_message(req.session_id, ChatMessage(role="assistant", content=full, timestamp=now))

    yield _sse(StreamEvent(type="agent_finished", agent=outcome.used_agent))  # type: ignore[arg-type]
    yield _sse(StreamEvent(type="done"))


async def _decide_route(query: str, ollama) -> RoutingDecision:
    """Combine fast_route + route_with_model. Never raises."""
    fast = fast_route(query)
    if fast is not None:
        return RoutingDecision(
            primary_agent=fast,
            routing_confidence=0.9,
            routing_reason=f"fast-rule:{fast.lower()}",
        )
    return await route_with_model(query, ollama)


# Small helper so JSON marshaling can be tested without spinning up FastAPI.
def decision_to_json(d: RoutingDecision) -> str:  # pragma: no cover - trivial
    return json.dumps(d.model_dump(), separators=(",", ":"))
