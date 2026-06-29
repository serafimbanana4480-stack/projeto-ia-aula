"""PatternExtractor — extracts reusable patterns from successful executions.

Analyzes execution logs to identify recurring patterns in code,
tests, repairs, and deploys. Stores them in a Knowledge Graph
for future query and reuse.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Pattern:
    """A reusable pattern extracted from execution history."""

    pattern_id: str
    pattern_type: str  # code, test, repair, deploy
    name: str
    description: str
    context: str  # When to apply this pattern
    template: str  # Reusable template/snippet
    success_rate: float = 1.0
    usage_count: int = 1
    tags: list[str] = field(default_factory=list)
    stack: str = ""
    source_workflow_id: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_id": self.pattern_id,
            "pattern_type": self.pattern_type,
            "name": self.name,
            "description": self.description,
            "context": self.context,
            "template": self.template,
            "success_rate": self.success_rate,
            "usage_count": self.usage_count,
            "tags": self.tags,
            "stack": self.stack,
        }


class PatternExtractor:
    """Extracts patterns from execution logs."""

    def extract(self, logs: list[dict[str, Any]]) -> list[Pattern]:
        """Extract patterns from a batch of execution logs.

        Args:
            logs: List of execution log entries.

        Returns:
            List of extracted Patterns.
        """
        patterns: list[Pattern] = []

        for entry in logs:
            if not entry.get("success", False):
                continue

            # Extract code patterns
            code_patterns = self._extract_code_patterns(entry)
            patterns.extend(code_patterns)

            # Extract test patterns
            test_patterns = self._extract_test_patterns(entry)
            patterns.extend(test_patterns)

            # Extract repair patterns
            repair_patterns = self._extract_repair_patterns(entry)
            patterns.extend(repair_patterns)

            # Extract deploy patterns
            deploy_patterns = self._extract_deploy_patterns(entry)
            patterns.extend(deploy_patterns)

        logger.info("Extracted %d patterns from %d logs", len(patterns), len(logs))
        return patterns

    def _extract_code_patterns(self, entry: dict[str, Any]) -> list[Pattern]:
        """Extract code structure patterns from a successful execution."""
        patterns: list[Pattern] = []

        code_summary = entry.get("code_summary", "")
        if not code_summary:
            return patterns

        stack = entry.get("stack", "python")
        workflow_id = entry.get("workflow_id", "")

        # Pattern: project structure
        if entry.get("files_created", 0) > 1:
            pattern_id = self._hash(f"multi-file-{workflow_id}")
            patterns.append(Pattern(
                pattern_id=pattern_id,
                pattern_type="code",
                name="Multi-file project structure",
                description=f"Generated {entry['files_created']} files with consistent structure",
                context="When creating new projects or features",
                template=code_summary,
                tags=["project-structure", "multi-file", stack],
                stack=stack,
                source_workflow_id=workflow_id,
            ))

        # Pattern: specific stack pattern
        if stack:
            pattern_id = self._hash(f"stack-{stack}-{workflow_id}")
            patterns.append(Pattern(
                pattern_id=pattern_id,
                pattern_type="code",
                name=f"{stack.upper()} project pattern",
                description=f"Successful {stack} code generation pattern",
                context=f"When generating {stack} code",
                template=code_summary,
                tags=[stack, "code-generation"],
                stack=stack,
                source_workflow_id=workflow_id,
            ))

        return patterns

    def _extract_test_patterns(self, entry: dict[str, Any]) -> list[Pattern]:
        """Extract testing patterns from execution."""
        patterns: list[Pattern] = []

        test_summary = entry.get("test_summary", "")
        if not test_summary:
            return patterns

        workflow_id = entry.get("workflow_id", "")
        coverage = entry.get("coverage_pct", 0)

        if coverage >= 90:
            pattern_id = self._hash(f"high-coverage-{workflow_id}")
            patterns.append(Pattern(
                pattern_id=pattern_id,
                pattern_type="test",
                name="High-coverage test suite",
                description=f"Achieved {coverage}% coverage with passing tests",
                context="When high test coverage is required",
                template=test_summary,
                tags=["testing", "high-coverage", f"coverage-{coverage}"],
                source_workflow_id=workflow_id,
            ))

        return patterns

    def _extract_repair_patterns(self, entry: dict[str, Any]) -> list[Pattern]:
        """Extract repair patterns from fix cycles."""
        patterns: list[Pattern] = []

        repairs = entry.get("repairs", [])
        if not repairs:
            return patterns

        workflow_id = entry.get("workflow_id", "")

        for i, repair in enumerate(repairs):
            if repair.get("success", False):
                pattern_id = self._hash(f"repair-{workflow_id}-{i}")
                patterns.append(Pattern(
                    pattern_id=pattern_id,
                    pattern_type="repair",
                    name=f"Successful repair: {repair.get('error_type', 'unknown')}",
                    description=repair.get("fix_description", "Automated fix applied"),
                    context=f"When encountering {repair.get('error_type', 'similar errors')}",
                    template=repair.get("patch", ""),
                    tags=["repair", repair.get("error_type", "unknown")],
                    source_workflow_id=workflow_id,
                ))

        return patterns

    def _extract_deploy_patterns(self, entry: dict[str, Any]) -> list[Pattern]:
        """Extract deployment patterns."""
        patterns: list[Pattern] = []

        deploy_info = entry.get("deploy", {})
        if not deploy_info:
            return patterns

        workflow_id = entry.get("workflow_id", "")
        strategy = deploy_info.get("strategy", "")

        if strategy:
            pattern_id = self._hash(f"deploy-{strategy}-{workflow_id}")
            patterns.append(Pattern(
                pattern_id=pattern_id,
                pattern_type="deploy",
                name=f"Deploy strategy: {strategy}",
                description=f"Successful deployment using {strategy} strategy",
                context=f"When deploying with {strategy}",
                template=json_safe_dumps(deploy_info),
                tags=["deploy", strategy],
                source_workflow_id=workflow_id,
            ))

        return patterns

    def _hash(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()[:12]


def json_safe_dumps(obj: Any) -> str:
    """Safe JSON dump that never fails."""
    import json
    try:
        return json.dumps(obj, indent=2, default=str)
    except Exception:
        return str(obj)


class KnowledgeGraphStore:
    """Stores and queries patterns in a knowledge graph.

    Uses in-memory storage with vector-like search capability.
    In production, this would use Qdrant + Elasticsearch.
    """

    def __init__(self) -> None:
        self._patterns: dict[str, Pattern] = {}
        self._index: dict[str, list[str]] = {}  # tag -> pattern_ids

    def store(self, pattern: Pattern) -> None:
        """Store a pattern in the knowledge graph."""
        self._patterns[pattern.pattern_id] = pattern

        for tag in pattern.tags:
            if tag not in self._index:
                self._index[tag] = []
            if pattern.pattern_id not in self._index[tag]:
                self._index[tag].append(pattern.pattern_id)

    def store_batch(self, patterns: list[Pattern]) -> int:
        """Store multiple patterns at once."""
        for p in patterns:
            self.store(p)
        return len(patterns)

    def query_by_tags(self, tags: list[str], pattern_type: str | None = None,
                      limit: int = 0) -> list[Pattern]:
        """Find patterns matching any of the given tags."""
        matching_ids: set[str] = set()
        for tag in tags:
            matching_ids.update(self._index.get(tag, []))

        results = [self._patterns[pid] for pid in matching_ids if pid in self._patterns]

        if pattern_type:
            results = [p for p in results if p.pattern_type == pattern_type]

        # Sort by success_rate * usage_count
        results = sorted(results, key=lambda p: p.success_rate * p.usage_count, reverse=True)

        if limit > 0:
            results = results[:limit]
        return results

    def query_by_type(self, pattern_type: str, limit: int = 10) -> list[Pattern]:
        """Get patterns of a specific type."""
        results = [p for p in self._patterns.values() if p.pattern_type == pattern_type]
        return sorted(results, key=lambda p: p.success_rate, reverse=True)[:limit]

    def search_similar(self, query: str, limit: int = 5) -> list[Pattern]:
        """Simple keyword-based similarity search.

        In production, this would use Qdrant vector search.
        """
        query_lower = query.lower()
        scored: list[tuple[float, Pattern]] = []

        for pattern in self._patterns.values():
            score = 0.0
            text = f"{pattern.name} {pattern.description} {' '.join(pattern.tags)}".lower()

            # Simple word overlap scoring
            query_words = set(query_lower.split())
            text_words = set(text.split())
            overlap = query_words & text_words
            if overlap:
                score = len(overlap) / max(len(query_words), 1)
                scored.append((score, pattern))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:limit]]

    def get_pattern(self, pattern_id: str) -> Pattern | None:
        return self._patterns.get(pattern_id)

    def get_stats(self) -> dict[str, int]:
        """Get statistics about stored patterns."""
        stats: dict[str, int] = {"total": len(self._patterns)}
        for pattern in self._patterns.values():
            key = pattern.pattern_type
            stats[key] = stats.get(key, 0) + 1
        return stats


class PatternQuery:
    """High-level interface for querying patterns."""

    def __init__(self, store: KnowledgeGraphStore) -> None:
        self._store = store

    def find_for_task(self, task_type: str, stack: str = "",
                      limit: int = 5) -> list[Pattern]:
        """Find patterns relevant to a task type."""
        tags = [task_type]
        if stack:
            tags.append(stack)
        return self._store.query_by_tags(tags, limit=limit)

    def find_similar_code(self, description: str, limit: int = 5) -> list[Pattern]:
        """Find code patterns similar to a description."""
        results = self._store.search_similar(description, limit=limit * 2)
        return [p for p in results if p.pattern_type == "code"][:limit]

    def find_repairs_for_error(self, error_type: str, limit: int = 3) -> list[Pattern]:
        """Find repair patterns for a specific error type."""
        return self._store.query_by_tags([error_type, "repair"], pattern_type="repair")[:limit]