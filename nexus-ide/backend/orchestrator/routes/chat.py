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
import contextlib
import enum
import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from backend.agents.base import AgentRequest
from backend.config.settings import (
    REPO_ROOT,
    get_mode_config,
)
from backend.core.disk_guard import DiskPressureError
from backend.llm.multi_llm_manager import MultiLLMManager
from backend.middleware.auth import require_auth
from backend.models.api import AgentName, ChatRequest, RoutingDecision, StreamEvent
from backend.observability.advanced_logging import get_structured_logger
from backend.orchestrator.cancellation import get_cancellation_registry
from backend.orchestrator.execution_contracts import ErrorCategory, ExecutionMode, RunContext
from backend.orchestrator.fallback import FallbackOutcome, invoke_with_fallback
from backend.orchestrator.llm_client_lifecycle import acquire_llm_client, release_llm_client
from backend.orchestrator.registry import get_registry, resolve
from backend.orchestrator.router import fast_route, route_with_model
from backend.orchestrator.routing_config import MODEL_TIER_TO_AGENT as _MODEL_TIER_TO_AGENT
from backend.orchestrator.smart_router import smart_route_tier
from backend.orchestrator.swarm import SwarmOrchestrator
from backend.persistence.db import (
    add_message,
    create_session,
    get_session,
    interrupt_active_session_runs,
    upsert_session_run,
)
from backend.token_management import count_tokens
from backend.tools.ollama_client import ChatMessage
from backend.tools.sanitizer import detect_injection

logger = logging.getLogger(__name__)
router = APIRouter()


def _json_safe(value: Any, _depth: int = 0) -> Any:
    """Convert arbitrary event payloads into JSON-serialisable structures.

    Event producers occasionally attach live objects (dataclasses such as
    ``ExecutionPlan``/``DependencyGraph``, enums, sets, …) to ``event.data``.
    A single unserialisable value used to raise inside ``_sse`` and silently
    kill the whole SSE bridge, which is why the chat appeared to "stop
    responding" exactly when a run finished.  This sanitizer keeps the
    bridge alive no matter what a producer publishes.
    """
    if _depth > 8:
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v, _depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v, _depth + 1) for v in value]
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            return _json_safe(to_dict(), _depth + 1)
        except Exception:
            return str(value)
    if isinstance(value, enum.Enum):
        return _json_safe(value.value, _depth + 1)
    return str(value)


def _sse(event: StreamEvent) -> str:
    """Serialise a :class:`StreamEvent` as one SSE frame."""
    return f"data: {event.model_dump_json()}\n\n"


async def _tier_for_model_id(model_id: str) -> str:
    """Best-effort tier for a concrete model id, for agent selection only.

    The tier decides *which agent* handles the request (CODER, ARCHITECT, …);
    the model id itself is still honoured verbatim. Returns ``""`` when the
    model is unknown, in which case normal routing applies.
    """
    from backend.llm.model_catalog import aggregate_models

    catalog = await aggregate_models()
    for entry in catalog.get("models", []):
        if entry.get("id") == model_id:
            tier = str(entry.get("tier") or "")
            return tier
    return ""


# Message emitted by the DEMO fallback when no real LLM provider is configured.
# Clearly labelled so it is never mistaken for genuine AI output.
_DEMO_FALLBACK_MESSAGE = (
    "⚠️ MODO DEMO (sem provedor LLM configurado): respondi de forma simulada. "
    "Define OPENAI_API_KEY / ANTHROPIC_API_KEY / GEMINI_API_KEY "
    "(ou outro em config/settings.py) para respostas reais."
)


def _is_llm_unavailable(llm_client) -> bool:
    """True when no real LLM provider can serve the request.

    This is the case when ``MultiLLMManager`` was created without any API
    keys (zero registered providers) or when no client was wired at all. In
    that situation every real attempt would fail with "Upstream unavailable",
    so we fall back to a clearly-labelled demo stream instead of failing.
    """
    if llm_client is None:
        return True
    if isinstance(llm_client, MultiLLMManager):
        return len(llm_client.providers) == 0
    return False


def _demo_agent(req: "ChatRequest") -> AgentName:
    """Pick a deterministic (non-LLM) agent label for the demo response.

    Uses the fast deterministic router so the label still reflects the kind of
    task, without ever calling an LLM. Falls back to CODER for unknown modes.
    """
    routed = fast_route(req.message)
    if routed:
        return routed
    mode = (getattr(req, "mode", "agent") or "agent").lower()
    return {
        "ask": "MICRO",
        "fast": "MICRO",
        "debug": "DEBUGGER",
        "deep": "ARCHITECT",
        "coder": "CODER",
        "reviewer": "REVIEWER",
        "analyst": "ANALYZER",
    }.get(mode, "CODER")  # type: ignore[return-value]


async def _demo_response(req: "ChatRequest", agent_name: AgentName) -> AsyncIterator[str]:
    """Emit a clearly-labelled simulated chat response (demo fallback).

    Mirrors the real SSE shape exactly (agent_started → token(s) →
    agent_finished → done) so the frontend ``foldEvents`` renders it without
    special-casing. Only triggered when no real provider is available.
    """
    yield _sse(StreamEvent(type="agent_started", agent=agent_name))
    yield _sse(
        StreamEvent(type="token", agent=agent_name, content=f"> {req.message}\n\n")
    )
    # Stream the demo notice in small chunks to mimic token streaming.
    for i in range(0, len(_DEMO_FALLBACK_MESSAGE), 24):
        yield _sse(
            StreamEvent(
                type="token", agent=agent_name, content=_DEMO_FALLBACK_MESSAGE[i : i + 24]
            )
        )
    prompt_tokens = count_tokens(req.message, agent_name)
    output_tokens = count_tokens(_DEMO_FALLBACK_MESSAGE, agent_name)
    yield _sse(
        StreamEvent(
            type="metric",
            agent=agent_name,
            data={
                "usage": {
                    "input_tokens": prompt_tokens,
                    "output_tokens": output_tokens,
                    "reasoning_tokens": 0,
                    "total_tokens": prompt_tokens + output_tokens,
                    "source": "estimated",
                    "cache_status": "not_reported",
                    "context": {
                        "prompt": prompt_tokens,
                        "history": 0,
                        "reasoning": 0,
                        "response": output_tokens,
                        "project": 0,
                    },
                }
            },
        )
    )
    yield _sse(StreamEvent(type="agent_finished", agent=agent_name))
    yield _sse(StreamEvent(type="done"))


# Inline event tags emitted by the ReAct loop in backend/agents/base.py.
# We convert them into first-class SSE events so the frontend can render
# tool calls cleanly instead of showing raw JSON.
_INLINE_EVENT_RE = re.compile(r"<event>([^|>]+)(?:\|(.*?))?</event>", re.DOTALL)

_THINK_OPEN_RE = re.compile(r"<(?:think|thinking)>", re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"</(?:think|thinking)>", re.IGNORECASE)

class _IncrementalResponseParser:
    """Turn provider chunks into UI events without waiting for a full reply.

    Provider-native thinking tags are frequently split across network chunks.
    The old implementation buffered the complete ``<think>`` block, which made
    the UI show thinking only after the model had already finished. This parser
    keeps only the small possible-tag suffix and emits safe thinking text as it
    arrives. It deliberately exposes progress text, not a raw private chain of
    thought, to keep the chat useful and readable.
    """

    _OPEN_TAGS = ("<think>", "<thinking>")
    _CLOSE_TAGS = ("</think>", "</thinking>")
    _TOOL_OPEN_TAG = "<tool_call>"
    _TOOL_CLOSE_TAG = "</tool_call>"
    _TOOL_FENCE_OPEN = "```tool"
    _TOOL_FENCE_CLOSE = "```"

    def __init__(self, agent: str) -> None:
        self.agent = agent
        self.buffer = ""
        self.in_thinking = False
        # Tool markup is an implementation detail. The ReAct loop emits
        # structured tool_call/tool_result events after parsing it, so showing
        # the raw provider syntax in the conversation is both noisy and makes
        # an unsuccessful parse look like a completed action.
        self.tool_delimiter: str | None = None

    def _text_events(self, text: str) -> list[StreamEvent]:
        if not text:
            return []
        return _parse_inline_events(text, self.agent)

    @staticmethod
    def _partial_tag_suffix_length(text: str, tags: tuple[str, ...]) -> int:
        lowered = text.lower()
        for size in range(min(len(text), max(map(len, tags)) - 1), 0, -1):
            suffix = lowered[-size:]
            if any(tag.lower().startswith(suffix) for tag in tags):
                return size
        return 0

    def feed(self, chunk: str) -> list[StreamEvent]:
        self.buffer += chunk
        events: list[StreamEvent] = []

        while self.buffer:
            if self.tool_delimiter == "xml":
                close_at = self.buffer.lower().find(self._TOOL_CLOSE_TAG)
                if close_at >= 0:
                    self.buffer = self.buffer[close_at + len(self._TOOL_CLOSE_TAG) :]
                    self.tool_delimiter = None
                    continue

                # Keep only a possible split closing-tag suffix. Everything
                # before it is tool markup that will be represented by a
                # structured event later in the same stream.
                self.buffer = self.buffer[-(len(self._TOOL_CLOSE_TAG) - 1) :]
                break

            if self.tool_delimiter == "fence":
                lowered = self.buffer.lower()
                nested_at = lowered.find(self._TOOL_FENCE_OPEN)
                close_at = self.buffer.find(self._TOOL_FENCE_CLOSE)
                # A malformed provider response can start a new ```tool block
                # without closing the previous one. Consume the new opener and
                # stay in transport mode instead of leaking the word "tool"
                # and its JSON payload into the conversation.
                if nested_at >= 0 and (close_at < 0 or nested_at <= close_at):
                    self.buffer = self.buffer[nested_at + len(self._TOOL_FENCE_OPEN) :]
                    continue
                if close_at >= 0:
                    self.buffer = self.buffer[close_at + len(self._TOOL_FENCE_CLOSE) :]
                    self.tool_delimiter = None
                    continue

                keep = len(self._TOOL_FENCE_OPEN) - 1
                self.buffer = self.buffer[-keep:]
                break

            tool_at = self.buffer.lower().find(self._TOOL_OPEN_TAG)
            fence_at = self.buffer.lower().find(self._TOOL_FENCE_OPEN)
            opening = _THINK_OPEN_RE.search(self.buffer)
            tool_candidates = [
                (tool_at, "xml", len(self._TOOL_OPEN_TAG)),
                (fence_at, "fence", len(self._TOOL_FENCE_OPEN)),
            ]
            tool_candidates = [candidate for candidate in tool_candidates if candidate[0] >= 0]
            next_tool = min(tool_candidates, default=None, key=lambda item: item[0])
            if next_tool is not None and (
                opening is None or next_tool[0] < opening.start()
            ):
                events.extend(self._text_events(self.buffer[: next_tool[0]]))
                self.buffer = self.buffer[next_tool[0] + next_tool[2] :]
                self.tool_delimiter = next_tool[1]
                continue

            if self.in_thinking:
                close = _THINK_CLOSE_RE.search(self.buffer)
                if close:
                    content = self.buffer[: close.start()]
                    if content.strip():
                        events.append(StreamEvent(type="thinking", agent=self.agent, content=content))
                    self.buffer = self.buffer[close.end() :]
                    self.in_thinking = False
                    continue

                safe_length = len(self.buffer) - self._partial_tag_suffix_length(
                    self.buffer, self._CLOSE_TAGS
                )
                if safe_length:
                    content = self.buffer[:safe_length]
                    if content.strip():
                        events.append(StreamEvent(type="thinking", agent=self.agent, content=content))
                    self.buffer = self.buffer[safe_length:]
                break

            if opening:
                events.extend(self._text_events(self.buffer[: opening.start()]))
                self.buffer = self.buffer[opening.end() :]
                self.in_thinking = True
                continue

            # Keep a short suffix in case the next provider chunk completes an
            # opening tag such as ``<thin`` + ``k>`` or ``<tool_cal`` + ``l>``.
            safe_length = len(self.buffer) - self._partial_tag_suffix_length(
                self.buffer,
                self._OPEN_TAGS + (self._TOOL_OPEN_TAG, self._TOOL_FENCE_OPEN),
            )
            if safe_length:
                events.extend(self._text_events(self.buffer[:safe_length]))
                self.buffer = self.buffer[safe_length:]
            break

        return events

    def flush(self) -> list[StreamEvent]:
        """Flush a truncated/malformed tail as visible text or progress."""
        if not self.buffer:
            return []
        text = self.buffer
        self.buffer = ""
        if self.tool_delimiter is not None:
            self.tool_delimiter = None
            return []
        if self.in_thinking:
            self.in_thinking = False
            return [StreamEvent(type="thinking", agent=self.agent, content=text)] if text.strip() else []
        return self._text_events(text)

# Per-token streaming timeout is intentionally disabled by default. A model can
# spend several minutes loading or reasoning locally and the chat must not turn
# that into a false failure. Operators may opt in to a watchdog with
# NEXUS_STREAM_TOKEN_TIMEOUT=<seconds> when running behind an infrastructure
# proxy that requires one.
_token_timeout_raw = os.environ.get("NEXUS_STREAM_TOKEN_TIMEOUT", "").strip()
try:
    TOKEN_TIMEOUT_SECONDS: float | None = (
        float(_token_timeout_raw) if float(_token_timeout_raw) > 0 else None
    ) if _token_timeout_raw else None
except ValueError:
    TOKEN_TIMEOUT_SECONDS = None


