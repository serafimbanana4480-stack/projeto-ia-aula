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
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx
from fastapi import APIRouter, Depends, Request
from backend.middleware.auth import require_auth
from fastapi.responses import StreamingResponse
from backend.agents.base import AgentRequest
from backend.config.settings import get_model_config, get_settings, load_models_config
from backend.llm.multi_llm_manager import MultiLLMManager
from backend.middleware.rate_limit import limiter
from backend.models.api import ChatRequest, RoutingDecision, StreamEvent
from backend.orchestrator.fallback import invoke_with_fallback
from backend.orchestrator.registry import get_registry, resolve
from backend.orchestrator.router import fast_route, route_with_model
from backend.orchestrator.smart_router import smart_route_tier
from backend.persistence.db import add_message, create_session, get_session
from backend.tools.ollama_client import ChatMessage
from backend.tools.sanitizer import detect_injection

logger = logging.getLogger(__name__)
router = APIRouter()


def _sse(event: StreamEvent) -> str:
    """Serialise a :class:`StreamEvent` as one SSE frame."""
    return f"data: {event.model_dump_json()}\n\n"


# Inline event tags emitted by the ReAct loop in backend/agents/base.py.
# We convert them into first-class SSE events so the frontend can render
# tool calls cleanly instead of showing raw JSON.
_INLINE_EVENT_RE = re.compile(r"<event>([^|>]+)(?:\|([^>]*)?)</event>")


def _parse_inline_events(token: str, agent: str) -> list[StreamEvent]:
    """Parse <event>...</event> tags produced by agents into structured events.

    Returns a list of StreamEvents. Any non-event text is returned as a token
    event. Multiple inline events in one token are supported.
    """
    events: list[StreamEvent] = []
    last_end = 0
    has_event = False

    for match in _INLINE_EVENT_RE.finditer(token):
        has_event = True
        # Emit any plain text before the tag as a token
        if match.start() > last_end:
            plain = token[last_end:match.start()]
            if plain:
                events.append(StreamEvent(type="token", agent=agent, content=plain))
        last_end = match.end()

        event_type = match.group(1)
        payload = match.group(2) or ""

        if event_type == "tool_call":
            # payload: tool_name|json_args
            if "|" in payload:
                tool_name, raw_args = payload.split("|", 1)
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {"raw": raw_args}
                events.append(
                    StreamEvent(
                        type="tool_call",
                        agent=agent,
                        tool_name=tool_name,
                        tool_args=args if isinstance(args, dict) else {"raw": args},
                    )
                )
        elif event_type == "tool_result":
            # payload: tool_name|json_result
            if "|" in payload:
                tool_name, raw_result = payload.split("|", 1)
                try:
                    result = json.loads(raw_result)
                except json.JSONDecodeError:
                    result = raw_result
                events.append(
                    StreamEvent(
                        type="tool_result",
                        agent=agent,
                        tool_name=tool_name,
                        tool_result=result,
                    )
                )
        elif event_type == "tool_error":
            events.append(
                StreamEvent(
                    type="tool_error",
                    agent=agent,
                    tool_error=payload,
                )
            )
        elif event_type == "warning":
            events.append(StreamEvent(type="token", agent=agent, content=f"⚠ {payload}"))
        # answer / thinking / thinking_end are internal signals; drop them

    if not has_event:
        events.append(StreamEvent(type="token", agent=agent, content=token))
        return events

    # Trailing plain text after the last tag
    if last_end < len(token):
        plain = token[last_end:]
        if plain:
            events.append(StreamEvent(type="token", agent=agent, content=plain))

    return events


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


