"""Routing strategies used by the orchestrator router.

This module implements the Strategy pattern on top of the previous level-1
(keyword rules) and level-2 (LLM classification) routing functions that used
to live in :mod:`backend.orchestrator.router`. Each strategy is an
:class:`RoutingStrategy` that knows how to produce a :class:`RoutingDecision`
for a given query, or to return ``None`` so the chain can fall through to
the next strategy.

Strategies provided:

* :class:`KeywordRoutingStrategy` — deterministic keyword matching ported
  verbatim from the original ``fast_route`` implementation.
* :class:`LLMRoutingStrategy` — wraps a small LLM call (typically the NANO
  model) that emits a JSON routing decision. Returns ``None`` on any failure
  so the chain can fall through.
* :class:`RecordingStrategy` — test-only strategy that records every query
  and returns a hard-coded ``MICRO`` decision.

The module also exports the shared :data:`FALLBACK_DECISION` and the
:func:`parse_routing_decision` helper used by :class:`LLMRoutingStrategy` and
the router engine.
"""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Final

from pydantic import ValidationError

from backend.config.settings import get_model_config, load_prompt
from backend.models.api import AgentName, RoutingDecision
from backend.tools.ollama_client import ChatMessage
from backend.tools.sanitizer import detect_injection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers used by the LLM strategy and the router engine.
# ---------------------------------------------------------------------------

