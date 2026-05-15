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

import json
import logging
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from slowapi import Limiter
from slowapi.util import get_remote_address

from backend.agents.base import AgentRequest
from backend.config.settings import get_model_config
from backend.models.api import ChatRequest, RoutingDecision, StreamEvent
from backend.orchestrator.fallback import invoke_with_fallback
from backend.orchestrator.registry import resolve
from backend.orchestrator.router import fast_route, route_with_model
from backend.orchestrator.smart_router import smart_route_tier
from backend.persistence.db import add_message, create_session, get_session
from backend.tools.ollama_client import ChatMessage, OllamaError
from backend.tools.sanitizer import detect_injection

logger = logging.getLogger(__name__)
router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


def _sse(event: StreamEvent) -> str:
    """Serialise a :class:`StreamEvent` as one SSE frame."""
    return f"data: {event.model_dump_json()}\n\n"


# Map model tier keys (from frontend) to the agent that should handle them.
# When the user explicitly selects a model, we route to the corresponding agent.
_MODEL_TIER_TO_AGENT: dict[str, str] = {
    "micro": "MICRO",
    "fast": "DOCUMENTER",
    "coder": "CODER",
    "reasoning": "ARCHITECT",
    "deep": "ARCHITECT",
    # Legacy aliases (kept for backward compatibility)
    "small": "DOCUMENTER",
    "medium": "CODER",
    "large": "ANALYZER",
    "expert": "ARCHITECT",
    "nano": "MICRO",
    "dashboard": "MICRO",
}


async def _decide_route(query: str, ollama) -> RoutingDecision:
    """Combine fast_route + smart_route_tier + route_with_model. Never raises.

    Routing strategy:
    1. fast_route: deterministic keyword match → direct agent
    2. smart_route_tier: heuristic tier selection → map tier to agent
    3. route_with_model: LLM-based agent classification (fallback)
    """
    # Level 1: Fast deterministic rules
    fast = fast_route(query)
    if fast is not None:
        return RoutingDecision(
            primary_agent=fast,
            routing_confidence=0.9,
            routing_reason=f"fast-rule:{fast.lower()}",
        )

    # Level 2: Smart tier selection (heuristic + optional LLM fallback)
    try:
        tier = await smart_route_tier(query, ollama)
        agent_name = _MODEL_TIER_TO_AGENT.get(tier, "CODER")
        return RoutingDecision(
            primary_agent=agent_name,  # type: ignore[arg-type]
            routing_confidence=0.8,
            routing_reason=f"smart-tier:{tier}",
        )
    except Exception as exc:
        logger.warning("SmartRouter failed, falling back to model routing: %s", exc)

    # Level 3: LLM-based agent classification
    decision = await route_with_model(query, ollama)

    # If the model indicates web search is needed, ensure RESEARCHER is involved
    if decision.requires_web_search and decision.primary_agent != "RESEARCHER":
        decision = decision.model_copy(
            update={
                "secondary_agents": list(set(decision.secondary_agents + ["RESEARCHER"])),
                "requires_web_search": True,
            }
        )

    return decision


@router.post("/chat")
@limiter.limit("60/minute")
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
    event_bus = getattr(request.app.state, "event_bus", None)

    async def event_stream() -> AsyncIterator[str]:
        async for chunk in _run_pipeline(
            req, ollama, registry, context, event_bus
        ):
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


