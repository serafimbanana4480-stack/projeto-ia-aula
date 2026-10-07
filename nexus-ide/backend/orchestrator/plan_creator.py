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
from collections.abc import Mapping
from typing import Any

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
    PLAN_REPAIR_TIMEOUT_SECONDS = 45.0
    MAX_PLAN_REPAIR_ATTEMPTS = 1
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

        planner_model = planner_models[0] if planner_models else "coder"
        candidate_plan = self._parse_plan(plan_content, objective, session_id)
        repair_attempts = 0
        if candidate_plan is None and self.MAX_PLAN_REPAIR_ATTEMPTS:
            repaired = await self._repair_plan_content(
                plan_content,
                objective,
                planner_model,
                planner_cfg,
            )
            repair_attempts += 1
            if repaired:
                candidate_plan = self._parse_plan(repaired, objective, session_id)

        # A provider can return a body that is non-empty but not executable.
        # Preserve a validated deterministic proposal so the user can continue
        # explicitly, but never mark it ready here: ``execute_autonomous``
        # auto-approves ready plans, which would turn malformed model output
        # into an unreviewed multi-agent run.
        if candidate_plan is None:
            await self._events.publish(
                OrchestratorEvent(
                    event_type=EventType.WARNING,
                    source="PLANNER",
                    session_id=session_id,
                    content=(
                        "Planner output was not executable after "
                        f"{repair_attempts} structured repair attempt(s); "
                        "a validated deterministic fallback is available for "
                        "explicit continuation."
                    ),
                )
            )
            deterministic.source = "deterministic_fallback"  # type: ignore[attr-defined]
            return PlanningResult(
                status="blocked",
                source="deterministic_fallback",
                error="planner output was not a parseable structured plan",
                deterministic_proposal=deterministic,
            )
        candidate_plan.created_at = time.time()
        candidate_validation = validate_execution_plan(
            candidate_plan, facts, self.MAX_PLAN_STEPS
        )
        if not candidate_validation.valid:
            await self._events.publish(
                OrchestratorEvent(
                    event_type=EventType.WARNING,
                    source="PLANNER",
                    session_id=session_id,
                    content=(
                        "Planner schema validation failed; a validated "
                        "deterministic fallback is available for explicit "
                        "continuation: "
                        + "; ".join(candidate_validation.errors[:4])
                    ),
                )
            )
            deterministic.source = "deterministic_fallback"  # type: ignore[attr-defined]
            return PlanningResult(
                status="blocked",
                source="deterministic_fallback",
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

    async def _repair_plan_content(
        self,
        invalid_content: str,
        objective: str,
        planner_model: str,
        planner_cfg: Mapping[str, Any],
    ) -> str:
        """Ask the same planner for one bounded, JSON-only repair attempt.

        The repair prompt must restate *the same* schema the planning prompt
        asked for. An earlier version asked for a differently-named envelope
        object, so the repair pass converted near-valid output into a shape
        the parser could not read — turning a recoverable formatting slip
        into a blocked run.
        """
        prompt = f"""Repair the following planner response into the required JSON array.

{self._build_planning_prompt(objective, "")}

INVALID RESPONSE TO REPAIR:
{invalid_content[:20000]}

Return ONLY the JSON array. Keep the intent of the invalid response; do not
invent file paths, commands, or tool names that it did not mention."""
        parts: list[str] = []
        try:
            async with asyncio.timeout(self.PLAN_REPAIR_TIMEOUT_SECONDS):
                async for token in self._llm_client.chat_stream(
                    model=planner_model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You repair structured plans. Output JSON only.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    options={
                        "temperature": min(float(planner_cfg.get("temperature", 0.2)), 0.1),
                        "num_predict": 8192,
                    },
                ):
                    if isinstance(token, str):
                        parts.append(token)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Structured planner repair failed: %s", exc)
        return "".join(parts).strip()

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

    @staticmethod
    def _agent_contract_table() -> str:
        """Render the *real* agent/model/tool contract for the prompt.

        The previous prompt hard-coded a prose list of agents and never
        mentioned ``model_key`` or legal tool names, so a model that
        followed it produced a plan the validator rejected on every step.
        Deriving the table from ``capability_matrix()`` keeps the prompt and
        the validator in sync by construction.
        """
        try:
            from backend.orchestrator.agent_capabilities import capability_matrix

            matrix = capability_matrix()
        except Exception:  # pragma: no cover - capability matrix is optional
            return (
                "- CODER (model_key: coder) — implementation\n"
                "- DEBUGGER (model_key: coder) — verification, runs tests\n"
                "- ANALYZER (model_key: reasoning) — review and audit\n"
            )
        wanted = ("ARCHITECT", "CODER", "ANALYZER", "DEBUGGER", "RESEARCHER", "DOCUMENTER")
        lines: list[str] = []
        for agent in wanted:
            capability = matrix.get(agent)
            if capability is None:
                continue
            models = [m for m in capability.allowed_models if "/" not in m]
            tools = ", ".join(sorted(capability.allowed_tools)[:12]) or "(none)"
            lines.append(
                f'- {agent} — model_key: "{models[0] if models else "coder"}" — '
                f"allowed_tools must be a subset of: {tools}"
            )
        return "\n".join(lines)

    def _build_planning_prompt(self, objective: str, context: str) -> str:
        """Build the planning prompt.

        Every field the validator requires is described *and* present in the
        worked example, so a model that copies the example produces an
        executable plan. ``backend/tests/runtime/test_evidence_planner_contract.py``
        pins this: the example is parsed and validated on every test run.
        """
        return f"""Create a small, executable plan for this objective.

OBJECTIVE: {objective}

ADDITIONAL CONTEXT: {context or "None"}

Respond with ONLY a JSON array of steps. No prose, no markdown fence.

Each step is an object with EXACTLY these keys:
  "name"                  short imperative step name
  "description"           what the step does
  "agent"                 one of the agents listed below
  "model_key"             the model_key listed for that agent
  "depends_on"            array of 0-based indexes of earlier steps
  "priority"              "high" | "medium" | "low"
  "file_scope"            array of concrete project-relative paths the step touches
  "completion_criteria"   array of observable, checkable outcomes
  "verification_commands" array of concrete commands (REQUIRED for DEBUGGER)
  "risk"                  "low" | "medium" | "high"
  "rollback"              a concrete rollback instruction
  "lock_scope"            "read:<path>" or "write:<path>" — the smallest scope
  "allowed_tools"         array of tool names allowed for that agent
  "sandboxed"             boolean

AGENTS:
{self._agent_contract_table()}

HARD RULES:
- Emit 3 to 8 steps. Fewer, larger steps beat many tiny ones.
- The final step MUST be a DEBUGGER step with non-empty
  "verification_commands"; a plan with no verification step is rejected.
- Never invent file paths, commands, or tool names. If you do not know a
  path, use "." as the file_scope entry.
- Never name a step "Execute Objective".

WORKED EXAMPLE (copy this shape exactly):
[
  {{"name": "Locate the failing scheduler path", "description": "Read the scheduler and the failing test to identify the ordering defect.", "agent": "ANALYZER", "model_key": "reasoning", "depends_on": [], "priority": "high", "file_scope": ["backend/orchestrator/plan_executor.py"], "completion_criteria": ["the defective code path is identified with a file and line"], "verification_commands": [], "risk": "low", "rollback": "no change is made in this step", "lock_scope": "read:backend/orchestrator", "allowed_tools": ["read_file", "search_codebase"], "sandboxed": false}},
  {{"name": "Fix dependency admission in the scheduler", "description": "Only mark a task READY once every dependency is COMPLETED.", "agent": "CODER", "model_key": "coder", "depends_on": [0], "priority": "high", "file_scope": ["backend/orchestrator/plan_executor.py"], "completion_criteria": ["no task starts while a dependency is unfinished"], "verification_commands": [], "risk": "medium", "rollback": "git checkout -- backend/orchestrator/plan_executor.py", "lock_scope": "write:backend/orchestrator/plan_executor.py", "allowed_tools": ["read_file", "write_file", "search_codebase"], "sandboxed": false}},
  {{"name": "Verify the ordering fix", "description": "Run the scheduler ordering tests and confirm they pass.", "agent": "DEBUGGER", "model_key": "coder", "depends_on": [1], "priority": "high", "file_scope": ["backend/tests/runtime"], "completion_criteria": ["the ordering tests pass"], "verification_commands": ["python -m pytest backend/tests/runtime -q"], "risk": "low", "rollback": "revert the previous step", "lock_scope": "read:backend/tests", "allowed_tools": ["run_tests", "read_file"], "sandboxed": false}}
]"""

    def _parse_plan(
        self,
        plan_content: str,
        objective: str,
        session_id: str,
    ) -> ExecutionPlan | None:
        """Parse equivalent structured JSON envelopes without inventing steps."""
        cleaned = str(plan_content or "").lstrip("\ufeff")
        cleaned = re.sub(
            r"<(?:thinking|think)>.*?</(?:thinking|think)>\s*",
            "",
            cleaned,
            flags=re.DOTALL | re.IGNORECASE,
        )
        cleaned = re.sub(r"```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = cleaned.replace("```", "")

        raw_steps = self._extract_structured_steps(cleaned)
        if raw_steps is None:
            text_plan = self._parse_text_plan(cleaned, objective)
            if text_plan is not None and len(text_plan.steps) > 1:
                text_plan.session_id = session_id
                return text_plan
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
            name_value = raw.get("name", raw.get("id", raw.get("task_id", "")))
            name = name_value if isinstance(name_value, str) else ""
            description = raw.get("description") if isinstance(raw.get("description"), str) else ""
            agent_value = raw.get("agent", raw.get("agent_type", ""))
            agent = agent_value if isinstance(agent_value, str) else ""
            file_scope = self._normalize_string_list(raw.get("file_scope", raw.get("files", [])))
            criteria = self._normalize_string_list(
                raw.get("completion_criteria", raw.get("acceptance_criteria", []))
            )
            verification = self._normalize_string_list(
                raw.get("verification_commands", raw.get("validation", []))
            )
            allowed_tools = self._normalize_string_list(
                raw.get("allowed_tools", raw.get("tools", []))
            )
            steps.append(
                TaskNode(
                    name=name.strip(),
                    description=description.strip(),
                    agent=agent.strip().upper(),
                    model_key=str(raw.get("model_key", raw.get("model", ""))).strip(),
                    priority=priority,
                    sandboxed=raw.get("sandboxed", False) is True,
                    file_scope=file_scope,
                    completion_criteria=criteria,
                    verification_commands=verification,
                    risk=str(raw.get("risk", "")),
                    rollback=str(raw.get("rollback", "")),
                    lock_scope=str(raw.get("lock_scope", raw.get("scope", ""))),
                    allowed_tools=allowed_tools,
                )
            )
        name_to_idx: dict[str, int] = {
            step.name.lower(): idx for idx, step in enumerate(steps) if step.name
        }
        for i, raw in enumerate(valid_raw_steps):
            raw_deps = raw.get("depends_on", raw.get("dependencies", []))
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
    def _normalize_string_list(value: Any) -> list[str]:
        """Normalize provider aliases without turning arbitrary objects into tools."""
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if not isinstance(value, list):
            return []
        normalized: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                normalized.append(item.strip())
            elif isinstance(item, dict):
                command = item.get("command") or item.get("name")
                if isinstance(command, str) and command.strip():
                    normalized.append(command.strip())
        return normalized

    @staticmethod
    def _extract_structured_steps(content: str) -> list[Any] | None:
        """Extract a JSON array or a documented ``steps``/``plan`` envelope.

        Providers commonly wrap otherwise valid JSON in a short preamble or an
        object envelope.  This method only unwraps known structural forms; it
        never repairs missing fields or converts prose into executable tasks.
        """
        decoder = json.JSONDecoder()
        candidates: list[str] = []
        # Providers often put bullets, a title, or a second fenced block before
        # the JSON. Try every plausible opening marker in a bounded window so a
        # harmless preamble cannot make an otherwise valid plan disappear.
        starts = [
            index
            for index, char in enumerate(content[:32_000])
            if char in "[{"
        ][:64]
        for start in starts:
            candidates.append(content[start:])

        for candidate in candidates:
            try:
                value, _end = decoder.raw_decode(candidate)
            except json.JSONDecodeError:
                # Keep the existing narrow tolerance for trailing commas in
                # otherwise JSON-shaped provider output.
                try:
                    repaired = re.sub(r",\s*([}\]])", r"\1", candidate)
                    value, _end = decoder.raw_decode(repaired)
                except json.JSONDecodeError:
                    continue

            if isinstance(value, list) and value:
                return value
            if isinstance(value, dict):
                for key in ("steps", "plan", "tasks"):
                    nested = value.get(key)
                    if isinstance(nested, list) and nested:
                        return nested
        return None

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