def _parse_inline_events(token: str, agent: str) -> list[StreamEvent]:
    """Parse <event>...</event> tags produced by agents into structured events.

    Also extracts ``<think>...</think>`` blocks (e.g. from DeepSeek / Qwen)
    and emits them as proper ``thinking`` events for the dashboard feed.

    Returns a list of StreamEvents. Any non-event text is returned as a token
    event. Multiple inline events in one token are supported.
    """
    events: list[StreamEvent] = []
    last_end = 0
    has_event = False

    # Extract both provider-native <think> blocks and the ReAct loop's
    # <thinking> blocks. Previously the latter was swallowed by the generic
    # inline-event parser below, so thinking was enabled but never reached UI.
    think_re = re.compile(r"<(?:think|thinking)>(.*?)</(?:think|thinking)>", re.DOTALL)
    for m in think_re.finditer(token):
        content = m.group(1).strip()
        if content:
            events.append(StreamEvent(type="thinking", agent=agent, content=content))
        # Replace the <think> block with a marker so the event scanner skips it
        token = token.replace(m.group(0), "", 1)

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
            tool_name = None
            error_payload = payload
            if "|" in payload:
                tool_name, error_payload = payload.split("|", 1)
            events.append(
                StreamEvent(
                    type="tool_error",
                    agent=agent,
                    tool_name=tool_name,
                    tool_error=error_payload,
                )
            )
        elif event_type == "error":
            # AgentBase emits this when every model/provider fails.  Treat it
            # as a first-class SSE error rather than dropping the tag and
            # letting the frontend receive a misleading successful ``done``.
            events.append(StreamEvent(type="error", agent=agent, content=payload))
        elif event_type == "tool_confirmation":
            try:
                confirmation = json.loads(payload)
            except json.JSONDecodeError:
                confirmation = {"message": payload}
            events.append(
                StreamEvent(
                    type="tool_confirmation",
                    agent=agent,
                    tool_name=confirmation.get("tool_name"),
                    tool_args=confirmation.get("tool_args"),
                    data=confirmation,
                )
                )
        elif event_type == "thinking":
            # The ReAct loop emits an iteration marker before asking the model
            # for its next response.  It is progress metadata, not private
            # chain-of-thought; expose a short status so the UI does not look
            # stalled while tools are being planned.
            iteration_match = re.fullmatch(r"iteration:(\d+)", payload.strip())
            label = (
                f"A analisar a tarefa (passo {iteration_match.group(1)})…"
                if iteration_match
                else "A analisar a tarefa…"
            )
            events.append(StreamEvent(type="thinking", agent=agent, content=label))
        elif event_type == "warning":
            events.append(
                StreamEvent(
                    type="progress",
                    agent=agent,
                    content=payload,
                    data={
                        "event": "agent_warning",
                        "kind": "validation",
                        "status": "running",
                    },
                )
            )
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

# A keyword such as "backend" is not enough to justify a costly autonomous
# run.  The more reliable signal is a request that combines distinct phases:
# inspect a project, change it, then verify or report the result.  This also
# covers natural Portuguese requests such as "Analisa este projeto, encontra
# os problemas, corrige os críticos, executa os testes e apresenta os
# resultados" which previously went through the single-turn ReAct path.
_COMPLEX_TASK_INTENT_MARKERS: tuple[tuple[str, ...], ...] = (
    (
        "analyze", "analyse", "audit", "inspect", "review", "assess",
        "evaluate", "evaluation", "self-evaluation", "analisa", "analisar",
        "audita", "auditar", "inspeciona", "rever", "avaliar", "avaliação",
    ),
    (
        "fix", "correct", "implement", "improve", "refactor", "change",
        "corrige", "corrigir", "implementa", "melhora", "melhorar",
        "refatora", "alterar",
    ),
    (
        "run tests", "test", "tests", "regression", "verify", "validation",
        "execute", "retest", "executa os testes", "executar", "teste", "testa",
        "testar", "testes", "retestar", "regress", "verifica", "verificar", "validar",
    ),
    (
        "document", "report", "results", "summarize", "summary",
        "documenta", "relatório", "resultados", "apresenta",
    ),
)

# Pre-compiled word-boundary patterns. Plain substring matching produced
# false positives — "escrever" contains "rever", "testa" contains "test" —
# sending simple one-phase requests to the full multi-agent pipeline.
def _compile_marker_pattern(markers: tuple[str, ...]) -> "re.Pattern[str]":
    alternatives = "|".join(re.escape(m) for m in sorted(markers, key=len, reverse=True))
    return re.compile(rf"(?<![\w])(?:{alternatives})(?![\w])", re.IGNORECASE)


_COMPLEX_TASK_INTENT_RES: tuple["re.Pattern[str]", ...] = tuple(
    _compile_marker_pattern(markers) for markers in _COMPLEX_TASK_INTENT_MARKERS
)

# A long operational prompt may contain a final question as its success
# criterion.  That question must not downgrade the request to the lightweight
# Q&A lane when the message also contains explicit execution verbs.
_ACTIONABLE_QUESTION_INTENT_RE = _compile_marker_pattern(
    (
        "analyze", "audit", "inspect", "review", "assess", "investigate",
        "fix", "correct", "implement", "improve", "refactor", "change",
        "update", "create", "build", "write", "run", "execute", "perform",
        "identify", "retest", "verify", "validate", "use",
        "analisar", "auditar", "inspecionar", "rever", "avaliar", "investigar",
        "corrigir", "implementar", "melhorar", "refatorar", "alterar", "atualizar",
        "criar", "construir", "escrever", "executar", "testar", "identificar",
        "retestar", "verificar", "validar", "usar",
    )
)

# Informational questions must never trigger multi-agent orchestration, even
# when they contain strong keywords ("como funciona a autenticação?" mentions
# "autenticação" but asks for an explanation, not a change).
_COMPLEX_TASK_QUESTION_STARTERS: tuple[str, ...] = (
    "como ", "o que", "que é", "porque", "porquê", "por que",
    "qual ", "quais ", "quando ", "onde ", "explica", "explain",
    "what ", "what's", "why ", "how ", "which ", "quanto ",
)


def _is_informational_question(query: str) -> bool:
    """True when the message asks for an explanation rather than an action."""
    stripped = query.strip().lower()
    if not stripped:
        return False
    has_action_intent = bool(_ACTIONABLE_QUESTION_INTENT_RE.search(stripped))
    starts_as_question = any(
        stripped.startswith(starter) for starter in _COMPLEX_TASK_QUESTION_STARTERS
    )
    if starts_as_question:
        return not has_action_intent
    # A trailing question mark is only a reliable Q&A signal when the message
    # contains no operational command.  This preserves prompts such as
    # "run the tests and report what prevents the project improving?".
    return stripped.endswith("?") and not has_action_intent


_ASSISTED_ACTION_RE = _compile_marker_pattern(
    (
        "create", "build", "write", "change", "update", "remove", "modify",
        "criar", "construir", "escrever", "alterar", "atualizar", "remover",
    )
)

def classify_execution_mode(
    message: str, requested_mode: str, project_path: str
) -> ExecutionMode:
    """Classify a turn into the explicit CHAT, ASSISTED, or MISSION lane.

    The automatic lane uses observable intent phases only.  Topic words such
    as ``backend`` or ``autenticação`` never imply a mission, and questions
    stay in CHAT even when they mention a project concept.
    """
    text = (message or "").strip()
    lowered = text.lower()
    requested = (requested_mode or "auto").strip().lower()

    if re.match(r"^/mission(?:\s|$)", lowered):
        return ExecutionMode.MISSION
    explicit = {
        "chat": ExecutionMode.CHAT,
        "assisted": ExecutionMode.ASSISTED,
        "mission": ExecutionMode.MISSION,
        "ask": ExecutionMode.CHAT,
        "fast": ExecutionMode.CHAT,
        "plan": ExecutionMode.MISSION,
        "swarm": ExecutionMode.MISSION,
        "auto_swarm": ExecutionMode.MISSION,
        "debug": ExecutionMode.ASSISTED,
        "coder": ExecutionMode.ASSISTED,
        "reviewer": ExecutionMode.ASSISTED,
        "analyst": ExecutionMode.ASSISTED,
        "deep": ExecutionMode.ASSISTED,
    }
    if requested in explicit and requested not in {"auto", "agent"}:
        return explicit[requested]

    if _is_informational_question(text):
        return ExecutionMode.CHAT

    phase_count = sum(1 for marker_re in _COMPLEX_TASK_INTENT_RES if marker_re.search(lowered))
    if (
        _COMPLEX_TASK_INTENT_RES[0].search(lowered)
        and _COMPLEX_TASK_INTENT_RES[1].search(lowered)
        and _COMPLEX_TASK_INTENT_RES[2].search(lowered)
    ):
        return ExecutionMode.MISSION
    if _ASSISTED_ACTION_RE.search(lowered):
        return ExecutionMode.ASSISTED
    if phase_count >= 1 and (
        _RUNTIME_EVIDENCE_ACTION_RE.search(lowered)
        or _FAST_CHAT_ACTION_RE.search(lowered)
    ):
        return ExecutionMode.ASSISTED
    return ExecutionMode.CHAT


def _should_persist_project_memory(mode: ExecutionMode, project_path: str) -> bool:
    """Only project-bound non-CHAT lanes may mutate project memory."""
    return mode is not ExecutionMode.CHAT and bool(project_path)


def _is_complex_task(query: str) -> bool:
    """Heuristic: true if the task likely needs multi-phase orchestrated execution.

    Keeps simple Q&A and one-file edits on the fast ReAct path while routing
    larger feature requests through the full Plan → Execute → Verify pipeline.
    """
    words = query.split()
    if len(words) < _COMPLEX_TASK_MIN_WORDS:
        return False
    if _is_informational_question(query):
        return False
    lowered = query.lower()
    if any(kw in lowered for kw in _COMPLEX_TASK_KEYWORDS):
        return True

    # Require at least two distinct phases (word-boundary matching). This
    # avoids sending a simple "analisa este ficheiro" request to the heavier
    # plan/execution engine, while correctly escalating an audit → fix →
    # test workflow.
    intent_count = sum(
        1 for marker_re in _COMPLEX_TASK_INTENT_RES if marker_re.search(lowered)
    )
    return intent_count >= 2


_FAST_CHAT_ACTION_RE = _compile_marker_pattern(
    (
        "create", "build", "implement", "write", "develop", "design", "refactor",
        "optimize", "fix", "debug", "analyze", "review", "add", "remove", "update",
        "modify", "generate", "install", "deploy", "test", "criar", "construir",
        "implementar", "escrever", "desenvolver", "projetar", "otimizar", "corrigir",
        "depurar", "analisar", "auditar", "verificar", "testar", "melhorar",
    )
)


def _is_fast_chat_turn(query: str) -> bool:
    """Keep ordinary questions out of the autonomous ReAct loop."""
    stripped = query.strip()
    if not stripped or len(stripped.split()) > 12:
        return False
    if _FAST_CHAT_ACTION_RE.search(stripped):
        return False
    if _is_informational_question(stripped):
        return True
    return fast_route(stripped) == "MICRO"


_RUNTIME_EVIDENCE_ACTION_RE = _compile_marker_pattern(
    (
        "analisa", "analisar", "audita", "auditar", "auditoria", "investiga",
        "investigar", "verifica", "verificar", "testa", "testar", "corrige",
        "corrigir", "implementa", "implementar", "inspeciona", "inspecionar",
        "ler", "analyze", "audit", "investigate", "verify", "test", "fix",
        "implement", "inspect", "read",
    )
)
_RUNTIME_EVIDENCE_TARGET_RE = _compile_marker_pattern(
    (
        "projeto", "project", "codigo", "code", "ficheiro", "ficheiros",
        "arquivo", "file", "files", "pasta", "diretoria", "directory", "backend",
        "frontend", "repositorio", "repository", "modulo", "module", "ambiente",
        "environment",
    )
)


def _direct_runtime_evidence_requirement(query: str) -> str:
    """Require real tool evidence for actionable single-agent Auto requests."""
    if _is_informational_question(query):
        return ""
    if not _RUNTIME_EVIDENCE_ACTION_RE.search(query):
        return ""
    if not _RUNTIME_EVIDENCE_TARGET_RE.search(query):
        return ""
    return "substantive"


_QUOTED_WINDOWS_PATH_RE = re.compile(
    r"""(?P<quote>["'`])(?P<path>[A-Za-z]:[\\/][^"'`\r\n]+)(?P=quote)"""
)
_WINDOWS_PATH_TAIL_RE = re.compile(r"(?P<path>[A-Za-z]:[\\/][^\r\n]+)")
_COMMAND_HELP_RE = re.compile(
    r"^\s*(?:/commands?|/comandos?|"
    r"(?:q|que|quais)\s+comandos?(?:\s+(?:tens?|tem|existem|consegues\s+executar))?.*)\s*$",
    re.IGNORECASE,
)


def _existing_directory_from_message(message: str) -> str:
    """Return an explicitly mentioned existing Windows directory, if any.

    Users often paste an unquoted path containing spaces followed by normal
    prose. Starting with the longest candidate and trimming one word at a time
    recovers ``C:\\...\\red nexus`` without treating the following instruction
    as part of the path.
    """
    quoted = _QUOTED_WINDOWS_PATH_RE.search(message or "")
    candidates: list[str] = [quoted.group("path")] if quoted else []
    tail = _WINDOWS_PATH_TAIL_RE.search(message or "")
    if tail:
        raw = tail.group("path").strip()
        boundaries = [len(raw), *(match.start() for match in reversed(list(re.finditer(r"\s+", raw))))]
        candidates.extend(raw[:end] for end in boundaries)

    for candidate in candidates:
        cleaned = candidate.strip().rstrip(".,;:!?)]}")
        if cleaned and os.path.isdir(cleaned):
            return str(Path(cleaned).resolve())
    return ""


