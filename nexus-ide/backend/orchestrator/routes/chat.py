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

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.agents.base import AgentRequest
from backend.config.settings import get_mode_config, get_settings, load_models_config, resolve_project_path
from backend.llm.multi_llm_manager import MultiLLMManager
from backend.middleware.auth import require_auth
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
_INLINE_EVENT_RE = re.compile(r"<event>([^|>]+)(?:\|(.*?))?</event>", re.DOTALL)


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
            plain = token[last_end : match.start()]
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


# ---------------------------------------------------------------------------
# Complexity heuristic — decides if a task needs multi-phase orchestration
# ---------------------------------------------------------------------------

_COMPLEX_TASK_KEYWORDS: tuple[str, ...] = (
    # English
    "create a project",
    "build a",
    "build an",
    "full application",
    "full app",
    "complete system",
    "entire project",
    "from scratch",
    "scaffol",
    "implement all",
    "multi-step",
    "multiple files",
    "several files",
    "authentication system",
    "auth system",
    "jwt",
    "database schema",
    "rest api",
    "graphql api",
    "microservice",
    "backend",
    "react app",
    "next.js",
    "fastapi",
    "django",
    "flask",
    "step by step",
    "phase by phase",
    "all the",
    "everything",
    # Portuguese
    "criar projeto",
    "criar um projeto",
    "criar aplicação",
    "criar uma aplicação",
    "criar sistema",
    "criar um sistema",
    "criar api",
    "criar uma api",
    "sistema completo",
    "aplicação completa",
    "do zero",
    "de raiz",
    "implementar tudo",
    "todos os ficheiros",
    "vários ficheiros",
    "autenticação",
    "base de dados",
    "esquema de base",
    "passo a passo",
    "fase por fase",
)

_COMPLEX_TASK_MIN_WORDS = 8  # Short queries are always simple


def _is_complex_task(query: str) -> bool:
    """Heuristic: true if the task likely needs multi-phase orchestrated execution.

    Keeps simple Q&A and one-file edits on the fast ReAct path while routing
    larger feature requests through the full Plan → Execute → Verify pipeline.
    """
    words = query.split()
    if len(words) < _COMPLEX_TASK_MIN_WORDS:
        return False
    lowered = query.lower()
    return any(kw in lowered for kw in _COMPLEX_TASK_KEYWORDS)


