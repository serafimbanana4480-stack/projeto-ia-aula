"""Plan creation for the multi-agent orchestrator.

Extracted from :mod:`backend.orchestrator.engine` to keep the main
``OrchestrationEngine`` focused on coordination. ``PlanCreator`` owns the
JSON plan-generation logic, the planning prompt, and the plan parser.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from backend.config.settings import get_model_config, load_prompt
from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode, TaskPriority
from backend.orchestrator.events import EventEmitter, EventType, OrchestratorEvent
from backend.tools.ollama_client import ChatMessage

logger = logging.getLogger(__name__)


class PlanCreator:
    """Generate and parse structured execution plans from natural-language objectives."""

    def __init__(self, llm_client: Any, event_bus: Any) -> None:
        self._llm_client = llm_client
        self._events = event_bus

    async def create(
        self,
        objective: str,
        session_id: str,
        *,
        context: str = "",
        history: list[ChatMessage] | None = None,
    ) -> ExecutionPlan:
        """Create a structured execution plan using the coder model for clean JSON.

        Uses the coder model (qwen2.5-coder:7b) directly for planning because
        it follows structured output instructions much better than reasoning models.
        The ARCHITECT agent (reasoning model) is still used during plan execution
        for deep design tasks.
        """
        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.ORCHESTRATOR_STARTED,
                source="ORCHESTRATOR",
                session_id=session_id,
                data={"objective": objective, "phase": "planning"},
            )
        )

        # Build planning prompt
        planning_prompt = self._build_planning_prompt(objective, context)

        # Use coder model directly for clean JSON output (not the architect agent)
        planner_cfg = get_model_config("coder")
        planner_model = planner_cfg["id"]
        system_prompt = load_prompt("architect")

        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=planning_prompt),
        ]

        # Stream planning directly from Ollama
        plan_content_parts: list[str] = []
        async with EventEmitter(self._events, "PLANNER", session_id) as emit:
            async for token in self._llm_client.chat_stream(
                model=planner_model,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                options={
                    "temperature": planner_cfg.get("temperature", 0.2),
                    "num_predict": 16384,  # Large plans need more tokens
                },
            ):
                plan_content_parts.append(token)
                await emit.emit(EventType.TOKEN, content=token)
        plan_content = "".join(plan_content_parts)

        # Parse plan into structured steps
        plan = self._parse_plan(plan_content, objective, session_id)
        plan.created_at = time.time()

        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.PLAN_CREATED,
                source="ARCHITECT",
                session_id=session_id,
                data=plan.to_dict(),
            )
        )

        return plan

    def _build_planning_prompt(self, objective: str, context: str) -> str:
        """Build the prompt for creating a professional multi-phase execution plan."""
        return f"""You are a senior software architect and project manager. Create a COMPREHENSIVE, PROFESSIONAL execution plan for:

OBJECTIVE: {objective}

ADDITIONAL CONTEXT: {context or "None"}

IMPORTANT: Create a DETAILED plan with 10-25 steps organized into phases. Each phase builds on the previous one.
Think like a real project manager: setup -> implementation -> testing -> documentation -> review.

Available agents and their specialties:
- ARCHITECT: system design, architecture decisions, code review, final approval
- CODER: writing code, implementing features, creating files, scaffolding, refactoring
- ANALYZER: reviewing code quality, security audit, finding issues, code smells
- DEBUGGER: fixing bugs, troubleshooting, running tests, verifying fixes
- RESEARCHER: searching web, reading docs, gathering info, API documentation
- DOCUMENTER: writing docs, README, API docs, inline comments, changelogs
- OPTIMIZER: performance tuning, benchmarking, profiling, optimization

PHASE GUIDELINES:
1. SETUP: Project initialization, directory structure, dependencies, configuration
2. CORE IMPLEMENTATION: Main features, data models, business logic, API endpoints
3. TESTING: Unit tests, integration tests, edge cases, error handling
4. QUALITY ASSURANCE: Code review, security audit, performance check
5. DOCUMENTATION: README, API docs, inline comments, usage examples
6. FINAL REVIEW: Architecture review, integration verification, polish

