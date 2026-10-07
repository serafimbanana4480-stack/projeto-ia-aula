"""Architecture templates and pattern catalog for structured code generation.

Provides layered architecture templates, design pattern catalog,
and architectural decision recording.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class LayerRule:
    """Dependency rule between architecture layers."""

    from_layer: str
    to_layer: str
    allowed: bool = True


@dataclass
class ArchitectureTemplate:
    """Template defining layers and rules for a project architecture."""

    name: str
    description: str = ""
    layers: list[str] = field(default_factory=list)
    rules: list[LayerRule] = field(default_factory=list)
    default_files: dict[str, str] = field(default_factory=dict)

    def validate_dependency(self, from_layer: str, to_layer: str) -> bool:
        """Check if a dependency between layers is allowed."""
        for rule in self.rules:
            if rule.from_layer == from_layer and rule.to_layer == to_layer:
                return rule.allowed
        # Default: only upward dependencies allowed (lower → higher)
        if from_layer not in self.layers or to_layer not in self.layers:
            return False
        return self.layers.index(from_layer) <= self.layers.index(to_layer)

    def get_layer_for_file(self, file_path: str) -> str:
        """Determine which layer a file belongs to."""
        path_lower = file_path.lower()
        for layer in self.layers:
            if layer.lower() in path_lower:
                return layer
        return "unknown"


class TemplateRegistry:
    """Registry of architecture templates."""

    _TEMPLATES: dict[str, ArchitectureTemplate] = {
        "fastapi-layered": ArchitectureTemplate(
            name="fastapi-layered",
            description="FastAPI with layered architecture",
            layers=["routes", "services", "repositories", "models", "config"],
            rules=[
                LayerRule("routes", "services", True),
                LayerRule("routes", "repositories", False),
                LayerRule("services", "repositories", True),
                LayerRule("services", "models", True),
                LayerRule("repositories", "models", True),
                LayerRule("config", "models", True),
            ],
            default_files={
                "app/__init__.py": "",
                "app/main.py": "from app.routes import api\nfrom fastapi import FastAPI\napp = FastAPI()\napp.include_router(api.router)",
                "app/routes/__init__.py": "",
                "app/services/__init__.py": "",
                "app/repositories/__init__.py": "",
                "app/models/__init__.py": "",
                "app/config/__init__.py": "",
            },
        ),
        "react-layered": ArchitectureTemplate(
            name="react-layered",
            description="React with layered frontend architecture",
            layers=["pages", "components", "hooks", "api", "types", "utils"],
            rules=[
                LayerRule("pages", "components", True),
                LayerRule("pages", "hooks", True),
                LayerRule("pages", "api", True),
                LayerRule("components", "hooks", True),
                LayerRule("components", "utils", True),
                LayerRule("hooks", "api", True),
                LayerRule("hooks", "utils", True),
                LayerRule("api", "types", True),
            ],
            default_files={
                "src/main.tsx": "import React from 'react'",
                "src/pages/.gitkeep": "",
                "src/components/.gitkeep": "",
                "src/hooks/.gitkeep": "",
                "src/api/.gitkeep": "",
                "src/types/.gitkeep": "",
                "src/utils/.gitkeep": "",
            },
        ),
    }

    @classmethod
    def get(cls, name: str) -> ArchitectureTemplate:
        if name not in cls._TEMPLATES:
            raise KeyError(f"Unknown architecture: {name}")
        return cls._TEMPLATES[name]

    @classmethod
    def list_architectures(cls) -> list[str]:
        return list(cls._TEMPLATES.keys())


@dataclass
class DesignPattern:
    """A design pattern entry in the catalog."""

    name: str
    category: str  # creational, structural, behavioral
    description: str = ""
    when_to_use: str = ""
    code_template: str = ""
    trade_offs: str = ""


class PatternCatalog:
    """Searchable catalog of design patterns."""

    _PATTERNS: list[DesignPattern] = [
        DesignPattern(
            name="Repository",
            category="structural",
            description="Abstracts data access behind an interface",
            when_to_use="When you need testable data access and may switch storage",
            code_template="class {Name}Repository:\n    def get(self, id): ...\n    def save(self, entity): ...",
            trade_offs="+ Testable, - Extra abstraction layer",
        ),
        DesignPattern(
            name="Factory",
            category="creational",
            description="Creates objects without specifying exact class",
            when_to_use="When creation logic is complex or varies by input",
            code_template="class {Name}Factory:\n    @staticmethod\n    def create(type): ...",
            trade_offs="+ Flexible, - Can become over-engineered",
        ),
        DesignPattern(
            name="Observer",
            category="behavioral",
            description="Notifies dependents of state changes",
            when_to_use="When multiple components need to react to events",
            code_template="class EventBus:\n    def subscribe(self, handler): ...\n    def publish(self, event): ...",
            trade_offs="+ Loose coupling, - Can create memory leaks",
        ),
        DesignPattern(
            name="Singleton",
            category="creational",
            description="Ensures only one instance exists",
            when_to_use="For shared resources like config or connection pools",
            code_template="_instance = None\nclass {Name}:\n    def __new__(cls): ...",
            trade_offs="+ Global access, - Hard to test, hidden dependencies",
        ),
    ]

    @classmethod
    def search(cls, query: str) -> list[DesignPattern]:
        """Search patterns by name or description."""
        query_lower = query.lower()
        results = []
        for pattern in cls._PATTERNS:
            score = 0
            if query_lower in pattern.name.lower():
                score += 3
            if query_lower in pattern.description.lower():
                score += 1
            if query_lower in pattern.when_to_use.lower():
                score += 1
            if query_lower in pattern.category:
                score += 1
            if score > 0:
                results.append((score, pattern))
        results.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in results]

    @classmethod
    def get(cls, name: str) -> DesignPattern | None:
        for pattern in cls._PATTERNS:
            if pattern.name.lower() == name.lower():
                return pattern
        return None


@dataclass
class ArchitecturalDecision:
    """Records why an architectural choice was made."""

    decision_id: str
    context: str = ""
    decision: str = ""
    consequences: str = ""
    status: str = "proposed"  # proposed, accepted, deprecated, superseded
    date: str = ""
    related_files: list[str] = field(default_factory=list)

    def to_markdown(self) -> str:
        return f"""# ADR: {self.decision_id}

## Context

{self.context}

## Decision

{self.decision}

## Consequences

{self.consequences}

## Status

{self.status}

## Related Files

{chr(10).join(f'- `{f}`' for f in self.related_files)}
"""


class DecisionRecorder:
    """Records and manages architectural decisions."""

    def __init__(self) -> None:
        self._decisions: list[ArchitecturalDecision] = []

    def record(
        self,
        context: str,
        decision: str,
        consequences: str,
        related_files: list[str] | None = None,
    ) -> ArchitecturalDecision:
        """Record a new architectural decision."""
        from datetime import datetime

        adr = ArchitecturalDecision(
            decision_id=f"ADR-{len(self._decisions) + 1:03d}",
            context=context,
            decision=decision,
            consequences=consequences,
            status="accepted",
            date=datetime.now().isoformat(),
            related_files=related_files or [],
        )
        self._decisions.append(adr)
        logger.info("Recorded ADR %s", adr.decision_id)
        return adr

    def list_decisions(self) -> list[ArchitecturalDecision]:
        return self._decisions.copy()

    def export_adrs(self) -> str:
        """Export all ADRs as a combined markdown string."""
        return "\n\n---\n\n".join(d.to_markdown() for d in self._decisions)
