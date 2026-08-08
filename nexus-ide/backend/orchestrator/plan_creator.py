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
from typing import Any

from backend.config.settings import get_model_config, load_prompt
from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode, TaskPriority
from backend.orchestrator.events import EventEmitter, EventType, OrchestratorEvent
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

        # Feed the planner recalled project knowledge before it decomposes the
        # goal.  Specialist consultation is targeted rather than unconditional
        # so routine plans do not spend budget on irrelevant sub-agents.
        planning_context = await self._gather_planning_context(
            objective, session_id, context, project_path
        )
        planning_prompt = self._build_planning_prompt(objective, planning_context)

        # Use coder model directly for clean JSON output (not the architect agent)
        planner_cfg = get_model_config("coder")
        planner_models = self._planner_model_chain(planner_cfg)
        # Keep planning policy in a first-class agent prompt.  The planner
        # prompt requires recalled context, specialist consultation where it
        # is useful, and an executable verification step.
        system_prompt = load_prompt("planner")

        messages = [
            ChatMessage(role="system", content=system_prompt),
            ChatMessage(role="user", content=planning_prompt),
        ]

        # Stream planning, walking the model chain on transient provider errors.
        #
        # Why this loop exists: ``PlanCreator`` used to dispatch to a *single*
        # model. Every agent already had a fallback cascade in
        # ``AgentBase.stream_llm``, but planning did not — so one HTTP 429 from
        # the primary model produced an empty ``plan_content``, which
        # ``_parse_plan`` degraded into the three-step fallback plan. A request
        # for a deep multi-phase audit silently became "Execute Objective", and
        # the run reported ``completed`` after touching almost nothing.
        # Evidence: session 27437d6cc61e4753, 2026-07-27T08:18:55Z —
        # "Planner failed ... 429" immediately followed by
        # "creating single-step plan".
        plan_content = ""
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
                                "num_predict": 16384,  # Large plans need more tokens
                            },
                        ):
                            if not isinstance(token, str):
                                logger.warning(
                                    "Ignoring non-text token from planner: %s",
                                    type(token).__name__,
                                )
                                continue
                            plan_content_parts.append(token)
                            # Planner output is machine-readable JSON, not an
                            # assistant answer. Publishing it as TOKEN streamed
                            # the raw plan into chat and made a live run appear
                            # to stop after a JSON dump. PLAN_CREATED below
                            # exposes structured progress without polluting the
                            # user-facing reply.
                except TimeoutError as exc:  # asyncio.TimeoutError is an alias on 3.11+
                    logger.warning(
                        "Planner model %s timed out after %.1fs for session %s (attempt %d/%d)",
                        planner_model,
                        self.PLAN_STREAM_TIMEOUT_SECONDS,
                        session_id,
                        attempt + 1,
                        len(planner_models),
                    )
                    if not await self._retry_planning(
                        emit, planner_models, attempt, exc, retryable=True
                    ):
                        break
                    continue
                except asyncio.CancelledError:
                    # A user cancellation is a decision, never a provider fault.
                    raise
                except Exception as exc:  # noqa: BLE001 - provider errors must not strand a run
                    logger.warning(
                        "Planner model %s failed for session %s (attempt %d/%d): %s",
                        planner_model,
                        session_id,
                        attempt + 1,
                        len(planner_models),
                        exc,
                    )
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
                # An empty or whitespace-only body is a failure even when the
                # provider returned HTTP 200; treat it like any other dud so
                # the next model gets a turn instead of falling straight
                # through to the degraded plan.
                if candidate.strip():
                    plan_content = candidate
                    if attempt:
                        logger.info(
                            "Planner recovered on fallback model %s for session %s",
                            planner_model,
                            session_id,
                        )
                    break
                logger.warning(
                    "Planner model %s returned an empty body for session %s",
                    planner_model,
                    session_id,
                )
                if not await self._retry_planning(
                    emit, planner_models, attempt, None, retryable=True
                ):
                    break

            if not plan_content.strip():
                await emit.emit(
                    EventType.WARNING,
                    content=(
                        "Planning failed on every available model "
                        f"({', '.join(planner_models)}); continuing with a reduced plan."
                    ),
                )

        # Parse plan into structured steps
        plan = self._parse_plan(plan_content, objective, session_id)
        plan.created_at = time.time()

        # The author of the plan is the PLANNER path, not the ARCHITECT agent.
        # Reporting "ARCHITECT" here made the UI attribute planning to an agent
        # that never ran, which sent every debugging session looking in the
        # wrong module.
        await self._events.publish(
            OrchestratorEvent(
                event_type=EventType.PLAN_CREATED,
                source="PLANNER",
                session_id=session_id,
                data=plan.to_dict(),
            )
        )

        return plan

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
Priority values: "high", "medium", "low".
Make steps SPECIFIC and ACTIONABLE. Each step must produce a concrete deliverable.
Include at least 10 steps. More complex objectives should have 15-25 steps.
Use phase prefixes in step names: "Phase N: Name - Description"."""

    @staticmethod
    def _fallback_plan(
        objective: str,
        session_id: str,
        *,
        reason: str = "planner output unusable",
        raw_output: str = "",
    ) -> ExecutionPlan:
        """Return a minimal but *real* plan when planner output is unusable.

        The previous version emitted a single opaque CODER task literally
        named ``"Execute Objective"``.  That had two bad consequences:

        * A rich request ("audit the whole codebase deeply") silently
          collapsed into one generic step, so the run looked complete while
          almost nothing had been done.
        * The failure was invisible — a ``logger.warning`` with no trace of
          *what* the planner actually returned, so nobody could debug it.

        The fallback now degrades into an explicit analyse → execute → verify
        triple that at least matches the shape of a real plan, and logs the
        offending planner output so the root cause is diagnosable.
        """
        logger.warning(
            "Planner fallback engaged (%s) for objective %.120r; raw planner output: %.500r",
            reason,
            objective,
            raw_output,
        )

        short_title = objective.strip().splitlines()[0][:80] if objective.strip() else "Objective"

        analyse = TaskNode(
            name=f"Analyse: {short_title}",
            description=(
                "Break the objective below into concrete work items before "
                "changing anything. Identify the files, modules and risks "
                "involved, and state explicitly what is in and out of scope.\n\n"
                f"OBJECTIVE:\n{objective}"
            ),
            agent="ANALYZER",
            priority=TaskPriority.HIGH,
        )
        execute = TaskNode(
            name=f"Implement: {short_title}",
            description=(
                "Carry out the objective using the analysis from the previous "
                "step. Produce concrete, reviewable changes — do not stop at a "
                "summary.\n\n"
                f"OBJECTIVE:\n{objective}"
            ),
            agent="CODER",
            priority=TaskPriority.HIGH,
        )
        verify = TaskNode(
            name=f"Verify: {short_title}",
            description=(
                "Verify the implementation actually satisfies the objective. "
                "Run available tests, check for syntax and import errors, and "
                "report findings.\n\n"
                "End with a final line of exactly 'VERDICT: PASS' or "
                "'VERDICT: FAIL' followed by the problems found.\n\n"
                f"OBJECTIVE:\n{objective}"
            ),
            agent="DEBUGGER",
            priority=TaskPriority.HIGH,
        )

        execute.depends_on.append(analyse.task_id)
        analyse.required_by.append(execute.task_id)
        verify.depends_on.append(execute.task_id)
        execute.required_by.append(verify.task_id)

        return ExecutionPlan.from_steps(
            title=objective[:100],
            description=objective,
            steps=[analyse, execute, verify],
            session_id=session_id,
        )

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
                text_plan.session_id = session_id
                return text_plan

            return self._fallback_plan(
                objective,
                session_id,
                reason="no JSON array found in planner output",
                raw_output=plan_content,
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
                return self._fallback_plan(
                    objective,
                    session_id,
                    reason="planner JSON failed to parse",
                    raw_output=raw_text,
                )

        if not isinstance(raw_steps, list) or len(raw_steps) == 0:
            return self._fallback_plan(
                objective,
                session_id,
                reason="planner JSON is not a non-empty list",
                raw_output=json_match.group(0),
            )

        valid_raw_steps = [raw for raw in raw_steps if isinstance(raw, dict)]
        if not valid_raw_steps:
            return self._fallback_plan(
                objective,
                session_id,
                reason="planner JSON contained no object steps",
                raw_output=json_match.group(0),
            )
        if len(valid_raw_steps) > self.MAX_PLAN_STEPS:
            logger.warning(
                "Planner returned %d steps; limiting execution plan to %d",
                len(valid_raw_steps),
                self.MAX_PLAN_STEPS,
            )
            valid_raw_steps = valid_raw_steps[: self.MAX_PLAN_STEPS]

        steps: list[TaskNode] = []
        for i, raw in enumerate(valid_raw_steps):
            raw_priority = raw.get("priority", "medium")
            if not isinstance(raw_priority, str):
                raw_priority = "medium"
            priority_upper = raw_priority.strip().upper()
            resolved_priority = (
                TaskPriority[priority_upper]
                if priority_upper in TaskPriority.__members__
                else TaskPriority.MEDIUM
            )
            raw_name = raw.get("name")
            name = raw_name.strip() if isinstance(raw_name, str) else ""
            if not name:
                name = f"Step {i + 1}"
            raw_description = raw.get("description", "")
            description = raw_description.strip() if isinstance(raw_description, str) else ""
            raw_agent = raw.get("agent", "CODER")
            agent = raw_agent.strip().upper() if isinstance(raw_agent, str) else "CODER"
            if agent not in SUPPORTED_PLAN_AGENTS:
                logger.warning("Unknown planner agent %r; assigning task to CODER", raw_agent)
                agent = "CODER"
            task = TaskNode(
                name=name,
                description=description,
                agent=agent,
                priority=resolved_priority,
                sandboxed=raw.get("sandboxed", False) is True,
            )
            steps.append(task)

        if not steps:
            return self._fallback_plan(
                objective,
                session_id,
                reason="no valid steps survived parsing",
                raw_output=json_match.group(0),
            )

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

        for i, raw in enumerate(valid_raw_steps):
            raw_deps = raw.get("depends_on", [])
            if not isinstance(raw_deps, list):
                raw_deps = [raw_deps] if raw_deps else []
            seen_dependencies: set[str] = set()
            for dep_ref in raw_deps:
                dep_idx = self._resolve_dep_ref(dep_ref, len(steps), name_to_idx)
                if dep_idx is not None and dep_idx != i:
                    dependency_id = steps[dep_idx].task_id
                    if dependency_id in seen_dependencies:
                        continue
                    seen_dependencies.add(dependency_id)
                    steps[i].depends_on.append(dependency_id)
                    steps[dep_idx].required_by.append(steps[i].task_id)

        self._ensure_verification_step(steps)

        plan = ExecutionPlan.from_steps(
            title=objective[:100],
            description=objective,
            steps=steps,
            session_id=session_id,
        )
        valid, error = plan.dependency_graph.validate()
        if valid:
            return plan

        # A cyclic dependency means the executor can never find a ready task.
        # Recover deterministically by preserving every generated task but
        # executing them in their declared order.
        logger.warning("Invalid planner dependency graph (%s); rebuilding sequentially", error)
        for step in steps:
            step.depends_on.clear()
            step.required_by.clear()
        for previous, current in zip(steps, steps[1:], strict=False):
            current.depends_on.append(previous.task_id)
            previous.required_by.append(current.task_id)
        return ExecutionPlan.from_steps(
            title=objective[:100],
            description=objective,
            steps=steps,
            session_id=session_id,
        )

    @staticmethod
    def _ensure_verification_step(steps: list[TaskNode]) -> None:
        """Append one executable DEBUGGER gate unless the plan already has one.

        LLM-generated plans can omit their final test step.  A deterministic
        gate keeps verification part of the execution graph rather than a
        best-effort instruction in an agent prompt.
        """
        has_verification = any(
            step.agent == "DEBUGGER"
            and any(
                marker in f"{step.name} {step.description}".lower()
                for marker in ("verify", "verification", "test", "validate", "lint", "build")
            )
            for step in steps
        )
        if has_verification:
            return

        verification = TaskNode(
            name="Verification - run relevant checks",
            description=(
                "Use execute_code to run the narrowest relevant test, build, lint, "
                "or reproduction command. Report the command and its result."
            ),
            agent="DEBUGGER",
            priority=TaskPriority.HIGH,
        )
        for step in steps:
            verification.depends_on.append(step.task_id)
            step.required_by.append(verification.task_id)
        steps.append(verification)

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
