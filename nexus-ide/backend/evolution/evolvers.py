"""Evolvers — generate candidate mutations for evolvable components.

Each evolver takes a champion version + failure analysis and produces
candidate versions that address the top-prioritised failure categories.

Every ``generate()`` call is wrapped by :class:`BaseEvolver`, which:

    * validates each produced candidate (:func:`candidate_validation_errors`)
      and drops invalid ones, logging the rejection reason;
    * never lets generation errors escape (a crashing evolver yields ``[]``);
    * supports an optional deterministic ``seed`` so any stochastic mutation
      is reproducible across runs.

Evolvers:
    PromptEvolver      — mutates system prompt text
    SkillEvolver       — evolves skill definitions and usage
    WorkflowEvolver    — changes agent workflow ordering
    ToolEvolver        — adjusts tool selection policies
    MemoryEvolver      — tunes memory retrieval parameters
    CodeEvolver        — adjusts code generation budgets / constraints
    ModelEvolver       — swaps model assignments per task category
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import random
from dataclasses import dataclass
from typing import Any

from backend.evolution.registry import (
    ChampionRegistry,
    ComponentVersion,
    FailureCategory,
    FailurePriority,
)

logger = logging.getLogger(__name__)


@dataclass
class Candidate:
    """A single evolution candidate produced by an evolver."""

    component_kind: str
    config: dict[str, Any]
    changelog: str
    rationale: str
    mutation_type: str  # "prompt_add_constraint", "workflow_reorder", etc.
    targets: list[str]  # failure category names this addresses


# ── Candidate validation ──────────────────────────────────────────────────────

MAX_PROMPT_CHARS = 8000
MIN_TEMPERATURE = 0.0
MAX_TEMPERATURE = 2.0


def candidate_validation_errors(candidate: Candidate) -> list[str]:
    """Return a list of validation problems for a candidate (empty = valid).

    Rules:
        * ``prompt_text`` (when present) must be a non-empty string of at most
          ``MAX_PROMPT_CHARS`` characters.
        * ``temperature`` / ``default_temperature`` (when present) must be a
          real number within ``[MIN_TEMPERATURE, MAX_TEMPERATURE]``.
        * ``config`` must be a JSON-serialisable dict.
    """
    errors: list[str] = []
    config = candidate.config
    if not isinstance(config, dict):
        return [f"config must be a dict, got {type(config).__name__}"]

    if "prompt_text" in config:
        prompt_text = config["prompt_text"]
        if not isinstance(prompt_text, str) or not prompt_text.strip():
            errors.append("prompt_text must be a non-empty string")
        elif len(prompt_text) > MAX_PROMPT_CHARS:
            errors.append(
                f"prompt_text has {len(prompt_text)} chars (max {MAX_PROMPT_CHARS})"
            )

    for temp_key in ("temperature", "default_temperature"):
        if temp_key in config:
            temp = config[temp_key]
            if isinstance(temp, bool) or not isinstance(temp, int | float):
                errors.append(f"{temp_key} must be numeric, got {type(temp).__name__}")
            elif not MIN_TEMPERATURE <= float(temp) <= MAX_TEMPERATURE:
                errors.append(
                    f"{temp_key}={temp} outside [{MIN_TEMPERATURE}, {MAX_TEMPERATURE}]"
                )

    try:
        json.dumps(config)
    except (TypeError, ValueError) as exc:
        errors.append(f"config is not JSON-serialisable: {exc}")

    return errors


class BaseEvolver:
    """Base class for all evolvers.

    Subclasses implement :meth:`_mutate`; the public :meth:`generate` wraps it
    with candidate validation, crash-safety (never raises), and deterministic
    seeding.
    """

    component_kind: str = ""

    def __init__(self, registry: ChampionRegistry, seed: int | None = None) -> None:
        self._registry = registry
        self.seed = seed
        self._rng = random.Random(seed)

    def generate(
        self,
        champion: ComponentVersion,
        failure_priorities: list[FailurePriority],
        n_candidates: int = 3,
    ) -> list[Candidate]:
        """Generate *validated* candidate mutations.

        Wraps :meth:`_mutate`: invalid candidates are dropped with the reason
        logged, and any unexpected exception is caught and logged instead of
        propagating. Always returns a list.
        """
        try:
            raw = list(self._mutate(champion, failure_priorities, n_candidates))
        except Exception:
            logger.exception(
                "Evolver %s crashed while generating candidates; skipping",
                type(self).__name__,
            )
            return []
        return self._filter_valid(raw)

    def _mutate(
        self,
        champion: ComponentVersion,
        failure_priorities: list[FailurePriority],
        n_candidates: int = 3,
    ) -> list[Candidate]:
        """Produce raw candidate mutations (implemented by subclasses)."""
        raise NotImplementedError

    def _filter_valid(self, candidates: list[Candidate]) -> list[Candidate]:
        """Drop invalid candidates, logging each rejection reason."""
        valid: list[Candidate] = []
        for cand in candidates:
            problems = candidate_validation_errors(cand)
            if problems:
                logger.warning(
                    "Rejected %s candidate %r targeting %s: %s",
                    type(self).__name__,
                    cand.mutation_type,
                    ",".join(cand.targets) or "(none)",
                    "; ".join(problems),
                )
                continue
            valid.append(cand)
        return valid

    def _next_version(self) -> str:
        return self._registry.next_version(self.component_kind)

    def _hash_config(self, config: dict[str, Any]) -> str:
        """Get a short hash of config for versioning."""
        content = str(sorted(config.items()))
        return hashlib.md5(content.encode()).hexdigest()[:8]


class PromptEvolver(BaseEvolver):
    """Mutates system prompt text to address specific failure categories.

    What it mutates: appends constraint/instruction blocks to
    ``config["prompt_text"]`` (all other champion config keys are preserved).

    Strategies:
        - Add anti-hallucination constraints when HALLUCINATED_API is common
        - Add explicit planning steps for BAD_PLANNING
        - Add tool usage guidance for TOOL_SELECTION_ERROR
        - Add context-checking prompts for INSUFFICIENT_CONTEXT
    """

    component_kind = "prompt"

    # Prompt additions keyed by failure category
    _CONSTRAINTS: dict[FailureCategory, list[str]] = {
        FailureCategory.HALLUCINATED_API: [
            "Do NOT invent or hallucinate API calls. If you don't know the API, state this explicitly.",
            "Before calling a tool, verify its exact name exists in your available tools.",
        ],
        FailureCategory.BAD_PLANNING: [
            "Before writing code, outline your plan: 1) Identify the problem, 2) List required changes, 3) Implement step by step, 4) Verify.",
            "Always check dependencies between tasks before execution; never assume ordering.",
        ],
        FailureCategory.TOOL_SELECTION_ERROR: [
            "You have these tools available: read, write, edit, bash, grep, glob. Use them appropriately.",
            "Check tool arguments before calling — each tool has specific required parameters.",
        ],
        FailureCategory.INSUFFICIENT_CONTEXT: [
            "Before acting, read the relevant files to gather context. Don't guess.",
            "If information is missing, ask for it rather than assuming defaults.",
        ],
        FailureCategory.TOO_MANY_CALLS: [
            "Batch independent tool calls in a single message to reduce round-trips.",
            "Avoid redundant file reads — cache results from previous steps.",
        ],
        FailureCategory.TEST_MISUNDERSTANDING: [
            "Read the test file carefully. The test asserts specific behavior — match it exactly.",
            "Run tests after changes and read failure output to understand what's expected.",
        ],
        FailureCategory.DEPENDENCY_PROBLEM: [
            "Check installed packages before using them. Run 'pip list' or check requirements files.",
        ],
        FailureCategory.TIMEOUT: [
            "Set explicit timeouts for operations. If a task is taking too long, simplify the approach.",
        ],
        FailureCategory.INFINITE_LOOP: [
            "Track which steps you've already taken. If retrying the same step, stop and reassess.",
        ],
    }

    def _mutate(
        self,
        champion: ComponentVersion,
        failure_priorities: list[FailurePriority],
        n_candidates: int = 3,
    ) -> list[Candidate]:
        """Append category-specific constraints to the champion prompt text."""
        if not failure_priorities:
            return self._generate_generic(champion, n_candidates)

        candidates: list[Candidate] = []
        base_prompt = champion.config.get("prompt_text", "")
        for priority in failure_priorities:
            constraints = self._CONSTRAINTS.get(priority.category, [])
            if not constraints:
                continue
            for constraint in constraints:
                new_prompt = base_prompt + f"\n\n## Constraints\n{constraint}\n"
                candidate = Candidate(
                    component_kind=self.component_kind,
                    config={
                        **champion.config,
                        "prompt_text": new_prompt,
                        "mutation_hash": self._hash_config({"prompt": new_prompt}),
                    },
                    changelog=f"Added constraint for {priority.category.value}",
                    rationale=(
                        f"Priority {priority.priority_score:.3f} failure category "
                        f"{priority.category.value}: {constraint[:80]}..."
                    ),
                    mutation_type="prompt_add_constraint",
                    targets=[priority.category.value],
                )
                candidates.append(candidate)
                if len(candidates) >= n_candidates:
                    return candidates

        # If fewer candidates than requested, fill with generic mutations
        if len(candidates) < n_candidates:
            generic = self._generate_generic(champion, n_candidates - len(candidates))
            candidates.extend(generic)
        return candidates[:n_candidates]

    def _generate_generic(
        self, champion: ComponentVersion, n_candidates: int
    ) -> list[Candidate]:
        """Generate generic prompt mutations when no priorities exist."""
        base_prompt = champion.config.get("prompt_text", "")
        templates = [
            ("\n\n## Instruction\nBe concise and precise in all responses.\n", "concise_tone"),
            ("\n\n## Instruction\nDouble-check your work before finalizing.\n", "double_check"),
            ("\n\n## Instruction\nExplain your reasoning step by step.\n", "step_by_step"),
        ]
        candidates = []
        for addition, mutation in templates[:n_candidates]:
            new_prompt = base_prompt + addition
            candidates.append(Candidate(
                component_kind=self.component_kind,
                config={**champion.config, "prompt_text": new_prompt,
                        "mutation_hash": self._hash_config({"prompt": new_prompt})},
                changelog=f"Generic prompt mutation: {mutation}",
                rationale="No specific failures to address; generic improvement",
                mutation_type=mutation,
                targets=[],
            ))
        return candidates


class SkillEvolver(BaseEvolver):
    """Evolves skill definitions and usage policies.

    What it mutates: merges mutation params into the champion config and adds
    a structured ``config["skill_payload"]`` with a concrete ``skill_name``,
    ``description`` and an explicit ``rules`` list, so downstream skill
    registration receives actionable definitions instead of vague blobs.

    Strategies:
        - Increase retrieval k for MEMORY_RETRIEVAL_ERROR
        - Add new skill triggers for HALLUCINATED_API
        - Modify tool selection policies for TOOL_SELECTION_ERROR
        - Adjust confidence thresholds for TEST_MISUNDERSTANDING
    """

    component_kind = "skill"

    _SKILL_MUTATIONS: dict[FailureCategory, list[dict[str, Any]]] = {
        FailureCategory.MEMORY_RETRIEVAL_ERROR: [
            {
                "mutation": "increase_k",
                "params": {"retrieval_k": 15},
                "description": "Deepen memory retrieval when relevant context is missed.",
                "rules": [
                    "Retrieve up to 15 candidates from memory before ranking.",
                    "If fewer than 3 results score above 0.5, widen the query and retry once.",
                ],
            },
            {
                "mutation": "add_rerank",
                "params": {"rerank_threshold": 0.7},
                "description": "Re-rank retrieved memories to surface the most relevant hits.",
                "rules": [
                    "Re-rank all retrieval candidates; keep only those scoring >= 0.7.",
                    "Fall back to unranked top-k if the re-ranker errors or times out.",
                ],
            },
        ],
        FailureCategory.TOO_MANY_CALLS: [
            {
                "mutation": "batch_calls",
                "params": {"batch_size": 4},
                "description": "Batch independent tool calls to cut round-trips.",
                "rules": [
                    "Group up to 4 independent tool calls per message.",
                    "Never batch calls whose arguments depend on earlier results.",
                ],
            },
            {
                "mutation": "cache_results",
                "params": {"cache_ttl": 300},
                "description": "Cache tool/read results to avoid redundant work.",
                "rules": [
                    "Cache identical read/grep/glob results for 300 seconds.",
                    "Invalidate cached entries whenever a write touches the same path.",
                ],
            },
        ],
        FailureCategory.TOOL_SELECTION_ERROR: [
            {
                "mutation": "add_tool_validator",
                "params": {"validate_args": True},
                "description": "Validate tool arguments before invocation.",
                "rules": [
                    "Check every tool call against its declared required parameters.",
                    "On validation failure, fix the arguments instead of calling blind.",
                ],
            },
        ],
        FailureCategory.INFINITE_LOOP: [
            {
                "mutation": "optimize_loop",
                "params": {"max_iterations": 10},
                "description": "Cap retry loops so agents cannot spin forever.",
                "rules": [
                    "Stop after 10 iterations on the same sub-goal.",
                    "On hitting the cap, escalate with a summary of attempted steps.",
                ],
            },
        ],
    }

    def _mutate(
        self,
        champion: ComponentVersion,
        failure_priorities: list[FailurePriority],
        n_candidates: int = 3,
    ) -> list[Candidate]:
        """Merge mutation params and attach a structured skill payload."""
        candidates: list[Candidate] = []
        seen_mutations: set[str] = set()

        for priority in failure_priorities:
            mutations = self._SKILL_MUTATIONS.get(priority.category, [])
            for mut in mutations:
                if mut["mutation"] in seen_mutations:
                    continue
                seen_mutations.add(mut["mutation"])

                new_config = copy.deepcopy(champion.config)
                new_config.update(mut["params"])
                new_config["skill_payload"] = {
                    "skill_name": mut["mutation"],
                    "description": mut["description"],
                    "rules": list(mut["rules"]),
                }
                new_config["mutation_hash"] = self._hash_config(new_config)

                rules_summary = "; ".join(mut["rules"][:2])
                candidates.append(Candidate(
                    component_kind=self.component_kind,
                    config=new_config,
                    changelog=(
                        f"Skill mutation: {mut['mutation']} for {priority.category.value} "
                        f"({len(mut['rules'])} rules)"
                    ),
                    rationale=(
                        f"Addresses {priority.category.value} "
                        f"(priority {priority.priority_score:.3f}). "
                        f"Skill '{mut['mutation']}': {mut['description']} Rules: {rules_summary}"
                    ),
                    mutation_type=mut["mutation"],
                    targets=[priority.category.value],
                ))
                if len(candidates) >= n_candidates:
                    break
            if len(candidates) >= n_candidates:
                break

        return candidates


class WorkflowEvolver(BaseEvolver):
    """Changes agent workflow ordering and step structure.

    What it mutates: appends steps to ``config["workflow_steps"]`` (or
    reorders the first two steps in the generic fallback) and records the
    applied mutation under ``config["mutation_type"]``.

    Strategies:
        - Reorder steps for BAD_PLANNING
        - Add verification steps for INCORRECT_CODE
        - Add context-gathering steps for INSUFFICIENT_CONTEXT
    """

    component_kind = "workflow"

    _WORKFLOW_MUTATIONS: dict[FailureCategory, dict[str, Any]] = {
        FailureCategory.BAD_PLANNING: {
            "mutation": "add_planning_phase",
            "description": "Insert explicit planning phase before implementation",
            "steps_added": ["plan", "verify_plan", "implement"],
        },
        FailureCategory.INCORRECT_CODE: {
            "mutation": "add_verification_step",
            "description": "Add test verification after code generation",
            "steps_added": ["write_tests", "run_tests", "verify_output"],
        },
        FailureCategory.INSUFFICIENT_CONTEXT: {
            "mutation": "add_context_gathering",
            "description": "Gather context before acting",
            "steps_added": ["read_relevant_files", "understand_requirements"],
        },
        FailureCategory.TOO_MANY_CALLS: {
            "mutation": "consolidate_steps",
            "description": "Batch independent operations",
            "steps_added": ["batch_tool_calls"],
        },
    }

    def _mutate(
        self,
        champion: ComponentVersion,
        failure_priorities: list[FailurePriority],
        n_candidates: int = 3,
    ) -> list[Candidate]:
        """Append category-specific steps to the champion workflow."""
        candidates: list[Candidate] = []

        for priority in failure_priorities[:n_candidates]:
            mutation = self._WORKFLOW_MUTATIONS.get(priority.category)
            if mutation is None:
                continue

            new_config = copy.deepcopy(champion.config)
            base_steps = new_config.get("workflow_steps", [])
            added = mutation["steps_added"]
            new_config["workflow_steps"] = base_steps + added
            new_config["mutation_type"] = mutation["mutation"]
            new_config["mutation_hash"] = self._hash_config(new_config)

            candidates.append(Candidate(
                component_kind=self.component_kind,
                config=new_config,
                changelog=f"Workflow: {mutation['description']}",
                rationale=f"Addresses {priority.category.value} (priority {priority.priority_score:.3f})",
                mutation_type=mutation["mutation"],
                targets=[priority.category.value],
            ))

        # If fewer candidates than requested, add generic reorderings
        remaining = n_candidates - len(candidates)
        if remaining > 0:
            new_config = copy.deepcopy(champion.config)
            steps = new_config.get("workflow_steps", [])
            if len(steps) > 2:
                # Generic step reordering
                steps = list(reversed(steps[:2])) + steps[2:]
                new_config["workflow_steps"] = steps
                new_config["mutation_hash"] = self._hash_config(new_config)
                candidates.append(Candidate(
                    component_kind=self.component_kind,
                    config=new_config,
                    changelog="Generic workflow step reordering",
                    rationale="No specific failures to address",
                    mutation_type="reorder_steps",
                    targets=[],
                ))

        return candidates


class ToolEvolver(BaseEvolver):
    """Evolves tool selection and usage policies.

    What it mutates: merges tool policy params into the champion config
    (``validate_tool_args``, batching flags, ``tool_timeout_sec``,
    ``retry_attempts``); generic fallback raises ``timeout_sec``.

    Strategies:
        - Add validation for tool args (TOOL_SELECTION_ERROR)
        - Increase batch size for tool calls (TOO_MANY_CALLS)
        - Adjust retry policies for TIMEOUT
    """

    component_kind = "tool"

    _TOOL_MUTATIONS: dict[FailureCategory, dict[str, Any]] = {
        FailureCategory.TOOL_SELECTION_ERROR: {
            "mutation": "add_tool_validation",
            "params": {"validate_tool_args": True, "allowlist_tools": True},
        },
        FailureCategory.TOO_MANY_CALLS: {
            "mutation": "batch_tool_calls",
            "params": {"batch_tool_calls": True, "max_batch_size": 4},
        },
        FailureCategory.TIMEOUT: {
            "mutation": "add_timeout_retry",
            "params": {"tool_timeout_sec": 30, "retry_attempts": 3},
        },
    }

    def _mutate(
        self,
        champion: ComponentVersion,
        failure_priorities: list[FailurePriority],
        n_candidates: int = 3,
    ) -> list[Candidate]:
        """Merge category-specific tool policy params into the champion config."""
        candidates: list[Candidate] = []

        for priority in failure_priorities[:n_candidates]:
            mutation = self._TOOL_MUTATIONS.get(priority.category)
            if mutation is None:
                continue

            new_config = copy.deepcopy(champion.config)
            new_config.update(mutation["params"])
            new_config["mutation_hash"] = self._hash_config(new_config)

            candidates.append(Candidate(
                component_kind=self.component_kind,
                config=new_config,
                changelog=f"Tool: {mutation['mutation']}",
                rationale=f"Addresses {priority.category.value} (priority {priority.priority_score:.3f})",
                mutation_type=mutation["mutation"],
                targets=[priority.category.value],
            ))

        # Fill remaining with generic mutations
        remaining = n_candidates - len(candidates)
        if remaining > 0:
            new_config = copy.deepcopy(champion.config)
            new_config["timeout_sec"] = max(
                new_config.get("timeout_sec", 30) + 5, 60
            )
            new_config["mutation_hash"] = self._hash_config(new_config)
            candidates.append(Candidate(
                component_kind=self.component_kind,
                config=new_config,
                changelog="Increased tool timeout",
                rationale="Generic timeout improvement",
                mutation_type="increase_timeout",
                targets=[],
            ))

        return candidates


class MemoryEvolver(BaseEvolver):
    """Tunes memory retrieval parameters.

    What it mutates: ``config["retrieval_k"]`` and
    ``config["confidence_threshold"]`` (raised/lowered relative to the
    champion values, bounded to sane minimums).

    Strategies:
        - Increase retrieval k for MEMORY_RETRIEVAL_ERROR
        - Adjust confidence threshold for MEMORY_RETRIEVAL_ERROR
        - Change embedding model for MEMORY_RETRIEVAL_ERROR
    """

    component_kind = "memory"

    def _mutate(
        self,
        champion: ComponentVersion,
        failure_priorities: list[FailurePriority],
        n_candidates: int = 3,
    ) -> list[Candidate]:
        """Tune retrieval_k / confidence_threshold relative to the champion."""
        candidates: list[Candidate] = []
        memory_priorities = [p for p in failure_priorities if p.category == FailureCategory.MEMORY_RETRIEVAL_ERROR]
        # Memory-specific mutations
        mutations: list[tuple[dict[str, Any], str, str]] = []

        if memory_priorities:
            mutations.append(
                ({"retrieval_k": champion.config.get("retrieval_k", 5) + 3},
                 "increase_retrieval_k",
                 "Increased retrieval depth for memory misses")
            )
            mutations.append(
                ({"confidence_threshold": max(champion.config.get("confidence_threshold", 0.7) - 0.1, 0.3)},
                 "lower_confidence_threshold",
                 "Lowered confidence threshold to retrieve more context")
            )
        else:
            # Generic memory mutations
            mutations.append(
                ({"retrieval_k": champion.config.get("retrieval_k", 5) + 2},
                 "increase_retrieval_k",
                 "Generic: increased retrieval depth")
            )

        for params, mutation_type, changelog in mutations[:n_candidates]:
            new_config = copy.deepcopy(champion.config)
            new_config.update(params)
            new_config["mutation_hash"] = self._hash_config(new_config)

            targets = [p.category.value for p in memory_priorities]
            candidates.append(Candidate(
                component_kind=self.component_kind,
                config=new_config,
                changelog=changelog,
                rationale=f"Memory tuning for {len(memory_priorities)} priority failures",
                mutation_type=mutation_type,
                targets=targets,
            ))

        return candidates


class CodeEvolver(BaseEvolver):
    """Evolves code generation configuration (budgets, constraints).

    What it mutates: code-gen policy flags and budgets in the champion config
    (``review_iterations``, ``self_check``, ``test_driven``,
    ``max_iterations``, dependency checks); generic fallback reduces
    ``max_lines_per_file``.

    Strategies:
        - Increase review budget for INCORRECT_CODE
        - Add test-first approach for TEST_MISUNDERSTANDING
        - Adjust max iterations for INFINITE_LOOP
    """

    component_kind = "coder"

    _CODE_MUTATIONS: dict[FailureCategory, dict[str, Any]] = {
        FailureCategory.INCORRECT_CODE: {
            "mutation": "increase_review_budget",
            "params": {"review_iterations": 3, "self_check": True},
        },
        FailureCategory.TEST_MISUNDERSTANDING: {
            "mutation": "test_first",
            "params": {"test_driven": True, "run_tests_before_submit": True},
        },
        FailureCategory.INFINITE_LOOP: {
            "mutation": "limit_iterations",
            "params": {"max_iterations": 8, "early_exit_check": True},
        },
        FailureCategory.DEPENDENCY_PROBLEM: {
            "mutation": "check_deps",
            "params": {"verify_dependencies": True, "install_missing": True},
        },
    }

    def _mutate(
        self,
        champion: ComponentVersion,
        failure_priorities: list[FailurePriority],
        n_candidates: int = 3,
    ) -> list[Candidate]:
        """Merge category-specific code-gen policy params into the config."""
        candidates: list[Candidate] = []

        for priority in failure_priorities[:n_candidates]:
            mutation = self._CODE_MUTATIONS.get(priority.category)
            if mutation is None:
                continue

            new_config = copy.deepcopy(champion.config)
            new_config.update(mutation["params"])
            new_config["mutation_hash"] = self._hash_config(new_config)

            candidates.append(Candidate(
                component_kind=self.component_kind,
                config=new_config,
                changelog=f"Code: {mutation['mutation']}",
                rationale=f"Addresses {priority.category.value} (priority {priority.priority_score:.3f})",
                mutation_type=mutation["mutation"],
                targets=[priority.category.value],
            ))

        # Fill remaining with generic mutations
        remaining = n_candidates - len(candidates)
        if remaining > 0:
            new_config = copy.deepcopy(champion.config)
            new_config["max_lines_per_file"] = max(
                new_config.get("max_lines_per_file", 500) - 50, 200
            )
            new_config["mutation_hash"] = self._hash_config(new_config)
            candidates.append(Candidate(
                component_kind=self.component_kind,
                config=new_config,
                changelog="Reduced max lines per file to reduce code complexity",
                rationale="Generic code complexity reduction",
                mutation_type="reduce_complexity",
                targets=[],
            ))

        return candidates


class ModelEvolver(BaseEvolver):
    """Evolves model selection assignments per task category.

    What it mutates: ``config["default_model"]``, ``config["default_tier"]``
    and ``config["default_temperature"]`` (temperatures are always kept
    within ``[MIN_TEMPERATURE, MAX_TEMPERATURE]``); generic fallback upgrades
    the tier one step.

    Strategies:
        - Swap to more capable model for ERROR categories
        - Adjust temperature per task type
        - Change model tier assignment
    """

    component_kind = "model"

    # Model capability tiers
    _MODELS = {
        "micro": {"name": "gpt-4o-mini", "tier": "micro", "cost_per_1k": 0.00015},
        "fast": {"name": "gpt-4o", "tier": "fast", "cost_per_1k": 0.003},
        "coder": {"name": "o1-preview", "tier": "coder", "cost_per_1k": 0.015},
        "reasoning": {"name": "o1", "tier": "reasoning", "cost_per_1k": 0.06},
    }

    _CATEGORY_MODEL_MAPPING: dict[FailureCategory, dict[str, Any]] = {
        FailureCategory.INCORRECT_CODE: {"model": "coder", "temperature": 0.1},
        FailureCategory.HALLUCINATED_API: {"model": "reasoning", "temperature": 0.0},
        FailureCategory.INTERNAL_PLANNING: {"model": "reasoning", "temperature": 0.2},
        FailureCategory.TEST_MISUNDERSTANDING: {"model": "coder", "temperature": 0.0},
        FailureCategory.DEPENDENCY_PROBLEM: {"model": "fast", "temperature": 0.1},
        FailureCategory.TIMEOUT: {"model": "fast", "temperature": 0.1},
    }

    def _mutate(
        self,
        champion: ComponentVersion,
        failure_priorities: list[FailurePriority],
        n_candidates: int = 3,
    ) -> list[Candidate]:
        """Swap default_model / default_tier / default_temperature per category."""
        candidates: list[Candidate] = []
        seen_configs: set[str] = set()

        for priority in failure_priorities[:n_candidates]:
            mapping = self._CATEGORY_MODEL_MAPPING.get(priority.category)
            if mapping is None:
                continue

            new_config = copy.deepcopy(champion.config)
            model_info = self._MODELS.get(mapping["model"], {})
            new_config["default_model"] = model_info.get("name", "gpt-4o")
            new_config["default_tier"] = mapping["model"]
            new_config["default_temperature"] = mapping["temperature"]
            new_config["mutation_hash"] = self._hash_config(new_config)

            config_key = json.dumps(new_config, sort_keys=True)
            if config_key in seen_configs:
                continue
            seen_configs.add(config_key)

            candidates.append(Candidate(
                component_kind=self.component_kind,
                config=new_config,
                changelog=f"Switched to {mapping['model']} model for {priority.category.value}",
                rationale=f"More capable model for {priority.category.value} failures (priority {priority.priority_score:.3f})",
                mutation_type="model_swap",
                targets=[priority.category.value],
            ))

        if not candidates:
            # Generic: downgrade cheap model assignments to improve quality
            new_config = copy.deepcopy(champion.config)
            current_tier = new_config.get("default_tier", "micro")
            tier_order = ["micro", "fast", "coder", "reasoning"]
            if current_tier in tier_order and tier_order.index(current_tier) < len(tier_order) - 1:
                next_tier = tier_order[tier_order.index(current_tier) + 1]
                model_info = self._MODELS[next_tier]
                new_config["default_model"] = model_info["name"]
                new_config["default_tier"] = next_tier
                new_config["mutation_hash"] = self._hash_config(new_config)
                candidates.append(Candidate(
                    component_kind=self.component_kind,
                    config=new_config,
                    changelog=f"Upgraded model tier from {current_tier} to {next_tier}",
                    rationale="Generic model upgrade",
                    mutation_type="model_upgrade",
                    targets=[],
                ))

        return candidates


# ── Evolver factory ────────────────────────────────────────────────────────────

_EVOLVERS: dict[str, type[BaseEvolver]] = {
    "prompt": PromptEvolver,
    "skill": SkillEvolver,
    "workflow": WorkflowEvolver,
    "tool": ToolEvolver,
    "memory": MemoryEvolver,
    "coder": CodeEvolver,
    "model": ModelEvolver,
}


def valid_component_kinds() -> list[str]:
    """Return the component kinds that have an evolver."""
    return sorted(_EVOLVERS)


class UnknownComponentError(ValueError):
    """Raised when requesting an evolver for an unknown component kind."""

    def __init__(self, component_kind: str) -> None:
        self.component_kind = component_kind
        super().__init__(
            f"Unknown evolver component kind {component_kind!r}. "
            f"Valid kinds: {', '.join(valid_component_kinds())}"
        )


def get_evolver(
    component_kind: str,
    registry: ChampionRegistry,
    seed: int | None = None,
    *,
    strict: bool = False,
) -> BaseEvolver | None:
    """Factory: get the appropriate evolver for a component kind.

    Args:
        component_kind: One of :func:`valid_component_kinds`.
        registry: Champion registry shared by evolvers.
        seed: Optional deterministic seed forwarded to the evolver.
        strict: When True, raise :class:`UnknownComponentError` (with the
            list of valid kinds) instead of returning None for unknown kinds.

    Returns:
        The evolver instance, or None when unknown and ``strict`` is False.
    """
    evolver_cls = _EVOLVERS.get(component_kind)
    if evolver_cls is None:
        if strict:
            raise UnknownComponentError(component_kind)
        logger.warning(
            "No evolver registered for component kind %r (valid: %s)",
            component_kind,
            ", ".join(valid_component_kinds()),
        )
        return None
    return evolver_cls(registry, seed=seed)


def get_all_evolvers(registry: ChampionRegistry, seed: int | None = None) -> list[BaseEvolver]:
    """Get all evolvers, sharing the same optional deterministic seed."""
    return [cls(registry, seed=seed) for cls in _EVOLVERS.values()]
