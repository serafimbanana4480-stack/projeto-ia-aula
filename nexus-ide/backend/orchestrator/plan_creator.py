"""Plan creation for the multi-agent orchestrator.

Extracted from :mod:`backend.orchestrator.engine` to keep the main
``OrchestrationEngine`` focused on coordination. ``PlanCreator`` owns the
JSON plan-generation logic, the planning prompt, and the plan parser.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Mapping

from backend.config.settings import get_model_config, load_prompt
from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode, TaskPriority
from backend.orchestrator.events import EventEmitter, EventType, OrchestratorEvent
from backend.orchestrator.plan_validation import (
    PlanningResult,
    build_deterministic_plan,
    validate_execution_plan,
)
from backend.tools.ollama_client import ChatMessage

logger = logging.getLogger(__name__)


SUPPORTED_PLAN_AGENTS = frozenset(
    {
        "PLANNER",
        "ARCHITECT",
        "CODER",
        "ANALYZER",
        "DEBUGGER",
        "RESEARCHER",
        "DOCUMENTER",
        "OPTIMIZER",
        "DASHBOARD",
    }
)


#: Substrings that identify a provider-side capacity failure (as opposed to a
#: bad prompt).  These are worth retrying against another model; a 400 or a
#: schema error is not.
_RETRYABLE_PROVIDER_ERRORS = (
    "429",
    "rate limit",
    "rate-limit",
    "temporarily rate-limited",
    "502",
    "503",
    "504",
    "network connection lost",
    "provider_unavailable",
    "overloaded",
    "timeout",
    "timed out",
)


def _is_retryable_provider_error(exc: BaseException) -> bool:
    """True when ``exc`` looks like transient provider capacity, not a bad request."""
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(marker in text for marker in _RETRYABLE_PROVIDER_ERRORS)


class PlanCreator:
    """Generate and parse structured execution plans from natural-language objectives."""

    PLAN_STREAM_TIMEOUT_SECONDS = 180.0
    MAX_PLAN_STEPS = 50

    #: Seconds to wait before re-dispatching planning to the next model. A free
    #: OpenRouter tier allows 20 requests/minute, so hammering the cascade in
    #: under two seconds (the previous behaviour) guarantees that every model
    #: in the chain inherits the same 429.
    PLAN_RETRY_BACKOFF_SECONDS = (2.0, 6.0, 15.0)

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
        project_path: str = ".",
        snapshot: Mapping[str, Any] | None = None,
    ) -> PlanningResult:
        """Create a validated local proposal, then optionally enrich it.

        Provider failures are represented as ``blocked`` results.  In
        particular, this method never turns an unavailable model into an
        implicitly approved execution plan.
        """
        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.ORCHESTRATOR_STARTED,
                source="ORCHESTRATOR",
                session_id=session_id,
                data={"objective": objective, "phase": "planning"},
            )
        )
        facts: Mapping[str, Any] = snapshot or {
            "absolute_path": project_path,
            "root": project_path,
        }
        deterministic = build_deterministic_plan(objective, facts, session_id)
        baseline_validation = validate_execution_plan(
            deterministic, facts, self.MAX_PLAN_STEPS
        )
        if not baseline_validation.valid:
            error = "; ".join(baseline_validation.errors)
            return PlanningResult(
                status="blocked",
                source="deterministic",
                error=error,
                deterministic_proposal=deterministic,
            )

        planning_context = await self._gather_planning_context(
            objective, session_id, context, project_path
        )
        planning_prompt = self._build_planning_prompt(objective, planning_context)
        planner_cfg = get_model_config("coder")
        planner_models = self._eligible_planner_models(self._planner_model_chain(planner_cfg))
        system_prompt = load_prompt("planner")
        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=planning_prompt),
        ]
        plan_content = ""
        last_error: BaseException | None = None
        async with EventEmitter(self._events, "PLANNER", session_id) as emit:
            for attempt, planner_model in enumerate(planner_models):
                plan_content_parts: list[str] = []
                try:
                    async with asyncio.timeout(self.PLAN_STREAM_TIMEOUT_SECONDS):
                        async for token in self._llm_client.chat_stream(
                            model=planner_model,
                            messages=[{"role": m.role, "content": m.content} for m in messages],
                            options={
                                "temperature": planner_cfg.get("temperature", 0.2),
                                "num_predict": 16384,
                            },
                        ):
                            if isinstance(token, str):
                                plan_content_parts.append(token)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # provider failures become blocked results
                    last_error = exc
                    logger.warning("Planner model %s failed: %s", planner_model, exc)
                    if not await self._retry_planning(
                        emit,
                        planner_models,
                        attempt,
                        exc,
                        retryable=_is_retryable_provider_error(exc),
                    ):
                        break
                    continue
                candidate = "".join(plan_content_parts)
                if candidate.strip():
                    plan_content = candidate
                    break
                last_error = RuntimeError(f"planner model {planner_model} returned an empty body")
                if not await self._retry_planning(
                    emit, planner_models, attempt, last_error, retryable=True
                ):
                    break

            if not plan_content.strip():
                await emit.emit(
                    EventType.WARNING,
                    content=(
                        "Planning blocked: no eligible model produced a plan; "
                        "every available model was unavailable"
                        + (f" ({self._format_provider_error(last_error)})" if last_error else "")
                    ),
                )

        if not plan_content.strip():
            return PlanningResult(
                status="blocked",
                source="deterministic",
                error=self._format_provider_error(last_error)
                if last_error
                else "no eligible planning model produced output",
                deterministic_proposal=deterministic,
            )

        candidate_plan = self._parse_plan(plan_content, objective, session_id)
        if candidate_plan is None:
            return PlanningResult(
                status="blocked",
                source="model",
                error="planner output was not a parseable structured plan",
                deterministic_proposal=deterministic,
            )
        candidate_plan.created_at = time.time()
        candidate_validation = validate_execution_plan(
            candidate_plan, facts, self.MAX_PLAN_STEPS
        )
        if not candidate_validation.valid:
            return PlanningResult(
                status="blocked",
                source="model",
                error="; ".join(candidate_validation.errors),
                deterministic_proposal=deterministic,
            )
        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.PLAN_CREATED,
                source="PLANNER",
                session_id=session_id,
                data=candidate_plan.to_dict(),
            )
        )
        return PlanningResult(
            status="ready",
            plan=candidate_plan,
            source="model",
            deterministic_proposal=deterministic,
        )

    @staticmethod
    def _format_provider_error(exc: BaseException | None) -> str:
        if exc is None:
            return ""
        details = [f"{type(exc).__name__}: {exc}"]
        for label in ("category", "provider", "model", "retry_after", "quota"):
            value = getattr(exc, label, None)
            if value not in (None, ""):
                details.append(f"{label}={value}")
        return " | ".join(details)

    @staticmethod
    def _eligible_planner_models(models: list[str]) -> list[str]:
        """Keep known free/local aliases and explicit ``:free`` IDs only."""
        free_aliases = {
            "kimi-k2.7-code",
            "deepseek-v4-flash",
            "deepseek-v4-pro",
            "glm-5.2",
            "minimax-m3",
            "qwen3.7-max",
            "mimo-v2.5",
            "mimo-v2-pro",
            "coder",
        }
        eligible = [
            model for model in models
            if model in free_aliases
            or model.lower().endswith(("/free", ":free"))
            or model.lower().startswith(("ollama:", "ollama/"))
        ]
        # Test doubles and explicitly injected local model IDs are allowed
        # when the chain contains no provider-qualified paid model.
        if not eligible and models and all("/" not in model for model in models):
            return models
        return eligible

    @staticmethod
    def _planner_model_chain(planner_cfg: dict[str, Any]) -> list[str]:
        """Return the ordered list of models to try for planning.

        Built from the tier's own ``fallback_id`` plus the reasoning tier, so a
        capacity failure on the coder tier does not take planning down with it.
        Duplicates and blanks are dropped while preserving order.
        """
        candidates: list[Any] = [planner_cfg.get("id"), planner_cfg.get("fallback_id")]
        for extra_tier in ("reasoning", "fast"):
            try:
                extra_cfg = get_model_config(extra_tier)
            except KeyError:
                continue
            candidates.append(extra_cfg.get("id"))

        chain: list[str] = []
        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip() and candidate not in chain:
                chain.append(candidate)
        return chain or ["coder"]

    async def _retry_planning(
        self,
        emit: Any,
        planner_models: list[str],
        attempt: int,
        exc: BaseException | None,
        *,
        retryable: bool,
    ) -> bool:
        """Decide whether to try the next planner model, and wait before doing so.

        Returns ``True`` when the caller should continue the cascade. The sleep
        matters: the free OpenRouter tier caps at 20 requests/minute, so
        retrying three models inside two seconds — what the agent cascade in
        ``AgentBase.stream_llm`` still does — earns three identical 429s.
        """
        has_next = attempt + 1 < len(planner_models)
        if not retryable or not has_next:
            return False

        backoff = self.PLAN_RETRY_BACKOFF_SECONDS[
            min(attempt, len(self.PLAN_RETRY_BACKOFF_SECONDS) - 1)
        ]
        next_model = planner_models[attempt + 1]
        await emit.emit(
            EventType.WARNING,
            content=(
                f"Planning model {planner_models[attempt]} unavailable"
                f"{f' ({exc})' if exc else ''}; retrying with {next_model} "
                f"in {backoff:.0f}s."
            ),
        )
        await asyncio.sleep(backoff)
        return True

    @staticmethod
    async def _gather_planning_context(
        objective: str,
        session_id: str,
        context: str,
        project_path: str = ".",
    ) -> str:
        """Recall prior decisions and request focused specialist input.

        This is the planning memory loop: recall happens before decomposition,
        its results are included in the plan, and the executing agents persist
        their outcome through their normal ``store_memory`` action.
        """
        sections = [context] if context else []
        try:
            if project_path and project_path != ".":
                from backend.knowledge.project_memory import read_project_memory

                bootstrap = read_project_memory(project_path)
                if bootstrap:
                    sections.append("Compact project bootstrap (inert data):\n" + bootstrap)
        except Exception as exc:
            logger.info("Project bootstrap unavailable to planner: %s", exc)
        try:
            from backend.tools.memory_tools import recall_context

            recalled = await recall_context(
                query=objective,
                session_id=session_id,
                project_id=project_path if project_path and project_path != "." else "",
                top_k=3,
            )
            memories = recalled.get("memories", [])
            if memories:
                sections.append(
                    "Recalled project context:\n"
                    + "\n".join(
                        f"- {memory.get('content', '')[:500]}"
                        for memory in memories
                        if isinstance(memory, dict)
                    )
                )
        except Exception as exc:  # Memory is advisory; planning remains available.
            logger.info("Planner memory recall unavailable: %s", exc)

        lowered = objective.lower()
        consultations: list[tuple[str, str]] = []
        if any(
            term in lowered for term in ("research", "api", "documentation", "library", "framework")
        ):
            consultations.append(
                ("RESEARCHER", f"Identify relevant facts, APIs, or constraints for: {objective}")
            )
        if any(term in lowered for term in ("bug", "error", "fail", "regression", "crash", "test")):
            consultations.append(
                (
                    "DEBUGGER",
                    (
                        "This Nexus process runs on Windows with PowerShell. Do not use Unix "
                        "pipelines such as find|head. Prefer the dedicated read_file, list_dir, "
                        "search_in_files and run_tests tools. Identify likely failure modes and "
                        f"the smallest verification for: {objective}"
                    ),
                )
            )

        if consultations:
            try:
                from backend.tools.agent_comm import consult_agent

                replies = await asyncio.gather(
                    *(
                        consult_agent(
                            agent=agent,
                            question=question,
                            source_agent="PLANNER",
                            session_id=session_id,
                            timeout_seconds=45,
                            # Planning is advisory and nobody is watching a
                            # confirmation dialog at this point. Without
                            # ``autonomous=True`` the sub-agent that reaches a
                            # gated tool calls ``wait_for_confirmation`` and
                            # parks until the A2A timeout fires.
                            #
                            # Measured cost of the old behaviour, session
                            # 27437d6cc61e4753: DEBUGGER requested
                            # ``run_shell('ls -la')`` at 08:18:13 and the
                            # consultation timed out at 08:18:55 — 42 seconds,
                            # 27% of a 158-second run, spent waiting for a
                            # click that could never come, and no context
                            # gathered in return.
                            autonomous=True,
                            project_path=project_path,
                        )
                        for agent, question in consultations
                    ),
                    return_exceptions=True,
                )
                for (agent, _question), reply in zip(consultations, replies, strict=True):
                    if isinstance(reply, dict) and reply.get("response"):
                        sections.append(f"{agent} consultation:\n{str(reply['response'])[:2000]}")
            except Exception as exc:  # Consultations supplement, never block planning.
                logger.info("Planner specialist consultation unavailable: %s", exc)

        return "\n\n".join(section for section in sections if section)

    def _build_planning_prompt(self, objective: str, context: str) -> str:
        """Build the prompt for creating a professional multi-phase execution plan."""
        return f"""You are a senior software architect and project manager. Create a COMPREHENSIVE, PROFESSIONAL execution plan for:

