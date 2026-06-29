"""META_ANALYZER — the ultimate synthesizer and gatekeeper.

Observes ALL other agents, detects contradictions, enforces strict quality
criteria, and acts as the final approval authority. Nothing is "done" until
META_ANALYZER approves.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.config.settings import REPO_ROOT
from backend.core.agent_bus import get_agent_bus

from .base import AgentAction, AgentBase, AgentRequest

logger = logging.getLogger(__name__)

EVOLUTION_LOG_PATH: Path = REPO_ROOT / "data" / "evolution_log.md"


class QualityCriteria:
    """Immutable quality thresholds enforced by META_ANALYZER."""

    TEST_COVERAGE_MIN = 90  # percent
    TEST_FAILURES_MAX = 0
    SECURITY_CRITICAL_MAX = 0
    SECURITY_HIGH_MAX = 0
    PERFORMANCE_REGRESSION_PCT = 10  # ±10% of baseline
    CYCLOMATIC_MAX_FUNCTION = 15
    CYCLOMATIC_MAX_FILE = 50
    LINT_ERRORS_MAX = 0
    DOCSTRING_REQUIRED_PUBLIC = True


class MetaAnalyzerAgent(AgentBase):
    """Synthesizer agent that observes all other agents and decides perfection."""

    name = "META_ANALYZER"
    model_key = "reasoning"
    prompt_file = "meta_analyzer"
    supported_actions = {
        AgentAction.READ_FILE,
        AgentAction.SEARCH_CODEBASE,
        AgentAction.CONSULT_AGENT,
        AgentAction.RECALL_CONTEXT,
        AgentAction.ANALYZE_DATA,
        AgentAction.GENERATE_REPORT,
    }

    # Known agents to observe (excluding self to avoid recursion)
    _OBSERVED_AGENTS: set[str] = {
        "ARCHITECT",
        "RESEARCHER",
        "CODER",
        "ANALYZER",
        "DEBUGGER",
        "DOCUMENTER",
        "OPTIMIZER",
        "MICRO",
        "DASHBOARD",
        "SUPERVISOR",
        "GUARDIAN",
    }

    def __init__(self) -> None:
        super().__init__()
        self._last_report: dict[str, Any] | None = None
        self._ensure_evolution_log()

    def _ensure_evolution_log(self) -> None:
        """Create the evolution log if it does not exist."""
        if not EVOLUTION_LOG_PATH.exists():
            EVOLUTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            EVOLUTION_LOG_PATH.write_text(
                "# NEXUS IDE Evolution Log\n\n"
                "This file tracks all major architectural and quality decisions "
                "made by the META_ANALYZER agent.\n\n"
                "---\n\n",
                encoding="utf-8",
            )

    # ------------------------------------------------------------------
    # AgentBase contract
    # ------------------------------------------------------------------

    async def _execute(self, request: AgentRequest) -> AsyncIterator[str]:
        """Run META_ANALYZER with ReAct loop for deep synthesis."""
        # Pre-load context from other agents via the bus
        synthesis_context = await self._gather_agent_outputs(request.session_id)
        if synthesis_context:
            enriched_query = (
                f"{request.query}\n\n### Context from other agents:\n{synthesis_context}"
            )
        else:
            enriched_query = request.query

        # Build a modified request with enriched query
        from dataclasses import replace

        enriched_request = replace(request, query=enriched_query)

        async for token in self._run_react_loop(enriched_request):
            yield token

    # ------------------------------------------------------------------
    # Synthesis helpers
    # ------------------------------------------------------------------

    async def _gather_agent_outputs(self, session_id: str) -> str:
        """Collect recent messages from observed agents on the Agent Bus."""
        bus = get_agent_bus()
        contexts: list[str] = []

        for topic in (
            "code.changes",
            "test.results",
            "errors.found",
            "architecture.proposals",
            "review.completed",
            "agent.status",
        ):
            try:
                messages = await bus.get_history(topic, limit=20)
                for msg in messages:
                    if msg.source_agent in self._OBSERVED_AGENTS:
                        payload = json.dumps(msg.payload, default=str)
                        contexts.append(f"[{msg.source_agent} @ {topic}] {payload}")
            except Exception as exc:
                logger.debug("Failed to gather bus history for %s: %s", topic, exc)

        if not contexts:
            return ""

        return "\n".join(contexts[-50:])  # cap context length

    # ------------------------------------------------------------------
    # Quality criteria
    # ------------------------------------------------------------------

    def evaluate_quality(self, metrics: dict[str, Any]) -> dict[str, Any]:
        """Evaluate a metrics dict against the strict quality criteria.

        Returns a structured verdict with pass/fail per category.
        """
        verdict: dict[str, Any] = {
            "overall": "PASS",
            "categories": {},
            "violations": [],
        }

        # Tests
        coverage = metrics.get("test_coverage_percent", 0)
        failures = metrics.get("test_failures", 0)
        test_pass = (
            coverage >= QualityCriteria.TEST_COVERAGE_MIN
            and failures <= QualityCriteria.TEST_FAILURES_MAX
        )
        verdict["categories"]["tests"] = {
            "pass": test_pass,
            "coverage": coverage,
            "failures": failures,
        }
        if not test_pass:
            verdict["overall"] = "FAIL"
            if coverage < QualityCriteria.TEST_COVERAGE_MIN:
                verdict["violations"].append(
                    f"Test coverage {coverage}% < required {QualityCriteria.TEST_COVERAGE_MIN}%"
                )
            if failures > QualityCriteria.TEST_FAILURES_MAX:
                verdict["violations"].append(
                    f"Test failures {failures} > max {QualityCriteria.TEST_FAILURES_MAX}"
                )

        # Security
        critical = metrics.get("security_critical", 0)
        high = metrics.get("security_high", 0)
        sec_pass = (
            critical <= QualityCriteria.SECURITY_CRITICAL_MAX
            and high <= QualityCriteria.SECURITY_HIGH_MAX
        )
        verdict["categories"]["security"] = {
            "pass": sec_pass,
            "critical": critical,
            "high": high,
        }
        if not sec_pass:
            verdict["overall"] = "FAIL"
            if critical > QualityCriteria.SECURITY_CRITICAL_MAX:
                verdict["violations"].append(
                    f"Security critical issues {critical} > max {QualityCriteria.SECURITY_CRITICAL_MAX}"
                )
            if high > QualityCriteria.SECURITY_HIGH_MAX:
                verdict["violations"].append(
                    f"Security high issues {high} > max {QualityCriteria.SECURITY_HIGH_MAX}"
                )

        # Performance
        perf_regression = metrics.get("performance_regression_percent", 0)
        perf_pass = abs(perf_regression) <= QualityCriteria.PERFORMANCE_REGRESSION_PCT
        verdict["categories"]["performance"] = {
            "pass": perf_pass,
            "regression_percent": perf_regression,
        }
        if not perf_pass:
            verdict["overall"] = "FAIL"
            verdict["violations"].append(
                f"Performance regression {perf_regression}% exceeds ±{QualityCriteria.PERFORMANCE_REGRESSION_PCT}%"
            )

        # Complexity
        cc_func = metrics.get("cyclomatic_max_function", 0)
        cc_file = metrics.get("cyclomatic_max_file", 0)
        complexity_pass = (
            cc_func <= QualityCriteria.CYCLOMATIC_MAX_FUNCTION
            and cc_file <= QualityCriteria.CYCLOMATIC_MAX_FILE
        )
        verdict["categories"]["complexity"] = {
            "pass": complexity_pass,
            "max_function": cc_func,
            "max_file": cc_file,
        }
        if not complexity_pass:
            verdict["overall"] = "FAIL"
            if cc_func > QualityCriteria.CYCLOMATIC_MAX_FUNCTION:
                verdict["violations"].append(
                    f"Cyclomatic complexity per function {cc_func} > max {QualityCriteria.CYCLOMATIC_MAX_FUNCTION}"
                )
            if cc_file > QualityCriteria.CYCLOMATIC_MAX_FILE:
                verdict["violations"].append(
                    f"Cyclomatic complexity per file {cc_file} > max {QualityCriteria.CYCLOMATIC_MAX_FILE}"
                )

        # Style
        lint_errors = metrics.get("lint_errors", 0)
        style_pass = lint_errors <= QualityCriteria.LINT_ERRORS_MAX
        verdict["categories"]["style"] = {
            "pass": style_pass,
            "lint_errors": lint_errors,
        }
        if not style_pass:
            verdict["overall"] = "FAIL"
            verdict["violations"].append(
                f"Lint errors {lint_errors} > max {QualityCriteria.LINT_ERRORS_MAX}"
            )

        # Documentation
        missing_docs = metrics.get("missing_docstrings", 0)
        doc_pass = missing_docs == 0 if QualityCriteria.DOCSTRING_REQUIRED_PUBLIC else True
        verdict["categories"]["documentation"] = {
            "pass": doc_pass,
            "missing_docstrings": missing_docs,
        }
        if not doc_pass:
            verdict["overall"] = "FAIL"
            verdict["violations"].append(f"Missing docstrings on {missing_docs} public functions")

        return verdict

    # ------------------------------------------------------------------
    # Contradiction detection
    # ------------------------------------------------------------------

    def detect_contradictions(
        self, agent_outputs: dict[str, dict[str, Any]]
    ) -> list[dict[str, str]]:
        """Detect contradictions between agent outputs.

        Example: ARCHITECT says "use microservices" but ANALYZER says "too complex".
        """
        contradictions: list[dict[str, str]] = []

        # Simple heuristic: look for keyword oppositions
        oppositions: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
            (("microservices", "distributed"), ("monolith", "single process")),
            (("add complexity", "complex"), ("simplify", "reduce complexity")),
            (("sync", "synchronous"), ("async", "asynchronous")),
            (("relational", "sql"), ("nosql", "document")),
            (("optimistic",), ("pessimistic",)),
        ]

        texts: dict[str, str] = {}
        for agent, output in agent_outputs.items():
            content = output.get("content", "")
            if not content and "payload" in output:
                content = json.dumps(output["payload"])
            texts[agent] = content.lower()

        for pos_set, neg_set in oppositions:
            pos_agents = [a for a, t in texts.items() if any(p in t for p in pos_set)]
            neg_agents = [a for a, t in texts.items() if any(n in t for n in neg_set)]
            if pos_agents and neg_agents:
                contradictions.append(
                    {
                        "type": "architectural_opposition",
                        "description": f"Agents advocate opposing strategies: {pos_set} vs {neg_set}",
                        "agents_for": ", ".join(pos_agents),
                        "agents_against": ", ".join(neg_agents),
                        "recommendation": "Schedule a focused debate or escalate to human review.",
                    }
                )

        # Check for direct conflict in metrics
        if "ARCHITECT" in agent_outputs and "ANALYZER" in agent_outputs:
            arch_complexity = agent_outputs["ARCHITECT"].get("estimated_complexity", 0)
            anal_complexity = agent_outputs["ANALYZER"].get("estimated_complexity", 0)
            if arch_complexity and anal_complexity and abs(arch_complexity - anal_complexity) >= 4:
                contradictions.append(
                    {
                        "type": "complexity_mismatch",
                        "description": f"ARCHITECT estimates complexity {arch_complexity}, ANALYZER estimates {anal_complexity}",
                        "agents_for": "ARCHITECT",
                        "agents_against": "ANALYZER",
                        "recommendation": "Re-evaluate scope assumptions and refine estimates.",
                    }
                )

        return contradictions

    # ------------------------------------------------------------------
    # Evolution log
    # ------------------------------------------------------------------

    def log_evolution_entry(
        self,
        decision: str,
        rationale: str,
        agents_involved: list[str],
        quality_verdict: dict[str, Any] | None = None,
    ) -> None:
        """Append a major decision to the evolution log."""
        timestamp = datetime.now(UTC).isoformat()
        entry = [
            f"## Decision: {decision}",
            "",
            f"- **Timestamp:** {timestamp}",
            f"- **Agents involved:** {', '.join(agents_involved)}",
            f"- **Rationale:** {rationale}",
        ]
        if quality_verdict:
            entry.append(f"- **Quality verdict:** {quality_verdict.get('overall', 'UNKNOWN')}")
            if quality_verdict.get("violations"):
                entry.append("- **Violations:**")
                for v in quality_verdict["violations"]:
                    entry.append(f"  - {v}")
        entry.extend(["", "---", ""])

        try:
            with EVOLUTION_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(entry) + "\n")
            logger.info("Evolution log updated: %s", decision)
        except Exception as exc:
            logger.warning("Failed to write evolution log: %s", exc)

    # ------------------------------------------------------------------
    # Report helpers
    # ------------------------------------------------------------------

    def build_approval_report(
        self,
        verdict: dict[str, Any],
        contradictions: list[dict[str, str]],
        recommendations: list[str],
    ) -> str:
        """Build a structured approval/denial report."""
        approved = verdict.get("overall") == "PASS"
        lines = [
            "# META_ANALYZER Gatekeeper Report",
            "",
            f"## Overall Verdict: {'✅ APPROVED' if approved else '❌ DENIED'}",
            "",
            "### Quality Criteria Breakdown",
            "",
        ]

        for category, result in verdict.get("categories", {}).items():
            icon = "✅" if result.get("pass") else "❌"
            lines.append(f"- {icon} **{category.upper()}**")
            for k, v in result.items():
                if k != "pass":
                    lines.append(f"  - {k}: {v}")

        if contradictions:
            lines.extend(["", "### ⚠️ Contradictions Detected", ""])
            for i, c in enumerate(contradictions, 1):
                lines.append(f"{i}. **{c['type']}**")
                lines.append(f"   - {c['description']}")
                lines.append(f"   - Recommendation: {c['recommendation']}")

        if recommendations:
            lines.extend(["", "### Integration Proposals", ""])
            for i, r in enumerate(recommendations, 1):
                lines.append(f"{i}. {r}")

        lines.extend(["", "### Required Action Items", ""])
        if verdict.get("violations"):
            for v in verdict["violations"]:
                lines.append(f"- [ ] {v}")
        else:
            lines.append("- None — all criteria satisfied.")

        return "\n".join(lines)
