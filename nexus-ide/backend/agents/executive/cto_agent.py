"""CTOAgent — Chief Technology Officer executive agent for the NEXUS AI Company."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, AsyncIterator

from backend.agents.base import AgentBase, AgentRequest
from backend.agents.executive.technology_strategist import TechnologyStrategist
from backend.agents.executive.architecture_decision_maker import ArchitectureDecisionMaker
from backend.agents.executive.technical_roadmapper import TechnicalRoadmapper
from backend.agents.executive.stack_selector import StackSelector
from backend.agents.executive.technical_debt_manager import TechnicalDebtManager
from backend.agents.event_protocol import encode_event

logger = logging.getLogger(__name__)

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


class CTOAgent(AgentBase):
    """CTO Agent with technology strategy and architecture decision capabilities.

    Responsibilities:
    - Evaluate and recommend technology stacks
    - Record and manage Architecture Decision Records (ADRs)
    - Plan technical milestones and roadmaps
    - Track and prioritize technical debt
    - Provide general technical strategy guidance
    """

    name = "CTO"
    model_key = "deep"
    prompt_file = "cto_system"
    supported_actions = set()

    def __init__(
        self,
        technology_strategist: TechnologyStrategist | None = None,
        architecture_decision_maker: ArchitectureDecisionMaker | None = None,
        technical_roadmapper: TechnicalRoadmapper | None = None,
        stack_selector: StackSelector | None = None,
        technical_debt_manager: TechnicalDebtManager | None = None,
    ) -> None:
        super().__init__()
        self._strategist = technology_strategist or TechnologyStrategist()
        self._adr_maker = architecture_decision_maker or ArchitectureDecisionMaker()
        self._roadmapper = technical_roadmapper or TechnicalRoadmapper()
        self._stack_selector = stack_selector or StackSelector(self._strategist)
        self._debt_manager = technical_debt_manager or TechnicalDebtManager()

    def system_prompt(self) -> str:
        """Load the CTO system prompt from the local executive prompts directory."""
        prompt_path = PROMPTS_DIR / f"{self.prompt_file}.md"
        if not prompt_path.exists():
            raise FileNotFoundError(f"Prompt not found: {prompt_path}")
        return prompt_path.read_text(encoding="utf-8")

    # ── Core Agent Interface ──────────────────────────────────────────

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Execute the CTO agent — yields technical decisions and strategy."""
        yield encode_event("cto_start", request.query[:50])

        query = request.query.lower()

        if any(k in query for k in ("stack", "technology", "framework", "library", "tool")):
            async for chunk in self._handle_stack_request(request):
                yield chunk
        elif any(k in query for k in ("architecture", "adr", "decision", "pattern")):
            async for chunk in self._handle_architecture_request(request):
                yield chunk
        elif any(k in query for k in ("roadmap", "milestone", "timeline", "plan")):
            async for chunk in self._handle_roadmap_request(request):
                yield chunk
        elif any(k in query for k in ("debt", "technical debt", "refactor", "legacy")):
            async for chunk in self._handle_debt_request(request):
                yield chunk
        else:
            async for chunk in self._handle_general_request(request):
                yield chunk

        yield "<event>cto_end</event>"

    # ── Request Handlers ──────────────────────────────────────────────

    async def _handle_stack_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Technology Stack Analysis\n\n"

        stacks = self._strategist.list_stacks()
        if not stacks:
            yield "No stacks have been evaluated yet.\n"
            return

        # Determine if this is a comparison or recommendation
        query = request.query.lower()
        if "compare" in query or "versus" in query or "vs" in query:
            # Try to extract stack names from query
            names = [s.name for s in stacks]
            matched = [n for n in names if n.lower() in query]
            if matched:
                result = self._stack_selector.compare_stacks(matched)
                yield f"### Comparison Results\n\n"
                yield f"**Best overall:** {result.get('best_overall', 'N/A')}\n\n"
                for comp in result.get("comparisons", []):
                    yield f"- **{comp['name']}**: overall {comp['overall']:.2f}\n"
                return

        # Default: recommendation
        requirements = {"notes": request.query}
        selection = self._stack_selector.select_stack(requirements)
        if selection:
            yield f"**Recommended stack:** {selection.chosen_name}\n"
            yield f"**Score:** {selection.score:.2f}\n\n"
            if selection.compared_stacks:
                yield "**Also considered:**\n"
                for name in selection.compared_stacks[1:]:
                    yield f"- {name}\n"
        else:
            yield "Could not make a recommendation. Please evaluate stacks first.\n"

    async def _handle_architecture_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Architecture Decision Records\n\n"

        query = request.query.lower()
        if "new" in query or "record" in query or "create" in query:
            # Heuristic extraction: try to infer title from query
            title = request.query[:80]
            adr = self._adr_maker.record_decision(
                title=title,
                context=request.query,
                decision="Pending detailed review",
                consequences="To be determined after analysis",
                status="proposed",
            )
            yield f"Created ADR: **{adr.title}** (ID: `{adr.adr_id}`)\n"
            yield f"Status: {adr.status.value}\n"
            return

        if "stats" in query or "status" in query:
            stats = self._adr_maker.get_stats()
            yield f"**Total ADRs:** {stats['total']}\n"
            yield f"**Acceptance rate:** {stats['accepted_rate']:.0%}\n\n"
            for status, count in stats.get("by_status", {}).items():
                yield f"- {status}: {count}\n"
            return

        # List decisions
        status_filter = None
        for s in ("proposed", "accepted", "rejected", "deprecated", "superseded"):
            if s in query:
                status_filter = s
                break

        decisions = self._adr_maker.get_decisions(status=status_filter)
        if not decisions:
            yield f"No decisions found{f' with status `{status_filter}`' if status_filter else ''}.\n"
            return

        yield f"Found {len(decisions)} decision(s):\n\n"
        for d in decisions[:10]:
            yield f"- **{d.title}** (`{d.adr_id}`) — {d.status.value}\n"

    async def _handle_roadmap_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Technical Roadmap\n\n"

        query = request.query.lower()
        if "critical path" in query:
            path = self._roadmapper.get_critical_path()
            if not path:
                yield "No critical path milestones identified.\n"
                return
            yield "### Critical Path Milestones\n\n"
            for ms in path:
                status_icon = "🟢" if ms.status.value == "completed" else "🟡" if ms.status.value == "in_progress" else "⚪"
                yield f"{status_icon} **{ms.name}** — {ms.status.value}, {ms.progress:.0%} complete\n"
            return

        if "progress" in query:
            # Try to find milestone by name in query
            for ms in self._roadmapper.get_timeline():
                if ms.name.lower() in query:
                    # Extract a percentage if present
                    import re
                    match = re.search(r'(\d+)%', request.query)
                    if match:
                        pct = int(match.group(1)) / 100.0
                        self._roadmapper.update_progress(ms.milestone_id, pct)
                        yield f"Updated **{ms.name}** progress to {match.group(1)}%.\n"
                        return
            yield "Could not identify milestone to update. Mention the milestone name and a percentage.\n"
            return

        timeline = self._roadmapper.get_timeline()
        if not timeline:
            yield "No milestones on the roadmap yet.\n"
            return

        yield "### Timeline\n\n"
        from datetime import datetime
        for ms in timeline:
            date_str = datetime.fromtimestamp(ms.target_date).strftime("%Y-%m-%d")
            status_icon = "🟢" if ms.status.value == "completed" else "🟡" if ms.status.value == "in_progress" else "⚪"
            yield f"{status_icon} **{ms.name}** — {date_str} ({ms.progress:.0%})\n"
            if ms.deliverables:
                for d in ms.deliverables:
                    yield f"  - {d}\n"

    async def _handle_debt_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Technical Debt Register\n\n"

        query = request.query.lower()
        if "record" in query or "new" in query or "add" in query:
            # Heuristic: try to extract severity
            severity = "medium"
            for s in ("critical", "high", "medium", "low"):
                if s in query:
                    severity = s
                    break
            debt = self._debt_manager.record_debt(
                description=request.query[:120],
                severity=severity,
                location="unknown",
                estimated_effort=4.0,
                notes="Recorded from CTO query",
            )
            yield f"Recorded debt: `{debt.debt_id}` (severity: {debt.severity.value})\n"
            return

        if "stats" in query or "summary" in query:
            stats = self._debt_manager.get_stats()
            yield f"**Total items:** {stats['total']}\n"
            yield f"**Open:** {stats['open']} | **Resolved:** {stats['resolved']}\n"
            yield f"**Estimated effort remaining:** {stats['total_estimated_effort_open']:.1f}h\n\n"
            for sev, count in stats.get("by_severity", {}).items():
                yield f"- {sev}: {count}\n"
            return

        queue = self._debt_manager.get_debt_queue()
        if not queue:
            yield "No open technical debt items.\n"
            return

        yield f"### Open Debt Queue ({len(queue)} items)\n\n"
        for d in queue[:10]:
            icon = "🔴" if d.severity == "critical" else "🟠" if d.severity == "high" else "🟡" if d.severity == "medium" else "🟢"
            yield f"{icon} **{d.description[:60]}** — `{d.debt_id}` ({d.severity.value}, {d.estimated_effort:.1f}h)\n"

    async def _handle_general_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Technical Strategy Overview\n\n"

        stacks = self._strategist.list_stacks()
        adrs = self._adr_maker.get_decisions()
        milestones = self._roadmapper.get_timeline()
        debt = self._debt_manager.get_debt_queue()

        yield f"**Evaluated stacks:** {len(stacks)}\n"
        yield f"**Architecture decisions:** {len(adrs)}\n"
        yield f"**Roadmap milestones:** {len(milestones)}\n"
        yield f"**Open technical debt:** {len(debt)}\n\n"

        if stacks:
            top = stacks[0]
            yield f"Top rated stack: **{top.name}** (overall: {top.overall:.2f})\n\n"

        if milestones:
            active = [m for m in milestones if m.status.value in ("in_progress", "blocked")]
            if active:
                yield "### Active Milestones\n"
                for m in active[:3]:
                    yield f"- {m.name} ({m.progress:.0%})\n"

    # ── Public API ────────────────────────────────────────────────────

    def get_dashboard(self) -> dict[str, Any]:
        """Return CTO dashboard data aggregating all subsystems."""
        return {
            "stacks": self._strategist.stats(),
            "adrs": self._adr_maker.get_stats(),
            "roadmap": self._roadmapper.stats(),
            "stack_selections": self._stack_selector.stats(),
            "technical_debt": self._debt_manager.get_stats(),
        }