OBJECTIVE: {objective}

ADDITIONAL CONTEXT: {context or "None"}

IMPORTANT: Create a DETAILED but economical plan with 6-12 necessary steps organized into phases.
Combine closely related checks handled by the same agent; do not split work merely to increase the step count.
Each phase builds on the previous one: setup -> implementation -> testing -> documentation -> review.

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
Every step MUST include:
- "file_scope": an array of measured project-relative or absolute paths
- "completion_criteria": an array of observable acceptance criteria
- "verification_commands": an array of concrete commands (required for DEBUGGER)
- "risk": "low", "medium", or "high"
- "rollback": a concrete rollback instruction
- "lock_scope": the smallest read/write scope
- "allowed_tools": an array containing only tools available to the selected agent
Use a registered agent and model key for every step; do not emit "Execute Objective".
Priority values: "high", "medium", "low".
Make steps SPECIFIC and ACTIONABLE. Each step must produce a concrete deliverable.
Include at least 10 steps. More complex objectives should have 15-25 steps.
Use phase prefixes in step names: "Phase N: Name - Description"."""

    def _parse_plan(
        self,
        plan_content: str,
        objective: str,
        session_id: str,
    ) -> ExecutionPlan | None:
        """Parse model JSON without repairing or completing it."""
        cleaned = re.sub(r"<thinking>.*?</thinking>", "", plan_content, flags=re.DOTALL)
        cleaned = re.sub(r"```json\s*", "", cleaned)
        cleaned = re.sub(r"```\s*", "", cleaned)
        json_match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if not json_match:
            text_plan = self._parse_text_plan(cleaned, objective)
            if text_plan is not None and len(text_plan.steps) > 1:
                text_plan.session_id = session_id
                return text_plan
            return None
        raw_text = json_match.group(0)
        try:
            raw_steps = json.loads(raw_text)
        except json.JSONDecodeError:
            try:
                raw_steps = json.loads(re.sub(r",\s*([}\]])", r"\1", raw_text))
            except json.JSONDecodeError:
                return None
        if not isinstance(raw_steps, list) or not raw_steps:
            return None
        valid_raw_steps = [raw for raw in raw_steps if isinstance(raw, dict)]
        if not valid_raw_steps or len(valid_raw_steps) > self.MAX_PLAN_STEPS:
            return None
        steps: list[TaskNode] = []
        for raw in valid_raw_steps:
            raw_priority = raw.get("priority", "medium")
            priority_upper = str(raw_priority).strip().upper()
            priority = (
                TaskPriority[priority_upper]
                if priority_upper in TaskPriority.__members__
                else TaskPriority.MEDIUM
            )
            name = raw.get("name") if isinstance(raw.get("name"), str) else ""
            description = raw.get("description") if isinstance(raw.get("description"), str) else ""
            agent = raw.get("agent") if isinstance(raw.get("agent"), str) else ""
            steps.append(
                TaskNode(
                    name=name.strip(),
                    description=description.strip(),
                    agent=agent.strip().upper(),
                    model_key=str(raw.get("model_key", "")).strip(),
                    priority=priority,
                    sandboxed=raw.get("sandboxed", False) is True,
                    file_scope=raw.get("file_scope", []),
                    completion_criteria=raw.get("completion_criteria", []),
                    verification_commands=raw.get("verification_commands", []),
                    risk=str(raw.get("risk", "")),
                    rollback=str(raw.get("rollback", "")),
                    lock_scope=str(raw.get("lock_scope", "")),
                    allowed_tools=raw.get("allowed_tools", []),
                )
            )
        name_to_idx: dict[str, int] = {
            step.name.lower(): idx for idx, step in enumerate(steps) if step.name
        }
        for i, raw in enumerate(valid_raw_steps):
            raw_deps = raw.get("depends_on", [])
            refs = raw_deps if isinstance(raw_deps, list) else [raw_deps]
            for dep_ref in refs:
                dep_idx = self._resolve_dep_ref(dep_ref, len(steps), name_to_idx)
                if dep_idx is not None:
                    dependency_id = steps[dep_idx].task_id
                    if dependency_id not in steps[i].depends_on:
                        steps[i].depends_on.append(dependency_id)
                        steps[dep_idx].required_by.append(steps[i].task_id)
                elif dep_ref not in (None, ""):
                    # Preserve an unresolvable reference for validator output.
                    steps[i].depends_on.append(str(dep_ref))
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
        # ``bool`` is an ``int`` subclass, but true/false are never valid
        # dependency references from a structured plan.
        if isinstance(dep_ref, bool):
            return None

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
