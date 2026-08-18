"""CEOAgent — strategic executive agent for the NEXUS AI Company."""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from backend.agents.base import AgentBase, AgentRequest
from backend.agents.executive.strategic_memory import StrategicMemory
from backend.agents.executive.goal_hierarchy import GoalHierarchy, GoalPriority
from backend.agents.executive.resource_allocator import ResourceAllocator
from backend.agents.executive.priority_manager import PriorityManager, PriorityLevel
from backend.agents.executive.vision_aligner import VisionAligner
from backend.agents.event_protocol import encode_event

logger = logging.getLogger(__name__)


class CEOAgent(AgentBase):
    """CEO Agent with strategic decision-making capabilities.

    Responsibilities:
    - Decompose high-level goals into strategic initiatives
    - Allocate resources across teams
    - Set priorities for the organization
    - Ensure vision alignment
    - Record strategic decisions for learning
    """

    name = "CEO"
    model_key = "opus"
    prompt_file = "ceo_system"
    supported_actions = set()

    def __init__(
        self,
        strategic_memory: StrategicMemory | None = None,
        goal_hierarchy: GoalHierarchy | None = None,
        resource_allocator: ResourceAllocator | None = None,
        priority_manager: PriorityManager | None = None,
        vision_aligner: VisionAligner | None = None,
    ) -> None:
        super().__init__()
        self._memory = strategic_memory or StrategicMemory()
        self._goals = goal_hierarchy or GoalHierarchy()
        self._allocator = resource_allocator or ResourceAllocator()
        self._priorities = priority_manager or PriorityManager()
        self._vision = vision_aligner or VisionAligner(vision=self._memory.vision)

    # ── Core Agent Interface ──────────────────────────────────────────

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Execute the CEO agent — yields strategic decisions and plans."""
        yield encode_event("ceo_start", request.query[:50])

        # Parse the request
        query = request.query.lower()

        # Handle different types of requests
        if "vision" in query or "mission" in query:
            async for chunk in self._handle_vision_request(request):
                yield chunk
        elif "goal" in query or "objective" in query or "plan" in query:
            async for chunk in self._handle_goal_request(request):
                yield chunk
        elif "priority" in query or "urgent" in query:
            async for chunk in self._handle_priority_request(request):
                yield chunk
        elif "resource" in query or "allocate" in query or "team" in query:
            async for chunk in self._handle_resource_request(request):
                yield chunk
        elif "decision" in query or "strategy" in query:
            async for chunk in self._handle_decision_request(request):
                yield chunk
        else:
            # General strategic advice
            async for chunk in self._handle_general_request(request):
                yield chunk

        yield "<event>ceo_end</event>"

    # ── Request Handlers ──────────────────────────────────────────────

    async def _handle_vision_request(self, request: AgentRequest) -> AsyncIterator[str]:
        vision = self._memory.vision or "No vision defined yet."
        yield f"## Current Vision\n\n{vision}\n\n"
        yield f"**Values:** {', '.join(self._vision._values) or 'None defined'}\n\n"
        yield "To update the vision, provide a new statement.\n"

    async def _handle_goal_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Strategic Goal Planning\n\n"

        # Create a strategic goal
        goal = self._goals.create_goal(
            title=request.query[:80],
            description=request.query,
            priority=GoalPriority.HIGH,
        )

        yield f"Created strategic goal: **{goal.title}** (ID: {goal.goal_id})\n\n"

        # Check vision alignment
        alignment = self._vision.check_alignment(request.query)
        yield f"Vision alignment: {'✅ Aligned' if alignment.aligned else '⚠️ Needs attention'} (score: {alignment.score:.2f})\n"
        if alignment.suggestions:
            yield f"Suggestions: {', '.join(alignment.suggestions)}\n"
        yield "\n"

        # Decompose into subgoals
        subgoals = self._decompose_goal(goal.title)
        yield "### Proposed Subgoals\n"
        for i, sg in enumerate(subgoals, 1):
            sub = self._goals.create_goal(
                title=sg,
                description=f"Subgoal of: {goal.title}",
                priority=GoalPriority.MEDIUM,
                parent_id=goal.goal_id,
            )
            yield f"{i}. **{sg}** (ID: {sub.goal_id})\n"

        yield f"\nTotal subgoals created: {len(subgoals)}\n"

    async def _handle_priority_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Priority Queue\n\n"

        queue = self._priorities.get_queue(limit=10)
        if not queue:
            yield "No prioritized items found.\n"
            return

        for i, item in enumerate(queue, 1):
            yield f"{i}. **{item.title}** (Priority: {item.base_priority.name}, Score: {item.effective_priority:.2f})\n"

        # Auto-escalate stale items
        escalated = self._priorities.auto_escalate()
        if escalated:
            yield f"\n⚠️ Auto-escalated {len(escalated)} stale items\n"

    async def _handle_resource_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Resource Allocation\n\n"

        stats = self._allocator.stats()
        yield f"**Agent Pool:** {stats['total_agents']} agents, {stats['healthy']} healthy\n"
        yield f"**Average Load:** {stats['avg_load']:.1%}\n\n"

        # Show all agents
        for agent in self._allocator.get_all_agents():
            status_icon = "🟢" if agent.health_status == "healthy" else "🔴"
            yield f"{status_icon} **{agent.name}** — Load: {agent.current_load:.1%}, Capabilities: {', '.join(agent.capabilities)}\n"

    async def _handle_decision_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Strategic Decision Support\n\n"

        # Find similar past decisions
        similar = self._memory.find_similar(request.query, top_k=3)
        if similar:
            yield "### Similar Past Decisions\n"
            for d in similar:
                yield f"- **{d.chosen}** (confidence: {d.confidence:.0%}) — {d.reasoning[:100]}...\n"
            yield "\n"

        # Record the decision request
        decision = self._memory.record_decision(
            context=request.query,
            options=["proceed", "defer", "reject"],
            chosen="pending",
            reasoning="Decision under review",
            confidence=0.5,
        )

        yield f"Decision logged (ID: {decision.decision_id}).\n"
        yield "To finalize, provide: chosen option, reasoning, and confidence level.\n"

    async def _handle_general_request(self, request: AgentRequest) -> AsyncIterator[str]:
        yield "## Strategic Analysis\n\n"

        goals = self._goals.list_goals()
        active = [g for g in goals if g.status.value == "active"]
        pending = [g for g in goals if g.status.value == "pending"]

        yield f"**Active Goals:** {len(active)}\n"
        yield f"**Pending Goals:** {len(pending)}\n"
        yield f"**Total Decisions:** {self._memory.stats()['total_decisions']}\n"
        yield f"**Priority Queue:** {self._priorities.stats()['total']} items\n\n"

        if active:
            yield "### Top Active Goals\n"
            for g in active[:5]:
                yield f"- {g.title} (progress: {g.progress:.0%})\n"

    # ── Helpers ──────────────────────────────────────────────────────

    def _decompose_goal(self, title: str) -> list[str]:
        """Simple heuristic goal decomposition."""
        # In production, this would use the LLM
        words = title.lower().split()
        subgoals = []

        if "app" in words or "application" in words:
            subgoals.extend([
                "Design architecture and data model",
                "Implement core business logic",
                "Build user interface components",
                "Write comprehensive tests",
                "Deploy to production environment",
            ])
        elif "api" in words:
            subgoals.extend([
                "Design API contract and endpoints",
                "Implement authentication and authorization",
                "Build request handlers and validation",
                "Add documentation and examples",
                "Performance test and optimize",
            ])
        elif "fix" in words or "bug" in words:
            subgoals.extend([
                "Reproduce and diagnose the issue",
                "Develop the fix with tests",
                "Review and validate the solution",
                "Deploy the fix to production",
            ])
        else:
            subgoals.extend([
                "Analyze requirements and constraints",
                "Design the solution architecture",
                "Implement the core functionality",
                "Test and validate thoroughly",
                "Document and deploy",
            ])

        return subgoals[:5]

    # ── Public API ────────────────────────────────────────────────────

    def set_company_vision(self, vision: str, values: list[str] | None = None) -> None:
        self._memory.set_vision(vision)
        self._vision.set_vision(vision)
        if values:
            for v in values:
                self._vision.add_value(v)
        logger.info("Company vision set: %s...", vision[:100])

    def get_dashboard(self) -> dict[str, Any]:
        """Return executive dashboard data."""
        return {
            "vision": self._memory.vision,
            "values": self._vision._values,
            "goals": self._goals.stats(),
            "priorities": self._priorities.stats(),
            "resources": self._allocator.stats(),
            "decisions": self._memory.stats(),
        }