async def _stream_autonomous_execution(
    objective: str,
    session_id: str,
    llm_client,
    registry: dict,
    event_bus,
    project_path: str,
    history,
    context,
) -> AsyncIterator[str]:
    """Run execute_autonomous() and convert Engine EventBus events to SSE tokens.

    Bridges the OrchestrationEngine EventBus into the SSE stream so the
    frontend sees planning, task progress, and verification events live.
    The engine still runs synchronously; we concurrently read its event bus
    and yield SSE frames as events arrive. Falls back to a summary-only
    stream if the engine itself fails.
    """
    from backend.orchestrator.engine import OrchestrationEngine
    from backend.orchestrator.events import EventType

    engine = OrchestrationEngine(
        llm_client=llm_client,
        registry=registry,
        event_bus=event_bus,
        max_parallel=3,
        default_timeout=240,
    )

    yield _sse(StreamEvent(type="agent_started", agent="ARCHITECT"))
    yield _sse(
        StreamEvent(
            type="token",
            agent="ARCHITECT",
            content="🔭 Analisando a tarefa e criando plano de execução multi-fase...\n\n",
        )
    )

    EVENT_BRIDGE_DONE = "__done__"

    async def _consume_events() -> AsyncIterator[str]:
        """Subscribe to event_bus and yield SSE frames until engine is done."""
        if event_bus is None:
            return
        try:
            async for evt in event_bus.stream_events(event_types=["*"], session_id=session_id):
                et_value = (
                    evt.event_type.value
                    if hasattr(evt.event_type, "value")
                    else str(evt.event_type)
                )
                agent = evt.source or "ORCHESTRATOR"
                content = evt.content or ""
                data: dict[str, Any] = evt.data or {}

                try:
                    et = EventType(et_value)
                except ValueError:
                    et = None

                if et == EventType.TOKEN and content:
                    yield _sse(StreamEvent(type="token", agent=agent, content=content))
                elif et == EventType.THINKING and content:
                    yield _sse(StreamEvent(type="thinking", agent=agent, content=content))
                elif et in (
                    EventType.TASK_STARTED,
                    EventType.TASK_COMPLETED,
                    EventType.TASK_FAILED,
                    EventType.TASK_CANCELLED,
                    EventType.AGENT_STARTED,
                    EventType.AGENT_FINISHED,
                    EventType.AGENT_FAILED,
                    EventType.AGENT_RETRY,
                    EventType.ORCHESTRATOR_STARTED,
                    EventType.ORCHESTRATOR_FINISHED,
                    EventType.PLAN_CREATED,
                    EventType.STEP_COMPLETED,
                ):
                    label = et_value.replace("_", " ").title() if et else et_value
                    detail = data.get("task_name") or data.get("phase") or data.get("plan_id") or ""
                    msg = f"📋 [{label}] {agent}"
                    if detail:
                        msg += f" — {detail}"
                    msg += "\n"
                    yield _sse(StreamEvent(type="token", agent=agent, content=msg))
                elif et in (EventType.TOOL_CALL, EventType.TOOL_RESULT, EventType.TOOL_ERROR):
                    tool_name = data.get("tool_name") or data.get("name") or ""
                    if content:
                        snippet = content[:200]
                        msg = (
                            f"🔧 [Tool {et_value}] {tool_name}: {snippet}\n"
                            if tool_name
                            else f"🔧 [Tool {et_value}] {snippet}\n"
                        )
                    elif tool_name:
                        msg = f"🔧 [Tool {et_value}] {tool_name}\n"
                    else:
                        msg = f"🔧 [Tool {et_value}]\n"
                    yield _sse(StreamEvent(type="token", agent=agent, content=msg))
                elif et in (EventType.ERROR, EventType.WARNING):
                    msg = f"⚠️ [{et_value}] {content or str(data)[:200]}\n"
                    yield _sse(StreamEvent(type="token", agent=agent, content=msg))
        except Exception as exc:
            logger.debug("Event bridge ended: %s", exc)
        yield _sse(StreamEvent(type=EVENT_BRIDGE_DONE))

    try:
        engine_result_future: Any = asyncio.ensure_future(
            engine.execute_autonomous(
                objective=objective,
                session_id=session_id,
                context="",
                history=list(history) if history else [],
                project_path=project_path or ".",
                max_verify_iterations=2,
            )
        )
        event_stream = _consume_events()

        while not engine_result_future.done():
            try:
                ev = await asyncio.wait_for(event_stream.__anext__(), timeout=0.3)
                if isinstance(ev, str) and EVENT_BRIDGE_DONE in ev:
                    break
                yield ev
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError:
                continue

        result = await engine_result_future
    except Exception as exc:
        logger.warning("execute_autonomous failed: %s", exc)
        yield _sse(
            StreamEvent(
                type="token",
                agent="ARCHITECT",
                content=f"⚠️ Orquestrador falhou ({exc}). A tentar modo ReAct direto...\n",
            )
        )
        raise

    now = datetime.now(UTC).isoformat()
    await context.append_message(
        session_id, ChatMessage(role="user", content=objective, timestamp=now)
    )
    await context.append_message(
        session_id, ChatMessage(role="assistant", content="", timestamp=now)
    )

    summary_lines = [
        f"\n\n✅ **Execução Autónoma Concluída** ({result.state.value if hasattr(result, 'state') else 'completed'})",
        f"- Tarefas concluídas: {result.completed_tasks}",
        f"- Tarefas com falha: {result.failed_tasks}",
        f"- Duração total: {result.total_duration_ms / 1000:.1f}s",
    ]
    if result.errors:
        summary_lines.append(f"- Erros: {'; '.join(result.errors[:3])}")

    if result.task_results:
        summary_lines.append("\n**Resultados por tarefa:**")
        for artifact in list(result.task_results.values())[:10]:
            if isinstance(artifact, dict):
                name = artifact.get("name", "?")
                status = artifact.get("status", "?")
                agent = artifact.get("agent", "?")
                summary_lines.append(f"- [{agent}] {name}: {status}")

    summary = "\n".join(summary_lines)
    for line in summary.split("\n"):
        yield _sse(StreamEvent(type="token", agent="ARCHITECT", content=line + "\n"))

    await context.append_message(
        session_id, ChatMessage(role="assistant", content=summary, timestamp=now)
    )
    add_message(session_id, "user", objective, tier_used="ARCHITECT")
    add_message(session_id, "assistant", summary, tier_used="ORCHESTRATOR")

    yield _sse(StreamEvent(type="agent_finished", agent="ARCHITECT"))
    yield _sse(StreamEvent(type="done"))


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
async def chat(
    req: ChatRequest, request: Request, _user: dict = Depends(require_auth)
) -> StreamingResponse:
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
        async for chunk in _run_pipeline(req, llm_client, registry, context, event_bus, request):
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

    if not re.match(r"^[a-zA-Z0-9_-]{1,128}$", req.session_id):
        yield _sse(
            StreamEvent(
                type="error",
                content="Invalid session id. Use 1-128 alphanumeric characters, hyphens or underscores.",
            )
        )
        yield _sse(StreamEvent(type="done"))
        return

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

    MAX_MESSAGE_LENGTH = 50000
    if len(req.message) > MAX_MESSAGE_LENGTH:
        yield _sse(
            StreamEvent(
                type="error",
                content=f"Message too long ({len(req.message)} chars). Maximum is {MAX_MESSAGE_LENGTH} characters.",
            )
        )
        yield _sse(StreamEvent(type="done"))
        return

    # 2. Route — if user explicitly selected a model, honour it.
    mode = (getattr(req, "mode", "agent") or "agent").lower()
    user_model = getattr(req, "model", "") or ""

    ALLOWED_MODEL_TIERS = frozenset(
        {
            "micro",
            "fast",
            "coder",
            "reasoning",
            "deep",
            "small",
            "medium",
            "large",
            "expert",
            "nano",
            "dashboard",
        }
    )
    if user_model and user_model not in ALLOWED_MODEL_TIERS:
        yield _sse(
            StreamEvent(
                type="error",
                content=f"Unknown model tier '{user_model}'. Allowed: {', '.join(sorted(ALLOWED_MODEL_TIERS))}",
            )
        )
        yield _sse(StreamEvent(type="done"))
        return

    ALLOWED_PROVIDERS: frozenset[str] = frozenset(
        {
            "ollama",
            "openai",
            "deepseek",
            "kimi",
            "groq",
            "anthropic",
            "gemini",
            "openrouter",
        }
    )
    req_provider = getattr(req, "provider", "") or ""
    if req_provider and req_provider not in ALLOWED_PROVIDERS:
        yield _sse(
            StreamEvent(
                type="error",
                content=f"Unknown provider '{req_provider}'. Allowed: {', '.join(sorted(ALLOWED_PROVIDERS))}",
            )
        )
        yield _sse(StreamEvent(type="done"))
        return
    project_path, project_path_defaulted = resolve_project_path(
        getattr(req, "project_path", "") or ""
    )
    if project_path_defaulted:
        logger.warning(
            "Empty project_path — defaulting to workspace root: %s | session=%s",
            project_path,
            req.session_id,
        )

    # Load mode configuration once; every mode can contribute a system-prompt
    # addon, iteration budget, and thinking preference.
    mode_cfg = get_mode_config("auto" if mode in ("agent", "auto") else mode)
    if mode in ("agent", "auto"):
        mode_addon = (mode_cfg.get("system_prompt_addon") or "").strip()
        mode_max_iterations = int(mode_cfg.get("max_iterations", 7))
        mode_enable_thinking = bool(mode_cfg.get("enable_thinking", False))
    else:
        mode_addon = (mode_cfg.get("system_prompt_addon") or "").strip()
        mode_max_iterations = int(mode_cfg.get("max_iterations", 7))
        mode_enable_thinking = bool(mode_cfg.get("enable_thinking", False))

    effective_message = req.message

    # Load history early so it's available for plan mode and agent invocation.
    history = await context.get_history(req.session_id)

    # Routing decision placeholder; filled by every branch that reaches the
    # single-agent invocation path.
    decision: RoutingDecision | None = None

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
            context_needed="high"
            if user_model in ("reasoning", "deep", "expert", "large")
            else "low",
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
            plan_text = "# Execution Plan\n\n"
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
    elif mode in ("auto", "agent"):
        # Auto mode: for COMPLEX tasks, use the full Plan→Execute→Verify pipeline
        # via OrchestrationEngine.execute_autonomous(). For simple tasks, fall
        # through to the normal smart-routed single-agent ReAct loop.
        if _is_complex_task(req.message) and event_bus is not None:
            logger.info(
                "Auto mode: complex task detected, routing to execute_autonomous | session=%s | query=%.80s",
                req.session_id,
                req.message,
            )
            try:
                async for chunk in _stream_autonomous_execution(
                    objective=req.message,
                    session_id=req.session_id,
                    llm_client=llm_client,
                    registry=registry,
                    event_bus=event_bus,
                    project_path=project_path,
                    history=history,
                    context=context,
                ):
                    yield chunk
                return
            except Exception as exc:
                logger.warning(
                    "execute_autonomous failed for complex task, falling back to ReAct: %s", exc
                )
                # Fall through to single-agent path below

        elif _is_complex_task(req.message) and event_bus is None:
            logger.warning(
                "Auto mode: complex task detected but event_bus is unavailable — "
                "falling back to single-agent ReAct (OrchestrationEngine disabled). | query=%.80s",
                req.message,
            )

        # Simple tasks or autonomous fallback: smart routing → single agent → ReAct loop
        try:
            decision = await _decide_route(req.message, llm_client)
            # Auto mode needs an agent with tool support. Upgrade lightweight picks.
            if decision.primary_agent in ("MICRO", "DOCUMENTER"):
                logger.info(
                    "Auto mode upgraded agent %s -> CODER for tool autonomy",
                    decision.primary_agent,
                )
                decision = decision.model_copy(
                    update={
                        "primary_agent": "CODER",
                        "routing_reason": f"auto:upgraded-from-{decision.primary_agent}",
                    }
                )
            decision = decision.model_copy(
                update={
                    "routing_reason": f"auto:{decision.routing_reason}",
                    "thinking_mode": "iterative",
                    "context_needed": "high",
                    "task_type": "autonomous",
                }
            )
        except Exception as exc:
            logger.warning("Auto routing failed, falling back to CODER: %s", exc)
            decision = RoutingDecision(
                primary_agent="CODER",
                routing_confidence=1.0,
                routing_reason="auto:fallback-coder",
                thinking_mode="iterative",
                context_needed="high",
                task_type="autonomous",
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
    elif mode == "reviewer":
        decision = RoutingDecision(
            primary_agent="REVIEWER",
            routing_confidence=1.0,
            routing_reason="explicit-mode:reviewer",
            thinking_mode="iterative",
            context_needed="high",
            task_type="review",
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
                history=history,
                max_iterations=mode_max_iterations,
                enable_thinking=mode_enable_thinking,
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

            add_message(
                req.session_id, "user", req.message, tier_used="SWARM", latency_ms=latency_ms
            )
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
                    content="Swarm execution failed. Falling back to single-agent mode.\n",
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

    if project_path_defaulted:
        yield _sse(
            StreamEvent(
                type="token",
                agent=decision.primary_agent,  # type: ignore[arg-type]
                content=(
                    f"⚠ Nenhum projeto selecionado — a usar diretório raiz: {project_path}\n"
                ),
            )
        )

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
    # Compose the system-prompt addon for this mode. Include routing metadata so
    # the primary agent knows which secondary agents the router considered useful.
    enriched_addon = mode_addon
    if decision is not None:
        routing_info = (
            f"\n\n[ROUTING INFO] Primary agent: {decision.primary_agent}. "
            f"Reason: {decision.routing_reason}. "
            f"Confidence: {decision.routing_confidence:.2f}. "
            f"Secondary agents suggested: {', '.join(decision.secondary_agents) or 'none'}."
        )
        enriched_addon += routing_info

    def make_invocation(agent_name: str):
        async def invoke() -> AsyncIterator[str]:
            agent = resolve(registry, agent_name)  # type: ignore[arg-type]
            agent_context: dict[str, Any] = {}
            if project_path:
                agent_context["project_path"] = project_path
            if enriched_addon:
                agent_context["_system_addon"] = enriched_addon

            agent_req = AgentRequest(
                session_id=req.session_id,
                query=effective_message,
                client=effective_client,
                history=history,
                project_path=project_path,
                context=agent_context,
                max_iterations=mode_max_iterations,
                enable_thinking=mode_enable_thinking,
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
        yield _sse(
            StreamEvent(
                type="error",
                content="Upstream unavailable: all LLM providers failed. Please try again later.",
            )
        )
        yield _sse(StreamEvent(type="done"))
        return

    yield _sse(StreamEvent(type="agent_started", agent=outcome.used_agent))  # type: ignore[arg-type]

    # 5. Stream tokens and accumulate full response for history.
    parts: list[str] = []
    MAX_RESPONSE_LENGTH = 100_000  # ~100k chars to prevent memory DoS
    try:
        async for token in token_stream:
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
        yield _sse(StreamEvent(type="error", content="Stream interrupted. Please try again."))
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
        from backend.knowledge.memory import get_memory_store

        mem_store = get_memory_store()
        if full.strip():
            await mem_store.remember_conversation(
                user_message=req.message,
                assistant_message=full,
                session_id=req.session_id,
                project_id=project_path,
                source=outcome.used_agent,
                importance=0.6,
            )
    except Exception as exc:
        logger.debug("Semantic memory store failed (non-critical): %s", exc)

    yield _sse(StreamEvent(type="agent_finished", agent=outcome.used_agent))  # type: ignore[arg-type]
    yield _sse(StreamEvent(type="done"))


# Small helper so JSON marshaling can be tested without spinning up FastAPI.
def decision_to_json(d: RoutingDecision) -> str:  # pragma: no cover - trivial
    return json.dumps(d.model_dump(), separators=(",", ":"))