Respond with ONLY a JSON array. No markdown, no explanation, just the JSON:
[
  {{"name": "Phase 1: Setup - Initialize project structure", "description": "Create directory structure, setup configuration files, install dependencies", "agent": "CODER", "depends_on": [], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 1: Setup - Configure development environment", "description": "Set up linting, formatting, and build configuration", "agent": "CODER", "depends_on": [0], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 2: Core - Implement data models", "description": "Define core data structures and types", "agent": "CODER", "depends_on": [0], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 2: Core - Implement business logic", "description": "Write main application logic and algorithms", "agent": "CODER", "depends_on": [2], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 3: Testing - Write unit tests", "description": "Create comprehensive unit tests for all modules", "agent": "DEBUGGER", "depends_on": [3], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 4: QA - Code review and security audit", "description": "Review code quality, identify issues, check for security vulnerabilities", "agent": "ANALYZER", "depends_on": [3], "priority": "medium", "sandboxed": false}},
  {{"name": "Phase 4: QA - Fix issues from review", "description": "Address all issues found during code review and security audit", "agent": "DEBUGGER", "depends_on": [5], "priority": "high", "sandboxed": false}},
  {{"name": "Phase 5: Docs - Write documentation", "description": "Create README, API documentation, and usage examples", "agent": "DOCUMENTER", "depends_on": [6], "priority": "medium", "sandboxed": false}},
  {{"name": "Phase 6: Review - Final architecture review", "description": "Verify all components work together, review final code quality", "agent": "ARCHITECT", "depends_on": [7], "priority": "medium", "sandboxed": false}}
]

The depends_on field uses 0-based index of the step this depends on.
Priority values: "high", "medium", "low".
Make steps SPECIFIC and ACTIONABLE. Each step must produce a concrete deliverable.
Include at least 10 steps. More complex objectives should have 15-25 steps.
Use phase prefixes in step names: "Phase N: Name - Description"."""

    def _parse_plan(
        self,
        plan_content: str,
        objective: str,
        session_id: str,
    ) -> ExecutionPlan:
        """Parse the Architect's JSON output into an ExecutionPlan."""
        # Remove thinking blocks first (common with reasoning models)
        cleaned = re.sub(r"<thinking>.*?</thinking>", "", plan_content, flags=re.DOTALL)
        # Remove markdown code fences
        cleaned = re.sub(r"```json\s*", "", cleaned)
        cleaned = re.sub(r"```\s*", "", cleaned)
        # Remove any text before the first [ and after the last ]
        json_match = re.search(r"\[.*\]", cleaned, re.DOTALL)

        if not json_match:
            # Try to parse as natural text with numbered steps
            text_plan = self._parse_text_plan(cleaned, objective)
            if text_plan is not None and len(text_plan.steps) > 1:
                return text_plan

            logger.warning("No JSON array found in plan content, creating single-step plan")
            task = TaskNode(
                name="Execute Objective",
                description=objective,
                agent="CODER",
            )
            return ExecutionPlan.from_steps(
                title=objective[:100],
                description=objective,
                steps=[task],
                session_id=session_id,
            )

        try:
            raw_steps = json.loads(json_match.group(0))
        except json.JSONDecodeError:
            # Try to fix common JSON issues (trailing commas, etc.)
            raw_text = json_match.group(0)
            # Remove trailing commas before ] or }
            raw_text = re.sub(r",\s*([}\]])", r"\1", raw_text)
            try:
                raw_steps = json.loads(raw_text)
            except json.JSONDecodeError:
                logger.warning("Failed to parse plan JSON, creating single-step plan")
                task = TaskNode(
                    name="Execute Objective",
                    description=objective,
                    agent="CODER",
                )
                return ExecutionPlan.from_steps(
                    title=objective[:100],
                    description=objective,
                    steps=[task],
                    session_id=session_id,
                )

        if not isinstance(raw_steps, list) or len(raw_steps) == 0:
            logger.warning("Plan JSON is not a valid list, creating single-step plan")
            task = TaskNode(
                name="Execute Objective",
                description=objective,
                agent="CODER",
            )
            return ExecutionPlan.from_steps(
                title=objective[:100],
                description=objective,
                steps=[task],
                session_id=session_id,
            )

        steps: list[TaskNode] = []
        for i, raw in enumerate(raw_steps):
            if not isinstance(raw, dict):
                continue
            raw_priority = raw.get("priority", "medium")
            if not isinstance(raw_priority, str):
                raw_priority = "medium"
            priority_upper = raw_priority.upper()
            resolved_priority = (
                TaskPriority[priority_upper]
                if priority_upper in TaskPriority.__members__
                else TaskPriority.MEDIUM
            )
            task = TaskNode(
                name=raw.get("name", f"Step {i + 1}"),
                description=raw.get("description", ""),
                agent=raw.get("agent", "CODER").upper(),
                priority=resolved_priority,
                sandboxed=raw.get("sandboxed", False),
            )
            steps.append(task)

        if not steps:
            task = TaskNode(name="Execute Objective", description=objective, agent="CODER")
            steps.append(task)

        # Resolve dependencies (convert indices OR names to task_ids)
        # Build a name→index lookup for string-based depends_on
        name_to_idx: dict[str, int] = {}
        for idx, step in enumerate(steps):
            name_to_idx[step.name.lower().strip()] = idx
            # Also register shortened forms (e.g. "Phase 1: Setup" → "Setup")
            if ":" in step.name:
                short = step.name.split(":", 1)[-1].strip().lower()
                name_to_idx[short] = idx
            if "-" in step.name:
                short = step.name.split("-", 1)[-1].strip().lower()
                name_to_idx[short] = idx

        for i, raw in enumerate(raw_steps):
            if not isinstance(raw, dict):
                continue
            raw_deps = raw.get("depends_on", [])
            if not isinstance(raw_deps, list):
                raw_deps = [raw_deps] if raw_deps else []
            for dep_ref in raw_deps:
                dep_idx = self._resolve_dep_ref(dep_ref, len(steps), name_to_idx)
                if dep_idx is not None and dep_idx != i:
                    steps[i].depends_on.append(steps[dep_idx].task_id)
                    steps[dep_idx].required_by.append(steps[i].task_id)

        return ExecutionPlan.from_steps(
            title=objective[:100],
            description=objective,
            steps=steps,
            session_id=session_id,
        )

    @staticmethod
    def _resolve_dep_ref(
        dep_ref: Any,
        total_steps: int,
        name_to_idx: dict[str, int],
    ) -> int | None:
        """Resolve a depends_on reference to a step index.

        Handles:
        - Integer indices (0-based): directly validated
        - String names: fuzzy-matched against step names
        - 1-based indices from LLMs that forget 0-based convention
        """
        # Integer index (0-based)
        if isinstance(dep_ref, int):
            if 0 <= dep_ref < total_steps:
                return dep_ref
            # Maybe 1-based? Convert and check
            if 1 <= dep_ref <= total_steps:
                return dep_ref - 1
            return None

        # String reference — try exact then fuzzy match
        if isinstance(dep_ref, str):
            lowered = dep_ref.lower().strip()
            # Exact match
            if lowered in name_to_idx:
                return name_to_idx[lowered]
            # Try removing common prefixes
            for prefix in ("step ", "phase ", "task "):
                if lowered.startswith(prefix):
                    stripped = lowered[len(prefix) :]
                    if stripped in name_to_idx:
                        return name_to_idx[stripped]
            # Try numeric string (e.g. "1", "2")
            try:
                num = int(lowered)
                if 0 <= num < total_steps:
                    return num
                if 1 <= num <= total_steps:
                    return num - 1
            except ValueError:
                logger.debug("Non-numeric depends_on reference: %r", lowered)
            # Fuzzy: check if any step name contains this reference
            for name, idx in name_to_idx.items():
                if lowered in name or name in lowered:
                    return idx
            logger.warning("Could not resolve depends_on reference: %r", dep_ref)
            return None

        logger.warning("Unexpected depends_on type: %r", type(dep_ref))
        return None

    def _parse_text_plan(
        self,
        text: str,
        objective: str,
    ) -> ExecutionPlan | None:
        """Parse a natural-text plan into an ExecutionPlan.

        Handles formats like:
        - "1. Setup project\\n2. Implement feature\\n3. Write tests"
        - "Step 1: Setup\\nStep 2: Implement"
        - "- Setup project\\n- Implement feature"
        """
        # Match numbered steps: "1.", "1)", "Step 1:", etc.
        numbered_pattern = (
            r"(?:^|\n)\s*(?:step\s*)?(\d+)[.)]\s*(.+?)(?=(?:\n\s*(?:step\s*)?\d+[.)])|$)"
        )
        matches = re.findall(numbered_pattern, text, re.IGNORECASE | re.DOTALL)

        # If no numbered steps, try bullet points
        if not matches:
            bullet_pattern = r"(?:^|\n)\s*[-*]\s*(.+?)(?=(?:\n\s*[-*])|$)"
            bullets = re.findall(bullet_pattern, text, re.DOTALL)
            if len(bullets) >= 2:
                matches = [(str(i + 1), b.strip()) for i, b in enumerate(bullets)]

        if len(matches) < 2:
            return None

        steps: list[TaskNode] = []
        for _, content in matches:
            content = content.strip()
            if not content:
                continue

            # Try to extract agent from content (e.g. "[CODER]", "(architect)")
            agent_match = re.search(r"[\[(](\w+)[\])]", content)
            agent = agent_match.group(1).upper() if agent_match else "CODER"
            if agent not in (
                "ARCHITECT",
                "CODER",
                "ANALYZER",
                "DEBUGGER",
                "RESEARCHER",
                "DOCUMENTER",
                "OPTIMIZER",
                "DASHBOARD",
            ):
                agent = "CODER"

            # Clean content of agent markers
            description = re.sub(r"\s*[\[(]\w+[\])]", "", content).strip()

            task = TaskNode(
                name=description[:100],
                description=description,
                agent=agent,
            )
            steps.append(task)

        if len(steps) < 2:
            return None

        # Sequential dependencies (each step depends on previous)
        for i in range(1, len(steps)):
            steps[i].depends_on.append(steps[i - 1].task_id)
            steps[i - 1].required_by.append(steps[i].task_id)

        return ExecutionPlan.from_steps(
            title=objective[:100],
            description=objective,
            steps=steps,
            session_id="",
        )
