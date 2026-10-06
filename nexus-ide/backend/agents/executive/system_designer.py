"""SystemDesigner — high-level system design generator."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from backend.agents.executive.pattern_catalog import PatternCatalog


@dataclass
class SystemComponent:
    """A component in a system design."""

    component_id: str
    name: str
    type: str  # service, database, queue, gateway, etc.
    responsibilities: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    technologies: list[str] = field(default_factory=list)
    scale_notes: str = ""


@dataclass
class SystemDesign:
    """A complete system design document."""

    design_id: str
    name: str
    description: str
    components: list[SystemComponent] = field(default_factory=list)
    data_flows: list[dict[str, Any]] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    non_functional_requirements: dict[str, Any] = field(default_factory=dict)
    risks: list[str] = field(default_factory=list)


class SystemDesigner:
    """Generates and manages system designs."""

    def __init__(self) -> None:
        self._catalog = PatternCatalog()
        self._designs: dict[str, SystemDesign] = {}

    def create_design(
        self,
        name: str,
        description: str,
        requirements: list[str],
    ) -> SystemDesign:
        design_id = f"design-{uuid.uuid4().hex[:8]}"

        # Recommend patterns based on requirements
        recommendations = self._catalog.recommend(requirements)
        patterns = [p.pattern_id for _, p in recommendations[:3]]

        # Generate default components based on requirements
        components = self._generate_components(requirements)

        design = SystemDesign(
            design_id=design_id,
            name=name,
            description=description,
            components=components,
            patterns=patterns,
            non_functional_requirements={
                "scalability": "horizontal scaling",
                "availability": "99.9%",
                "security": "zero-trust",
            },
        )
        self._designs[design_id] = design
        return design

    def _generate_components(self, requirements: list[str]) -> list[SystemComponent]:
        components = []
        req_lower = [r.lower() for r in requirements]

        if any("api" in r for r in req_lower):
            components.append(SystemComponent(
                component_id=f"comp-{uuid.uuid4().hex[:4]}",
                name="API Gateway",
                type="gateway",
                responsibilities=["Route requests", "Rate limiting", "Auth"],
                technologies=["Kong", "Nginx", "FastAPI"],
            ))

        if any("database" in r or "storage" in r for r in req_lower):
            components.append(SystemComponent(
                component_id=f"comp-{uuid.uuid4().hex[:4]}",
                name="Primary Database",
                type="database",
                responsibilities=["Data persistence", "ACID transactions"],
                technologies=["PostgreSQL", "CockroachDB"],
            ))

        if any("cache" in r for r in req_lower):
            components.append(SystemComponent(
                component_id=f"comp-{uuid.uuid4().hex[:4]}",
                name="Cache Layer",
                type="cache",
                responsibilities=["Fast reads", "Session storage"],
                technologies=["Redis", "Memcached"],
            ))

        if any("queue" in r or "event" in r or "async" in r for r in req_lower):
            components.append(SystemComponent(
                component_id=f"comp-{uuid.uuid4().hex[:4]}",
                name="Message Queue",
                type="queue",
                responsibilities=["Async processing", "Event streaming"],
                technologies=["RabbitMQ", "Kafka", "Celery"],
            ))

        if any("search" in r for r in req_lower):
            components.append(SystemComponent(
                component_id=f"comp-{uuid.uuid4().hex[:4]}",
                name="Search Engine",
                type="search",
                responsibilities=["Full-text search", "Faceted search"],
                technologies=["Elasticsearch", "OpenSearch", "Meilisearch"],
            ))

        if not components:
            components.append(SystemComponent(
                component_id=f"comp-{uuid.uuid4().hex[:4]}",
                name="Application Service",
                type="service",
                responsibilities=["Business logic"],
                technologies=["FastAPI", "Node.js"],
            ))

        return components

    def get_design(self, design_id: str) -> SystemDesign | None:
        return self._designs.get(design_id)

    def add_component(self, design_id: str, component: SystemComponent) -> bool:
        design = self._designs.get(design_id)
        if not design:
            return False
        design.components.append(component)
        return True

    def add_data_flow(self, design_id: str, source: str, target: str, protocol: str) -> bool:
        design = self._designs.get(design_id)
        if not design:
            return False
        design.data_flows.append({
            "source": source,
            "target": target,
            "protocol": protocol,
        })
        return True

    def list_designs(self) -> list[SystemDesign]:
        return list(self._designs.values())

    def stats(self) -> dict[str, Any]:
        return {
            "total_designs": len(self._designs),
            "total_patterns_in_catalog": self._catalog.stats()["total"],
        }