def _requested_project_path(request_path: str, message: str) -> str:
    """Resolve the user's project target without granting extra permissions."""
    raw_request_path = (request_path or "").strip()
    if raw_request_path not in {"", ".", "./", ".\\"} and os.path.isdir(raw_request_path):
        return str(Path(raw_request_path).resolve())
    return _existing_directory_from_message(message)


def _is_command_help_request(message: str) -> bool:
    return _COMMAND_HELP_RE.fullmatch(message or "") is not None


def _command_help_text() -> str:
    """Build truthful slash-command help from the live command catalog."""
    try:
        from backend.orchestrator.advanced_modes import get_command_aliases

        commands = get_command_aliases()
    except Exception:
        logger.exception("Could not load slash-command catalog")
        commands = {}

    if not commands:
        return "Não há comandos avançados disponíveis nesta instalação."

    lines = ["Comandos disponíveis:"]
    for command in commands.values():
        aliases = [str(alias) for alias in command.get("aliases", []) if alias]
        if not aliases:
            continue
        description = str(command.get("description") or "").strip()
        line = f"- {aliases[0]}"
        if len(aliases) > 1:
            line += f" (atalhos: {', '.join(aliases[1:])})"
        if description:
            line += f" — {description}"
        lines.append(line)
    lines.append("\nEscreve um comando seguido do objetivo, por exemplo: `/proof verifica este projeto`.")
    return "\n".join(lines)


def _user_facing_preamble(query: str) -> str:
    """Describe the next action without exposing or inventing chain-of-thought."""
    lowered = query.lower()
    if any(word in lowered for word in ("bug", "erro", "falha", "debug", "corrig")):
        return "Vou reproduzir o problema, localizar a causa e validar a correção."
    if any(word in lowered for word in ("pesquisa", "research", "compar", "investig")):
        return "Vou reunir o contexto relevante, comparar a evidência e resumir o essencial."
    if any(word in lowered for word in ("cria", "criar", "implement", "build", "adicion", "melhor")):
        return "Vou mapear a implementação atual, fazer a alteração e verificar o resultado."
    if any(word in lowered for word in ("analisa", "analis", "review", "revis")):
        return "Vou inspecionar o contexto, identificar os pontos importantes e apresentar uma conclusão clara."
    return "Vou compreender o contexto, executar os passos necessários e confirmar o resultado."


def _mission_ui_payload(mission: Any) -> dict[str, Any]:
    """Return the small, public mission snapshot used by the chat.

    Mission Control deliberately keeps a rich diagnostic model.  That model is
    useful for the technical drawer and persistence, but sending ``to_dict``
    as chat text exposed prompts, file lists and internal planning details.
    The main chat receives only measured counters and short labels; the full
    object remains available through the persisted run/events endpoints.
    """
    snapshot = getattr(getattr(mission, "brief", None), "snapshot", None)
    plan = getattr(mission, "plan", None)
    phases: list[dict[str, Any]] = []
    for phase in getattr(plan, "phases", []) or []:
        phases.append(
            {
                "phase": getattr(getattr(phase, "phase", None), "value", str(getattr(phase, "phase", ""))),
                "label": getattr(phase, "phase", None).label
                if getattr(getattr(phase, "phase", None), "label", None)
                else str(getattr(phase, "phase", "")),
                "steps": [str(step)[:180] for step in (getattr(phase, "steps", []) or [])[:4]],
                "skipped": bool(getattr(phase, "skipped", False)),
            }
        )
    findings = getattr(snapshot, "findings", []) if snapshot is not None else []
    contracts = getattr(mission, "contracts", []) or []
    tasks_done = sum(
        1
        for contract in contracts
        if getattr(getattr(contract, "state", None), "value", getattr(contract, "state", ""))
        in {"completed", "skipped"}
    )
    return {
        "mission_id": getattr(mission, "id", ""),
        "session_id": getattr(mission, "session_id", ""),
        "objective": str(getattr(mission, "title", "") or "")[:240],
        "state": getattr(getattr(mission, "state", None), "value", str(getattr(mission, "state", "analysing"))),
        "phase": getattr(getattr(mission, "phase", None), "value", str(getattr(mission, "phase", "diagnosis"))),
        "progress": float(getattr(mission, "progress", 0.0) or 0.0),
        "tasks_total": int(len(contracts)),
        "tasks_done": tasks_done,
        "active_agents": int(getattr(mission, "active_agents", 0) or 0),
        "files_analyzed": int(getattr(snapshot, "file_count", 0) or 0) if snapshot else 0,
        "tests_total": int(getattr(snapshot, "test_files", 0) or 0) if snapshot else 0,
        "findings_count": len(findings),
        "priorities": [str(item)[:180] for item in (getattr(getattr(mission, "brief", None), "priorities", []) or [])[:4]],
        "phases": phases,
    }


def _mission_heartbeat_payload(mission: Any | None, started_at: float) -> tuple[str, dict[str, Any]]:
    """Build a truthful user-facing heartbeat from the current mission state."""
    payload = _mission_ui_payload(mission) if mission is not None else {}
    elapsed = max(0, int(time.monotonic() - started_at))
    payload.update({"elapsed_seconds": elapsed, "heartbeat": True})
    active = int(payload.get("active_agents", 0) or 0)
    total = int(payload.get("tasks_total", 0) or 0)
    done = int(payload.get("tasks_done", 0) or 0)
    if total:
        message = f"Continuo a executar a missão. {done}/{total} tarefas já terminaram; {active} continuam ativas."
    elif active:
        message = f"Continuo a executar a missão. {active} agente(s) continuam ativos."
    else:
        message = "Continuo a executar a missão; ainda não há uma nova etapa concluída para reportar."
    return message, payload


def _normalise_autonomous_status(
    state: str, failed_tasks: int = 0, blocked_tasks: int = 0
) -> str:
    """Map orchestration states to the only terminal UI outcomes."""
    normalized = str(state or "").strip().lower()
    if normalized == "cancelled":
        return "cancelled"
    if (
        normalized in {"failed", "planning_blocked", "blocked"}
        or failed_tasks > 0
        or blocked_tasks > 0
    ):
        return "failed"
    return "completed"


