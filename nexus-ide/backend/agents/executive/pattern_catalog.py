"""PatternCatalog — design pattern library for the Chief Architect."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PatternCategory(str, Enum):
    CREATIONAL = "creational"
    STRUCTURAL = "structural"
    BEHAVIORAL = "behavioral"
    ARCHITECTURAL = "architectural"
    CLOUD = "cloud"
    SECURITY = "security"


@dataclass
class DesignPattern:
    """A documented design pattern."""

    pattern_id: str
    name: str
    category: PatternCategory
    description: str
    problem: str
    solution: str
    consequences: str
    examples: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    when_to_use: str = ""
    when_not_to_use: str = ""


class PatternCatalog:
    """Library of design patterns for architecture decisions."""

    def __init__(self) -> None:
        self._patterns: dict[str, DesignPattern] = {}
        self._load_default_patterns()

    def _load_default_patterns(self) -> None:
        defaults = [
            DesignPattern(
                pattern_id="arch-001",
                name="Microservices",
                category=PatternCategory.ARCHITECTURAL,
                description="Decompose application into loosely coupled services",
                problem="Monolith becoming too large to scale or deploy independently",
                solution="Split into independently deployable services with clear APIs",
                consequences="+ scalability, + independent deploy\n- operational complexity, - distributed system challenges",
                examples=["Netflix", "Amazon"],
                tags=["scalability", "independence", "distributed"],
                when_to_use="Multiple teams, different scaling requirements",
                when_not_to_use="Small team, simple domain, low scale",
            ),
            DesignPattern(
                pattern_id="arch-002",
                name="Event Sourcing",
                category=PatternCategory.ARCHITECTURAL,
                description="Store state as a sequence of events",
                problem="Need audit trail and temporal query capability",
                solution="Persist events rather than current state; derive state on read",
                consequences="+ complete audit, + temporal queries\n- storage growth, - eventual consistency",
                examples=["Banking ledgers", "Inventory systems"],
                tags=["audit", "events", "cqrs"],
                when_to_use="Audit requirements, complex state transitions",
                when_not_to_use="Simple CRUD, strong consistency required",
            ),
            DesignPattern(
                pattern_id="sec-001",
                name="Zero Trust Architecture",
                category=PatternCategory.SECURITY,
                description="Never trust, always verify",
                problem="Perimeter-based security insufficient for cloud-native apps",
                solution="Authenticate and authorize every request regardless of origin",
                consequences="+ strong security posture\n- latency, - complexity",
                examples=["Google BeyondCorp", "Okta"],
                tags=["security", "auth", "microsegmentation"],
                when_to_use="Cloud-native, multi-tenant, regulated industries",
                when_not_to_use="Internal-only, low-risk applications",
            ),
            DesignPattern(
                pattern_id="cloud-001",
                name="CQRS",
                category=PatternCategory.CLOUD,
                description="Command Query Responsibility Segregation",
                problem="Read and write workloads have conflicting optimization needs",
                solution="Separate read models from write models",
                consequences="+ optimized reads and writes\n- eventual consistency, - complexity",
                examples=["E-commerce catalogs", "Analytics dashboards"],
                tags=["scalability", "performance", "events"],
                when_to_use="High read ratio, complex queries",
                when_not_to_use="Simple CRUD, small scale",
            ),
            DesignPattern(
                pattern_id="struct-001",
                name="Circuit Breaker",
                category=PatternCategory.STRUCTURAL,
                description="Prevent cascade failures in distributed systems",
                problem="Service failure cascades to dependent services",
                solution="Detect failures and fail fast with fallback",
                consequences="+ resilience, + graceful degradation\n- complexity, - stale fallbacks",
                examples=["Netflix Hystrix", "Resilience4j"],
                tags=["resilience", "fault-tolerance", "distributed"],
                when_to_use="External service dependencies",
                when_not_to_use="No external dependencies",
            ),
        ]
        for p in defaults:
            self._patterns[p.pattern_id] = p

    def add_pattern(self, pattern: DesignPattern) -> None:
        self._patterns[pattern.pattern_id] = pattern

    def get_pattern(self, pattern_id: str) -> DesignPattern | None:
        return self._patterns.get(pattern_id)

    def search(self, query: str, category: PatternCategory | None = None) -> list[DesignPattern]:
        query_lower = query.lower()
        results = []
        for p in self._patterns.values():
            if category and p.category != category:
                continue
            searchable = f"{p.name} {p.description} {p.problem} {p.solution} {' '.join(p.tags)}"
            if query_lower in searchable.lower():
                results.append(p)
        return results

    def get_by_category(self, category: PatternCategory) -> list[DesignPattern]:
        return [p for p in self._patterns.values() if p.category == category]

    def recommend(self, requirements: list[str]) -> list[tuple[float, DesignPattern]]:
        """Recommend patterns based on requirements overlap."""
        req_set = set(r.lower() for r in requirements)
        scored: list[tuple[float, DesignPattern]] = []
        for p in self._patterns.values():
            tag_set = set(t.lower() for t in p.tags)
            overlap = len(req_set & tag_set)
            if overlap > 0:
                scored.append((overlap, p))
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored

    def stats(self) -> dict[str, Any]:
        by_category = {}
        for p in self._patterns.values():
            by_category[p.category.value] = by_category.get(p.category.value, 0) + 1
        return {"total": len(self._patterns), "by_category": by_category}
