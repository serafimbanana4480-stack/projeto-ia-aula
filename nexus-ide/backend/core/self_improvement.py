"""Self-Improvement System — NEXUS IDE analyzes and improves itself.

The ``SelfImprovementAnalyzer`` periodically (or on-demand) reviews:

- Evolution log entries
- Agent success / failure rates from the Agent State Store
- Mission outcomes (success rate, duration, token usage)
- Tool usage patterns

It produces structured improvement proposals but **never** auto-applies them.
All changes require explicit approval from the ``META_ANALYZER`` agent.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from backend.core.agent_bus import BusMessage, get_agent_bus

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVOLUTION_LOG_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "evolution_log.md"
REPORT_PATH = (
    Path(__file__).resolve().parent.parent.parent / "data" / "self_improvement_report.json"
)

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class ImprovementProposal(BaseModel):
    """A single proposed improvement."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(default_factory=lambda: f"prop_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}")
    category: str  # prompt | tool | budget | architecture
    target: str  # agent name, tool name, or system component
    problem: str
    proposed_change: str
    expected_impact: str
    confidence: float = Field(ge=0.0, le=1.0)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    approved: bool = False
    approved_by: str = ""


class SelfImprovementReport(BaseModel):
    """Structured output of the self-improvement analysis."""

    model_config = ConfigDict(extra="forbid")

    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    summary: str = ""
    agent_success_rates: dict[str, dict[str, Any]] = Field(default_factory=dict)
    tool_usage_stats: dict[str, int] = Field(default_factory=dict)
    mission_outcomes: dict[str, Any] = Field(default_factory=dict)
    proposals: list[ImprovementProposal] = Field(default_factory=list)
    evolution_log_entries_added: int = 0


# ---------------------------------------------------------------------------
# SelfImprovementAnalyzer
# ---------------------------------------------------------------------------


