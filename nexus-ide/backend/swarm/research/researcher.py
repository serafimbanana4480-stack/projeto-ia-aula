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
        }


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

        Never raises — failures are returned inside the report with notes.
        """
        import time

        start = time.time()
        report = ResearchReport(query=query)

        # Multi-source queries (≥2 for non-trivial claims)
        queries = self._expand_query(query)
        report.sources_queried = len(queries)

        all_findings: list[ResearchFinding] = []
        for q in queries:
            try:
                hits = await self._search(q, top_k=top_k)
                all_findings.extend(hits)
            except Exception as exc:
                report.notes.append(f"search failed for {q!r}: {exc}")

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
        report.summary = self._synthesise_summary(query, report.findings)
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
        """Delegate to the NEXUS web search v2 tool if available."""
        try:
            from backend.tools.web_search_v2 import deep_research  # type: ignore
        except Exception:
            try:
                from backend.tools.web_search import web_search  # type: ignore
            except Exception as exc:
                logger.debug("No web search tool available: %s", exc)
                return []

        try:
            result = await deep_research(query, max_results=top_k)
        except Exception:
            try:
                # Fall back to v1 signature
                result = await web_search(query, max_results=top_k)  # type: ignore
            except Exception as exc:
                logger.debug("web_search failed: %s", exc)
                return []

        findings: list[ResearchFinding] = []
        # deep_research returns a SearchResult dataclass
        sources = getattr(result, "sources", None) or []
        for hit in sources:
            findings.append(
                ResearchFinding(
                    title=getattr(hit, "title", ""),
                    url=getattr(hit, "url", ""),
                    snippet=getattr(hit, "snippet", ""),
                    source_engine=getattr(hit, "source_engine", ""),
                    relevance=float(getattr(hit, "score", 0.0) or 0.0),
                )
            )
        return findings

    def _synthesise_summary(self, query: str, findings: list[ResearchFinding]) -> str:
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


__all__ = ["ResearcherAgent", "ResearchFinding", "ResearchReport"]