async def _stream_autonomous_execution(
    objective: str,
    session_id: str,
    llm_client,
    registry: dict,
    event_bus,
    project_path: str,
    history,
    context,
    outcome_state: dict[str, Any] | None = None,
    execution_context: str = "",
    cancellation_event: asyncio.Event | None = None,
    cancellation_request_id: str = "",
    checkpoint_callback: Callable[..., None] | None = None,
    run_id: str = "",
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
    execution_started_at = time.monotonic()

    try:
        autonomous_step_timeout = max(
            60, int(os.environ.get("NEXUS_AUTONOMOUS_STEP_TIMEOUT", "900"))
        )
    except ValueError:
        autonomous_step_timeout = 900
    engine = OrchestrationEngine(
        llm_client=llm_client,
        registry=registry,
        event_bus=event_bus,
        max_parallel=3,
        default_timeout=autonomous_step_timeout,
    )

    event_stream: AsyncGenerator[str, None] | None = None
    next_event_task: asyncio.Task[str] | None = None
    engine_result_future: asyncio.Task[Any] | None = None

    # Arm cancellation before Mission Control.  The pre-flight may itself
    # consult an agent/model, so waiting until ``execute_autonomous`` starts
    # leaves a sizeable window where the UI appears stopped but that advisory
    # work keeps running.  The registry watcher cancels this exact generator
    # task, including while it is awaiting the pre-flight.
    async def _cancel_stream_on_request() -> bool:
        cancelled = await get_cancellation_registry().wait_cancelled(
            cancellation_request_id
        )
        # An async generator can resume under a different task for each
        # ``anext`` call, so cancelling the task captured before the first
        # yield is unreliable.  Cancel the long-lived engine task directly.
        if cancelled and engine_result_future is not None and not engine_result_future.done():
            with contextlib.suppress(Exception):
                await engine.cancel(session_id)
            engine_result_future.cancel()
        return cancelled

    cancellation_watch_task: asyncio.Task[bool] | None = None
    if cancellation_request_id:
        cancellation_watch_task = asyncio.create_task(
            _cancel_stream_on_request()
        )

    yield _sse(StreamEvent(type="agent_started", agent="ARCHITECT"))

    # ── Mission Control: understand before spawning ────────────────────────
    #
    # Previously the next thing to happen was ``execute_autonomous()``, which
    # planned internally and auto-approved. The user saw agents appear with no
    # statement of what was understood, what the project looked like, or why
    # those agents. The brief and plan are published *first* — and no agent has
    # been created at the point they are emitted, which is the whole point.
    #
    # This is observability, so it is wrapped: a failure to describe the work
    # must never prevent the work.
    mission_tracker = None
    try:
        from backend.orchestrator.mission_control import start_mission
        from backend.orchestrator.routes.mission import register_mission

        mission_tracker = register_mission(
            start_mission(
                objective,
                session_id=session_id,
                project_path=project_path,
                deep_scan=False,  # keep the pre-flight sub-second on large repos
            )
        )
        mission = mission_tracker.mission
        mission_payload = _mission_ui_payload(mission)
        event_task_id = run_id or mission.id
        if event_bus is not None:
            from backend.orchestrator.events import OrchestratorEvent

            await event_bus.publish(
                OrchestratorEvent(
                    event_type=EventType.TOKEN,
                    source="ORCHESTRATOR",
                    session_id=session_id,
                    task_id=event_task_id,
                    content=_user_facing_preamble(objective) + "\n",
                    data={"public_message": True, "mission_id": mission.id},
                )
            )
            await event_bus.publish(
                OrchestratorEvent(
                    event_type=EventType.MISSION_BRIEF,
                    source="ORCHESTRATOR",
                    session_id=session_id,
                    task_id=event_task_id,
                    data=mission_payload,
                )
            )
            if mission.plan:
                await event_bus.publish(
                    OrchestratorEvent(
                        event_type=EventType.MISSION_PLAN,
                        source="ORCHESTRATOR",
                        session_id=session_id,
                        task_id=event_task_id,
                        data=mission_payload,
                    )
                )
        # The main agent speaks naturally.  The complete brief/plan remains
        # in structured event data for the technical drawer and recovery API.
        yield _sse(
            StreamEvent(
                type="token",
                agent="ORCHESTRATOR",
                content=_user_facing_preamble(objective) + "\n",
            )
        )
        yield _sse(
            StreamEvent(
                type="mission_brief",
                agent="ORCHESTRATOR",
                data=mission_payload,
            )
        )
        if mission.plan:
            yield _sse(
                StreamEvent(
                    type="mission_plan",
                    agent="ORCHESTRATOR",
                    data={**mission_payload, "phases": mission_payload.get("phases", [])},
                )
            )
        if checkpoint_callback:
            checkpoint_callback(
                phase="mission_planned",
                agent="ORCHESTRATOR",
                checkpoint=mission_payload,
            )
    except Exception:
        logger.warning("Mission Control pre-flight failed; continuing", exc_info=True)

    yield _sse(
        StreamEvent(
            type="thinking",
            agent="ARCHITECT",
            content="Vou analisar o pedido, dividir o trabalho e validar o resultado.",
        )
    )

    async def _consume_events() -> AsyncGenerator[str, None]:
        """Subscribe to event_bus and yield SSE frames until it is closed."""
        if event_bus is None:
            return
        response_parsers: dict[str, _IncrementalResponseParser] = {}

        def ui_agent(source: str) -> AgentName:
            """Keep infrastructure component names out of the public agent field."""
            known_agents = {
                "ROUTER", "PLANNER", "ARCHITECT", "ARCHITECT_DESIGN",
                "ARCHITECT_COMPLEXITY", "RESEARCHER", "RESEARCHER_WEB",
                "CODER", "REVIEWER", "ANALYZER", "DEBUGGER", "DOCUMENTER",
                "OPTIMIZER", "REFACTOR_PERFORMANCE", "REFACTOR_CLEAN",
                "DASHBOARD", "MICRO", "ORCHESTRATOR", "SWARM", "SUPERVISOR",
                "GUARDIAN", "TEST_RUNNER_UNIT", "TEST_RUNNER_E2E", "OVERSEER",
                "BUG_HUNTER_STATIC", "BUG_HUNTER_RUNTIME", "META_ANALYZER",
            }
            normalized = source.upper()
            return normalized if normalized in known_agents else "ORCHESTRATOR"  # type: ignore[return-value]

        try:
            async for evt in event_bus.stream_events(event_types=["*"], session_id=session_id):
                et_value = (
                    evt.event_type.value
                    if hasattr(evt.event_type, "value")
                    else str(evt.event_type)
                )
                agent = ui_agent(evt.source or "ORCHESTRATOR")
                content = evt.content or ""
                # Sanitize producer payloads: a single live object (e.g. a
                # DependencyGraph attached to ORCHESTRATOR_FINISHED) used to
                # raise in ``_sse`` and silently kill the entire bridge.
                raw_data = _json_safe(evt.data) if evt.data else {}
                data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
                event_metadata = {
                    key: value
                    for key, value in (
                        ("correlation_id", getattr(evt, "correlation_id", "")),
                        ("run_id", data.get("run_id")),
                        ("mission_id", data.get("mission_id")),
                    )
                    if value
                }

                def _event_sse(
                    event: StreamEvent,
                    metadata: dict[str, Any] = event_metadata,
                ) -> str:
                    return _sse(
                        event.model_copy(
                            update={"data": {**event.data, **metadata}}
                        )
                    )

                try:
                    et = EventType(et_value)
                except ValueError:
                    et = None

                if et == EventType.TOKEN and content:
                    parser = response_parsers.setdefault(
                        str(agent), _IncrementalResponseParser(str(agent))
                    )
                    for parsed in parser.feed(content):
                        yield _event_sse(parsed)
                elif et == EventType.THINKING and content:
                    yield _event_sse(StreamEvent(type="thinking", agent=agent, content=content))
                    # Also publish to the dashboard thinking feed (non-blocking)
                    try:
                        from backend.orchestrator.routes.thinking import publish_thought

                        publish_thought(
                            agent=agent, phase="thinking", text=content, model=data.get("model")
                        )
                    except Exception:
                        pass
                elif et in (EventType.AGENT_STARTED, EventType.AGENT_FINISHED):
                    yield _event_sse(
                        StreamEvent(
                            type="agent_started" if et == EventType.AGENT_STARTED else "agent_finished",
                            agent=agent,
                            data={
                                **data,
                                **event_metadata,
                                "task_id": evt.task_id,
                                "delegated": agent not in ("ARCHITECT", "ORCHESTRATOR"),
                            },
                        )
                    )
                elif et in (
                    EventType.TASK_STARTED,
                    EventType.TASK_WAITING_DEPENDENCY,
                    EventType.TASK_COMPLETED,
                    EventType.TASK_FAILED,
                    EventType.TASK_BLOCKED,
                    EventType.TASK_CANCELLED,
                    EventType.AGENT_FAILED,
                    EventType.AGENT_RETRY,
                    EventType.ORCHESTRATOR_STARTED,
                    EventType.ORCHESTRATOR_FINISHED,
                    EventType.PLAN_CREATED,
                    EventType.STEP_COMPLETED,
                    EventType.HEARTBEAT,
                ):
                    if mission_tracker is not None:
                        execution_status = {
                            EventType.TASK_STARTED: "running",
                            EventType.TASK_WAITING_DEPENDENCY: "waiting_dependency",
                            EventType.TASK_COMPLETED: "completed",
                            EventType.TASK_FAILED: "failed",
                            EventType.TASK_BLOCKED: "blocked",
                            EventType.TASK_CANCELLED: "cancelled",
                            EventType.AGENT_RETRY: "running",
                        }.get(et)
                        if execution_status:
                            mission_tracker.update_execution_task(
                                evt.task_id,
                                execution_status,
                                error=str(data.get("error") or "") or None,
                                activity=(
                                    "A aguardar dependências"
                                    if execution_status == "waiting_dependency"
                                    else None
                                ),
                            )
                        if et == EventType.PLAN_CREATED:
                            mission_tracker.sync_execution_plan(data)
                            yield _event_sse(
                                StreamEvent(
                                    type="mission_plan",
                                    agent="ORCHESTRATOR",
                                    data=_mission_ui_payload(mission_tracker.mission),
                                )
                            )
                    status = (
                        "running"
                        if et in (
                            EventType.TASK_STARTED,
                            EventType.TASK_WAITING_DEPENDENCY,
                            EventType.AGENT_RETRY,
                            EventType.ORCHESTRATOR_STARTED,
                            EventType.HEARTBEAT,
                        )
                        else "error"
                        if et in (
                            EventType.TASK_FAILED,
                            EventType.TASK_BLOCKED,
                            EventType.TASK_CANCELLED,
                            EventType.AGENT_FAILED,
                        )
                        else "success"
                    )
                    kind = (
                        "plan"
                        if et == EventType.PLAN_CREATED
                        else "agent"
                        if et in (EventType.AGENT_FAILED, EventType.AGENT_RETRY)
                        else "status"
                        if et in (EventType.ORCHESTRATOR_STARTED, EventType.ORCHESTRATOR_FINISHED, EventType.HEARTBEAT)
                        else "verification"
                        if et == EventType.STEP_COMPLETED
                        else "task"
                    )
                    task_name = (
                        data.get("task_name")
                        or data.get("name")
                        or data.get("phase")
                        or data.get("objective")
                        or ""
                    )
                    yield _event_sse(
                        StreamEvent(
                            type="progress",
                            agent=agent,
                            content=str(task_name),
                            data={
                                **data,
                                **event_metadata,
                                "kind": kind,
                                "status": status,
                                "event": et_value,
                                "task_id": evt.task_id,
                            },
                        )
                    )
                elif et in (EventType.TOOL_CALL, EventType.TOOL_RESULT, EventType.TOOL_ERROR):
                    tool_name = data.get("tool_name") or data.get("name") or ""
                    args = data.get("tool_args") or data.get("arguments") or data.get("args") or {}
                    result = data.get("tool_result", data.get("result", content or None))
                    error = str(data.get("error") or content or "")
                    yield _event_sse(
                        StreamEvent(
                            type=et_value,  # type: ignore[arg-type]
                            agent=agent,
                            tool_name=str(tool_name or "tool"),
                            tool_args=args if isinstance(args, dict) else {"raw": args},
                            tool_result=result if et == EventType.TOOL_RESULT else None,
                            tool_error=error if et == EventType.TOOL_ERROR else None,
                            data={**data, **event_metadata},
                        )
                    )
                elif et in (EventType.ERROR, EventType.WARNING):
                    yield _event_sse(
                        StreamEvent(
                            type="progress",
                            agent=agent,
                            content=content or str(data)[:200],
                            data={
                                **data,
                                **event_metadata,
                                "kind": "status",
                                "status": "error" if et == EventType.ERROR else "running",
                                "event": et_value,
                            },
                        )
                    )
            for parser in response_parsers.values():
                for parsed in parser.flush():
                    yield _event_sse(parsed)
        except Exception as exc:
            # WARNING, not DEBUG: a dead bridge is exactly the "modelo não
            # responde" symptom and must be visible in production logs.
            logger.warning("Event bridge ended: %s", exc, exc_info=True)

    _cancelled: bool = False
    last_output_at = time.monotonic()
    last_output_wall = datetime.now(UTC)
    next_heartbeat_at = last_output_at + 15.0
    try:
        # Start the subscription before the engine.  A task for ``anext`` is
        # deliberately kept alive across idle periods: using
        # ``wait_for(anext(...), 0.3)`` cancels the async generator every time
        # there is no event, which silently tears down the EventBus bridge.
        event_stream = _consume_events()
        next_event_task = asyncio.create_task(anext(event_stream))
        await asyncio.sleep(0)

        if (
            (cancellation_event is not None and cancellation_event.is_set())
            or (
                cancellation_watch_task is not None
                and cancellation_watch_task.done()
                and cancellation_watch_task.result()
            )
        ):
            raise asyncio.CancelledError

        engine_result_future = asyncio.create_task(
            engine.execute_autonomous(
                objective=objective,
                session_id=session_id,
                context=execution_context,
                history=list(history) if history else [],
                project_path=project_path or ".",
                max_verify_iterations=2,
            )
        )
        while True:
            if cancellation_event is not None and cancellation_event.is_set():
                raise asyncio.CancelledError
            waiting: set[asyncio.Task[Any]] = {engine_result_future}
            if next_event_task is not None:
                waiting.add(next_event_task)
            if cancellation_watch_task is not None:
                waiting.add(cancellation_watch_task)
            done, _ = await asyncio.wait(
                waiting,
                timeout=0.3,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancellation_event is not None and cancellation_event.is_set():
                raise asyncio.CancelledError
            if (
                cancellation_watch_task is not None
                and cancellation_watch_task in done
                and cancellation_watch_task.result()
            ):
                raise asyncio.CancelledError

            if next_event_task is not None and next_event_task in done:
                try:
                    frame = next_event_task.result()
                    last_output_at = time.monotonic()
                    last_output_wall = datetime.now(UTC)
                    next_heartbeat_at = last_output_at + 15.0
                    yield frame
                    if checkpoint_callback:
                        checkpoint_callback(
                            phase="event",
                            agent="ORCHESTRATOR",
                            checkpoint={"last_event_at": datetime.now(UTC).isoformat()},
                        )
                except StopAsyncIteration:
                    next_event_task = None
                else:
                    next_event_task = asyncio.create_task(anext(event_stream))

            if (
                next_event_task is not None
                and time.monotonic() >= next_heartbeat_at
                and not engine_result_future.done()
            ):
                heartbeat_text, heartbeat_data = _mission_heartbeat_payload(
                    mission_tracker.mission if mission_tracker is not None else None,
                    started_at=execution_started_at,
                )
                heartbeat_data["last_event_at"] = last_output_wall.isoformat()
                heartbeat_event_data = {
                    **heartbeat_data,
                    "event": "heartbeat",
                    "kind": "status",
                    "status": "running",
                }
                if event_bus is not None:
                    from backend.orchestrator.events import OrchestratorEvent

                    await event_bus.publish(
                        OrchestratorEvent(
                            event_type=EventType.HEARTBEAT,
                            source="ORCHESTRATOR",
                            session_id=session_id,
                            task_id=run_id,
                            content=heartbeat_text,
                            data=heartbeat_event_data,
                        )
                    )
                else:
                    yield _sse(
                        StreamEvent(
                            type="progress",
                            agent="ORCHESTRATOR",
                            content=heartbeat_text,
                            data=heartbeat_event_data,
                        )
                    )
                if checkpoint_callback:
                    checkpoint_callback(
                        phase="heartbeat",
                        agent="ORCHESTRATOR",
                        checkpoint=heartbeat_data,
                    )
                next_heartbeat_at = time.monotonic() + 15.0

            if engine_result_future in done:
                result = engine_result_future.result()
                break
    except asyncio.CancelledError:
        _cancelled = True
        yield _sse(StreamEvent(type="done"))
        raise
    except DiskPressureError:
        raise
    except Exception as exc:
        logger.warning("execute_autonomous failed: %s", exc)
        text = str(exc)
        if "free-models-per-day-high-balance" in text or "429" in text:
            yield _sse(
                StreamEvent(
                    type="error",
                    agent="ORCHESTRATOR",
                    content=(
                        "OpenRouter free-tier daily limit exhausted. "
                        "The autonomous run cannot complete. "
                        "Wait for the daily reset or add credits to your OpenRouter account."
                    ),
                )
            )
            yield _sse(StreamEvent(type="done"))
            return
        yield _sse(
            StreamEvent(
                type="token",
                agent="ARCHITECT",
                content=f"⚠️ Orquestrador falhou ({exc}). A tentar modo ReAct direto...\n",
            )
        )
        raise
    finally:
        # Never leave an EventBus subscriber or pending ``anext`` task behind
        # after a request disconnects, succeeds, or fails.
        # The SSE bridge and the engine are separate tasks. Cancelling only
        # the bridge used to remove the response from the UI while the full
        # autonomous plan kept reading files and calling models in the
        # background. Stop both halves before releasing the stream.
        if engine_result_future is not None and not engine_result_future.done():
            with contextlib.suppress(Exception):
                await engine.cancel(session_id)
            engine_result_future.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await engine_result_future
        if cancellation_watch_task is not None and not cancellation_watch_task.done():
            cancellation_watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await cancellation_watch_task
        if next_event_task is not None and not next_event_task.done():
            next_event_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                await next_event_task
        if event_stream is not None:
            with contextlib.suppress(RuntimeError):
                await event_stream.aclose()

    if _cancelled:
        raise

    state_value = str(
        result.state.value if hasattr(result.state, "value") else result.state or "completed"
    )
    normalized_status = _normalise_autonomous_status(
        state_value, result.failed_tasks, result.blocked_tasks
    )
    if outcome_state is not None:
        outcome_state.update(
            {
                "status": normalized_status,
                "state": state_value,
                "failed_tasks": result.failed_tasks,
                "errors": list(result.errors),
            }
        )

    now = datetime.now(UTC).isoformat()
    await context.append_message(
        session_id, ChatMessage(role="user", content=objective, timestamp=now)
    )

    icon = "✅" if normalized_status == "completed" else "⏹" if normalized_status == "cancelled" else "❌"
    title = (
        "Execução Autónoma Concluída"
        if normalized_status == "completed"
        else "Execução Autónoma Cancelada"
        if normalized_status == "cancelled"
        else "Execução Autónoma Falhou"
    )
    summary_lines = [
        f"\n\n{icon} **{title}**",
        f"- Tarefas concluídas: {result.completed_tasks}",
        f"- Tarefas com falha: {result.failed_tasks}",
        f"- Duração total: {result.total_duration_ms / 1000:.1f}s",
    ]
    if result.errors:
        summary_lines.append(f"- Erros: {'; '.join(result.errors[:3])}")

    # Errors the agents recovered from on their own (e.g. a wrong path that
    # was corrected via list_dir) are healthy autonomy — surface them as
    # visibility, not failure.
    recovered_count = 0
    for artifact in result.task_results.values():
        if isinstance(artifact, dict):
            recovered_count += len(artifact.get("recovered_tool_errors") or [])
    if recovered_count:
        summary_lines.append(
            f"- Erros recuperados autonomamente: {recovered_count} "
            "(o agente corrigiu-se sem intervenção)"
        )

    if result.task_results:
        summary_lines.append("\n**Resultados por tarefa:**")
        for artifact in list(result.task_results.values())[:10]:
            if isinstance(artifact, dict):
                name = artifact.get("name", "?")
                status = artifact.get("status", "?")
                agent = artifact.get("agent", "?")
                summary_lines.append(f"- [{agent}] {name}: {status}")

    # ── Mission Control: close the loop with a durable artefact ────────────
    #
    # "It ran and printed some lines" is not a deliverable. The report records
    # what was understood, what changed, what was verified with which exit
    # code, what is still broken, and how to undo it — the questions asked
    # after the terminal has scrolled away.
    if mission_tracker is not None:
        try:
            from backend.orchestrator.mission_control import MissionReport, MissionState

            for task_id, artifact in result.task_results.items():
                if not isinstance(artifact, dict):
                    continue
                mission_tracker.update_execution_task(
                    str(task_id),
                    str(artifact.get("status", "")),
                    error=str(artifact.get("error", "")) or None,
                )

            mission_tracker.complete(
                state={
                    "completed": MissionState.COMPLETED,
                    "cancelled": MissionState.CANCELLED,
                }.get(normalized_status, MissionState.FAILED),
                unresolved=list(result.errors[:10]),
            )
            mission_tracker.persist()
            report_path = MissionReport(mission_tracker.mission).write()
            if report_path is not None:
                summary_lines.append(f"\n📄 Relatório: `reports/{report_path.name}`")
            if normalized_status == "completed":
                yield _sse(
                    StreamEvent(
                        type="mission_completed",
                        agent="ORCHESTRATOR",
                        data={
                            "mission_id": mission_tracker.mission.id,
                            "report": report_path.name if report_path else None,
                            "status": normalized_status,
                        },
                    )
                )
            else:
                yield _sse(
                    StreamEvent(
                        type="error",
                        agent="ORCHESTRATOR",
                        content=(
                            "; ".join(result.errors[:3])
                            or "A missão não concluiu todas as fases com evidência verificável."
                        ),
                        data={
                            "error_category": "planning"
                            if state_value == "planning_blocked"
                            else "execution",
                            "mission_id": mission_tracker.mission.id,
                            "report": report_path.name if report_path else None,
                            "state": state_value,
                        },
                    )
                )
        except DiskPressureError as exc:
            detail = exc.to_dict()
            summary_lines.append(f"\nDisk pressure blocked mission artifact persistence: {exc}")
            yield _sse(
                StreamEvent(
                    type="error",
                    agent="ORCHESTRATOR",
                    content=str(exc),
                    data={"error_category": "disk_pressure", **detail},
                )
            )
        except Exception:
            logger.warning("Mission Control report generation failed", exc_info=True)

    summary = "\n".join(summary_lines)
    for line in summary.split("\n"):
        yield _sse(StreamEvent(type="token", agent="ARCHITECT", content=line + "\n"))

    await context.append_message(
        session_id, ChatMessage(role="assistant", content=summary, timestamp=now)
    )
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
    # The iterator starts on a later ASGI turn. Acquire now so a concurrent
    # settings update cannot retire and close this client before streaming
    # begins.
    acquire_llm_client(request.app, llm_client)

    async def event_stream() -> AsyncIterator[str]:
        """Keep the SSE contract intact even when post-processing fails.

        The response is already committed with HTTP 200 when the generator
        starts. An exception escaping here makes uvicorn terminate the
        chunked body without a final frame, which browsers surface as a
        generic ``NetworkError``. Convert late pipeline failures into the
        same structured error/done events used by the normal error paths.
        """
        pipeline = _run_pipeline(req, llm_client, registry, context, event_bus, request)
        next_chunk: asyncio.Task[str] | None = asyncio.create_task(anext(pipeline))
        terminal_done_seen = False
        try:
            while next_chunk is not None:
                ready, _ = await asyncio.wait({next_chunk}, timeout=15.0)
                if not ready:
                    # A comment frame keeps browsers and reverse proxies from
                    # treating a long provider/tool pause as a dead stream.
                    yield ": nexus-heartbeat\n\n"
                    continue
                try:
                    frame = next_chunk.result()
                    if frame.startswith("data:"):
                        try:
                            payload = json.loads(frame.split("data:", 1)[1].strip())
                            terminal_done_seen = payload.get("type") == "done"
                        except (TypeError, ValueError, json.JSONDecodeError):
                            pass
                    yield frame
                except StopAsyncIteration:
                    if not terminal_done_seen:
                        logger.error(
                            "Chat pipeline ended without terminal done event | session=%s",
                            req.session_id,
                        )
                        yield _sse(
                            StreamEvent(
                                type="error",
                                content=(
                                    "A execução terminou sem uma resposta final. "
                                    "O estado foi marcado como incompleto; tenta novamente."
                                ),
                                data={"error_category": ErrorCategory.INTERNAL.value},
                            )
                        )
                        yield _sse(StreamEvent(type="done"))
                    break
                next_chunk = asyncio.create_task(anext(pipeline))
        except asyncio.CancelledError:
            # The browser/client intentionally disconnected, or an explicit
            # cancellation was requested. Emit the terminal SSE event before
            # propagating the cancellation so the SSE contract is always
            # satisfied even when the stream is terminated early.
            yield _sse(StreamEvent(type="done"))
            raise
        except Exception as exc:
            logger.exception("Chat SSE pipeline failed after response started: %s", exc)
            yield _sse(
                StreamEvent(
                    type="error",
                    content="Ocorreu um erro interno ao finalizar a resposta. Tenta novamente.",
                )
            )
            yield _sse(StreamEvent(type="done"))
        finally:
            if next_chunk is not None and not next_chunk.done():
                next_chunk.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await next_chunk
            with contextlib.suppress(Exception):
                await pipeline.aclose()
            await release_llm_client(request.app, llm_client)

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
    run_id = f"run-{uuid.uuid4().hex}"
    goal_id = f"goal-{uuid.uuid4().hex[:12]}"
    correlation_id = uuid.uuid4().hex[:16]
    requested_mode = getattr(req, "mode", "auto") or "auto"
    execution_mode = classify_execution_mode(
        req.message, requested_mode, getattr(req, "project_path", "") or ""
    )
    run_context = RunContext(
        session_id=req.session_id,
        run_id=run_id,
        correlation_id=correlation_id,
        mission_id=None,
        project_path=getattr(req, "project_path", "") or None,
        mode=execution_mode,
        goal_id=goal_id,
    )
    run_started = False

    def _start_durable_run() -> None:
        """Make the user turn durable before any long-running provider call."""
        nonlocal run_started
        try:
            if get_session(req.session_id) is None:
                create_session(
                    title=req.message[:60] or "Nova sessão",
                    mode=req.mode or "auto",
                    session_id=req.session_id,
                )
            interrupt_active_session_runs(req.session_id, except_run_id=run_id)
            add_message(req.session_id, "user", req.message)
            upsert_session_run(
                run_id,
                req.session_id,
                prompt=req.message,
                phase="routing",
                checkpoint={"mode": execution_mode.value, "project_path": bool(req.project_path)},
                goal_id=run_context.goal_id,
                correlation_id=run_context.correlation_id,
                mode=execution_mode.value,
                execution_state="routing",
                provider=getattr(req, "provider", "") or None,
                model=getattr(req, "model", "") or None,
            )
            run_started = True
        except Exception:
            # The stream remains usable if an old database is read-only or is
            # being migrated; the failure is visible in logs and the normal
            # response path still handles the request.
            logger.exception("Could not create durable checkpoint for %s", run_id)

    def _checkpoint(
        *,
        status: str = "running",
        execution_state: str | None = None,
        phase: str,
        agent: str | None = None,
        partial_output: str = "",
        checkpoint: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        error: str | None = None,
        error_category: str | None = None,
        finished: bool = False,
    ) -> None:
        if not run_started:
            return
        try:
            upsert_session_run(
                run_id,
                req.session_id,
                status=status,
                agent=agent,
                phase=phase,
                prompt=req.message,
                partial_output=partial_output[-120_000:],
                checkpoint=checkpoint,
                usage=usage,
                error=error,
                finished=finished,
                correlation_id=run_context.correlation_id,
                goal_id=run_context.goal_id,
                mode=execution_mode.value,
                execution_state=(
                    execution_state
                    or ("completed" if finished and status == "completed" else status)
                ),
                provider=getattr(req, "provider", "") or None,
                model=getattr(req, "model", "") or None,
                error_category=error_category,
            )
        except Exception:
            logger.debug("Checkpoint write failed for %s", run_id, exc_info=True)

    terminal_error_persisted = False

    async def _persist_terminal_error(
        message: str,
        *,
        agent: str | None = None,
        error_category: str = ErrorCategory.PROVIDER.value,
        phase: str = "provider_error",
        partial_output: str = "",
        checkpoint: dict[str, Any] | None = None,
    ) -> None:
        """Keep terminal failures visible after the SSE stream is reloaded.

        The stream can legitimately emit an ``error`` followed by ``done``.
        Persisting only the run checkpoint in that path meant that
        ``ChatPanel.loadHistory`` erased the in-memory error and left the user
        with a missing assistant message.
        """
        nonlocal terminal_error_persisted
        if terminal_error_persisted:
            return
        terminal_error_persisted = True
        error_text = message.strip() or "O pedido falhou sem uma mensagem técnica."
        now = datetime.now(UTC).isoformat()
        try:
            await context.append_message(
                req.session_id,
                ChatMessage(role="user", content=req.message, timestamp=now),
            )
            await context.append_message(
                req.session_id,
                ChatMessage(
                    role="assistant",
                    content=f"⚠️ {error_text}",
                    timestamp=now,
                ),
            )
            add_message(
                req.session_id,
                "assistant",
                f"⚠️ {error_text}",
                tier_used=agent,
            )
        except Exception:
            logger.debug("Failed to persist terminal chat error", exc_info=True)
        _checkpoint(
            status="failed",
            phase=phase,
            agent=agent,
            partial_output=partial_output,
            error=error_text,
            error_category=error_category,
            checkpoint=checkpoint,
            finished=True,
        )

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

    # ``model`` accepts either a router tier ("fast", "coder", …) or a concrete
    # provider model id ("anthropic/claude-sonnet-4", "qwen2.5:7b").
    #
    # Previously only tiers were accepted, so the frontend mapped the chosen
    # model down to a tier and threw the id away — the tier then resolved to a
    # *different* model via config/models.yaml. Selecting a model in the UI had
    # no effect on which model answered. A concrete id is now carried through to
    # the agent via ``_model_override`` and used verbatim.
    model_tier = ""
    model_override = ""
    if user_model:
        if user_model in ALLOWED_MODEL_TIERS:
            model_tier = user_model
        elif user_model in ("auto", "default"):
            pass  # let the smart router decide
        else:
            model_override = user_model
            # Ask the catalog which tier this model belongs to so agent
            # selection (CODER vs. ARCHITECT …) still matches its strengths.
            try:
                model_tier = await _tier_for_model_id(user_model)
            except Exception:  # noqa: BLE001 - routing must not fail on this
                logger.debug("Could not infer tier for %s", user_model, exc_info=True)

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
            "opencode_go",
            "kilo",
        }
    )
    req_provider = getattr(req, "provider", "") or ""
    if req_provider and req_provider not in ALLOWED_PROVIDERS:
        _checkpoint(
            status="failed",
            phase="validation_error",
            error=f"Unknown provider: {req_provider}",
            finished=True,
        )
        yield _sse(
            StreamEvent(
                type="error",
                content=f"Provider desconhecido '{req_provider}'. Permitidos: {', '.join(sorted(ALLOWED_PROVIDERS))}",
                data={
                    "error_category": ErrorCategory.VALIDATION.value,
                    "run_id": run_context.run_id,
                    "correlation_id": run_context.correlation_id,
                    "provider": req_provider,
                },
            )
        )
        yield _sse(StreamEvent(type="done", data=run_context.to_dict()))
        return

    # Slash-command help is product metadata, not an LLM question. Answer it
    # from the live catalog so the model cannot invent aliases such as /write
    # or /lint that the chat router does not actually implement.
    if _is_command_help_request(req.message):
        help_text = _command_help_text()
        _start_durable_run()
        help_decision = RoutingDecision(
            primary_agent="ROUTER",
            mode=execution_mode,
            run_id=run_context.run_id,
            correlation_id=run_context.correlation_id,
            provider=getattr(req, "provider", "") or "",
            model=getattr(req, "model", "") or "",
            reason="command-catalog",
            routing_reason="command-catalog",
            routing_confidence=1.0,
            task_type="command_help",
        )
        yield _sse(
            StreamEvent(type="routing", routing=help_decision, data=run_context.to_dict())
        )
        now = datetime.now(UTC).isoformat()
        await context.append_message(
            req.session_id, ChatMessage(role="user", content=req.message, timestamp=now)
        )
        await context.append_message(
            req.session_id, ChatMessage(role="assistant", content=help_text, timestamp=now)
        )
        add_message(req.session_id, "assistant", help_text, tier_used="ROUTER")
        _checkpoint(
            status="completed",
            phase="command_help",
            agent="ROUTER",
            partial_output=help_text,
            checkpoint={"source": "command_catalog"},
            finished=True,
        )
        yield _sse(StreamEvent(type="agent_started", agent="ROUTER"))
        yield _sse(StreamEvent(type="token", agent="ROUTER", content=help_text))
        yield _sse(StreamEvent(type="agent_finished", agent="ROUTER"))
        yield _sse(StreamEvent(type="done"))
        return


    # CHAT never bootstraps a project or autonomous execution context.
    fast_candidate = execution_mode is ExecutionMode.CHAT or mode in {"ask", "fast"} or (
        mode in {"auto", "agent"} and _is_fast_chat_turn(req.message)
    )

    # The explicit request wins. If the UI has no active project, recover a
    # real absolute directory named in the user's message. The old order read
    # an arbitrary ``SELECT ... LIMIT 1`` project first and silently executed
    # against the wrong workspace.
    project_path = "" if fast_candidate else _requested_project_path(
        getattr(req, "project_path", "") or "",
        req.message,
    )
    project_path_defaulted = False

    if not project_path and not fast_candidate:
        try:
            from backend.persistence.db import get_connection_pool

            pool = get_connection_pool()
            conn = pool.get_connection()
            try:
                row = conn.execute(
                    "SELECT path FROM projects ORDER BY updated_at DESC, created_at DESC LIMIT 1"
                ).fetchone()
                candidate = str(row["path"]) if row and row["path"] else ""
                if candidate and os.path.isdir(candidate):
                    project_path = str(Path(candidate).resolve())
                    logger.info("Using most recent project from database: %s", project_path)
            finally:
                # The connection came from the shared pool; return it instead
                # of closing it so repeated chat requests cannot exhaust it.
                pool.return_connection(conn)
        except Exception as exc:
            logger.warning("Could not read project from database: %s", exc)

    if not project_path and not fast_candidate:
        project_path_defaulted = True
        project_path = str(REPO_ROOT)
        logger.warning(
            "No project found — using root: %s | session=%s",
            project_path,
            req.session_id,
        )

    # Create/read the compact project bootstrap on first use.  This is kept
    # outside the semantic memory store so the project can carry a small,
    # human-reviewable architecture map independently of transcripts and
    # embeddings.
    project_memory = ""
    try:
        from backend.knowledge.project_memory import read_project_memory

        project_memory = read_project_memory(project_path) if project_path else ""
    except Exception as exc:
        logger.warning("Could not load project memory for %s: %s", project_path, exc)

    # Load mode configuration once; every mode can contribute a system-prompt
    # addon, iteration budget, and thinking preference.
    mode_cfg = get_mode_config("auto" if mode in ("agent", "auto") else mode)
    if mode in ("agent", "auto"):
        mode_addon = (mode_cfg.get("system_prompt_addon") or "").strip()
        mode_max_iterations = int(mode_cfg.get("max_iterations", 0))
        mode_enable_thinking = bool(mode_cfg.get("enable_thinking", False))
    else:
        mode_addon = (mode_cfg.get("system_prompt_addon") or "").strip()
        mode_max_iterations = int(mode_cfg.get("max_iterations", 0))
        mode_enable_thinking = bool(mode_cfg.get("enable_thinking", False))
    # The UI control used to be transported but never applied. It now opts in
    # to the public progress/approach stream even for modes such as swarm.
    # ``medium`` is the historical UI default, but it must not make every
    # ordinary question enter a long visible reasoning path.
    if req.thinking_strength == "high" or (
        req.thinking_strength == "medium" and not _is_fast_chat_turn(req.message)
    ):
        mode_enable_thinking = True
    if fast_candidate:
        # ``auto`` enables thinking for complex work, but that default must
        # not leak a thinking preamble into an ordinary informational turn.
        mode_enable_thinking = False

    effective_message = req.message

    # ── Advanced Mode /command resolution ────────────────────────────────
    # If the message starts with a recognised /command, strip the command,
    # activate the corresponding advanced mode, and inject its system prompt
    # addon into the pipeline.
    _advanced_mode_addon = None
    _advanced_profile: dict[str, Any] = {}
    _advanced_command_mode: str | None = None
    _advanced_force_autonomous = False
    _advanced_force_swarm = False
    _advanced_preferred_agent: str | None = None
    _trimmed = effective_message.lstrip()
    if _trimmed.startswith("/"):
        # Extract command and rest of message
        parts = _trimmed.split(None, 1)
        cmd_text = parts[0] if parts else ""
        rest = parts[1] if len(parts) > 1 else ""
        try:
            from backend.orchestrator.advanced_modes import (
                get_orchestrator,
                resolve_command,
            )
            resolved = resolve_command(cmd_text)
            if resolved:
                mode_id = resolved["mode"]
                orch = get_orchestrator()
                execution_target = orch.get_execution_target(mode_id)
                _advanced_command_mode = mode_id
                _advanced_force_autonomous = execution_target.get("kind") == "autonomous"
                _advanced_force_swarm = execution_target.get("kind") == "swarm"
                _advanced_preferred_agent = execution_target.get("agent")
                # Activate the advanced mode
                orch.activate_mode(mode_id)
                # Prepare mode context with the actual request (without the command)
                context_data = orch.prepare_mode_context(
                    mode_id,
                    rest or f"Execute advanced mode: {mode_id}",
                )
                _advanced_mode_addon = context_data.get("addon", "")
                effective_message = rest or f"Activate {mode_id} mode"
                logger.info(
                    "Advanced mode /command resolved: %s -> %s | msg=%s",
                    cmd_text, mode_id, effective_message[:80],
                )
        except ImportError as _exc:
            logger.debug("Advanced modes not available: %s", _exc)
        except Exception as _exc:
            logger.warning("Failed to resolve advanced mode command: %s", _exc)

    # A mode toggled in the Infinity panel must affect subsequent requests;
    # otherwise "ACTIVE" is only cosmetic.  Compose a compact policy profile
    # when no explicit slash command selected the strategy for this turn.
    if not _advanced_command_mode:
        try:
            from backend.orchestrator.advanced_modes import get_orchestrator

            _advanced_profile = get_orchestrator().prepare_active_execution_profile(effective_message)
            if _advanced_profile.get("active_mode_ids"):
                _advanced_mode_addon = _advanced_profile.get("addon", "")
                _advanced_force_autonomous = bool(_advanced_profile.get("force_autonomous"))
        except Exception as _exc:
            logger.warning("Failed to compose active advanced modes: %s", _exc)

    # Merge advanced mode addon into the pipeline's system prompt addon
    if _advanced_mode_addon:
        mode_addon = _advanced_mode_addon + "\n\n" + mode_addon
        mode_max_iterations = 0  # Unlimited for advanced modes
        mode_enable_thinking = True

    # Load history early so it's available for plan mode and agent invocation.
    run_context = RunContext(
        session_id=req.session_id,
        run_id=run_id,
        correlation_id=correlation_id,
        mission_id=None,
        project_path=project_path or None,
        mode=execution_mode,
        goal_id=goal_id,
    )
    history = await context.get_history(req.session_id)
    # Persist the current user turn only after taking the pre-turn snapshot;
    # otherwise the same prompt would be fed back as part of its own history.
    _start_durable_run()

    # Publish exactly one routing frame before any plan, mission, or provider
    # token.  Later heuristics refine the agent choice but retain this run
    # envelope so the client can correlate every event.
    initial_agent: AgentName = (
        "ARCHITECT"
        if execution_mode is ExecutionMode.MISSION
        else "CODER"
        if execution_mode is ExecutionMode.ASSISTED
        else "MICRO"
    )
    decision: RoutingDecision = RoutingDecision(
        primary_agent=initial_agent,
        mode=execution_mode,
        run_id=run_context.run_id,
        correlation_id=run_context.correlation_id,
        provider=getattr(req, "provider", "") or "",
        model=model_override or user_model,
        reason=f"classified:{execution_mode.value}",
        routing_reason=f"classified:{execution_mode.value}",
        routing_confidence=1.0,
        thinking_mode="deep" if execution_mode is ExecutionMode.MISSION else "fast",
        context_needed="high" if execution_mode is not ExecutionMode.CHAT else "low",
        task_type=execution_mode.value,
    )
    yield _sse(StreamEvent(type="routing", routing=decision, data=run_context.to_dict()))

    # When the user explicitly picks a chat mode (anything other than the
    # default "agent" mode), the mode always wins over the selected model tier.
    # Only honour the model choice when no specific mode has been chosen.
    if mode == "agent" and model_tier and model_tier in _MODEL_TIER_TO_AGENT:
        # Route straight to the agent that matches the chosen model's strengths.
        agent_name = _MODEL_TIER_TO_AGENT[model_tier]
        heavy = model_tier in ("reasoning", "deep", "expert")
        decision = RoutingDecision(
            primary_agent=agent_name,  # type: ignore[arg-type]
            routing_confidence=1.0,
            routing_reason=(
                f"user-selected-model:{model_override or model_tier}"
                + (f" (tier {model_tier})" if model_override else "")
            ),
            thinking_mode="deep" if heavy else "fast",
            context_needed="high" if heavy or model_tier == "large" else "low",
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
            planning = await engine.create_plan(
                objective=req.message,
                session_id=req.session_id,
                history=history,
            )
            if planning.status == "blocked" or planning.plan is None:
                error = planning.error or "planning blocked"
                _checkpoint(
                    status="failed",
                    phase="planning_blocked",
                    agent="ARCHITECT",
                    error=error,
                    checkpoint={"status": "planning_blocked", "source": planning.source},
                    finished=True,
                )
                yield _sse(
                    StreamEvent(
                        type="error",
                        agent="ARCHITECT",
                        content=f"Planning blocked: {error}",
                        data={
                            "status": "planning_blocked",
                            "source": planning.source,
                            "error": error,
                            "deterministic_proposal": (
                                planning.deterministic_proposal.to_dict()
                                if planning.deterministic_proposal is not None
                                else None
                            ),
                        },
                    )
                )
                yield _sse(StreamEvent(type="done"))
                return
            plan = planning.plan
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
            _checkpoint(
                status="completed",
                phase="plan_completed",
                agent="ARCHITECT",
                partial_output=plan_text,
                checkpoint={"mode": "plan"},
                finished=True,
            )
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
    elif (
        execution_mode is ExecutionMode.MISSION
        or mode in ("auto", "agent")
        or (_advanced_force_autonomous and not fast_candidate)
    ) and not _advanced_force_swarm:
        # Auto mode: for COMPLEX tasks, use the full Plan→Execute→Verify pipeline
        # via OrchestrationEngine.execute_autonomous(). For simple tasks, fall
        # through to the normal smart-routed single-agent ReAct loop.
        # Keep the default ``auto`` lane principal-first. The synchronous
        # Plan->Execute->Verify path is reserved for an explicitly activated
        # advanced autonomous mode; otherwise a complex request is handled by
        # the principal, which may use ``spawn_task`` for independent work.
        if (
            execution_mode is ExecutionMode.MISSION
            or (_advanced_force_autonomous and not fast_candidate)
        ) and event_bus is not None:
            logger.info(
                "Auto mode: complex task detected, routing to execute_autonomous | session=%s | query=%.80s",
                req.session_id,
                req.message,
            )
            try:
                autonomous_outcome: dict[str, Any] = {
                    "status": "failed",
                    "state": "failed",
                    "failed_tasks": 0,
                    "errors": [],
                }
                inner_cancellation_event: asyncio.Event | None = None
                inner_cancellation_request_id = ""
                if request is not None:
                    request_id = getattr(
                        getattr(request, "state", None),
                        "nexus_request_id",
                        "",
                    ) or request.headers.get("X-Nexus-Request-Id", "")
                    if request_id:
                        inner_cancellation_request_id = request_id
                        cancellation_entry = get_cancellation_registry().get(request_id)
                        if cancellation_entry is not None:
                            inner_cancellation_event = cancellation_entry.event
                async for chunk in _stream_autonomous_execution(
                    objective=effective_message,
                    session_id=req.session_id,
                    llm_client=llm_client,
                    registry=registry,
                    event_bus=event_bus,
                    project_path=project_path,
                    history=history,
                    context=context,
                    outcome_state=autonomous_outcome,
                    execution_context=mode_addon,
                    cancellation_event=inner_cancellation_event,
                    cancellation_request_id=inner_cancellation_request_id,
                    checkpoint_callback=lambda *, phase, agent, checkpoint: _checkpoint(
                        phase=phase,
                        agent=agent,
                        checkpoint=checkpoint,
                    ),
                    run_id=run_id,
                ):
                    yield chunk
                outcome_status = str(autonomous_outcome["status"])
                _checkpoint(
                    status=outcome_status,
                    phase=(
                        "autonomous_completed"
                        if outcome_status == "completed"
                        else "autonomous_cancelled"
                        if outcome_status == "cancelled"
                        else "autonomous_failed"
                    ),
                    agent="ORCHESTRATOR",
                    checkpoint={
                        "mode": "autonomous",
                        "state": autonomous_outcome["state"],
                        "failed_tasks": autonomous_outcome["failed_tasks"],
                    },
                    error=(
                        "; ".join(str(item) for item in autonomous_outcome["errors"][:3])
                        if outcome_status != "completed"
                        else None
                    ),
                    error_category=(
                        "planning"
                        if autonomous_outcome.get("state") == "planning_blocked"
                        else None
                    ),
                    finished=True,
                )
                return
            except DiskPressureError as exc:
                detail = exc.to_dict()
                autonomous_outcome.update(
                    {
                        "status": "blocked",
                        "state": "blocked",
                        "failed_tasks": [],
                        "errors": [str(exc)],
                        "disk_pressure": detail,
                    }
                )
                _checkpoint(
                    # ``session_runs.status`` is constrained to the terminal
                    # values used by the UI. Keep the more precise blocked
                    # reason in the execution envelope instead of attempting
                    # to persist an invalid status that would leave the run
                    # stuck as ``running``.
                    status="failed",
                    execution_state="blocked",
                    phase="disk_pressure",
                    agent="ORCHESTRATOR",
                    checkpoint={"mode": "autonomous", "error_category": "disk_pressure", **detail},
                    error=str(exc),
                    error_category="disk_pressure",
                    finished=True,
                )
                now = datetime.now(UTC).isoformat()
                blocked_message = f"Autonomous run blocked by disk pressure: {exc}"
                await context.append_message(
                    req.session_id,
                    ChatMessage(role="assistant", content=blocked_message, timestamp=now),
                )
                add_message(req.session_id, "assistant", blocked_message, tier_used="ORCHESTRATOR")
                yield _sse(
                    StreamEvent(
                        type="error",
                        agent="ORCHESTRATOR",
                        content=blocked_message,
                        data={"error_category": "disk_pressure", **detail},
                    )
                )
                yield _sse(StreamEvent(type="done"))
                return
            except Exception as exc:
                logger.warning(
                    "execute_autonomous failed for complex task, falling back to ReAct: %s", exc
                )
                # Fall through to single-agent path below

        elif (
            execution_mode is ExecutionMode.MISSION
            or (_advanced_force_autonomous and not fast_candidate)
        ) and event_bus is None:
            logger.warning(
                "Auto mode: complex task detected but event_bus is unavailable — "
                "falling back to single-agent ReAct (OrchestrationEngine disabled). | query=%.80s",
                req.message,
            )

        # Simple tasks or autonomous fallback: smart routing → single agent → ReAct loop
        try:
            decision = await _decide_route(req.message, llm_client)
            if execution_mode is ExecutionMode.CHAT:
                # Informational turns stay on the schema-free MICRO lane even
                # when the generic router sees a specialist keyword.
                decision = decision.model_copy(
                    update={
                        "primary_agent": "MICRO",
                        "secondary_agents": [],
                        "requires_web_search": False,
                        "routing_reason": "chat:validated-micro",
                    }
                )
            # Auto mode needs an agent with tool support. Upgrade lightweight picks.
            if (
                execution_mode is not ExecutionMode.CHAT
                and decision.primary_agent in ("MICRO", "DOCUMENTER")
                and not _is_fast_chat_turn(req.message)
            ):
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
            fast_chat_turn = _is_fast_chat_turn(req.message) and not _advanced_force_autonomous
            decision = decision.model_copy(
                update={
                    "routing_reason": f"auto:{decision.routing_reason}",
                    "thinking_mode": "fast" if fast_chat_turn else "iterative",
                    "context_needed": "low" if fast_chat_turn else "high",
                    "task_type": "question" if fast_chat_turn else "autonomous",
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
    elif mode in ("swarm", "auto_swarm") or _advanced_force_swarm:
        try:
            swarm_agents = getattr(req, "swarm_agents", []) or []
            swarm_strategy = getattr(req, "swarm_strategy", "adaptive") or "adaptive"

            if not swarm_agents:
                if mode == "auto_swarm" or _advanced_force_swarm:
                    # Auto swarm: let the orchestrator pick the team and the
                    # strategy adaptively from the objective itself.
                    swarm_agents = ["ARCHITECT", "CODER", "ANALYZER", "DEBUGGER", "DOCUMENTER"]
                else:
                    swarm_agents = ["ARCHITECT", "CODER", "ANALYZER"]

            # Live queue: the swarm pushes per-agent start/finish/progress
            # events here so the UI sees subagent activity as it happens
            # instead of a long silent wait until the swarm completes.
            live_queue: asyncio.Queue[dict] = asyncio.Queue()
            swarm = SwarmOrchestrator(
                llm_client=llm_client,
                registry=registry,
                event_bus=event_bus,
                max_agents=5,
                event_queue=live_queue,
            )

            yield _sse(StreamEvent(type="agent_started", agent="SWARM"))

            swarm_task = asyncio.create_task(
                swarm.execute_swarm(
                    objective=effective_message,
                    session_id=req.session_id,
                    agents=swarm_agents,
                    strategy=swarm_strategy,
                    project_path=project_path,
                    history=history,
                    max_iterations=mode_max_iterations,
                    enable_thinking=mode_enable_thinking,
                    autonomous=req.autonomous,
                )
            )

            # Drain live swarm events while the swarm runs.
            while True:
                if swarm_task.done() and live_queue.empty():
                    break
                try:
                    live_evt = await asyncio.wait_for(live_queue.get(), timeout=0.5)
                except TimeoutError:
                    continue
                try:
                    yield _sse(StreamEvent(**live_evt))
                except Exception:
                    logger.debug("Invalid live swarm event dropped: %s", live_evt)

            result = swarm_task.result()

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
                    mode=mode,
                    session_id=req.session_id,
                )

            add_message(req.session_id, "assistant", full, tier_used="SWARM", latency_ms=latency_ms)
            _checkpoint(
                status="completed",
                phase="swarm_completed",
                agent="SWARM",
                partial_output=full,
                checkpoint={"mode": "swarm", "agents": swarm_agents},
                finished=True,
            )

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
    if execution_mode is ExecutionMode.CHAT and not _advanced_command_mode:
        decision = decision.model_copy(
            update={
                "primary_agent": "MICRO",
                "secondary_agents": [],
                "requires_web_search": False,
                "routing_reason": "chat:validated-micro",
            }
        )
    decision = decision.model_copy(
        update={
            "mode": execution_mode,
            "run_id": run_context.run_id,
            "correlation_id": run_context.correlation_id,
            "provider": getattr(req, "provider", "") or "",
            "model": model_override or user_model,
            "reason": decision.reason or decision.routing_reason,
        }
    )

    # Tell the UI which agent is taking the request before model setup,
    # semantic memory, or fallback resolution. This prevents a silent gap
    # before the first provider token arrives.
    yield _sse(StreamEvent(type="agent_started", agent=decision.primary_agent))
    if mode_enable_thinking and not _is_fast_chat_turn(effective_message):
        yield _sse(
            StreamEvent(
                type="thinking",
                agent=decision.primary_agent,
                content=_user_facing_preamble(req.message),
            )
        )

    if project_path_defaulted:
        yield _sse(
            StreamEvent(
                type="progress",
                agent=decision.primary_agent,  # type: ignore[arg-type]
                content=f"Nenhum projeto selecionado; a usar diretório raiz: {project_path}",
                data={
                    "event": "project_defaulted",
                    "kind": "status",
                    "status": "success",
                },
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
    #
    # A pinned model only works if it is sent to the provider that actually
    # serves it: asking OpenCode Go for "anthropic/claude-sonnet-4" 404s. When
    # the caller pinned a model but no provider, resolve the owning provider
    # from the catalog.
    effective_provider = req.provider or ""
    if not effective_provider and model_override:
        try:
            from backend.llm.model_catalog import aggregate_models

            catalog = await aggregate_models()
            for entry in catalog.get("models", []):
                if entry.get("id") == model_override:
                    effective_provider = str(entry.get("provider") or "")
                    break
        except Exception:  # noqa: BLE001 - fall back to the default client
            logger.debug("Could not resolve provider for %s", model_override, exc_info=True)

    effective_client = llm_client
    if effective_provider and isinstance(llm_client, MultiLLMManager):
        effective_client = llm_client.providers.get(effective_provider) or llm_client
        if effective_client is llm_client:
            logger.warning(
                "Provider '%s' is not configured; using the default client for model '%s'",
                effective_provider,
                model_override or "(tier)",
            )

    # A concrete provider selection is an assertion, not a hint. Never send a
    # request to the default provider when the selected provider is absent;
    # that makes the UI lie about which service handled the message.
    requested_client_provider = getattr(effective_client, "provider_name", "")
    provider_missing = bool(req.provider) and (
        effective_client is llm_client and requested_client_provider != req.provider
    )
    if provider_missing:
        get_structured_logger().warning(
            "Requested provider is not configured",
            session_id=req.session_id,
            source="chat_routing",
            extra={
                "event": "chat_provider_unavailable",
                "requested_provider": req.provider,
                "model": model_override or "",
            },
        )
        _checkpoint(
            status="failed",
            phase="provider_error",
            error=f"Provider '{req.provider}' is not configured",
            error_category=ErrorCategory.PROVIDER.value,
            checkpoint={
                "reason": "provider_unavailable",
                "provider": req.provider,
                "model": model_override or user_model or None,
            },
            finished=True,
        )
        yield _sse(
            StreamEvent(
                type="error",
                content=(
                    f"Provider '{req.provider}' não está configurado/ativo; "
                    "o pedido foi interrompido para não trocar silenciosamente de provider."
                ),
                data={
                    "error_category": ErrorCategory.PROVIDER.value,
                    "run_id": run_context.run_id,
                    "correlation_id": run_context.correlation_id,
                    "provider": req.provider,
                    "model": model_override or user_model or None,
                },
            )
        )
        yield _sse(StreamEvent(type="done", data=run_context.to_dict()))
        return

    # Audit-only routing evidence. Keep provider/model identifiers, never
    # prompts, headers, URLs or credentials.
    get_structured_logger().info(
        "Chat provider resolved",
        session_id=req.session_id,
        source="chat_routing",
        extra={
            "event": "chat_provider_resolved",
            "requested_provider": req.provider or "",
            "effective_provider": effective_provider,
            "client": effective_client.__class__.__name__,
            "model": model_override or "",
        },
    )

    # Explicit advanced commands select a truthful existing specialist.  A
    # passive profile intentionally leaves the smart router in control and only
    # contributes policies, avoiding a hidden agent switch on every message.
    if _advanced_command_mode and _advanced_preferred_agent and decision is not None:
        decision = decision.model_copy(
            update={
                "primary_agent": _advanced_preferred_agent,
                "routing_reason": f"advanced-command:{_advanced_command_mode}",
                "thinking_mode": "iterative",
                "context_needed": "high",
            }
        )

    # 3. Resolve agent + build per-agent request factory.
    # Compose the system-prompt addon for this mode. Include routing metadata so
    # the primary agent knows which secondary agents the router considered useful.
    enriched_addon = mode_addon
    strength_guidance = {
        "low": (
            "Use a fast, direct approach. Verify the essential facts and keep "
            "the public approach summary to one short sentence."
        ),
        "medium": (
            "Use balanced reasoning. Check the main alternatives and surface "
            "only a concise user-facing approach summary."
        ),
        "high": (
            "Use deeper analysis for difficult decisions, verify assumptions, "
            "and surface only a concise user-facing approach summary, never private chain-of-thought."
        ),
    }
    fast_chat_turn = execution_mode is ExecutionMode.CHAT or mode in {"ask", "fast"} or (
        mode in {"auto", "agent"}
        and not _advanced_command_mode
        and _is_fast_chat_turn(effective_message)
    )
    if req.thinking_strength in strength_guidance and not fast_chat_turn:
        enriched_addon += f"\n\n[REASONING DEPTH]\n{strength_guidance[req.thinking_strength]}"
    if fast_chat_turn:
        enriched_addon += (
            "\n\n[FAST CHAT LANE] Answer directly in one concise response. "
            "Do not use tools, planning, thinking markers, or subagents."
        )
    if decision is not None:
        routing_info = (
            f"\n\n[ROUTING INFO] Primary agent: {decision.primary_agent}. "
            f"Reason: {decision.routing_reason}. "
            f"Confidence: {decision.routing_confidence:.2f}. "
            f"Secondary agents suggested: {', '.join(decision.secondary_agents) or 'none'}."
        )
        enriched_addon += routing_info

    # Captured from the agent immediately before the provider call. This is
    # more precise than the routing tier and lets persisted metrics rank real
    # model ids even when the user leaves model selection on Auto.
    resolved_model_id = model_override or ""

    def make_invocation(agent_name: str):
        async def invoke() -> AsyncIterator[str]:
            nonlocal resolved_model_id
            agent = resolve(registry, agent_name)  # type: ignore[arg-type]
            agent_context: dict[str, Any] = {"run_context": run_context}
            if project_path:
                agent_context["project_path"] = project_path
            if project_memory and execution_mode is not ExecutionMode.CHAT:
                agent_context["_project_memory"] = project_memory
            if enriched_addon:
                agent_context["_system_addon"] = enriched_addon
            if fast_chat_turn:
                # CHAT is a direct, schema-free lane: no tools, memory,
                # planning, subagents, or A2A consultations.
                agent_context["_fast_chat_lane"] = True
                agent_context["_allowed_tools"] = ()
            elif execution_mode is ExecutionMode.ASSISTED:
                agent_context["_assisted_tool_budget"] = 3
                agent_context["_allowed_tools"] = (
                    "read_file", "search_in_files", "run_tests", "type_check"
                )
                agent_context["_tool_evidence_requirement"] = (
                    _direct_runtime_evidence_requirement(effective_message) or "substantive"
                )
            if _advanced_profile and execution_mode is not ExecutionMode.CHAT:
                agent_context["_advanced_profile"] = {
                    key: value
                    for key, value in _advanced_profile.items()
                    if key != "addon"
                }
            if model_override:
                # Agents are shared singletons, so the pinned model travels with
                # the request rather than being set on the instance.
                agent_context["_model_override"] = model_override

            agent_req = AgentRequest(
                session_id=req.session_id,
                query=effective_message,
                client=effective_client,
                history=history,
                project_path=project_path,
                context=agent_context,
                max_iterations=(
                    2
                    if execution_mode is ExecutionMode.CHAT
                    else 3
                    if execution_mode is ExecutionMode.ASSISTED
                    else mode_max_iterations
                ),
                enable_thinking=(
                    mode_enable_thinking
                    and execution_mode is not ExecutionMode.CHAT
                ),
                autonomous=bool(
                    req.autonomous
                    and execution_mode in {ExecutionMode.ASSISTED, ExecutionMode.MISSION}
                ),
            )
            resolved_model_id = agent.resolve_model_id(agent_req)
            return agent.run(agent_req)

        return invoke

    # CHAT and ASSISTED deliberately invoke one registry agent only.  Mission
    # is the sole lane allowed to use the autonomous fallback chain.
    try:
        if execution_mode in {ExecutionMode.CHAT, ExecutionMode.ASSISTED}:
            token_stream = await make_invocation(decision.primary_agent)()
            outcome = FallbackOutcome(
                used_agent=decision.primary_agent,
                attempts=1,
                notified_dashboard=False,
                reason="single-agent-lane",
            )
        else:
            outcome, token_stream = await invoke_with_fallback(
                decision.primary_agent,
                lambda name: make_invocation(name)(),
                stream_start_timeout=None,
            )
    except Exception as exc:
        logger.exception("All fallbacks exhausted: %s", exc)
        detail = str(exc).strip().replace("\n", " ")[:500]
        err_text = (
            "O provedor LLM não conseguiu responder. "
            f"Causa técnica: {detail or 'erro upstream desconhecido'}. "
            "Para respostas reais, usa uma chave/provider com quota disponível ou liga um Ollama local."
        )
        yield _sse(
            StreamEvent(
                type="error",
                content=err_text,
                data={
                    "error_category": ErrorCategory.PROVIDER.value,
                    "run_id": run_context.run_id,
                    "correlation_id": run_context.correlation_id,
                    "provider": getattr(req, "provider", "") or None,
                    "model": model_override or user_model or None,
                    "message": detail or "provider unavailable",
                },
            )
        )
        await _persist_terminal_error(
            err_text,
            agent=str(outcome.used_agent),
            checkpoint={"reason": "provider_unavailable"},
        )
        return

    if outcome.used_agent != decision.primary_agent:
        yield _sse(StreamEvent(type="agent_started", agent=outcome.used_agent))  # type: ignore[arg-type]

    # 5. Stream tokens and accumulate full response for history.
    parts: list[str] = []
    thinking_parts: list[str] = []
    tool_names: list[str] = []
    tool_context_tokens = 0
    mcp_context_tokens = 0
    last_checkpoint_at = 0.0
    # No product cap on a streamed answer. Set this env var only when a
    # deployment needs an explicit resource budget.
    try:
        MAX_RESPONSE_LENGTH = max(0, int(os.environ.get("NEXUS_MAX_RESPONSE_LENGTH", "0")))
    except ValueError:
        MAX_RESPONSE_LENGTH = 0
    response_parser = _IncrementalResponseParser(str(outcome.used_agent))
    model_for_counting = outcome.used_agent
    stream_aborted = False
    token_iter = token_stream.__aiter__()
    try:
        while True:
            try:
                next_token = token_iter.__anext__()
                token = (
                    await asyncio.wait_for(next_token, timeout=TOKEN_TIMEOUT_SECONDS)
                    if TOKEN_TIMEOUT_SECONDS is not None
                    else await next_token
                )
            except StopAsyncIteration:
                break
            except TimeoutError:
                stream_aborted = True
                logger.warning(
                    "Token streaming timeout after %ds", TOKEN_TIMEOUT_SECONDS
                )
                # Close the agent stream so a wedged tool call inside the
                # ReAct generator is cancelled instead of running orphaned in
                # the background after the client already saw the error.
                try:
                    aclose = getattr(token_stream, "aclose", None)
                    if aclose is not None:
                        await aclose()
                except Exception:
                    logger.debug("Failed to close timed-out token stream", exc_info=True)
                yield _sse(
                    StreamEvent(
                        type="error",
                        content=f"Stream timeout ({TOKEN_TIMEOUT_SECONDS}s). Try again.",
                        agent=outcome.used_agent,
                    )
                )
                break

            # Parse provider chunks incrementally. Thinking events are emitted
            # while the provider is still generating, not after </think>.
            for evt in response_parser.feed(token):
                if evt.type in {"error", "execution_error"}:
                    error_event = evt.model_copy(
                        update={
                            "data": {
                                **evt.data,
                                "error_category": ErrorCategory.PROVIDER.value,
                                "run_id": run_context.run_id,
                                "correlation_id": run_context.correlation_id,
                                "provider": getattr(req, "provider", "") or None,
                                "model": model_override or user_model or None,
                            }
                        }
                    )
                    yield _sse(error_event)
                    await _persist_terminal_error(
                        evt.content or "Provider stream error",
                        agent=str(outcome.used_agent),
                        partial_output="".join(parts),
                        checkpoint={"last_event": evt.type, "tools": tool_names[-20:]},
                    )
                    yield _sse(StreamEvent(type="done", data=run_context.to_dict()))
                    return
                if evt.type == "token":
                    parts.append(evt.content or "")
                elif evt.type == "thinking" and evt.content:
                    thinking_parts.append(evt.content)
                    try:
                        from backend.orchestrator.routes.thinking import publish_thought

                        publish_thought(
                            agent=outcome.used_agent,
                            phase="thinking",
                            text=evt.content,
                            model=None,
                        )
                    except Exception:
                        pass
                elif evt.type in {"tool_call", "tool_result", "tool_error"}:
                    tool_name = str(evt.tool_name or "tool")
                    if tool_name not in tool_names:
                        tool_names.append(tool_name)
                    payload = evt.tool_args if evt.type == "tool_call" else evt.tool_result
                    tool_tokens = count_tokens(
                        json.dumps(payload, ensure_ascii=False, default=str),
                        model_for_counting,
                    )
                    tool_context_tokens += tool_tokens
                    if tool_name.lower().startswith("mcp") or "mcp" in tool_name.lower():
                        mcp_context_tokens += tool_tokens
                yield _sse(evt)
                if time.time() - last_checkpoint_at >= 5 or evt.type in {
                    "tool_call",
                    "tool_result",
                    "tool_error",
                }:
                    last_checkpoint_at = time.time()
                    _checkpoint(
                        phase="streaming",
                        agent=str(outcome.used_agent),
                        partial_output="".join(parts),
                        checkpoint={
                            "events": len(parts) + len(thinking_parts),
                            "last_event": evt.type,
                            "tools": tool_names[-20:],
                        },
                    )
            # Prevent unbounded memory growth
            if MAX_RESPONSE_LENGTH > 0 and sum(len(p) for p in parts) > MAX_RESPONSE_LENGTH:
                logger.warning("Response exceeded max length, truncating")
                break
        # Flush any incomplete tag/content at end of stream.
        for evt in response_parser.flush():
            if evt.type == "token":
                parts.append(evt.content or "")
            elif evt.type == "thinking" and evt.content:
                thinking_parts.append(evt.content)
            yield _sse(evt)
    except asyncio.CancelledError:
        _checkpoint(
            status="cancelled",
            phase="cancelled",
            agent=str(outcome.used_agent),
            partial_output="".join(parts),
            checkpoint={"tools": tool_names[-20:]},
            error="Client or server cancelled the stream",
            finished=True,
        )
        raise
    except Exception as exc:
        logger.exception("Stream interrupted: %s", exc)
        err_text = f"Stream interrupted: {exc}"
        yield _sse(
            StreamEvent(
                type="error",
                content="Stream interrupted. Please try again.",
                data={
                    "error_category": ErrorCategory.PROVIDER.value,
                    "run_id": run_context.run_id,
                    "correlation_id": run_context.correlation_id,
                    "provider": getattr(req, "provider", "") or None,
                    "model": model_override or user_model or None,
                    "message": str(exc)[:500],
                },
            )
        )
        yield _sse(StreamEvent(type="done", data=run_context.to_dict()))
        # Persist the user message + an explicit error assistant message so
        # the error stays visible after a refresh (otherwise it would be
        # silently lost when getSessionHistory loads from the DB).
        try:
            err_now = datetime.now(UTC).isoformat()
            await context.append_message(
                req.session_id, ChatMessage(role="user", content=req.message, timestamp=err_now)
            )
            await context.append_message(
                req.session_id,
                ChatMessage(role="assistant", content=f"⚠ {err_text}", timestamp=err_now),
            )
            add_message(req.session_id, "assistant", f"⚠ {err_text}")
            _checkpoint(
                status="interrupted",
                phase="stream_error",
                agent=str(outcome.used_agent),
                partial_output="".join(parts),
                error=err_text,
                error_category=ErrorCategory.PROVIDER.value,
                checkpoint={"tools": tool_names[-20:]},
                finished=True,
            )
        except Exception as persist_exc:  # pragma: no cover - best-effort
            logger.debug("Failed to persist error to DB: %s", persist_exc)
        return

    # 6. Persist exchange.
    full = "".join(parts)
    if MAX_RESPONSE_LENGTH > 0:
        full = full[:MAX_RESPONSE_LENGTH]
    if not full.strip():
        empty_response_error = (
            "O provider terminou a execução sem conteúdo visível. "
            "A resposta não foi marcada como concluída; verifica o provider, "
            "a quota e os eventos de thinking antes de tentar novamente."
        )
        await _persist_terminal_error(
            empty_response_error,
            agent=str(outcome.used_agent),
            phase="empty_provider_response",
            partial_output="".join(thinking_parts),
            checkpoint={
                "reason": "empty_visible_response",
                "thinking_tokens": count_tokens(
                    "".join(thinking_parts), model_for_counting
                ),
                "tools": tool_names[-20:],
            },
        )
        yield _sse(
            StreamEvent(
                type="error",
                agent=outcome.used_agent,
                content=empty_response_error,
                data={
                    "error_category": ErrorCategory.PROVIDER.value,
                    "run_id": run_context.run_id,
                    "correlation_id": run_context.correlation_id,
                    "reason": "empty_visible_response",
                },
            )
        )
        yield _sse(StreamEvent(type="done", data=run_context.to_dict()))
        return
    def _message_content(message: Any) -> str:
        if isinstance(message, dict):
            return str(message.get("content") or "")
        return str(getattr(message, "content", "") or "")

    prompt_tokens = count_tokens(req.message, model_for_counting)
    history_tokens = sum(count_tokens(_message_content(message), model_for_counting) for message in history)
    reasoning_tokens = sum(count_tokens(text, model_for_counting) for text in thinking_parts)
    output_tokens = count_tokens(full, model_for_counting) + reasoning_tokens
    total_tokens = prompt_tokens + history_tokens + output_tokens
    context_total_tokens = (
        prompt_tokens
        + history_tokens
        + reasoning_tokens
        + count_tokens(full, model_for_counting)
        + (count_tokens(project_path, model_for_counting) if project_path else 0)
        + tool_context_tokens
    )
    usage_data = {
        "input_tokens": prompt_tokens + history_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "total_tokens": total_tokens,
        "source": "estimated",
        "cache_read_tokens": None,
        "cache_write_tokens": None,
        "cache_status": "not_reported",
        "context": {
            "prompt": prompt_tokens,
            "history": history_tokens,
            "reasoning": reasoning_tokens,
            "response": count_tokens(full, model_for_counting),
            "project": count_tokens(project_path, model_for_counting) if project_path else 0,
            "tools": tool_context_tokens,
            "mcp": mcp_context_tokens,
            "total": context_total_tokens,
        },
    }
    yield _sse(StreamEvent(type="metric", agent=outcome.used_agent, data={"usage": usage_data}))
    now = datetime.now(UTC).isoformat()
    await context.append_message(
        req.session_id, ChatMessage(role="user", content=req.message, timestamp=now)
    )
    await context.append_message(
        req.session_id, ChatMessage(role="assistant", content=full, timestamp=now)
    )
    latency_ms = int((time.time() - started_at) * 1000)

    _checkpoint(
        status="interrupted" if stream_aborted else "completed",
        phase="stream_timeout" if stream_aborted else "completed",
        agent=str(outcome.used_agent),
        partial_output=full,
        checkpoint={"tools": tool_names[-20:]},
        usage=usage_data,
        finished=True,
    )
    add_message(
        req.session_id,
        "assistant",
        full,
        tier_used=decision.primary_agent,
        model_used=resolved_model_id or req.model or str(outcome.used_agent),
        tokens_in=history_tokens,
        tokens_out=output_tokens,
        latency_ms=latency_ms,
    )

    # 7. Store in semantic memory for future recall (best-effort, non-blocking).
    try:
        from backend.knowledge.memory import get_memory_store

        mem_store = get_memory_store()
        if full.strip() and not fast_chat_turn:
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

    # Keep the per-project bootstrap useful over time without turning it into
    # a transcript.  The topic is reduced to inert keywords by AgentBase and
    # only a bounded, verified completion marker is persisted.
    if _should_persist_project_memory(execution_mode, project_path):
        try:
            from backend.agents.base import AgentBase
            from backend.knowledge.project_memory import record_verified_session

            record_verified_session(
                project_path,
                session_id=req.session_id,
                status="completed" if not stream_aborted else "interrupted",
                topic=AgentBase._memory_topic(req.message),
                evidence=(f"agent={outcome.used_agent}; tools={','.join(tool_names[-8:])}"),
            )
        except Exception as exc:
            logger.debug("Project memory update failed (non-critical): %s", exc)

    yield _sse(StreamEvent(type="agent_finished", agent=outcome.used_agent))  # type: ignore[arg-type]
    yield _sse(StreamEvent(type="done"))


# Small helper so JSON marshaling can be tested without spinning up FastAPI.
def decision_to_json(d: RoutingDecision) -> str:  # pragma: no cover - trivial
    return json.dumps(d.model_dump(), separators=(",", ":"))