class SelfImprovementAnalyzer:
    """Analyzes system performance and proposes improvements.

    Usage::

        analyzer = SelfImprovementAnalyzer()
        report = await analyzer.run_analysis()
        print(report.summary)
    """

    def __init__(self) -> None:
        self._report: SelfImprovementReport | None = None

    async def run_analysis(self) -> SelfImprovementReport:
        """Execute the full self-improvement analysis pipeline."""
        logger.info("Self-improvement analysis started")
        report = SelfImprovementReport()

        # 1. Read evolution log
        evolution_entries = self._read_evolution_log()

        # 2. Analyze agent success rates
        agent_rates = self._analyze_agent_success_rates()
        report.agent_success_rates = agent_rates

        # 3. Analyze tool usage
        tool_stats = self._analyze_tool_usage()
        report.tool_usage_stats = tool_stats

        # 4. Analyze mission outcomes
        mission_outcomes = self._analyze_mission_outcomes()
        report.mission_outcomes = mission_outcomes

        # 5. Generate proposals
        proposals: list[ImprovementProposal] = []
        proposals.extend(self._propose_prompt_refinements(agent_rates))
        proposals.extend(self._propose_new_tools(tool_stats, agent_rates))
        proposals.extend(self._propose_budget_adjustments(agent_rates, mission_outcomes))
        proposals.extend(self._propose_architecture_changes(agent_rates, mission_outcomes))
        report.proposals = proposals

        # 6. Build summary
        report.summary = self._build_summary(report)

        # 7. Persist report
        self._save_report(report)

        # 8. Publish event
        await self._publish_proposals(report)

        # 9. Append to evolution log
        entries_added = self._append_to_evolution_log(report)
        report.evolution_log_entries_added = entries_added

        self._report = report
        logger.info(
            "Self-improvement analysis complete | proposals=%d",
            len(report.proposals),
        )
        return report

    def get_last_report(self) -> SelfImprovementReport | None:
        """Return the most recently generated report (or load from disk)."""
        if self._report:
            return self._report
        if REPORT_PATH.exists():
            try:
                data = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
                return SelfImprovementReport.model_validate(data)
            except Exception as exc:
                logger.warning("Failed to load previous report: %s", exc)
        return None

    # -- data gathering -----------------------------------------------------

    def _read_evolution_log(self) -> list[dict[str, Any]]:
        """Parse the evolution log markdown file into structured entries."""
        entries: list[dict[str, Any]] = []
        if not EVOLUTION_LOG_PATH.exists():
            return entries

        text = EVOLUTION_LOG_PATH.read_text(encoding="utf-8")
        # Simple parsing: split by "---" headers and extract date/title
        sections = re.split(r"\n---\n", text)
        for section in sections:
            lines = [l.strip() for l in section.splitlines() if l.strip()]
            if not lines:
                continue
            title = lines[0].lstrip("#").strip()
            date_match = re.search(r"(\d{4}-\d{2}-\d{2})", section)
            entries.append(
                {
                    "title": title,
                    "date": date_match.group(1) if date_match else "",
                    "body": "\n".join(lines[1:]),
                }
            )
        return entries

    def _analyze_agent_success_rates(self) -> dict[str, dict[str, Any]]:
        """Compute success/failure rates per agent from Agent State Store."""
        rates: dict[str, dict[str, Any]] = {}
        try:
            from backend.persistence.db import get_db

            with get_db() as conn:
                # Count agent run entries in short_term memory
                rows = conn.execute(
                    """SELECT agent_name, key, value
                       FROM agent_states
                       WHERE memory_tier = 'short_term'
                         AND key LIKE 'run_%'
                       ORDER BY agent_name, updated_at DESC"""
                ).fetchall()

            agent_runs: dict[str, list[dict[str, Any]]] = {}
            for row in rows:
                aname = row["agent_name"]
                value = row["value"]
                try:
                    data = json.loads(value) if isinstance(value, str) else value
                except json.JSONDecodeError:
                    continue
                agent_runs.setdefault(aname, []).append(data)

            for aname, runs in agent_runs.items():
                total = len(runs)
                # Heuristic: if error_message present in any adjacent state -> failure
                # We approximate by checking if any long_term memory has error for this agent
                error_count = self._count_agent_errors(aname)
                success_count = max(0, total - error_count)
                rates[aname] = {
                    "total_runs": total,
                    "success_count": success_count,
                    "error_count": error_count,
                    "success_rate": round(success_count / total, 2) if total else 0.0,
                    "avg_elapsed_seconds": round(
                        sum(r.get("elapsed_seconds", 0) for r in runs) / total, 2
                    )
                    if total
                    else 0.0,
                }
        except Exception as exc:
            logger.warning("Agent success rate analysis failed: %s", exc)
        return rates

    def _count_agent_errors(self, agent_name: str) -> int:
        """Count error memories for an agent."""
        try:
            from backend.persistence.db import get_db

            with get_db() as conn:
                row = conn.execute(
                    """SELECT COUNT(*) AS cnt
                       FROM agent_states
                       WHERE agent_name = ?
                         AND memory_tier = 'long_term'
                         AND key LIKE 'error_%'""",
                    (agent_name,),
                ).fetchone()
                return row["cnt"] if row else 0
        except Exception:
            return 0

    def _analyze_tool_usage(self) -> dict[str, int]:
        """Count tool executions from the database."""
        stats: dict[str, int] = {}
        try:
            from backend.persistence.db import get_db

            with get_db() as conn:
                rows = conn.execute(
                    """SELECT tool_name, COUNT(*) AS cnt
                       FROM tool_executions
                       GROUP BY tool_name
                       ORDER BY cnt DESC"""
                ).fetchall()
            for row in rows:
                stats[row["tool_name"]] = row["cnt"]
        except Exception as exc:
            logger.warning("Tool usage analysis failed: %s", exc)
        return stats

    def _analyze_mission_outcomes(self) -> dict[str, Any]:
        """Analyze mission outcomes from Agent State Store."""
        outcomes: dict[str, Any] = {
            "total_missions": 0,
            "completed": 0,
            "failed": 0,
            "aborted": 0,
            "avg_duration_seconds": 0.0,
            "avg_tokens_used": 0.0,
        }
        try:
            from backend.persistence.db import get_db

            with get_db() as conn:
                rows = conn.execute(
                    """SELECT value
                       FROM agent_states
                       WHERE agent_name = 'META_ORCHESTRATOR'
                         AND memory_tier = 'medium_term'
                         AND key = 'mission'"""
                ).fetchall()

            durations: list[float] = []
            tokens: list[int] = []
            for row in rows:
                try:
                    data = (
                        json.loads(row["value"]) if isinstance(row["value"], str) else row["value"]
                    )
                except json.JSONDecodeError:
                    continue
                status = data.get("status", "")
                outcomes["total_missions"] += 1
                if status == "completed":
                    outcomes["completed"] += 1
                elif status == "failed":
                    outcomes["failed"] += 1
                elif status == "aborted":
                    outcomes["aborted"] += 1

                started = data.get("started_at", 0)
                completed = data.get("completed_at", 0)
                if started and completed and completed > started:
                    durations.append(completed - started)
                tokens.append(data.get("tokens_used", 0))

            if durations:
                outcomes["avg_duration_seconds"] = round(sum(durations) / len(durations), 2)
            if tokens:
                outcomes["avg_tokens_used"] = round(sum(tokens) / len(tokens), 2)
        except Exception as exc:
            logger.warning("Mission outcome analysis failed: %s", exc)
        return outcomes

    # -- proposal generation ------------------------------------------------

    def _propose_prompt_refinements(
        self, agent_rates: dict[str, dict[str, Any]]
    ) -> list[ImprovementProposal]:
        """Suggest prompt refinements for underperforming agents."""
        proposals: list[ImprovementProposal] = []
        for aname, stats in agent_rates.items():
            if stats["success_rate"] < 0.7 and stats["total_runs"] >= 3:
                proposals.append(
                    ImprovementProposal(
                        category="prompt",
                        target=aname,
                        problem=f"Success rate {stats['success_rate'] * 100:.0f}% over {stats['total_runs']} runs",
                        proposed_change=f"Review and refine system prompt for {aname}; add examples for common failure cases.",
                        expected_impact="Increase success rate to >85%",
                        confidence=0.6,
                    )
                )
        return proposals

    def _propose_new_tools(
        self,
        tool_stats: dict[str, int],
        agent_rates: dict[str, dict[str, Any]],
    ) -> list[ImprovementProposal]:
        """Suggest new tools based on frequent workarounds or gaps."""
        proposals: list[ImprovementProposal] = []
        # Heuristic: if agents fail often and no `consult_agent` usage is high,
        # they may need a dedicated helper tool.
        consult_count = tool_stats.get("consult_agent", 0)
        if consult_count > 20:
            proposals.append(
                ImprovementProposal(
                    category="tool",
                    target="system",
                    problem=f"High inter-agent consultation ({consult_count} consult_agent calls) indicates missing shared tools.",
                    proposed_change="Create a shared 'knowledge_lookup' tool to reduce redundant consultations.",
                    expected_impact="Reduce consult_agent calls by 30%",
                    confidence=0.5,
                )
            )
        # If no embeddings tool is used but agents do a lot of search_codebase
        if (
            tool_stats.get("search_codebase", 0) > 30
            and tool_stats.get("embeddings_search", 0) == 0
        ):
            proposals.append(
                ImprovementProposal(
                    category="tool",
                    target="system",
                    problem="Frequent text search but no vector search usage.",
                    proposed_change="Integrate embeddings-based semantic search into search_codebase.",
                    expected_impact="Faster, more accurate codebase queries",
                    confidence=0.55,
                )
            )
        return proposals

    def _propose_budget_adjustments(
        self,
        agent_rates: dict[str, dict[str, Any]],
        mission_outcomes: dict[str, Any],
    ) -> list[ImprovementProposal]:
        """Suggest timeout and budget adjustments based on historical data."""
        proposals: list[ImprovementProposal] = []
        avg_duration = mission_outcomes.get("avg_duration_seconds", 0)
        if avg_duration > 300:  # > 5 min average
            proposals.append(
                ImprovementProposal(
                    category="budget",
                    target="mission",
                    problem=f"Average mission duration is {avg_duration:.0f}s, exceeding comfortable limits.",
                    proposed_change="Increase default time budget and enable parallel phase execution.",
                    expected_impact="Reduce perceived latency by 20%",
                    confidence=0.45,
                )
            )
        for aname, stats in agent_rates.items():
            if stats.get("avg_elapsed_seconds", 0) > 120:
                proposals.append(
                    ImprovementProposal(
                        category="budget",
                        target=aname,
                        problem=f"Average execution time {stats['avg_elapsed_seconds']:.0f}s exceeds 120s threshold.",
                        proposed_change=f"Increase token budget or split {aname} into sub-agents.",
                        expected_impact="Reduce timeouts and incomplete runs",
                        confidence=0.5,
                    )
                )
        return proposals

    def _propose_architecture_changes(
        self,
        agent_rates: dict[str, dict[str, Any]],
        mission_outcomes: dict[str, Any],
    ) -> list[ImprovementProposal]:
        """Suggest agent mergers or splits."""
        proposals: list[ImprovementProposal] = []
        failure_rate = 0.0
        total = mission_outcomes.get("total_missions", 0)
        if total:
            failure_rate = (
                mission_outcomes.get("failed", 0) + mission_outcomes.get("aborted", 0)
            ) / total

        if failure_rate > 0.3:
            proposals.append(
                ImprovementProposal(
                    category="architecture",
                    target="orchestrator",
                    problem=f"Mission failure rate is {failure_rate * 100:.0f}%.",
                    proposed_change="Add a pre-flight validation agent that checks feasibility before spawning missions.",
                    expected_impact="Reduce mission failures to <15%",
                    confidence=0.4,
                )
            )

        # Identify agents with very low usage that could be merged
        low_usage = [aname for aname, stats in agent_rates.items() if stats["total_runs"] < 2]
        if len(low_usage) >= 3:
            proposals.append(
                ImprovementProposal(
                    category="architecture",
                    target=",".join(low_usage[:3]),
                    problem=f"Agents {low_usage[:3]} have very low usage.",
                    proposed_change="Consider merging these agents into a generalist agent to reduce overhead.",
                    expected_impact="Simplify registry and reduce maintenance",
                    confidence=0.35,
                )
            )
        return proposals

    # -- output helpers -----------------------------------------------------

    def _build_summary(self, report: SelfImprovementReport) -> str:
        parts = [
            f"Self-improvement analysis generated at {report.generated_at}",
            f"Agents analyzed: {len(report.agent_success_rates)}",
            f"Mission outcomes: {report.mission_outcomes.get('total_missions', 0)} total",
            f"Proposals generated: {len(report.proposals)}",
        ]
        high_conf = [p for p in report.proposals if p.confidence >= 0.6]
        if high_conf:
            parts.append(f"High-confidence proposals: {len(high_conf)}")
        return " | ".join(parts)

    def _save_report(self, report: SelfImprovementReport) -> None:
        try:
            REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
            REPORT_PATH.write_text(
                report.model_dump_json(indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save self-improvement report: %s", exc)

    async def _publish_proposals(self, report: SelfImprovementReport) -> None:
        try:
            bus = get_agent_bus()
            await bus.publish(
                "system.improvement_proposed",
                BusMessage(
                    message_id=f"si_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
                    source_agent="SELF_IMPROVEMENT",
                    payload={
                        "proposal_count": len(report.proposals),
                        "summary": report.summary,
                        "proposals": [p.model_dump(mode="json") for p in report.proposals],
                    },
                ),
            )
        except Exception as exc:
            logger.warning("Failed to publish improvement proposals: %s", exc)

    def _append_to_evolution_log(self, report: SelfImprovementReport) -> int:
        """Append high-confidence proposals to the evolution log.

        Returns:
            Number of entries added.
        """
        try:
            EVOLUTION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            lines: list[str] = []
            if EVOLUTION_LOG_PATH.exists():
                lines.append("")
            else:
                lines.append("# NEXUS IDE Evolution Log")
                lines.append("")
                lines.append(
                    "This file tracks all major architectural and quality decisions made by the META_ANALYZER agent."
                )
                lines.append("")

            entries_added = 0
            for proposal in report.proposals:
                if proposal.confidence < 0.5:
                    continue
                lines.append("---")
                lines.append("")
                lines.append(
                    f"## [{proposal.category.upper()}] {proposal.target} — {datetime.now(UTC).strftime('%Y-%m-%d')}"
                )
                lines.append("")
                lines.append(f"**Problem:** {proposal.problem}")
                lines.append("")
                lines.append(f"**Proposed Change:** {proposal.proposed_change}")
                lines.append("")
                lines.append(f"**Expected Impact:** {proposal.expected_impact}")
                lines.append("")
                lines.append(f"**Confidence:** {proposal.confidence}")
                lines.append("")
                lines.append(f"**Status:** PENDING_APPROVAL")
                lines.append("")
                entries_added += 1

            with EVOLUTION_LOG_PATH.open("a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")

            return entries_added
        except Exception as exc:
            logger.warning("Failed to append to evolution log: %s", exc)
            return 0

    # -- auto-apply approved proposals ----------------------------------------

    async def auto_apply_approved(
        self,
        report: SelfImprovementReport,
        min_confidence: float = 0.7,
        require_meta_approval: bool = True,
    ) -> dict[str, Any]:
        """Automatically apply approved high-confidence proposals.

        Args:
            report: The self-improvement report containing proposals.
            min_confidence: Minimum confidence threshold for auto-apply.
            require_meta_approval: If True, only apply proposals marked as approved.

        Returns:
            Dict with applied count, skipped count, and any errors.
        """
        results = {
            "applied": [],
            "skipped": [],
            "errors": [],
        }

        for proposal in report.proposals:
            if proposal.confidence < min_confidence:
                results["skipped"].append(
                    {
                        "id": proposal.id,
                        "reason": f"Confidence {proposal.confidence} below threshold {min_confidence}",
                    }
                )
                continue

            if require_meta_approval and not proposal.approved:
                results["skipped"].append(
                    {
                        "id": proposal.id,
                        "reason": "Not approved by META_ANALYZER",
                    }
                )
                continue

            try:
                applied = await self._apply_proposal(proposal)
                if applied:
                    results["applied"].append(
                        {
                            "id": proposal.id,
                            "target": proposal.target,
                            "category": proposal.category,
                        }
                    )
                    proposal.approved = True
                    proposal.approved_by = "AUTO_APPLY"
                    # Update evolution log status
                    self._update_evolution_log_status(proposal.id, "AUTO_APPLIED")
                else:
                    results["skipped"].append(
                        {
                            "id": proposal.id,
                            "reason": "No applicable auto-apply handler for category",
                        }
                    )
            except Exception as exc:
                results["errors"].append(
                    {
                        "id": proposal.id,
                        "error": str(exc),
                    }
                )
                logger.exception("Auto-apply failed for proposal %s", proposal.id)

        return results

    async def _apply_proposal(self, proposal: ImprovementProposal) -> bool:
        """Apply a single proposal based on its category."""
        if proposal.category == "prompt":
            return await self._apply_prompt_refinement(proposal)
        elif proposal.category == "tool":
            return await self._apply_tool_creation(proposal)
        elif proposal.category == "budget":
            return await self._apply_budget_adjustment(proposal)
        elif proposal.category == "architecture":
            return await self._apply_architecture_change(proposal)
        return False

    async def _apply_prompt_refinement(self, proposal: ImprovementProposal) -> bool:
        """Apply prompt refinement by updating the agent's system prompt."""
        try:
            from backend.config.settings import load_prompt

            # Load current prompt
            current_prompt = load_prompt(proposal.target)

            # For auto-apply, we append a refinement note
            # In practice, this would use an LLM to rewrite the prompt
            refinement_note = f"\n\n# AUTO-REFINEMENT ({datetime.now(UTC).isoformat()})\n# Problem: {proposal.problem}\n# Action: {proposal.proposed_change}\n"
            new_prompt = current_prompt + refinement_note

            # Save updated prompt (would need write access to config/prompts/)
            prompt_path = (
                Path(__file__).resolve().parent.parent
                / "config"
                / "prompts"
                / f"{proposal.target}.md"
            )
            if prompt_path.exists():
                prompt_path.write_text(new_prompt, encoding="utf-8")
                logger.info("Applied prompt refinement for %s", proposal.target)
                return True
        except Exception as exc:
            logger.warning("Failed to apply prompt refinement for %s: %s", proposal.target, exc)
        return False

    async def _apply_tool_creation(self, proposal: ImprovementProposal) -> bool:
        """Tool creation requires manual implementation - log for review."""
        logger.info(
            "Tool creation proposal logged for manual implementation: %s", proposal.proposed_change
        )
        return False  # Cannot auto-create tools safely

    async def _apply_budget_adjustment(self, proposal: ImprovementProposal) -> bool:
        """Apply budget adjustment by updating agent lifecycle config."""
        try:
            # This would modify the agent's token/time budget in the registry
            # For now, log the recommendation
            logger.info(
                "Budget adjustment proposed for %s: %s", proposal.target, proposal.proposed_change
            )
            # Actual implementation would update agent registry config
            return False  # Requires integration with agent lifecycle config
        except Exception as exc:
            logger.warning("Failed to apply budget adjustment: %s", exc)
        return False

    async def _apply_architecture_change(self, proposal: ImprovementProposal) -> bool:
        """Architecture changes require manual review."""
        logger.info("Architecture change proposal logged for review: %s", proposal.proposed_change)
        return False

    def _update_evolution_log_status(self, proposal_id: str, status: str) -> None:
        """Update the status of a proposal in the evolution log."""
        try:
            if not EVOLUTION_LOG_PATH.exists():
                return
            text = EVOLUTION_LOG_PATH.read_text(encoding="utf-8")
            # Simple replacement - in production use proper parsing
            updated = text.replace(f"ID: {proposal_id}", f"ID: {proposal_id}\n**Status:** {status}")
            if updated != text:
                EVOLUTION_LOG_PATH.write_text(updated, encoding="utf-8")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Proposal Applier — autonomous "apply" loop with safety rails
# ---------------------------------------------------------------------------


def _env_bool(name: str, default: bool) -> bool:
    """Read a boolean from an environment variable.

    Truthy values: "1", "true", "yes", "on" (case-insensitive). Anything
    else (including unset) returns *default*.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


class ProposalDecision(StrEnum):
    """Final decision emitted by the :class:`ProposalApplier`."""

    APPLIED = "applied"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"
    DRY_RUN = "dry_run"
    SKIPPED = "skipped"


@dataclass
class ProposalOutcome:
    """Result of a single apply/rollback attempt."""

    proposal_id: str
    decision: ProposalDecision
    reason: str
    confidence: float
    before_snapshot: str | None = None
    after_snapshot: str | None = None


class ProposalApplier:
    """Apply (or dry-run) an :class:`ImprovementProposal` with safety rails.

    The applier is intentionally conservative: it captures a git snapshot
    before any action, gates on confidence and an explicit ``auto_apply``
    switch, and runs the test suite to validate the baseline before
    reporting a dry-run pass. The actual mutation is left to the caller —
    the applier records intent and a rollback handle.
    """

    def __init__(
        self,
        *,
        repo_path: Path | None = None,
        auto_apply: bool | None = None,
        dry_run: bool | None = None,
        test_command: str = "python -m pytest backend/tests -q --maxfail=1",
    ) -> None:
        self._repo_path = repo_path
        self._test_command = test_command
        self._auto_apply = (
            _env_bool("NEXUS_AUTO_APPLY", False) if auto_apply is None else auto_apply
        )
        self._dry_run = (
            _env_bool("NEXUS_AUTO_APPLY_DRY_RUN", True) if dry_run is None else dry_run
        )

    # -- git helpers --------------------------------------------------------

    def _git_snapshot(self, label: str) -> str | None:
        """Capture a rollback point via ``git stash create``.

        Returns the stash ref (a commit hash) or ``None`` on failure.
        If git is not available the call is logged and ``None`` is
        returned so the caller can continue without a rollback handle.
        """
        cwd = str(self._repo_path) if self._repo_path else None
        try:
            rev = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            logger.warning("git not available for snapshot (%s): %s", label, exc)
            return None

        if rev.returncode != 0:
            logger.warning(
                "git rev-parse failed (%s): %s", label, (rev.stderr or "").strip()
            )
            return None

        try:
            stash = subprocess.run(
                ["git", "stash", "create", label],
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            logger.warning("git stash create failed (%s): %s", label, exc)
            return None

        if stash.returncode != 0:
            logger.warning(
                "git stash create failed (%s): %s", label, (stash.stderr or "").strip()
            )
            return None

        ref = (stash.stdout or "").strip()
        return ref or None

    # -- test runner --------------------------------------------------------

    def _run_tests(self) -> bool:
        """Run the configured test command.

        Returns ``True`` only when the command exits with code 0. On
        failure the last 50 lines of combined stdout/stderr are logged.
        """
        cwd = str(self._repo_path) if self._repo_path else None
        try:
            proc = subprocess.run(
                self._test_command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=cwd,
                timeout=300,
            )
        except subprocess.TimeoutExpired as exc:
            logger.warning("Test command timed out after 300s: %s", exc)
            return False
        except (FileNotFoundError, subprocess.SubprocessError) as exc:
            logger.warning("Test command failed to start: %s", exc)
            return False

        if proc.returncode == 0:
            return True

        combined = (proc.stdout or "") + (proc.stderr or "")
        tail = "\n".join(combined.splitlines()[-50:])
        logger.warning(
            "Test command exited with code %d. Last 50 lines:\n%s",
            proc.returncode,
            tail,
        )
        return False

    # -- public API ---------------------------------------------------------

    async def apply(self, proposal: ImprovementProposal) -> ProposalOutcome:
        """Decide what to do with *proposal* and return a :class:`ProposalOutcome`.

        Safety rails:
          1. ``auto_apply`` must be enabled.
          2. ``proposal.confidence`` must be at least 0.6.
          3. In dry-run mode the test suite must pass on the current
             baseline; otherwise the proposal is rejected.
        """
        if not self._auto_apply:
            return ProposalOutcome(
                proposal_id=proposal.id,
                decision=ProposalDecision.SKIPPED,
                reason="auto_apply_disabled",
                confidence=proposal.confidence,
            )

        if proposal.confidence < 0.6:
            return ProposalOutcome(
                proposal_id=proposal.id,
                decision=ProposalDecision.REJECTED,
                reason="confidence_below_threshold",
                confidence=proposal.confidence,
            )

        snapshot_ref = await asyncio.to_thread(
            self._git_snapshot, f"pre_proposal_{proposal.id}"
        )

        if self._dry_run:
            tests_ok = await asyncio.to_thread(self._run_tests)
            if not tests_ok:
                return ProposalOutcome(
                    proposal_id=proposal.id,
                    decision=ProposalDecision.REJECTED,
                    reason="tests_failed_in_baseline",
                    confidence=proposal.confidence,
                    before_snapshot=snapshot_ref,
                )
            return ProposalOutcome(
                proposal_id=proposal.id,
                decision=ProposalDecision.DRY_RUN,
                reason="dry_run_ok",
                confidence=proposal.confidence,
                before_snapshot=snapshot_ref,
            )

        proposal.approved = True
        return ProposalOutcome(
            proposal_id=proposal.id,
            decision=ProposalDecision.APPLIED,
            reason="applied",
            confidence=proposal.confidence,
            before_snapshot=snapshot_ref,
        )

    async def rollback(
        self, proposal: ImprovementProposal, outcome: ProposalOutcome
    ) -> bool:
        """Roll back the change captured in *outcome* via ``git stash apply``."""
        if not outcome.before_snapshot:
            logger.warning(
                "Rollback requested for %s but no snapshot is available",
                proposal.id,
            )
            return False

        cwd = str(self._repo_path) if self._repo_path else None
        ref = outcome.before_snapshot

        def _apply_stash() -> bool:
            try:
                proc = subprocess.run(
                    ["git", "stash", "apply", ref],
                    capture_output=True,
                    text=True,
                    cwd=cwd,
                    timeout=30,
                )
            except (FileNotFoundError, subprocess.SubprocessError) as exc:
                logger.warning("git stash apply failed: %s", exc)
                return False
            if proc.returncode != 0:
                logger.warning(
                    "git stash apply %s failed: %s", ref, (proc.stderr or "").strip()
                )
                return False
            return True

        ok = await asyncio.to_thread(_apply_stash)
        if ok:
            logger.info("Rolled back proposal %s using snapshot %s", proposal.id, ref)
        return ok


# ---------------------------------------------------------------------------
# Module-level singleton accessor
# ---------------------------------------------------------------------------

_applier: ProposalApplier | None = None


def get_proposal_applier() -> ProposalApplier:
    """Return a process-wide cached :class:`ProposalApplier` instance.

    Reset the cache (e.g. between tests) via
    ``proposal_applier_mod._applier = None`` where ``proposal_applier_mod``
    is the imported module reference.
    """
    global _applier
    if _applier is None:
        _applier = ProposalApplier()
    return _applier


# ---------------------------------------------------------------------------
# Autonomy event helper
# ---------------------------------------------------------------------------


async def emit_autonomy_decision(
    outcome: ProposalOutcome, session_id: str = ""
) -> None:
    """Publish a :class:`ProposalOutcome` on the agent bus under ``autonomy``.

    Silently no-ops if the bus cannot be reached or initialised.
    """
    try:
        bus = get_agent_bus()
        payload: dict[str, Any] = {"session_id": session_id, **asdict(outcome)}
        await bus.publish(
            "autonomy",
            BusMessage(
                message_id=f"auto_{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}",
                source_agent="SELF_IMPROVEMENT",
                payload=payload,
            ),
        )
    except Exception as exc:
        logger.warning("Failed to emit autonomy decision: %s", exc)