async def _decide_route(query: str, llm_client) -> RoutingDecision:
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
        tier = await smart_route_tier(query, llm_client)
        agent_name = _MODEL_TIER_TO_AGENT.get(tier, "CODER")
        return RoutingDecision(
            primary_agent=agent_name,  # type: ignore[arg-type]
            routing_confidence=0.8,
            routing_reason=f"smart-tier:{tier}",
        )
    except Exception as exc:
        logger.warning("SmartRouter failed, falling back to model routing: %s", exc)

    # Level 3: LLM-based agent classification
    decision = await route_with_model(query, llm_client)

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
async def chat(req: ChatRequest, request: Request, _user: dict = Depends(require_auth)) -> StreamingResponse:
    """Stream the agent response as Server-Sent Events.

    We deliberately always return ``200 OK`` even on upstream errors: the
    failure is delivered to the client as an ``error`` SSE event so the UI
    can render it gracefully. Returning 4xx/5xx would break the EventSource
    contract on most browsers.
    """
    llm_client = request.app.state.llm_client
    registry = get_registry(request.app)
    context = request.app.state.context
    event_bus = getattr(request.app.state, "event_bus", None)

    async def event_stream() -> AsyncIterator[str]:
        async for chunk in _run_pipeline(
            req, llm_client, registry, context, event_bus, request
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
    req: ChatRequest, llm_client, registry, context, event_bus=None, request: Request | None = None
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

    # Default effective message; auto mode may prepend an autonomy prefix.
    effective_message = req.message

    # Load history early so it's available for plan mode and agent invocation.
    history = await context.get_history(req.session_id)

    # When the user explicitly picks a chat mode (anything other than the
    # default "agent" mode), the mode always wins over the selected model tier.
    # Only honour user_model when no specific mode has been chosen.
    if mode == "agent" and user_model and user_model in _MODEL_TIER_TO_AGENT:
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
                llm_client=llm_client,
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
        # Autonomous mode: delegate to CODER with an autonomous system prefix.
        # The full OrchestrationEngine is powerful but too heavy for the small
        # local models used in this environment and does not stream progress
        # back through the SSE channel, which makes the UI hang/reconnect.
        # Using CODER keeps the stream alive and gives the user full visibility.
        auto_prefix = (
            "[MODO AUTÓNOMO] Atua como engenheiro autónomo. "
            "Analisa o pedido, planeia os passos necessários, executa as ferramentas "
            "(write_file_absolute para caminhos absolutos como C:\\Users\\..., "
            "write_file para caminhos relativos, list_dir, read_file, execute_code), "
            "verifica o resultado e responde com um resumo profissional do que foi feito.\n\n"
        )
        decision = RoutingDecision(
            primary_agent="CODER",
            routing_confidence=1.0,
            routing_reason="explicit-mode:auto",
            thinking_mode="iterative",
            context_needed="high",
            task_type="implementation",
        )
        effective_message = auto_prefix + req.message
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
    elif mode == "fast":
        decision = RoutingDecision(
            primary_agent="MICRO",
            routing_confidence=1.0,
            routing_reason="explicit-mode:fast",
            thinking_mode="fast",
            context_needed="low",
            task_type="question",
        )
    elif mode == "deep":
        decision = RoutingDecision(
            primary_agent="ARCHITECT",
            routing_confidence=1.0,
            routing_reason="explicit-mode:deep",
            thinking_mode="deep",
            context_needed="high",
            task_type="analysis",
        )
    elif mode == "coder":
        decision = RoutingDecision(
            primary_agent="CODER",
            routing_confidence=1.0,
            routing_reason="explicit-mode:coder",
            thinking_mode="iterative",
            context_needed="high",
            task_type="implementation",
        )
    elif mode == "analyst":
        decision = RoutingDecision(
            primary_agent="ANALYZER",
            routing_confidence=1.0,
            routing_reason="explicit-mode:analyst",
            thinking_mode="deep",
            context_needed="high",
            task_type="analysis",
        )
    elif mode == "swarm":
        try:
            from backend.orchestrator.swarm import SwarmOrchestrator

            swarm_agents = getattr(req, "swarm_agents", []) or []
            swarm_strategy = getattr(req, "swarm_strategy", "divide") or "divide"

            if not swarm_agents:
                swarm_agents = ["ARCHITECT", "CODER", "ANALYZER"]

            swarm = SwarmOrchestrator(
                llm_client=llm_client,
                registry=registry,
                event_bus=event_bus,
                max_agents=5,
            )

            yield _sse(StreamEvent(type="agent_started", agent="SWARM"))

            result = await swarm.execute_swarm(
                objective=req.message,
                session_id=req.session_id,
                agents=swarm_agents,
                strategy=swarm_strategy,
                project_path=project_path,
            )

            for ar in result.agent_results:
                yield _sse(StreamEvent(type="agent_started", agent=ar.agent))
                output_text = ar.output if ar.output else ar.error
                for line in output_text.split("\n"):
                    yield _sse(StreamEvent(type="token", agent=ar.agent, content=line + "\n"))
                yield _sse(StreamEvent(type="agent_finished", agent=ar.agent))

            yield _sse(StreamEvent(type="agent_started", agent="SWARM"))
            for line in result.final_answer.split("\n"):
                yield _sse(StreamEvent(type="token", agent="SWARM", content=line + "\n"))
            yield _sse(StreamEvent(type="agent_finished", agent="SWARM"))

            # Persist exchange
            full = result.final_answer
            now = datetime.now(UTC).isoformat()
            await context.append_message(
                req.session_id, ChatMessage(role="user", content=req.message, timestamp=now)
            )
            await context.append_message(
                req.session_id, ChatMessage(role="assistant", content=full, timestamp=now)
            )
            latency_ms = int((time.time() - started_at) * 1000)

            if get_session(req.session_id) is None:
                create_session(
                    title=req.message[:60] or "Nova sessão",
                    mode="swarm",
                    session_id=req.session_id,
                )

            add_message(req.session_id, "user", req.message, tier_used="SWARM", latency_ms=latency_ms)
            add_message(req.session_id, "assistant", full, tier_used="SWARM", latency_ms=latency_ms)

            try:
                from backend.knowledge.memory import MemoryType, get_memory_store

                mem_store = get_memory_store()
                await mem_store.store(
                    content=f"User: {req.message}",
                    memory_type=MemoryType.CONVERSATION,
                    session_id=req.session_id,
                    source="SWARM",
                    tags=["user_query", "swarm"],
                    importance=0.6,
                )
                if full.strip():
                    await mem_store.store(
                        content=f"Assistant (SWARM): {full[:2000]}",
                        memory_type=MemoryType.CONVERSATION,
                        session_id=req.session_id,
                        source="SWARM",
                        tags=["assistant_response", "swarm"],
                        importance=0.5,
                    )
            except Exception as exc:
                logger.debug("Semantic memory store failed (non-critical): %s", exc)

            yield _sse(StreamEvent(type="done"))
            return
        except Exception as exc:
            logger.warning("Swarm execution failed, falling back to CODER: %s", exc)
            yield _sse(
                StreamEvent(
                    type="token",
                    agent="SWARM",
                    content=f"Swarm execution failed: {exc}. Falling back to single-agent mode.\n",
                )
            )
            decision = RoutingDecision(
                primary_agent="CODER",
                routing_confidence=0.7,
                routing_reason="swarm-mode-fallback",
                thinking_mode="deep",
                context_needed="high",
                task_type="implementation",
            )
    else:
        decision = await _decide_route(req.message, llm_client)
    yield _sse(StreamEvent(type="routing", routing=decision))

    # Ensure session exists in relational DB BEFORE invoking the agent.
    # Agents may execute tools that log to tool_executions (FK to sessions).
    if get_session(req.session_id) is None:
        create_session(
            title=req.message[:60] or "Nova sessão",
            mode=req.mode or "auto",
            session_id=req.session_id,
        )

    # Determine effective LLM client (respect provider selection).
    effective_client = llm_client
    if req.provider and isinstance(llm_client, MultiLLMManager):
        effective_client = llm_client.providers.get(req.provider) or llm_client

    # 3. Resolve agent + build per-agent request factory.
    def make_invocation(agent_name: str):
        async def invoke() -> AsyncIterator[str]:
            agent = resolve(registry, agent_name)  # type: ignore[arg-type]
            agent_req = AgentRequest(
                session_id=req.session_id,
                query=effective_message,
                client=effective_client,
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
    except Exception as exc:
        logger.exception("All fallbacks exhausted: %s", exc)
        yield _sse(StreamEvent(type="error", content=f"Upstream unavailable: {exc}"))
        yield _sse(StreamEvent(type="done"))
        return

    yield _sse(StreamEvent(type="agent_started", agent=outcome.used_agent))  # type: ignore[arg-type]

    # 5. Stream tokens and accumulate full response for history.
    parts: list[str] = []
    MAX_RESPONSE_LENGTH = 100_000  # ~100k chars to prevent memory DoS
    try:
        async for token in token_stream:
            # Check if client disconnected to avoid wasting tokens
            if request is not None and await request.is_disconnected():
                logger.debug("Client disconnected, stopping stream")
                break
            # Convert inline <event> tags from the agent into structured SSE
            # events (tool_call / tool_result / tool_error) while keeping plain
            # text as regular tokens.
            parsed_events = _parse_inline_events(token, outcome.used_agent)  # type: ignore[arg-type]
            for evt in parsed_events:
                if evt.type == "token":
                    parts.append(evt.content or "")
                yield _sse(evt)
            # Prevent unbounded memory growth
            if sum(len(p) for p in parts) > MAX_RESPONSE_LENGTH:
                logger.warning("Response exceeded max length, truncating")
                break
    except Exception as exc:
        logger.exception("Stream interrupted: %s", exc)
        yield _sse(StreamEvent(type="error", content=f"Stream interrupted: {exc}"))
        yield _sse(StreamEvent(type="done"))
        return

    # 6. Persist exchange.
    full = "".join(parts)[:MAX_RESPONSE_LENGTH]
    now = datetime.now(UTC).isoformat()
    await context.append_message(
        req.session_id, ChatMessage(role="user", content=req.message, timestamp=now)
    )
    await context.append_message(
        req.session_id, ChatMessage(role="assistant", content=full, timestamp=now)
    )
    latency_ms = int((time.time() - started_at) * 1000)

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

        mem_store = get_memory_store()

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


@router.get("/providers")
async def list_providers(request: Request, _user: dict = Depends(require_auth)) -> dict:
    """Return available LLM providers and their health status."""
    settings = get_settings()
    cfg = load_models_config()
    providers_cfg = cfg.get("providers", {})

    llm_client = request.app.state.llm_client
    health_data: dict[str, dict] = {}

    if isinstance(llm_client, MultiLLMManager):
        health_data = await llm_client.health_check_all()
    else:
        name = settings.llm_provider.lower()
        try:
            client = getattr(llm_client, "_client", None)
            if isinstance(client, httpx.AsyncClient):
                resp = await client.get("/models", timeout=5.0)
                health = {
                    "status": "healthy" if resp.status_code == 200 else "unhealthy",
                    "latency": 0,
                }
            elif hasattr(client, "_client") and isinstance(
                client._client, httpx.AsyncClient
            ):
                base_url = str(client._client.base_url).rstrip("/")
                async with httpx.AsyncClient(timeout=5.0) as temp:
                    resp = await temp.get(f"{base_url}/api/tags")
                    health = {
                        "status": "healthy" if resp.status_code == 200 else "unhealthy",
                        "latency": 0,
                    }
            else:
                health = {"status": "unknown"}
        except Exception as exc:
            health = {"status": "unhealthy", "error": str(exc)}
        health_data = {name: health}

    result: list[dict] = []
    active_provider = settings.llm_provider.lower()
    for key, pcfg in providers_cfg.items():
        requires_key = pcfg.get("requires_api_key", False)
        api_key_set = False
        if requires_key:
            key_attr = f"{key}_api_key"
            api_key_set = bool(getattr(settings, key_attr, ""))

        result.append(
            {
                "id": key,
                "name": pcfg.get("name", key),
                "base_url": pcfg.get("base_url", ""),
                "default_models": pcfg.get("default_models", []),
                "requires_api_key": requires_key,
                "api_key_set": api_key_set,
                "active": key == active_provider,
                "health": health_data.get(key, {"status": "unknown"}),
            }
        )

    return {
        "providers": result,
        "active_provider": active_provider,
    }


# Small helper so JSON marshaling can be tested without spinning up FastAPI.
def decision_to_json(d: RoutingDecision) -> str:  # pragma: no cover - trivial
    return json.dumps(d.model_dump(), separators=(",", ":"))