async def _run_pipeline(
    req: ChatRequest, ollama, registry, context, event_bus=None
) -> AsyncIterator[str]:
    """The core chat pipeline, extracted for testability (keeps the route tiny)."""
    started_at = time.time()

    # 1. Sanitize.
    injection = detect_injection(req.message)
    if injection.detected:
        logger.info("Blocked potential prompt injection: %s", injection.pattern)
        yield _sse(
            StreamEvent(
                type="error",
                content=f"Request blocked: potential prompt injection ({injection.pattern}).",
            )
        )
        yield _sse(StreamEvent(type="done"))
        return

    # 2. Route — if user explicitly selected a model, honour it.
    mode = (getattr(req, "mode", "agent") or "agent").lower()
    user_model = getattr(req, "model", "") or ""
    project_path = getattr(req, "project_path", "") or ""

    # Load history early so it's available for plan mode and agent invocation.
    history = await context.get_history(req.session_id)

    if user_model and user_model in _MODEL_TIER_TO_AGENT:
        # User explicitly chose a model tier — route directly to the matching agent.
        agent_name = _MODEL_TIER_TO_AGENT[user_model]
        decision = RoutingDecision(
            primary_agent=agent_name,  # type: ignore[arg-type]
            routing_confidence=1.0,
            routing_reason=f"user-selected-model:{user_model}",
            thinking_mode="deep" if user_model in ("reasoning", "deep", "expert") else "fast",
            context_needed="high" if user_model in ("reasoning", "deep", "expert", "large") else "low",
            task_type="user-override",
        )
    elif mode == "plan":
        # Plan mode: use orchestration engine for structured planning
        try:
            from backend.orchestrator.engine import OrchestrationEngine
            engine = OrchestrationEngine(
                ollama=ollama,
                registry=registry,
                event_bus=event_bus,
            )
            plan = await engine.create_plan(
                objective=req.message,
                session_id=req.session_id,
                history=history,
            )
            # Stream the plan as structured output
            yield _sse(StreamEvent(type="agent_started", agent="ARCHITECT"))
            plan_text = f"# Execution Plan\n\n"
            plan_text += f"**Objective:** {plan.title or req.message}\n\n"
            for i, step in enumerate(plan.steps, 1):
                plan_text += f"## Step {i}: {step.name}\n"
                plan_text += f"- **Agent:** {step.agent}\n"
                plan_text += f"- **Description:** {step.description}\n"
                if step.depends_on:
                    plan_text += f"- **Depends on:** {', '.join(step.depends_on)}\n"
                plan_text += "\n"
            # Stream plan text by lines for efficient SSE delivery
            for line in plan_text.split("\n"):
                yield _sse(StreamEvent(type="token", agent="ARCHITECT", content=line + "\n"))
            yield _sse(StreamEvent(type="agent_finished", agent="ARCHITECT"))
            yield _sse(StreamEvent(type="done"))
            return
        except Exception as exc:
            logger.warning("Plan engine failed, falling back to ARCHITECT: %s", exc)
            # Fall through to normal routing
            decision = RoutingDecision(
                primary_agent="ARCHITECT",
                routing_confidence=1.0,
                routing_reason="explicit-mode:plan-fallback",
                thinking_mode="deep",
                context_needed="high",
                task_type="planning",
            )
    elif mode == "auto":
        # Autonomous mode: Plan → Execute → Verify → Iterate (full autonomy)
        try:
            from backend.orchestrator.engine import OrchestrationEngine
            engine = OrchestrationEngine(
                ollama=ollama,
                registry=registry,
                event_bus=event_bus,
            )

            yield _sse(StreamEvent(type="agent_started", agent="ORCHESTRATOR"))
            yield _sse(StreamEvent(
                type="token", agent="ORCHESTRATOR",
                content="Starting autonomous execution...\n\n",
            ))

            # Run autonomous execution
            result = await engine.execute_autonomous(
                objective=req.message,
                session_id=req.session_id,
                history=history,
                project_path=project_path,
            )

            # Stream the result summary
            summary = f"\n## Autonomous Execution Complete\n\n"
            summary += f"**State:** {result.state.value}\n"
            summary += f"**Completed tasks:** {result.completed_tasks}\n"
            summary += f"**Failed tasks:** {result.failed_tasks}\n"
            summary += f"**Duration:** {result.total_duration_ms}ms\n"

            if result.errors:
                summary += f"\n**Errors:**\n"
                for err in result.errors[:5]:
                    summary += f"- {err}\n"

            for line in summary.split("\n"):
                yield _sse(StreamEvent(type="token", agent="ORCHESTRATOR", content=line + "\n"))

            yield _sse(StreamEvent(type="agent_finished", agent="ORCHESTRATOR"))
            yield _sse(StreamEvent(type="done"))
            return
        except Exception as exc:
            logger.warning("Autonomous execution failed, falling back to CODER: %s", exc)
            yield _sse(StreamEvent(
                type="token", agent="ORCHESTRATOR",
                content=f"Autonomous execution failed: {exc}. Falling back to single-agent mode.\n",
            ))
            # Fall through to normal routing
            decision = RoutingDecision(
                primary_agent="CODER",
                routing_confidence=0.7,
                routing_reason="auto-mode-fallback",
                thinking_mode="deep",
                context_needed="high",
                task_type="implementation",
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
    def make_invocation(agent_name: str):
        async def invoke() -> AsyncIterator[str]:
            agent = resolve(registry, agent_name)  # type: ignore[arg-type]
            agent_req = AgentRequest(
                session_id=req.session_id,
                query=req.message,
                client=ollama,
                history=history,
                project_path=project_path,
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
            yield _sse(
                StreamEvent(
                    type="token",
                    agent=outcome.used_agent,  # type: ignore[arg-type]
                    content=token,
                )
            )
    except OllamaError as exc:
        logger.exception("Stream interrupted: %s", exc)
        yield _sse(StreamEvent(type="error", content=f"Stream interrupted: {exc}"))
        yield _sse(StreamEvent(type="done"))
        return

    # 6. Persist exchange.
    full = "".join(parts)
    now = datetime.now(UTC).isoformat()
    await context.append_message(
        req.session_id, ChatMessage(role="user", content=req.message, timestamp=now)
    )
    await context.append_message(
        req.session_id, ChatMessage(role="assistant", content=full, timestamp=now)
    )
    latency_ms = int((time.time() - started_at) * 1000)

    # Ensure session exists in relational DB before writing messages (FK guard).
    if get_session(req.session_id) is None:
        create_session(
            title=req.message[:60] or "Nova sessão",
            mode=req.mode or "auto",
            session_id=req.session_id,
        )

    add_message(
        req.session_id,
        "user",
        req.message,
        tier_used=decision.primary_agent,
        latency_ms=latency_ms,
    )
    add_message(
        req.session_id,
        "assistant",
        full,
        tier_used=decision.primary_agent,
        latency_ms=latency_ms,
    )

    # 7. Store in semantic memory for future recall (best-effort, non-blocking).
    try:
        from backend.knowledge.memory import MemoryType, get_memory_store

        mem_store = get_memory_store(ollama_host=str(ollama._host) if hasattr(ollama, "_host") else "")

        # Store the user query
        await mem_store.store(
            content=f"User: {req.message}",
            memory_type=MemoryType.CONVERSATION,
            session_id=req.session_id,
            source=decision.primary_agent,
            tags=["user_query", decision.primary_agent],
            importance=0.6,
        )

        # Store the assistant response (truncated for efficiency)
        if full.strip():
            await mem_store.store(
                content=f"Assistant ({outcome.used_agent}): {full[:2000]}",
                memory_type=MemoryType.CONVERSATION,
                session_id=req.session_id,
                source=outcome.used_agent,
                tags=["assistant_response", outcome.used_agent],
                importance=0.5,
            )
    except Exception as exc:
        logger.debug("Semantic memory store failed (non-critical): %s", exc)

    yield _sse(StreamEvent(type="agent_finished", agent=outcome.used_agent))  # type: ignore[arg-type]
    yield _sse(StreamEvent(type="done"))


# Small helper so JSON marshaling can be tested without spinning up FastAPI.
def decision_to_json(d: RoutingDecision) -> str:  # pragma: no cover - trivial
    return json.dumps(d.model_dump(), separators=(",", ":"))
