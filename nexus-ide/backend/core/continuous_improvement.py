"""Continuous self-improvement loop.

Runs ``SelfImprovementAnalyzer`` periodically in the background, optionally
auto-applying high-confidence prompt refinements. Architecture, tool-creation
and budget proposals are NEVER auto-applied — they are surfaced to the
``/api/improvement/proposals`` endpoints for human review.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from backend.core.self_improvement import ImprovementProposal, SelfImprovementAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class ImprovementStats:
    """Running counters for self-improvement activity."""

    runs_total: int = 0
    proposals_generated_total: int = 0
    proposals_applied_total: int = 0
    proposals_rejected_total: int = 0
    last_run_at: float = 0.0
    last_run_duration_s: float = 0.0
    last_error: str | None = None
    last_proposals: list[ImprovementProposal] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "runs_total": self.runs_total,
            "proposals_generated_total": self.proposals_generated_total,
            "proposals_applied_total": self.proposals_applied_total,
            "proposals_rejected_total": self.proposals_rejected_total,
            "last_run_at": self.last_run_at,
            "last_run_duration_s": self.last_run_duration_s,
            "last_error": self.last_error,
            "last_proposal_count": len(self.last_proposals),
        }


class ContinuousImprovementLoop:
    """Background loop that periodically analyses and applies improvements.

    Configuration via environment variables:
        NEXUS_SELF_IMPROVE_ENABLED — "true" to enable (default: false)
        NEXUS_SELF_IMPROVE_INTERVAL_MINUTES — period (default: 60)
        NEXUS_SELF_IMPROVE_TIMEOUT_S — per-run timeout (default: 120)
        NEXUS_SELF_IMPROVE_AUTO_APPLY — "true" to auto-apply high-confidence
            prompt proposals (default: false). Architecture, tool and budget
            proposals are NEVER auto-applied.
        NEXUS_SELF_IMPROVE_MIN_CONFIDENCE — min confidence for auto-apply
            (default: 0.8)
    """

    def __init__(self) -> None:
        self._analyzer = SelfImprovementAnalyzer()
        self._task: asyncio.Task | None = None
        self._running = False
        self.stats = ImprovementStats()
        # Pending proposals awaiting human review (in-memory; persisted in evolution_log.md)
        self._pending_proposals: list[ImprovementProposal] = []
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------------ Lifecycle
    async def start(self) -> None:
        """Start the background loop (no-op if disabled)."""
        if os.environ.get("NEXUS_SELF_IMPROVE_ENABLED", "").lower() != "true":
            logger.info("Continuous improvement loop is disabled (NEXUS_SELF_IMPROVE_ENABLED != true)")
            return
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.create_task(self._run_forever(), name="continuous-improvement-loop")
        logger.info("Continuous improvement loop started")

    async def stop(self) -> None:
        """Stop the background loop gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        logger.info("Continuous improvement loop stopped")

    # ------------------------------------------------------------------ Main loop
    async def _run_forever(self) -> None:
        """Periodically run analysis."""
        interval_s = int(os.environ.get("NEXUS_SELF_IMPROVE_INTERVAL_MINUTES", "60")) * 60
        timeout_s = int(os.environ.get("NEXUS_SELF_IMPROVE_TIMEOUT_S", "120"))
        # Initial jitter to avoid thundering herd
        await asyncio.sleep(min(60, interval_s // 10))
        while self._running:
            try:
                await self.run_once(timeout_s=timeout_s)
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001
                logger.exception("Continuous improvement run failed: %s", e)
                self.stats.last_error = str(e)
            # Sleep until next run
            try:
                await asyncio.sleep(interval_s)
            except asyncio.CancelledError:
                break

    # ------------------------------------------------------------------ Operations
    async def run_once(self, timeout_s: int = 120, force: bool = False) -> dict[str, Any]:
        """Run a single analysis cycle.

        Args:
            timeout_s: Hard timeout for the analysis.
            force: If True, bypass the per-hour rate limit.

        Returns:
            dict with stats and proposals.
        """
        # Rate limit: max 1 per hour (configurable) unless forced
        now = time.monotonic()
        if not force and self.stats.last_run_at > 0:
            elapsed_h = (now - self.stats.last_run_at) / 3600
            if elapsed_h < 1.0:
                return {
                    "status": "skipped",
                    "reason": f"Rate limit: last run was {elapsed_h:.2f}h ago (min 1h)",
                    "stats": self.stats.to_dict(),
                }

        start = time.monotonic()
        try:
            report = await asyncio.wait_for(
                asyncio.to_thread(self._analyzer.run_analysis),
                timeout=timeout_s,
            )
        except TimeoutError:
            self.stats.last_error = f"Timeout after {timeout_s}s"
            logger.error("Self-improvement run timed out after %ds", timeout_s)
            return {"status": "timeout", "stats": self.stats.to_dict()}

        duration = time.monotonic() - start
        self.stats.runs_total += 1
        self.stats.last_run_at = time.monotonic()
        self.stats.last_run_duration_s = round(duration, 2)
        self.stats.last_error = None

        # Collect proposals
        proposals = report.proposals if report else []
        self.stats.proposals_generated_total += len(proposals)
        self.stats.last_proposals = proposals

        async with self._lock:
            # Add to pending list (deduplicate by id)
            existing_ids = {p.id for p in self._pending_proposals}
            for p in proposals:
                if p.id not in existing_ids:
                    self._pending_proposals.append(p)

        # Auto-apply high-confidence prompt proposals
        auto_apply = os.environ.get("NEXUS_SELF_IMPROVE_AUTO_APPLY", "").lower() == "true"
        if auto_apply:
            await self._auto_apply_prompts(proposals)

        logger.info(
            "self_improvement.analysis_completed proposals=%d duration=%.2fs",
            len(proposals),
            duration,
        )
        return {
            "status": "completed",
            "stats": self.stats.to_dict(),
            "proposal_count": len(proposals),
            "duration_s": round(duration, 2),
        }

    async def _auto_apply_prompts(self, proposals: list[ImprovementProposal]) -> None:
        """Auto-apply high-confidence prompt proposals (only)."""
        min_conf = float(os.environ.get("NEXUS_SELF_IMPROVE_MIN_CONFIDENCE", "0.8"))
        applied = 0
        for p in proposals:
            if p.category != "prompt":
                continue
            if p.confidence < min_conf:
                continue
            try:
                # Prompt files live in config/prompts/<agent>.md
                prompt_path = self._get_prompt_path(p.target)
                if not prompt_path:
                    continue
                # Append refinement to the prompt file (with marker)
                from datetime import UTC, datetime
                ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                marker = (
                    f"\n\n<!-- AUTO-REFINEMENT @ {ts} (confidence={p.confidence:.2f}) -->\n"
                    f"{p.proposed_change}\n"
                )
                with open(prompt_path, "a", encoding="utf-8") as f:
                    f.write(marker)
                applied += 1
                logger.info(
                    "self_improvement.proposal_applied id=%s target=%s confidence=%.2f",
                    p.id,
                    p.target,
                    p.confidence,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to apply proposal %s: %s", p.id, e)
        self.stats.proposals_applied_total += applied

    def _get_prompt_path(self, target: str):
        """Resolve agent name to prompt file path."""
        import pathlib
        project_root = pathlib.Path(__file__).resolve().parents[2]
        path = project_root / "config" / "prompts" / f"{target}.md"
        return path if path.exists() else None

    # ------------------------------------------------------------------ Proposal management
    async def list_proposals(self, status: str = "pending") -> list[dict[str, Any]]:
        """List proposals in the given status.

        Args:
            status: "pending" (default), "all", or "applied" (only tracked if we updated stats).

        Returns:
            List of proposal dicts.
        """
        async with self._lock:
            return [p.model_dump() for p in self._pending_proposals]

    async def get_proposal(self, proposal_id: str) -> dict[str, Any] | None:
        """Get a proposal by ID."""
        async with self._lock:
            for p in self._pending_proposals:
                if p.id == proposal_id:
                    return p.model_dump()
        return None

    async def apply_proposal(self, proposal_id: str) -> bool:
        """Manually apply a proposal. Returns True if applied."""
        async with self._lock:
            for i, p in enumerate(self._pending_proposals):
                if p.id == proposal_id:
                    # Force-apply regardless of category (user-approval)
                    if p.category == "prompt":
                        prompt_path = self._get_prompt_path(p.target)
                        if prompt_path:
                            from datetime import UTC, datetime
                            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                            marker = (
                                f"\n\n<!-- MANUAL-REFINEMENT @ {ts} (id={p.id}) -->\n"
                                f"{p.proposed_change}\n"
                            )
                            with open(prompt_path, "a", encoding="utf-8") as f:
                                f.write(marker)
                            self._pending_proposals.pop(i)
                            self.stats.proposals_applied_total += 1
                            return True
                    elif p.category == "tool":
                        # Tool proposals are logged but not auto-implemented
                        logger.info("Tool proposal %s: %s", p.id, p.proposed_change)
                        self._pending_proposals.pop(i)
                        self.stats.proposals_rejected_total += 1
                        return False
                    elif p.category == "budget":
                        # Budget proposals require config edit
                        logger.info("Budget proposal %s: %s", p.id, p.proposed_change)
                        self._pending_proposals.pop(i)
                        self.stats.proposals_rejected_total += 1
                        return False
                    elif p.category == "architecture":
                        # Architecture always requires deeper review
                        logger.info("Architecture proposal %s requires manual review: %s", p.id, p.proposed_change)
                        return False
        return False

    async def reject_proposal(self, proposal_id: str) -> bool:
        """Reject (discard) a proposal. Returns True if found and removed."""
        async with self._lock:
            for i, p in enumerate(self._pending_proposals):
                if p.id == proposal_id:
                    self._pending_proposals.pop(i)
                    self.stats.proposals_rejected_total += 1
                    return True
        return False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_loop: ContinuousImprovementLoop | None = None


def get_continuous_improvement_loop() -> ContinuousImprovementLoop:
    """Get the singleton continuous improvement loop (creates it if needed)."""
    global _loop
    if _loop is None:
        _loop = ContinuousImprovementLoop()
    return _loop