FALLBACK_DECISION: Final[RoutingDecision] = RoutingDecision(
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


def parse_routing_decision(raw: str) -> RoutingDecision:
    """Extract the first JSON object from ``raw`` and validate it.

    Mirrors the behaviour of the original ``_parse_routing_decision`` helper
    in :mod:`backend.orchestrator.router` so existing tests keep working.
    """
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        logger.warning("Router output contained no JSON object: %r", raw[:200])
        return FALLBACK_DECISION
    try:
        payload = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("Router JSON malformed (%s): %r", exc, match.group(0)[:200])
        return FALLBACK_DECISION

    # Fix common model errors: convert string values to expected types
    if "routing_confidence" in payload and isinstance(payload["routing_confidence"], str):
        try:
            value = payload["routing_confidence"].lower()
            if value == "high":
                payload["routing_confidence"] = 0.8
            elif value == "low":
                payload["routing_confidence"] = 0.2
            elif value == "medium":
                payload["routing_confidence"] = 0.5
            else:
                payload["routing_confidence"] = float(payload["routing_confidence"])
        except (ValueError, AttributeError):
            payload["routing_confidence"] = 0.5  # Default fallback

    try:
        return RoutingDecision.model_validate(payload)
    except ValidationError as exc:
        logger.warning("Router decision failed validation: %s", exc)
        return FALLBACK_DECISION


# ---------------------------------------------------------------------------
# Strategy interface
# ---------------------------------------------------------------------------


class RoutingStrategy(ABC):
    """Abstract routing strategy.

    Implementations should return a :class:`RoutingDecision` when they can
    classify the query, or ``None`` when they want the chain to try the
    next strategy.
    """

    @abstractmethod
    async def route(self, query: str, *, context: dict | None = None) -> RoutingDecision | None:
        """Classify ``query`` and return a decision, or ``None`` to defer."""


# ---------------------------------------------------------------------------
# Keyword strategy (level 1)
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
_FILE_OPS_MARKERS: Final = (
    "create a file",
    "create file",
    "write a file",
    "write file",
    "save a file",
    "save to file",
    "make a file",
    "criar ficheiro",
    "criar um ficheiro",
    "criar arquivo",
    "criar um arquivo",
    "escrever ficheiro",
    "escrever um ficheiro",
    "guardar ficheiro",
    "modificar ficheiro",
    "alterar ficheiro",
    ".txt",
    ".csv",
    ".json",
    ".md",
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


def _keyword_classify(normalized_query: str) -> AgentName | None:
    """Return the agent name matched by deterministic keyword rules.

    The priority order is preserved verbatim from the original
    ``fast_route`` implementation. The input must already be normalized
    (lowered + stripped) by the caller.
    """
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

    # 4f. FILE_OPS - explicit file create/modify requests (route to CODER with tools)
    if any(marker in lowered for marker in _FILE_OPS_MARKERS):
        return "CODER"

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


class KeywordRoutingStrategy(RoutingStrategy):
    """Deterministic keyword-based routing strategy.

    This strategy is the level-1 router from the original implementation. It
    has no external dependencies and never returns ``None`` for non-empty
    queries that match one of the configured markers. For unmatched queries
    it returns ``None`` so the chain can fall through to the next strategy.
    """

    def __init__(self) -> None:
        # No state — markers live at module scope to keep the class cheap.
        pass

    async def route(self, query: str, *, context: dict | None = None) -> RoutingDecision | None:
        if not query or not query.strip():
            return None
        agent = _keyword_classify(query.lower().strip())
        if agent is None:
            return None
        return RoutingDecision(
            primary_agent=agent,
            secondary_agents=[],
            requires_web_search=False,
            thinking_mode="fast",
            estimated_complexity=3,
            task_type="keyword_match",
            context_needed="low",
            routing_confidence=0.9,
            routing_reason="keyword-rule",
        )


# ---------------------------------------------------------------------------
# LLM strategy (level 2)
# ---------------------------------------------------------------------------


class LLMRoutingStrategy(RoutingStrategy):
    """LLM-based routing strategy.

    The strategy delegates classification to a small chat-completion model
    (typically the NANO tier) that returns a JSON object validated against
    :class:`RoutingDecision`. On any failure (missing client, network error,
    malformed payload, validation error) the strategy returns ``None`` so
    the chain can fall through.

    When ``llm_client`` is ``None`` the strategy short-circuits to ``None`` —
    this is useful for environments where the LLM is intentionally disabled
    (tests, CI without LLM access, etc.).
    """

    def __init__(self, llm_client: Any, model_id: str | None = None) -> None:
        self._client = llm_client
        self._model_id = model_id

    async def route(self, query: str, *, context: dict | None = None) -> RoutingDecision | None:
        if self._client is None:
            return None
        if not query or not query.strip():
            return None

        if detect_injection(query).detected:
            decision = FALLBACK_DECISION.model_copy(
                update={"routing_reason": "prompt-injection-detected", "primary_agent": "MICRO"}
            )
            return decision

        try:
            model_id = self._model_id or get_model_config("nano")["id"]
            system = load_prompt("router")
        except (KeyError, FileNotFoundError) as exc:
            logger.error("Router misconfigured: %s", exc)
            return None

        try:
            raw = await self._client.chat_complete(
                model=model_id,
                messages=[
                    ChatMessage(role="system", content=system),
                    ChatMessage(role="user", content=query),
                ],
                options={"temperature": 0.1, "num_predict": 512},
            )
        except Exception as exc:  # pragma: no cover - network failure path
            logger.warning("Router model call failed: %s", exc)
            return None

        return parse_routing_decision(raw)


# ---------------------------------------------------------------------------
# Recording strategy (test-only)
# ---------------------------------------------------------------------------


class RecordingStrategy(RoutingStrategy):
    """Test-only strategy that records every query and returns MICRO.

    The strategy is used by the unit tests to assert that the router engine
    calls strategies in order and forwards queries verbatim.
    """

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.contexts: list[dict | None] = []

    async def route(self, query: str, *, context: dict | None = None) -> RoutingDecision | None:
        self.queries.append(query)
        self.contexts.append(context)
        return RoutingDecision(
            primary_agent="MICRO",
            secondary_agents=[],
            requires_web_search=False,
            thinking_mode="fast",
            estimated_complexity=1,
            task_type="test",
            context_needed="low",
            routing_confidence=1.0,
            routing_reason="recording-strategy",
        )


__all__ = [
    "RoutingStrategy",
    "KeywordRoutingStrategy",
    "LLMRoutingStrategy",
    "RecordingStrategy",
    "FALLBACK_DECISION",
    "parse_routing_decision",
]
