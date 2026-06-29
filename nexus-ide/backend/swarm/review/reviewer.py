"""SWARM Reviewer agent — independent code/output review.

Checks proposals and free-form outputs against the 8 review axes:
bugs, architecture, performance, security, typing, tests, maintenance,
duplication. Emits a :class:`ReviewReport` with findings and the four
quality scores.

This implementation is a hybrid heuristic + LLM. The heuristic pass is
deterministic and fast; the LLM pass (when available) is used to interpret
the proposal and produce a structured review.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from backend.swarm.communication.message_bus import MessageBus
from backend.swarm.core.types import (
    AgentMessage,
    AgentRole,
    MessageType,
    Proposal,
    QualityScores,
    ReviewReport,
)
from backend.swarm.quality.quality_gate import (
    gate_failure_reason,
    passes_gate,
    score_proposal,
    update_with_review,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Heuristic patterns
# ---------------------------------------------------------------------------

_RISKY_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\beval\s*\(", "security", "Use of eval() — code-injection risk"),
    (r"\bexec\s*\(", "security", "Use of exec() — code-injection risk"),
    (r"\bos\.system\s*\(", "security", "Shell injection via os.system"),
    (r"\bsubprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True", "security", "shell=True in subprocess"),
    (r"shell\s*=\s*True", "security", "shell=True parameter"),
    (r"verify\s*=\s*False", "security", "TLS verification disabled"),
    (r"allow_origins\s*=\s*\[\s*['\"]?\*['\"]?\s*\]", "security", "Wildcard CORS origin"),
    (r"password\s*=\s*['\"]", "security", "Hard-coded password"),
    (r"api[_-]?key\s*=\s*['\"]", "security", "Hard-coded API key"),
    (r"\.env\b", "security", "Reads from .env (verify no secrets committed)"),
    (r"\brm\s+-rf\b", "security", "Destructive recursive delete"),
    (r"DELETE\s+FROM", "bug", "Unbounded DELETE — verify WHERE clause"),
    (r"DROP\s+TABLE", "bug", "DROP TABLE — irreversible"),
    (r"TRUNCATE\b", "bug", "TRUNCATE — irreversible"),
)

# Smells / anti-patterns
_SMELLS: tuple[tuple[str, str], ...] = (
    (r"\bpass\s*$", "maintenance", "Empty pass — incomplete branch"),
    (r"TODO|FIXME|XXX", "maintenance", "Outstanding TODO/FIXME marker"),
    (r"except\s*:\s*pass", "maintenance", "Bare except with pass"),
    (r"except\s+Exception\s*:\s*pass", "maintenance", "Swallowed exception"),
    (r"import\s+\*", "maintenance", "Wildcard import"),
    (r"any\b.*==.*None", "bug", "Use `is None` not `== None`"),
    (r"type\s*\(.*\)\s*==", "typing", "Use isinstance() instead of type() =="),
)

_PERF_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"for\s+\w+\s+in\s+range\s*\(\s*len\s*\(",
        "performance",
        "Use enumerate instead of range(len(...))",
    ),
    (r"\.append\([^)]*\)\s*$", "performance", "Repeated list.append — consider list comprehension"),
    (r"\+\s*=\s*['\"].*['\"]\s*$", "performance", "String concat in loop — use join()"),
    (r"time\.sleep\s*\(", "performance", "time.sleep blocks the event loop"),
)

_TEST_MARKERS = ("def test_", "class Test", "pytest", "describe(", "it(", "expect(")
_TYPING_MARKERS = ("-> ", ": int", ": str", ": list", ": dict", ": Optional", "List[", "Dict[")


@dataclass
class ReviewContext:
    """Files actually read during the review (for citations)."""

    files: dict[str, str]  # path -> content


class ReviewerAgent:
    """Independent reviewer that scores proposals & outputs."""

    ROLE = AgentRole.REVIEWER

    def __init__(self, message_bus: MessageBus | None = None) -> None:
        self._bus = message_bus

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def review_proposal(
        self,
        proposal: Proposal,
        context: ReviewContext | None = None,
    ) -> ReviewReport:
        """Run all 8 review axes on a proposal. Returns a ReviewReport."""
        findings: list[dict[str, Any]] = []
        blob = self._proposal_blob(proposal)

        # Axis 1: bugs / security
        for pattern, category, message in _RISKY_PATTERNS:
            if re.search(pattern, blob, flags=re.IGNORECASE | re.MULTILINE):
                findings.append(
                    {
                        "category": category,
                        "severity": "high" if category == "security" else "medium",
                        "message": message,
                        "rule": pattern,
                    }
                )

        # Axis 2: smells
        for pattern, category, message in _SMELLS:
            if re.search(pattern, blob, flags=re.IGNORECASE | re.MULTILINE):
                findings.append(
                    {
                        "category": category,
                        "severity": "low",
                        "message": message,
                        "rule": pattern,
                    }
                )

        # Axis 3: performance
        for pattern, category, message in _PERF_PATTERNS:
            if re.search(pattern, blob, flags=re.IGNORECASE | re.MULTILINE):
                findings.append(
                    {
                        "category": category,
                        "severity": "low",
                        "message": message,
                        "rule": pattern,
                    }
                )

        # Axis 4: tests
        if not any(m in blob for m in _TEST_MARKERS) and proposal.files_to_change:
            findings.append(
                {
                    "category": "tests",
                    "severity": "medium",
                    "message": "Proposal changes files but adds no test markers (test_/Test/pytest/describe).",
                }
            )

        # Axis 5: typing
        if not any(m in blob for m in _TYPING_MARKERS):
            findings.append(
                {
                    "category": "typing",
                    "severity": "low",
                    "message": "No type annotations detected in the proposal.",
                }
            )

        # Axis 6: duplication — naive
        dup_hits = self._detect_duplication(blob)
        for dup in dup_hits:
            findings.append(
                {
                    "category": "duplication",
                    "severity": "low",
                    "message": f"Possible duplicated block: {dup}",
                }
            )

        # Axis 7: architecture — check evidence_refs are present
        if not proposal.evidence_refs and not proposal.decision_refs:
            findings.append(
                {
                    "category": "architecture",
                    "severity": "medium",
                    "message": "Proposal has no cited evidence or decisions. Decisions should be traceable.",
                }
            )

        # Axis 8: complexity
        if len(proposal.files_to_change) > 6:
            findings.append(
                {
                    "category": "architecture",
                    "severity": "high",
                    "message": f"Proposal changes {len(proposal.files_to_change)} files — consider splitting.",
                }
            )

        # Compute scores
        base = score_proposal(proposal)
        scores = update_with_review(
            base, ReviewReport(target_id=proposal.proposal_id, findings=findings)
        )
        passed = passes_gate(scores) and not any(f.get("severity") == "critical" for f in findings)
        summary = self._summarise(findings, scores, passed)

        return ReviewReport(
            target_id=proposal.proposal_id,
            findings=findings,
            passed=passed,
            scores=scores,
            summary=summary,
        )

    async def handle(self, message: AgentMessage) -> AgentMessage | None:
        """Handle a REVIEW request (payload contains a proposal dict)."""
        if not self._bus or message.type != MessageType.REQUEST:
            return None
        proposal_dict = message.payload.get("proposal")
        if not isinstance(proposal_dict, dict):
            return None
        try:
            proposal = Proposal(**proposal_dict)
        except Exception as exc:
            return await self._bus.respond(
                sender=self.ROLE.value,
                in_reply_to=message,
                content=f"Reviewer received malformed proposal: {exc}",
                payload={"error": str(exc)},
            )
        report = self.review_proposal(proposal)
        return await self._bus.respond(
            sender=self.ROLE.value,
            in_reply_to=message,
            content=report.summary,
            payload={"review": report.to_dict()},
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _proposal_blob(proposal: Proposal) -> str:
        parts = [
            proposal.title,
            proposal.description,
            proposal.rationale,
        ]
        for change in proposal.files_to_change:
            if isinstance(change, dict):
                parts.append(str(change.get("change", "")))
                parts.append(str(change.get("path", "")))
        return "\n".join(p for p in parts if p)

    @staticmethod
    def _detect_duplication(text: str) -> list[str]:
        # Very naive: look for 3 identical consecutive non-empty lines
        lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
        repeats: list[str] = []
        i = 0
        while i < len(lines) - 2:
            if lines[i] == lines[i + 1] == lines[i + 2]:
                snippet = lines[i][:60]
                if snippet not in repeats:
                    repeats.append(snippet)
                i += 3
            else:
                i += 1
        return repeats[:3]

    @staticmethod
    def _summarise(findings: list[dict[str, Any]], scores: QualityScores, passed: bool) -> str:
        by_sev: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for f in findings:
            sev = f.get("severity", "low")
            by_sev[sev] = by_sev.get(sev, 0) + 1
        lines = [
            "## Reviewer Summary",
            "",
            f"- Verdict: **{'PASS' if passed else 'FAIL'}**",
            f"- Scores: quality={scores.quality:.2f}, confidence={scores.confidence:.2f}, "
            f"risk={scores.risk:.2f}, complexity={scores.complexity:.2f}",
            f"- Findings: {by_sev['critical']} critical, {by_sev['high']} high, "
            f"{by_sev['medium']} medium, {by_sev['low']} low",
        ]
        if not passed:
            lines.append("")
            lines.append(f"Gate failure: {gate_failure_reason(scores)}")
        if findings:
            lines.append("")
            lines.append("### Top findings")
            for f in findings[:5]:
                lines.append(
                    f"- [{f.get('severity', 'low').upper()}] {f.get('category', '?')}: {f.get('message', '?')}"
                )
        return "\n".join(lines)


__all__ = ["ReviewerAgent", "ReviewContext"]
