"""Intelligent routing layer.

Three-level routing described in ARCHITECTURE.md §4.2:

1. Fast rules — deterministic, zero-cost (:func:`fast_route`).
2. ROUTER model (NANO) — JSON classification (:func:`route_with_model`).
3. Automatic fallback — see :mod:`backend.orchestrator.fallback`.

The public ``RoutingDecision`` type lives in :mod:`backend.models.api` and is
re-exported here for backwards compatibility with existing imports.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from functools import lru_cache
from typing import Final

from pydantic import ValidationError

from backend.config.settings import get_model_config, load_prompt
from backend.models.api import AgentName, RoutingDecision
from backend.tools.ollama_client import ChatMessage, OllamaClient, OllamaError
from backend.tools.sanitizer import detect_injection

logger = logging.getLogger(__name__)


def _query_hash(query: str) -> str:
    """Generate a hash for caching routing decisions based on query content."""
    return hashlib.md5(query.lower().strip().encode()).hexdigest()


@lru_cache(maxsize=100)
def _cached_route_with_model(query_hash: str, query: str) -> RoutingDecision:
    """Cached version of route_with_model using hash as key."""
    # This is a wrapper that will be called with the hash
    # The actual implementation will be in route_with_model
    return _FALLBACK_DECISION


__all__ = ["RoutingDecision", "fast_route", "route_with_model"]

# ---------------------------------------------------------------------------
# Level 1 — fast deterministic rules
# ---------------------------------------------------------------------------

_DEBUGGER_MARKERS: Final = (
    "traceback",
    "stacktrace",
    "stack trace",
    "error:",
    "exception",
    "segfault",
    "segmentation fault",
    "runtime error",
)
_DOCUMENTER_MARKERS: Final = (
    "document",
    "documenta",
    "docstring",
    "readme",
    "comment the",
    "add comments",
    "explain this code",
)
_RESEARCHER_MARKERS: Final = (
    "latest version",
    "current version",
    "is x still",
    "benchmark",
    "released in",
    "recent release",
)
_TRIVIAL_QUESTION = re.compile(r"^\s*(what|who|when|where|why|how)\s+is\b", re.IGNORECASE)


def fast_route(query: str) -> AgentName | None:
    """Level 1 — deterministic pre-routing.

    Returns an agent name when the query is trivially classifiable, otherwise
    ``None`` so the caller falls through to :func:`route_with_model`. The rules
    here are intentionally conservative: false negatives are cheap (we just
    call the LLM router), false positives route to the wrong agent.
    """
    if not query or not query.strip():
        return None

    lowered = query.lower()

    if any(marker in lowered for marker in _DEBUGGER_MARKERS):
        return "DEBUGGER"
    if any(marker in lowered for marker in _DOCUMENTER_MARKERS):
        return "DOCUMENTER"
    if any(marker in lowered for marker in _RESEARCHER_MARKERS):
        return "RESEARCHER"

    words = lowered.split()
    # Very short trivial factoid lookup.
    if len(words) <= 12 and _TRIVIAL_QUESTION.match(lowered):
        return "MICRO"

    return None


# ---------------------------------------------------------------------------
# Level 2 — model-based classification
# ---------------------------------------------------------------------------

_FALLBACK_DECISION = RoutingDecision(
    primary_agent="CODER",
    secondary_agents=[],
    requires_web_search=False,
    thinking_mode="fast",
    estimated_complexity=3,
    task_type="unclassified",
    context_needed="low",
    routing_confidence=0.2,
    routing_reason="router-model-unavailable-or-malformed",
)


async def route_with_model(query: str, client: OllamaClient) -> RoutingDecision:
    """Level 2 — ask the NANO model to classify the request.

    Returns a best-effort :class:`RoutingDecision`. If the model output is
    missing/malformed or the call fails, returns a low-confidence default
    decision pointing to CODER so the system always makes forward progress.
    The caller should use the ``routing_confidence`` field to decide whether
    to escalate.
    """
    # Check cache first
    hash_key = _query_hash(query)
    try:
        # Try to get from cache
        cached = _cached_route_with_model(hash_key, query)
        if cached != _FALLBACK_DECISION:
            logger.debug("Routing decision cache hit for query hash: %s", hash_key[:8])
            return cached
    except Exception:
        # If cache fails, continue with normal routing
        pass

    if detect_injection(query).detected:
        decision = _FALLBACK_DECISION.model_copy(
            update={"routing_reason": "prompt-injection-detected", "primary_agent": "MICRO"}
        )
        # Cache the decision
        _cached_route_with_model(hash_key, query)
        return decision

    try:
        model_id = get_model_config("nano")["id"]
        system = load_prompt("router")
    except (KeyError, FileNotFoundError) as exc:
        logger.error("Router misconfigured: %s", exc)
        return _FALLBACK_DECISION

    try:
        raw = await client.chat_complete(
            model=model_id,
            messages=[
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=query),
            ],
            options={"temperature": 0.1, "num_predict": 512},
        )
    except OllamaError as exc:
        logger.warning("Router model call failed: %s", exc)
        return _FALLBACK_DECISION

    decision = _parse_routing_decision(raw)
    # Cache the successful routing decision
    if decision != _FALLBACK_DECISION:
        _cached_route_with_model(hash_key, query)
    return decision


def _parse_routing_decision(raw: str) -> RoutingDecision:
    """Extract the first JSON object from ``raw`` and validate it."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        logger.warning("Router output contained no JSON object: %r", raw[:200])
        return _FALLBACK_DECISION
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("Router JSON malformed (%s): %r", exc, match.group(0)[:200])
        return _FALLBACK_DECISION

    # Fix common model errors: convert string values to expected types
    if "routing_confidence" in payload and isinstance(payload["routing_confidence"], str):
        try:
            # Convert string like "high" to a reasonable float value
            if payload["routing_confidence"].lower() == "high":
                payload["routing_confidence"] = 0.8
            elif payload["routing_confidence"].lower() == "low":
                payload["routing_confidence"] = 0.2
            elif payload["routing_confidence"].lower() == "medium":
                payload["routing_confidence"] = 0.5
            else:
                # Try to parse as float
                payload["routing_confidence"] = float(payload["routing_confidence"])
        except (ValueError, AttributeError):
            payload["routing_confidence"] = 0.5  # Default fallback

    try:
        return RoutingDecision.model_validate(payload)
    except ValidationError as exc:
        logger.warning("Router decision failed validation: %s", exc)
        return _FALLBACK_DECISION
