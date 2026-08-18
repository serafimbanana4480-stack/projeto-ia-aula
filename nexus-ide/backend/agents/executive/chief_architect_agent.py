"""ChiefArchitectAgent — system design and pattern expertise agent."""
from __future__ import annotations

from typing import Any, AsyncIterator

from backend.agents.base import AgentBase, AgentRequest
from backend.agents.executive.pattern_catalog import PatternCatalog, PatternCategory
from backend.agents.executive.system_designer import SystemDesigner, SystemComponent
from backend.agents.executive.quality_gate import QualityGate
from backend.agents.executive.integration_planner import IntegrationPlanner
from backend.agents.event_protocol import encode_event


class ChiefArchitectAgent(AgentBase):
    """Chief Architect Agent with system design and pattern expertise.

    Responsibilities:
    - Recommend design patterns for given requirements
    - Generate system architecture proposals
    - Validate designs against quality gates
    - Plan cross-system integrations
    """

    name = "CHIEF_ARCHITECT"
    model_key = "opus"
    prompt_file = "chief_architect_system"
    supported_actions = set()

    def __init__(
        self,
        pattern_catalog: PatternCatalog | None = None,
        system_designer: SystemDesigner | None = None,
        quality_gate: QualityGate | None = None,
        integration_planner: IntegrationPlanner | None = None,
    ) -> None:
        super().__init__()
        self._catalog = pattern_catalog or PatternCatalog()
        self._designer = system_designer or SystemDesigner()
        self._gate = quality_gate or QualityGate()
        self._planner = integration_planner or IntegrationPlanner()

    # ── Core Agent Interface ──────────────────────────────────────────

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        yield encode_event("architect_start", request.query[:50])

        query = request.query.lower()

        if "pattern" in query or "design pattern" in query:
            async for chunk in self._handle_pattern_request(request):
                yield chunk
        elif "design" in query or "architecture" in query or "system" in query:
            async for chunk in self._handle_design_request(request):
                yield chunk
        elif "quality" in query or "check" in query or "validate" in query:
            async for chunk in self._handle_quality_request(request):
                yield chunk
        elif "integrate" in query or "integration" in query or "connect" in query:
            async for chunk in self._handle_integration_request(request):
                yield chunk
        else:
            async for chunk in self._handle_general_request(request):
                yield chunk

        yield "<event>architect_end</event>"

    # ── Request Handlers ──────────────────────────────────────────────

    async def _handle_pattern_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Design Pattern Recommendations\n\n"

        requirements = request.query.split()
        recommendations = self._catalog.recommend(requirements)

        if not recommendations:
            yield "No patterns match your requirements. Try describing the problem differently.\n"
            return

        for score, pattern in recommendations[:5]:
            yield f"### {pattern.name} (Match: {score})\n"
            yield f"**Category:** {pattern.category.value}\n"
            yield f"**Problem:** {pattern.problem}\n"
            yield f"**Solution:** {pattern.solution}\n"
            yield f"**When to use:** {pattern.when_to_use}\n\n"

    async def _handle_design_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## System Design Proposal\n\n"

        requirements = request.query.split()
        design = self._designer.create_design(
            name=request.query[:50],
            description=request.query,
            requirements=requirements,
        )

        yield f"**Design ID:** {design.design_id}\n"
        yield f"**Name:** {design.name}\n\n"

        yield "### Components\n"
        for c in design.components:
            yield f"- **{c.name}** ({c.type})\n"
            yield f"  - Responsibilities: {', '.join(c.responsibilities)}\n"
            yield f"  - Technologies: {', '.join(c.technologies)}\n"

        if design.patterns:
            yield "\n### Recommended Patterns\n"
            for pid in design.patterns:
                pattern = self._catalog.get_pattern(pid)
                if pattern:
                    yield f"- {pattern.name}: {pattern.description}\n"

    async def _handle_quality_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Architecture Quality Assessment\n\n"

        # Get latest design or use empty components
        designs = self._designer.list_designs()
        if designs:
            design = designs[-1]
            components = [{"name": c.name, "responsibilities": c.responsibilities} for c in design.components]
            data_flows = design.data_flows
        else:
            components = []
            data_flows = []

        checks = self._gate.run_all_checks(components, data_flows)

        for check in checks:
            icon = "✅" if check.passed else "❌"
            yield f"{icon} **{check.name}** ({check.severity.value})\n"
            yield f"   {check.message}\n"
            if check.recommendation:
                yield f"   💡 {check.recommendation}\n"
            yield "\n"

        summary = self._gate.get_summary()
        yield f"**Overall Score:** {summary['score']:.0%} ({summary['passed']}/{summary['total']} checks passed)\n"
        if summary["blockers"] > 0:
            yield f"⚠️ **{summary['blockers']} blockers must be resolved before proceeding.**\n"

    async def _handle_integration_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Integration Planning\n\n"

        # Simple heuristic: look for "integrate X with Y"
        words = request.query.lower().split()
        if "with" in words:
            idx = words.index("with")
            source = words[idx - 1] if idx > 0 else "system-a"
            target = words[idx + 1] if idx < len(words) - 1 else "system-b"
        else:
            source, target = "system-a", "system-b"

        plan = self._planner.create_plan(
            name=f"{source.title()} → {target.title()}",
            source_system=source,
            target_system=target,
            integration_type="api",
            protocol="REST + JSON",
        )

        yield f"**Plan ID:** {plan.plan_id}\n"
        yield f"**Source:** {plan.source_system}\n"
        yield f"**Target:** {plan.target_system}\n"
        yield f"**Type:** {plan.integration_type}\n"
        yield f"**Protocol:** {plan.protocol}\n"
        yield f"**Error Handling:** {plan.error_handling}\n"

    async def _handle_general_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Architecture Overview\n\n"

        yield f"**Patterns in Catalog:** {self._catalog.stats()['total']}\n"
        yield f"**System Designs:** {len(self._designer.list_designs())}\n"
        yield f"**Integration Plans:** {len(self._planner.list_plans())}\n\n"

        designs = self._designer.list_designs()
        if designs:
            yield "### Recent Designs\n"
            for d in designs[-3:]:
                yield f"- {d.name} ({len(d.components)} components)\n"

    # ── Public API ────────────────────────────────────────────────────

    def get_dashboard(self) -> dict[str, Any]:
        return {
            "patterns": self._catalog.stats(),
            "designs": len(self._designer.list_designs()),
            "integrations": self._planner.stats(),
            "quality_score": self._gate.get_summary().get("score", 0.0),
        }
