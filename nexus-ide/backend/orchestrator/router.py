"""Intelligent routing layer.

Three-level routing described in ARCHITECTURE.md §4.2:

1. Fast rules - deterministic, zero-cost (:func:`fast_route`).
2. ROUTER model (NANO) - JSON classification (:func:`route_with_model`).
3. Automatic fallback - see :mod:`backend.orchestrator.fallback`.

The public ``RoutingDecision`` type lives in :mod:`backend.models.api` and is
re-exported here for backwards compatibility with existing imports.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import re
import time
from typing import Final

from pydantic import ValidationError

from backend.config.settings import get_model_config, load_prompt
from backend.models.api import AgentName, RoutingDecision
from backend.tools.ollama_client import ChatMessage, OllamaError
from typing import Any
from backend.tools.sanitizer import detect_injection

logger = logging.getLogger(__name__)


def _query_hash(query: str) -> str:
    """Generate a hash for caching routing decisions based on query content."""
    return hashlib.md5(query.lower().strip().encode()).hexdigest()


# In-memory cache for routing decisions (keyed by query hash).
# Each entry stores (decision, timestamp) for TTL-based expiry.
_routing_cache: dict[str, tuple[RoutingDecision, float]] = {}
_ROUTING_CACHE_TTL = 300.0  # 5 minutes
_ROUTING_CACHE_MAX = 1000


def _get_cached_decision(query_hash: str) -> RoutingDecision | None:
    """Return a cached routing decision if not expired, else None."""
    entry = _routing_cache.get(query_hash)
    if entry is None:
        return None
    decision, ts = entry
    if time.time() - ts > _ROUTING_CACHE_TTL:
        del _routing_cache[query_hash]
        return None
    return decision


def _store_cached_decision(query_hash: str, decision: RoutingDecision) -> None:
    """Store a routing decision in cache with TTL timestamp."""
    if len(_routing_cache) >= _ROUTING_CACHE_MAX:
        # Evict oldest entries (FIFO) and expired entries
        now = time.time()
        expired = [k for k, (_, ts) in _routing_cache.items() if now - ts > _ROUTING_CACHE_TTL]
        for k in expired:
            del _routing_cache[k]
        if len(_routing_cache) >= _ROUTING_CACHE_MAX:
            keys_to_remove = list(_routing_cache.keys())[:100]
            for k in keys_to_remove:
                del _routing_cache[k]
    _routing_cache[query_hash] = (decision, time.time())


__all__ = ["RoutingDecision", "fast_route", "route_with_model", "warm_routing_cache"]

# Common queries used to warm the routing cache at startup.
_COMMON_QUERIES: dict[str, RoutingDecision] = {
    "what is python": RoutingDecision(
        primary_agent="MICRO",
        secondary_agents=[],
        requires_web_search=False,
        thinking_mode="fast",
        estimated_complexity=1,
        task_type="question",
        context_needed="low",
        routing_confidence=0.95,
        routing_reason="common-trivial-question",
    ),
    "write a function": RoutingDecision(
        primary_agent="CODER",
        secondary_agents=[],
        requires_web_search=False,
        thinking_mode="fast",
        estimated_complexity=4,
        task_type="code_generation",
        context_needed="low",
        routing_confidence=0.9,
        routing_reason="common-code-request",
    ),
    "fix the bug": RoutingDecision(
        primary_agent="DEBUGGER",
        secondary_agents=[],
        requires_web_search=False,
        thinking_mode="iterative",
        estimated_complexity=5,
        task_type="debugging",
        context_needed="high",
        routing_confidence=0.9,
        routing_reason="common-debug-request",
    ),
    "optimize performance": RoutingDecision(
        primary_agent="OPTIMIZER",
        secondary_agents=[],
        requires_web_search=False,
        thinking_mode="deep",
        estimated_complexity=6,
        task_type="optimization",
        context_needed="high",
        routing_confidence=0.9,
        routing_reason="common-optimization-request",
    ),
    "design the architecture": RoutingDecision(
        primary_agent="ARCHITECT",
        secondary_agents=[],
        requires_web_search=False,
        thinking_mode="deep",
        estimated_complexity=8,
        task_type="design",
        context_needed="high",
        routing_confidence=0.9,
        routing_reason="common-architecture-request",
    ),
}


def warm_routing_cache() -> None:
    """Pre-populate the routing cache with common queries at startup."""
    for query, decision in _COMMON_QUERIES.items():
        h = _query_hash(query)
        _store_cached_decision(h, decision)
    logger.info("Routing cache warmed with %d common queries", len(_COMMON_QUERIES))

# ---------------------------------------------------------------------------
# Level 1 - fast deterministic rules
# ---------------------------------------------------------------------------

_DEBUGGER_MARKERS: Final = (
    "traceback",
    "stacktrace",
    "stack trace",
    "error:",
    "error in",
    "typeerror",
    "valueerror",
    "keyerror",
    "indexerror",
    "attributeerror",
    "importerror",
    "filenotfounderror",
    "zerodivisionerror",
    "overflowerror",
    "syntaxerror",
    "nameerror",
    "exception",
    "segfault",
    "segmentation fault",
    "runtime error",
    "not working",
    "broken",
    "bug in",
    "fix the",
    "fix this",
    "debug",
    "crash",
    "failing",
    "depurar",
    "corrigir o erro",
    "erro no",
    "falha no",
)
_CODER_MARKERS: Final = (
    "write a function",
    "write a class",
    "create a function",
    "create a class",
    "implement",
    "refactor",
    "build a",
    "add a feature",
    "write code",
    "write a script",
    "write a test",
    "code this",
    "program a",
    "develop a",
    "scaffold",
    "generate code",
    "def ",
    "function that",
    "class that",
    "api endpoint",
    "rest api",
    "login system",
    "authentication",
    "web scraper",
    "cli tool",
    "criar uma função",
    "criar uma classe",
    "implementar",
    "construir",
    "desenvolver",
    "gerar código",
    "escrever código",
)
_ARCHITECT_MARKERS: Final = (
    "design the",
    "design a",
    "architect",
    "architecture",
    "plan the",
    "plan a",
    "structure the",
    "structure a",
    "how should i",
    "what should i",
    "system design",
    "database schema",
    "microservices",
    "tech stack",
    "project structure",
    "api design",
    "projetar",
    "arquitetar",
    "planejar",
    "estruturar",
    "esquema do banco",
)
_REVIEWER_MARKERS: Final = (
    "peer review",
    "review code",
    "review this pr",
    "review this pull request",
    "code review this",
    "review my code",
    "review the implementation",
    "review the changes",
    "review pr",
    "pr review",
    "pull request review",
    "review the module",
    "review the file",
    "review for bugs",
    "review for security",
    "security review",
    "performance review",
    "style review",
    "lint review",
    "quality review",
    "revisar codigo",
    "revisar código",
    "revisar implementacao",
    "revisar implementação",
    "revisar pr",
    "revisao de codigo",
    "revisão de código",
    "revisao de seguranca",
    "revisão de segurança",
    "analise de qualidade",
    "análise de qualidade",
)
_ANALYZER_MARKERS: Final = (
    "analyze",
    "analyse",
    "review the",
    "review this",
    "audit",
    "security check",
    "code review",
    "find vulnerabilities",
    "assess",
    "evaluate",
    "is this secure",
    "is this correct",
    "analisar",
    "revisar",
    "auditar",
    "avaliar",
)
_OPTIMIZER_MARKERS: Final = (
    "optimize",
    "optimise",
    "improve performance",
    "speed up",
    "make faster",
    "reduce memory",
    "make more efficient",
    "slow query",
    "bottleneck",
    "profiling",
    "otimizar",
    "melhorar performance",
    "acelerar",
    "reduzir memória",
)
_REFACTOR_PERF_MARKERS: Final = (
    "refactor performance",
    "performance refactor",
    "profile code",
    "cache optimization",
    "memoize",
    "vectorize",
    "async optimization",
    "parallelize",
    "execution time",
    "memory usage",
    "benchmark",
    "hot path",
)
_REFACTOR_CLEAN_MARKERS: Final = (
    "clean code",
    "clean up",
    "cleanup",
    "code cleanup",
    "refactor clean",
    "solid principles",
    "dry violation",
    "remove duplication",
    "improve naming",
    "add type hints",
    "cognitive complexity",
    "pep8",
    "style guide",
    "linting",
    "format code",
)
_BUG_HUNTER_STATIC_MARKERS: Final = (
    "static analysis",
    "lint",
    "linter",
    "pylint",
    "mypy",
    "bandit",
    "ruff",
    "code smell",
    "anti-pattern",
    "cyclomatic complexity",
    "security audit",
    "vulnerability scan",
    "find vulnerabilities",
    "sql injection",
    "xss",
    "path traversal",
    "scan code",
    "analise estatica",
    "analise estática",
    "vulnerabilidade",
    "auditoria de seguranca",
)
_BUG_HUNTER_RUNTIME_MARKERS: Final = (
    "runtime error",
    "runtime bug",
    "test failure",
    "fuzz test",
    "fuzzing",
    "edge case",
    "stress test",
    "malformed input",
    "api test",
    "integration test",
    "e2e bug",
    "memory leak",
    "race condition",
    "stack trace",
    "exception handling",
    "reproduce bug",
    "runtime crash",
    "erro em tempo de execucao",
    "teste de stress",
)
_TEST_RUNNER_UNIT_MARKERS: Final = (
    "unit test",
    "write unit tests",
    "create unit tests",
    "pytest",
    "unittest",
    "test function",
    "test class",
    "mock test",
    "fixture",
    "parametrize",
    "assert equal",
    "test coverage",
    "teste unitario",
    "teste unitário",
    "escrever testes",
)
_TEST_RUNNER_E2E_MARKERS: Final = (
    "end to end test",
    "e2e test",
    "integration test",
    "selenium",
    "playwright",
    "cypress",
    "automation test",
    "browser test",
    "ui test",
    "workflow test",
    "teste e2e",
    "teste de integracao",
    "teste de integração",
)
_DOCUMENTER_MARKERS: Final = (
    "document",
    "documenta",
    "docstring",
    "readme",
    "comment the",
    "add comments",
    "explain this code",
    "write docs",
    "api documentation",
    "changelog",
    "documentar",
    "escrever documentação",
)
_RESEARCHER_MARKERS: Final = (
    "latest version",
    "current version",
    "is x still",
    "benchmark",
    "released in",
    "recent release",
)
_RESEARCHER_WEB_MARKERS: Final = (
    "deep research",
    "comprehensive research",
    "research report",
    "literature review",
    "market analysis",
    "competitive analysis",
    "survey of",
    "state of the art",
    "current state of",
    "latest developments in",
    "recent advances",
    "what does the research say",
    "find all sources",
    "cross-reference",
    "validate this claim",
    "fact check",
)
_WEB_SEARCH_MARKERS: Final = (
    "search the web",
    "search online",
    "look up online",
    "google",
    "pesquisar na web",
    "buscar online",
    "latest news",
    "current status of",
    "find online",
    "search for",
    "look up",
    "what is the latest",
    "what are the latest",
)
_TRIVIAL_QUESTION = re.compile(r"^\s*(what|who|when|where|why|how)\s+is\b", re.IGNORECASE)


@functools.lru_cache(maxsize=1000)
def _fast_route_cached(normalized_query: str) -> AgentName | None:
    """Cached inner implementation - operates on pre-normalized query."""
    lowered = normalized_query

    # 1. DEBUGGER - error/debug patterns (most specific, check first)
    if any(marker in lowered for marker in _DEBUGGER_MARKERS):
        return "DEBUGGER"

    # 1b. BUG_HUNTER_RUNTIME - runtime testing and reproduction patterns
    if any(marker in lowered for marker in _BUG_HUNTER_RUNTIME_MARKERS):
        return "BUG_HUNTER_RUNTIME"

    # 2. ARCHITECT - design/planning patterns
    if any(marker in lowered for marker in _ARCHITECT_MARKERS):
        return "ARCHITECT"

    # 3. REVIEWER - peer code review patterns (more specific than generic analyzer)
    if any(marker in lowered for marker in _REVIEWER_MARKERS):
        return "REVIEWER"

    # 3a. ANALYZER - review/audit patterns
    if any(marker in lowered for marker in _ANALYZER_MARKERS):
        return "ANALYZER"

    # 3b. BUG_HUNTER_STATIC - static analysis and security scan patterns
    if any(marker in lowered for marker in _BUG_HUNTER_STATIC_MARKERS):
        return "BUG_HUNTER_STATIC"

    # 4. OPTIMIZER - performance patterns
    if any(marker in lowered for marker in _OPTIMIZER_MARKERS):
        return "OPTIMIZER"

    # 4b. REFACTOR_PERFORMANCE - specific performance refactoring patterns
    if any(marker in lowered for marker in _REFACTOR_PERF_MARKERS):
        return "REFACTOR_PERFORMANCE"

    # 4c. REFACTOR_CLEAN - code cleanliness refactoring patterns
    if any(marker in lowered for marker in _REFACTOR_CLEAN_MARKERS):
        return "REFACTOR_CLEAN"

    # 4d. TEST_RUNNER_UNIT - unit testing patterns
    if any(marker in lowered for marker in _TEST_RUNNER_UNIT_MARKERS):
        return "TEST_RUNNER_UNIT"

    # 4e. TEST_RUNNER_E2E - end-to-end testing patterns
    if any(marker in lowered for marker in _TEST_RUNNER_E2E_MARKERS):
        return "TEST_RUNNER_E2E"

    # 5. CODER - code generation patterns
    if any(marker in lowered for marker in _CODER_MARKERS):
        return "CODER"

    # 6. DOCUMENTER - documentation patterns
    if any(marker in lowered for marker in _DOCUMENTER_MARKERS):
        return "DOCUMENTER"

    # 7. RESEARCHER_WEB - deep research patterns (check before simple researcher)
    if any(marker in lowered for marker in _RESEARCHER_WEB_MARKERS):
        return "RESEARCHER_WEB"

    # 7b. RESEARCHER - research/web search patterns
    if any(marker in lowered for marker in _RESEARCHER_MARKERS):
        return "RESEARCHER"
    if any(marker in lowered for marker in _WEB_SEARCH_MARKERS):
        return "RESEARCHER"

    # 8. MICRO - trivial factoid lookup (very short, simple questions)
    words = lowered.split()
    if len(words) <= 12 and _TRIVIAL_QUESTION.match(lowered):
        return "MICRO"

    return None


def fast_route(query: str) -> AgentName | None:
    """Level 1 - deterministic pre-routing.

    Returns an agent name when the query is trivially classifiable, otherwise
    ``None`` so the caller falls through to :func:`route_with_model`.

    Priority order matters: more specific markers are checked first to avoid
    false positives. For example, "fix the error" should route to DEBUGGER,
    not CODER, even though "fix" could imply coding.

    Results are cached with LRU (maxsize=1000) for repeated queries.
    """
    if not query or not query.strip():
        return None

    return _fast_route_cached(query.lower().strip())

    # 1. DEBUGGER - error/debug patterns (most specific, check first)
    if any(marker in lowered for marker in _DEBUGGER_MARKERS):
        return "DEBUGGER"

    # 1b. BUG_HUNTER_RUNTIME - runtime testing and reproduction patterns
    if any(marker in lowered for marker in _BUG_HUNTER_RUNTIME_MARKERS):
        return "BUG_HUNTER_RUNTIME"

    # 2. ARCHITECT - design/planning patterns
    if any(marker in lowered for marker in _ARCHITECT_MARKERS):
        return "ARCHITECT"

    # 3. ANALYZER - review/audit patterns
    if any(marker in lowered for marker in _ANALYZER_MARKERS):
        return "ANALYZER"

    # 3b. BUG_HUNTER_STATIC - static analysis and security scan patterns
    if any(marker in lowered for marker in _BUG_HUNTER_STATIC_MARKERS):
        return "BUG_HUNTER_STATIC"

    # 4. OPTIMIZER - performance patterns
    if any(marker in lowered for marker in _OPTIMIZER_MARKERS):
        return "OPTIMIZER"

    # 4b. REFACTOR_PERFORMANCE - specific performance refactoring patterns
    if any(marker in lowered for marker in _REFACTOR_PERF_MARKERS):
        return "REFACTOR_PERFORMANCE"

    # 4c. REFACTOR_CLEAN - code cleanliness refactoring patterns
    if any(marker in lowered for marker in _REFACTOR_CLEAN_MARKERS):
        return "REFACTOR_CLEAN"

    # 4d. TEST_RUNNER_UNIT - unit testing patterns
    if any(marker in lowered for marker in _TEST_RUNNER_UNIT_MARKERS):
        return "TEST_RUNNER_UNIT"

    # 4e. TEST_RUNNER_E2E - end-to-end testing patterns
    if any(marker in lowered for marker in _TEST_RUNNER_E2E_MARKERS):
        return "TEST_RUNNER_E2E"

    # 5. CODER - code generation patterns
    if any(marker in lowered for marker in _CODER_MARKERS):
        return "CODER"

    # 6. DOCUMENTER - documentation patterns
    if any(marker in lowered for marker in _DOCUMENTER_MARKERS):
        return "DOCUMENTER"

    # 7. RESEARCHER - research/web search patterns
    if any(marker in lowered for marker in _RESEARCHER_MARKERS):
        return "RESEARCHER"
    if any(marker in lowered for marker in _WEB_SEARCH_MARKERS):
        return "RESEARCHER"

    # 8. MICRO - trivial factoid lookup (very short, simple questions)
    words = lowered.split()
    if len(words) <= 12 and _TRIVIAL_QUESTION.match(lowered):
        return "MICRO"

    return None


# ---------------------------------------------------------------------------
# Level 2 - model-based classification
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


async def route_with_model(query: str, client: Any) -> RoutingDecision:
    """Level 2 - ask the NANO model to classify the request.

    Returns a best-effort :class:`RoutingDecision`. If the model output is
    missing/malformed or the call fails, returns a low-confidence default
    decision pointing to CODER so the system always makes forward progress.
    The caller should use the ``routing_confidence`` field to decide whether
    to escalate.
    """
    # Check cache first
    hash_key = _query_hash(query)
    cached = _get_cached_decision(hash_key)
    if cached is not None:
        logger.debug("Routing decision cache hit for query hash: %s", hash_key[:8])
        return cached

    if detect_injection(query).detected:
        decision = _FALLBACK_DECISION.model_copy(
            update={"routing_reason": "prompt-injection-detected", "primary_agent": "MICRO"}
        )
        _store_cached_decision(hash_key, decision)
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
    except Exception as exc:
        logger.warning("Router model call failed: %s", exc)
        return _FALLBACK_DECISION

    decision = _parse_routing_decision(raw)
    # Cache the successful routing decision
    _store_cached_decision(hash_key, decision)
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
