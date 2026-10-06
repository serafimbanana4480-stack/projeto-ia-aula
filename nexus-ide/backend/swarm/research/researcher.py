"""SWARM Research agent — gathers authoritative external information.

Wraps the existing NEXUS web search v2 to perform multi-source research with
explicit provenance and confidence scoring. Falls back to a deterministic
result when no network / no LLM is available so the swarm never blocks.

Public API
----------
``ResearcherAgent`` — the worker class
``ResearchFinding`` — a single structured finding
``ResearchReport``  — the structured output of a research task
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from backend.swarm.communication.message_bus import MessageBus
from backend.swarm.core.types import AgentMessage, AgentRole, MessageType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ResearchFinding:
    title: str
    url: str
    snippet: str
    source_engine: str = ""
    relevance: float = 0.0


@dataclass
class ResearchReport:
    query: str
    findings: list[ResearchFinding] = field(default_factory=list)
    summary: str = ""
    confidence: float = 0.0
    sources_queried: int = 0
    elapsed_ms: int = 0
    notes: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "summary": self.summary,
            "confidence": round(self.confidence, 3),
            "sources_queried": self.sources_queried,
            "elapsed_ms": self.elapsed_ms,
            "findings": [
                {
                    "title": f.title,
                    "url": f.url,
                    "snippet": f.snippet,
                    "source_engine": f.source_engine,
                    "relevance": round(f.relevance, 3),
                }
                for f in self.findings
            ],
            "notes": self.notes,
            "error": self.error,
        }


class ResearchError(RuntimeError):
    """Swarm research could not obtain external results.

    Raised instead of returning an empty findings list: an empty list reads as
    "nothing was found", which is a materially different answer from "the search
    never completed" (missing web tool, provider failure, or a failure shape
    returned by the web tool itself).
    """


# ---------------------------------------------------------------------------
# Researcher agent
# ---------------------------------------------------------------------------


class ResearcherAgent:
    """External-research worker for the SWARM system.

    Pulls the query from the message bus, performs multi-source research
    (preferring ≥2 independent sources), and posts a RESEARCH + EVIDENCE
    response back to the requester.
    """

    ROLE = AgentRole.RESEARCHER
    DEFAULT_TOP_K = 6

    def __init__(self, message_bus: MessageBus | None = None) -> None:
        self._bus = message_bus

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def research(self, query: str, top_k: int = DEFAULT_TOP_K) -> ResearchReport:
        """Run a research task and return a structured report.

        Never raises — failures are returned inside the report: ``notes`` records
        every per-query failure and ``error`` carries a joined, user-visible
        reason. A failed search never looks like a completed search that found
        nothing.
        """
        import time

        start = time.time()
        report = ResearchReport(query=query)

        # Multi-source queries (≥2 for non-trivial claims)
        queries = self._expand_query(query)
        report.sources_queried = len(queries)

        all_findings: list[ResearchFinding] = []
        errors: list[str] = []
        for q in queries:
            try:
                hits = await self._search(q, top_k=top_k)
                all_findings.extend(hits)
            except Exception as exc:
                errors.append(f"{q!r}: {exc}")
                report.notes.append(f"search failed for {q!r}: {exc}")
                logger.warning("Swarm research search failed for %r: %s", q, exc)

        # Deduplicate by URL
        seen: set[str] = set()
        deduped: list[ResearchFinding] = []
        for f in all_findings:
            if f.url and f.url in seen:
                continue
            if f.url:
                seen.add(f.url)
            deduped.append(f)
        report.findings = deduped[:top_k]
        report.error = "; ".join(errors[:3])
        report.summary = self._synthesise_summary(query, report.findings, report.error)
        report.confidence = self._score_confidence(report.findings, queries)
        report.elapsed_ms = int((time.time() - start) * 1000)
        return report

    async def handle(self, message: AgentMessage) -> AgentMessage | None:
        """Handle a REQUEST message and post a RESEARCH response on the bus."""
        if not self._bus or message.type != MessageType.REQUEST:
            return None
        query = (message.content or message.payload.get("query", "")).strip()
        if not query:
            return None
        report = await self.research(query)
        return await self._bus.respond(
            sender=self.ROLE.value,
            in_reply_to=message,
            content=report.summary,
            payload={
                "report": report.to_dict(),
                "confidence": report.confidence,
            },
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _expand_query(self, query: str) -> list[str]:
        """Generate ≥2 query variants to satisfy the 'multiple sources' rule."""
        variants = [query]
        # Add a "documentation" variant when relevant
        lowered = query.lower()
        if any(k in lowered for k in ("how", "what", "use", "tutorial", "example")):
            variants.append(f"{query} documentation")
        # Always add a "best practice" variant for engineering queries
        if any(
            k in lowered
            for k in (
                "python",
                "fastapi",
                "react",
                "typescript",
                "rust",
                "go",
                "java",
                "sql",
                "api",
                "library",
                "framework",
            )
        ):
            variants.append(f"{query} best practice official")
        # Deduplicate while preserving order
        seen: set[str] = set()
        out: list[str] = []
        for v in variants:
            v = v.strip()
            if v and v not in seen:
                seen.add(v)
                out.append(v)
        return out

    async def _search(self, query: str, top_k: int) -> list[ResearchFinding]:
        """Run one query through the NEXUS web tools and return its findings.

        The imports stay lazy (the swarm must not block on the web stack), but
        every failure now surfaces as a :class:`ResearchError` instead of an
        empty list.

        Raises:
            ResearchError: no web tool could be imported, every tool raised, or a
                tool reported that the search itself failed.
        """
        # `backend.tools.web_search_v2` exposes `search_and_answer` (which is
        # also the handler behind the registered `deep_research` tool) and
        # `backend.tools.web_search` exposes `search_web`. Neither module has a
        # `deep_research` or `web_search` callable; importing those names raised
        # ImportError and the old `except: return []` swallowed it, so swarm
        # web research was silently dead.
        attempts: list[tuple[str, Any, str]] = []
        failures: list[str] = []
        try:
            from backend.tools.web_search_v2 import search_and_answer

            # `search_and_answer` -> dict with sources/answer/confidence/consensus
            # and, in failure shapes, error/error_category/attempted_urls/
            # fetch_failure_count.
            attempts.append(("web_search_v2.search_and_answer", search_and_answer, "sources"))
        except Exception as exc:
            failures.append(f"cannot import web_search_v2.search_and_answer: {exc}")
        try:
            from backend.tools.web_search import search_web

            # `search_web` -> dict with query/hits/count (hits carry source_engine).
            attempts.append(("web_search.search_web", search_web, "hits"))
        except Exception as exc:
            failures.append(f"cannot import web_search.search_web: {exc}")

        if not attempts:
            raise ResearchError("no web search tool available: " + "; ".join(failures))

        for tool_name, tool, results_key in attempts:
            try:
                payload = await tool(query, max_results=top_k)
            except Exception as exc:
                # The tool itself is broken -> the next one may still work.
                failures.append(f"{tool_name} raised {type(exc).__name__}: {exc}")
                logger.warning("%s failed for %r: %s", tool_name, query, exc)
                continue
            findings, failure = self._findings_from_payload(payload, results_key)
            if failure:
                # The tool answered, and the answer is "the search did not work".
                # Both modules sit on the same providers, so retrying the other
                # one would only repeat the same outage -- report it now.
                raise ResearchError(f"{tool_name}: {failure}")
            return findings
        raise ResearchError("; ".join(failures))

    @staticmethod
    def _findings_from_payload(
        payload: Any, results_key: str
    ) -> tuple[list[ResearchFinding], str]:
        """Normalise a web tool return shape into findings plus a failure string.

        Returns ``(findings, "")`` on success and ``([], reason)`` on failure.
        The ``error``/``error_category`` check must come first: the ``no_evidence``
        failure shape still populates ``sources``, so reading the sources alone
        would report a provider outage as a thin-but-real result.
        """
        if not isinstance(payload, dict):
            return [], f"returned {type(payload).__name__}, expected dict"
        error = payload.get("error")
        if error:
            category = payload.get("error_category") or "error"
            return [], (
                f"{category}: {error} "
                f"(fetch_failure_count={payload.get('fetch_failure_count')})"
            )
        findings = [
            ResearchFinding(
                title=str(hit.get("title") or ""),
                url=str(hit.get("url") or ""),
                snippet=str(hit.get("snippet") or ""),
                source_engine=str(hit.get("source_engine") or ""),
                relevance=float(hit.get("score") or 0.0),
            )
            for hit in (payload.get(results_key) or [])
            if isinstance(hit, dict)
        ]
        if not findings:
            return [], f"returned no results under {results_key!r}"
        return findings, ""

    def _synthesise_summary(
        self, query: str, findings: list[ResearchFinding], error: str = ""
    ) -> str:
        if error and not findings:
            return (
                f"## Research summary for: {query}\n\n"
                f"**External research FAILED — no source was retrieved.** {error}\n\n"
                "This is a missing result, not a confirmed absence of results.\n"
            )
        if not findings:
            return (
                f"## Research summary for: {query}\n\n"
                "No external sources returned. Falling back to internal knowledge.\n"
            )
        lines: list[str] = [f"## Research summary for: {query}", ""]
        for i, f in enumerate(findings[:5], start=1):
            title = (f.title or "(untitled)").strip()
            snippet = re.sub(r"\s+", " ", f.snippet or "").strip()
            lines.append(f"{i}. **{title}**")
            if snippet:
                lines.append(f"   {snippet[:300]}{'…' if len(snippet) > 300 else ''}")
            if f.url:
                lines.append(f"   Source: {f.url}")
        if error:
            lines.append("")
            lines.append(f"> Partial failure: {error}")
        return "\n".join(lines)

    def _score_confidence(self, findings: list[ResearchFinding], queries: list[str]) -> float:
        if not findings:
            return 0.0
        # Heuristic: more findings from more queries → higher confidence.
        base = min(1.0, len(findings) / max(1, 5))
        multi_source = 0.2 if len(queries) >= 2 else 0.0
        official_bonus = 0.0
        for f in findings:
            url = (f.url or "").lower()
            if any(
                marker in url
                for marker in (
                    "docs.",
                    "/docs/",
                    "developer.",
                    "learn.",
                    "github.com",
                    "stackoverflow.com",
                    "mdn.io",
                )
            ):
                official_bonus = max(official_bonus, 0.1)
        return min(1.0, base + multi_source + official_bonus)


__all__ = ["ResearcherAgent", "ResearchError", "ResearchFinding", "ResearchReport"]
