"""FailureMiner — classifies task failures from traces into prioritised categories.

FASE 7. Reads structured traces from the TraceLake, inspects failure events,
classifies them into FailureCategory groups, and produces a prioritised list
of failure patterns for the candidate generators.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.evolution.registry import (
    DEFAULT_DB_PATH,
    FailureCategory,
    FailurePriority,
    _connect,
    _utcnow_iso,
)
from backend.experience.lake import TraceLake, get_trace_lake

logger = logging.getLogger(__name__)


# ── Classification heuristics ─────────────────────────────────────────────────
# Keyword → category mapping for error pattern matching
_FAILURE_PATTERNS: dict[FailureCategory, list[str]] = {
    FailureCategory.BAD_PLANNING: [
        "invalid plan", "plan rejected", "planning failed", "bad plan",
        "sequence of steps", "ordering error", "dependency cycle",
    ],
    FailureCategory.INCORRECT_CODE: [
        "syntax error", "syntaxerror", "SyntaxError", "runtime error",
        "exception", "traceback",
        "undefined variable", "type error", "value error", "attribute error",
        "index out of range", "assertion error",
    ],
    FailureCategory.INSUFFICIENT_CONTEXT: [
        "not enough context", "missing information", "need more info",
        "unknown variable", "undefined reference",
    ],
    FailureCategory.TOO_MANY_CALLS: [
        "too many tool calls", "exceeded budget", "call limit",
        "maximum iterations", "over budget", "rate limit",
    ],
    FailureCategory.TOOL_SELECTION_ERROR: [
        "wrong tool", "tool misuse", "invalid tool", "no such tool",
        "unsupported tool", "tool not found",
    ],
    FailureCategory.MEMORY_RETRIEVAL_ERROR: [
        "memory miss", "retrieval failed", "not found in memory",
        "context window", "memory full",
    ],
    FailureCategory.HALLUCINATED_API: [
        "hallucinated", "fake api", "nonexistent", "invented",
        "not a real", "does not exist",
    ],
    FailureCategory.TEST_MISUNDERSTANDING: [
        "test failed", "assertion", "expected", "test expectation",
        "spec mismatch", "wrong behavior",
    ],
    FailureCategory.DEPENDENCY_PROBLEM: [
        "import error", "module not found", "no module named",
        "version conflict", "incompatible", "missing dependency",
    ],
    FailureCategory.TIMEOUT: [
        "timeout", "timed out", "deadline", "slow", "hang",
    ],
    FailureCategory.INFINITE_LOOP: [
        "infinite", "looping", "stuck", "repeating", "circular",
    ],
    FailureCategory.REGRESSION: [
        "regression", "previously working", "used to work", "broke",
        "reverted", "rollback needed",
    ],
    FailureCategory.MODEL_LIMITATION: [
        "token limit", "context length", "model capacity",
        "out of memory", "model unavailable",
    ],
}


class FailureMiner:
    """Classifies failures from trace lake into prioritised categories.

    Usage:
        miner = FailureMiner()
        priorities = miner.analyze_failures()
        miner.store_classifications(priorities)
    """

    def __init__(
        self,
        lake: TraceLake | None = None,
        db_path: str | Path | None = None,
    ) -> None:
        self._lake = lake or get_trace_lake()
        self.db_path = Path(db_path) if db_path else Path(DEFAULT_DB_PATH)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._patterns = self._build_patterns()
        self._init_schema()
    def _init_schema(self) -> None:
        """Create failure_classification table if it doesn't exist."""
        conn = _connect(self.db_path)
        try:
            conn.execute("BEGIN")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS failure_classification (
                    id              TEXT PRIMARY KEY,
                    category        TEXT NOT NULL,
                    frequency       REAL,
                    impact          REAL,
                    repairability   REAL,
                    priority_score  REAL,
                    affected_tasks  TEXT,
                    evidence        TEXT,
                    last_seen       TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fail_cat ON failure_classification(category)"
            )
            conn.commit()
        finally:
            conn.close()

    def _build_patterns(self) -> list[tuple[FailureCategory, re.Pattern[str]]]:
        """Compile regex patterns for each failure category with word boundaries.

        Single-word keywords get word-boundary protection to avoid
        partial matches (e.g., 'expected' matching 'unexpected').
        Multi-word keywords are matched as exact substrings.
        """
        patterns: list[tuple[FailureCategory, re.Pattern[str]]] = []
        for category, keywords in _FAILURE_PATTERNS.items():
            parts: list[str] = []
            for kw in keywords:
                if " " in kw:
                    # Multi-word: exact substring (already escaped)
                    parts.append(re.escape(kw))
                else:
                    # Single word: word-boundary match
                    parts.append(r"\b" + re.escape(kw) + r"\b")
            combined = "|".join(parts)
            patterns.append((category, re.compile(combined, re.IGNORECASE)))
        return patterns

    def classify_error(
        self,
        error_text: str,
        context: dict[str, Any] | None = None,
    ) -> FailureCategory:
        """Classify a single error into a FailureCategory.

        Uses keyword matching against error text, trace metadata, and component info.
        Falls back to FailureCategory.UNKNOWN.
        """
        full_text = error_text or ""
        if context:
            full_text += " " + json.dumps(context, default=str)

        best_category: FailureCategory = FailureCategory.UNKNOWN
        best_score: int = 0

        for category, pattern in self._patterns:
            matches = len(pattern.findall(full_text))
            if matches > best_score:
                best_score = matches
                best_category = category

        # Structural heuristics if keyword matching found nothing
        if best_score == 0:
            best_category = self._structural_classify(error_text, context)

        return best_category

    def _structural_classify(
        self,
        error_text: str,
        context: dict[str, Any] | None,
    ) -> FailureCategory:
        """Use structured trace info to classify when keyword matching fails."""
        if not context:
            return FailureCategory.UNKNOWN

        component = str(context.get("component_kind", "")).lower()
        task_type = str(context.get("task_type", "")).lower()
        error_type = str(context.get("error_type", "")).lower()
        full_text = (error_text or "").lower()

        # Check error text for type-based classification
        if any(k in error_type for k in ("syntax", "type", "value", "attribute", "name")):
            return FailureCategory.INCORRECT_CODE
        if "planner" in component:
            return FailureCategory.BAD_PLANNING
        if "memory" in component:
            return FailureCategory.MEMORY_RETRIEVAL_ERROR
        if "tool" in component:
            return FailureCategory.TOOL_SELECTION_ERROR
        if "timeout" in error_type or "timeout" in full_text:
            return FailureCategory.TIMEOUT

        # Use task_type as a hint
        if "code" in task_type:
            return FailureCategory.INCORRECT_CODE
        if "plan" in task_type:
            return FailureCategory.BAD_PLANNING

        return FailureCategory.UNKNOWN

    def analyze_failures(
        self,
        component_kind: str | None = None,
        time_window_hours: int = 24,
    ) -> list[FailurePriority]:
        """Analyze traces in the lake and return prioritised failure categories.

        Args:
            component_kind: If set, only analyze failures for this component.
            time_window_hours: How far back to look in the trace lake.

        Returns:
            List of FailurePriority, sorted by priority_score descending.
        """
        # Compute "after" timestamp for time window
        after = None
        if time_window_hours > 0:
            cutoff = datetime.now(UTC) - timedelta(hours=time_window_hours)
            after = cutoff.isoformat()

        traces = self._lake.query_traces(
            success=False,
            component_kind=component_kind,
            after=after,
            limit=500,
        )

        if not traces:
            logger.info("No failed traces in lake for analysis")
            return []

        # Count failures per category
        category_counts: Counter[FailureCategory] = Counter()
        category_tasks: dict[FailureCategory, list[str]] = defaultdict(list)
        category_evidence: dict[FailureCategory, list[str]] = defaultdict(list)

        total_tasks = len(traces)

        for row in traces:
            error_text = row.get("result_error") or row.get("result_output") or ""
            trace_context = {
                "component_kind": row.get("component_kind", ""),
                "task_type": row.get("task_type", ""),
                "category": row.get("category", ""),
                "model_name": row.get("model_name", ""),
            }
            category = self.classify_error(error_text, trace_context)
            category_counts[category] += 1
            task_id = row.get("task_id", "")
            if task_id and task_id not in category_tasks[category]:
                category_tasks[category].append(task_id)
            if error_text and len(category_evidence[category]) < 5:
                category_evidence[category].append(error_text[:200])

        priorities: list[FailurePriority] = []
        for category, count in category_counts.items():
            if category == FailureCategory.UNKNOWN:
                continue  # Skip unclassified failures

            frequency = count / total_tasks if total_tasks else 0
            impact = self._estimate_impact(category)
            repairability = self._estimate_repairability(category)
            priority_score = frequency * impact * repairability

            priority = FailurePriority(
                category=category,
                frequency=frequency,
                impact=impact,
                repairability=repairability,
                priority_score=priority_score,
                affected_tasks=category_tasks[category],
                evidence=str(category_evidence[category][:3]),
            )
            priorities.append(priority)

        # Sort by priority score descending
        priorities.sort(key=lambda p: p.priority_score, reverse=True)
        return priorities

    def _estimate_impact(self, category: FailureCategory) -> float:
        """Estimate the impact (0-1) of failures in this category."""
        impact_map: dict[FailureCategory, float] = {
            FailureCategory.REGRESSION: 1.0,
            FailureCategory.INCORRECT_CODE: 0.95,
            FailureCategory.HALLUCINATED_API: 0.95,
            FailureCategory.BAD_PLANNING: 0.90,
            FailureCategory.INSUFFICIENT_CONTEXT: 0.85,
            FailureCategory.TOO_MANY_CALLS: 0.80,
            FailureCategory.DEPENDENCY_PROBLEM: 0.75,
            FailureCategory.TOOL_SELECTION_ERROR: 0.70,
            FailureCategory.TEST_MISUNDERSTANDING: 0.70,
            FailureCategory.TIMEOUT: 0.60,
            FailureCategory.INFINITE_LOOP: 0.95,
            FailureCategory.MEMORY_RETRIEVAL_ERROR: 0.65,
            FailureCategory.MODEL_LIMITATION: 0.50,
            FailureCategory.UNKNOWN: 0.3,
        }
        return impact_map.get(category, 0.3)

    def _estimate_repairability(self, category: FailureCategory) -> float:
        """Estimate how easily this failure category can be fixed (0-1)."""
        repairability_map: dict[FailureCategory, float] = {
            FailureCategory.REGRESSION: 0.90,
            FailureCategory.BAD_PLANNING: 0.75,
            FailureCategory.TOO_MANY_CALLS: 0.85,
            FailureCategory.TOOL_SELECTION_ERROR: 0.70,
            FailureCategory.MEMORY_RETRIEVAL_ERROR: 0.65,
            FailureCategory.HALLUCINATED_API: 0.55,
            FailureCategory.TEST_MISUNDERSTANDING: 0.50,
            FailureCategory.INSUFFICIENT_CONTEXT: 0.45,
            FailureCategory.MODEL_LIMITATION: 0.40,
            FailureCategory.DEPENDENCY_PROBLEM: 0.35,
            FailureCategory.TIMEOUT: 0.30,
            FailureCategory.INFINITE_LOOP: 0.20,
            FailureCategory.INCORRECT_CODE: 0.25,
        }
        return repairability_map.get(category, 0.3)

    def store_classifications(self, priorities: list[FailurePriority]) -> None:
        """Persist failure classifications to the database."""
        conn = _connect(self.db_path)
        try:
            conn.execute("BEGIN")
            for p in priorities:
                conn.execute(
                    "INSERT OR REPLACE INTO failure_classification "
                    "(id, category, frequency, impact, repairability, priority_score, "
                    " affected_tasks, evidence, last_seen) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"fc-{int(time.time() * 1000)}-{p.category.value}",
                        p.category.value,
                        p.frequency,
                        p.impact,
                        p.repairability,
                        p.priority_score,
                        json.dumps(p.affected_tasks),
                        p.evidence,
                        _utcnow_iso(),
                    ),
                )
            conn.commit()
        finally:
            conn.close()

    def get_failure_summary(self) -> dict[str, Any]:
        """Get summary of stored failure classifications."""
        conn = _connect(self.db_path)
        try:
            rows = conn.execute(
                "SELECT * FROM failure_classification ORDER BY priority_score DESC LIMIT 20"
            ).fetchall()
            return {
                "classifications": [dict(row) for row in rows],
                "total_classified": len(rows),
            }
        finally:
            conn.close()
