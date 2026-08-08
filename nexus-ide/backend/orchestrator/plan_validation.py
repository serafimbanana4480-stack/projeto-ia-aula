"""Deterministic construction and validation for execution plans.

Planning is deliberately fail-closed: a model may improve a known local
proposal, but it may not invent an executable plan that has not passed these
checks.  This module contains no provider calls and is safe to use in tests or
when the model service is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from backend.orchestrator.dependency_graph import ExecutionPlan, TaskNode, TaskPriority

PlanningStatus = Literal["ready", "blocked"]


@dataclass
class PlanValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class PlanningResult:
    """The only planning value consumed by the orchestration engine."""

    status: PlanningStatus
    plan: ExecutionPlan | None = None
    source: str = ""
    error: str | None = None
    deterministic_proposal: ExecutionPlan | None = None

    # The forwarding properties keep older integrations that inspected the
    # former ExecutionPlan return value readable while callers migrate to the
    # explicit result contract.
    def __getattr__(self, name: str) -> Any:
        plan = object.__getattribute__(self, "plan")
        if plan is not None:
            return getattr(plan, name)
        proposal = object.__getattribute__(self, "deterministic_proposal")
        if proposal is not None:
            return getattr(proposal, name)
        raise AttributeError(name)

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def blocked(self) -> bool:
        return self.status == "blocked"


def _snapshot_value(snapshot: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = snapshot.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _as_text_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _project_files(snapshot: Mapping[str, Any]) -> list[str]:
    candidates: list[str] = []
    for key in ("modified_files", "files", "entrypoints", "dependency_manifests", "config_files"):
        candidates.extend(_as_text_list(snapshot.get(key)))
    root = _snapshot_value(snapshot, "absolute_path", "root", "project_path")
    if root:
        candidates.insert(0, str(root))
    # Preserve order: it makes the generated proposal stable across runs.
    return list(dict.fromkeys(candidates)) or ["."]


def _commands(snapshot: Mapping[str, Any], *, verification: bool = False) -> list[str]:
    value = _snapshot_value(snapshot, "verification_commands" if verification else "commands", "test_commands")
    commands = _as_text_list(value)
    if commands:
        return commands[:8]
    frameworks = {str(item).lower() for item in _as_text_list(snapshot.get("test_frameworks"))}
    manifests = {str(item).lower() for item in _as_text_list(snapshot.get("dependency_manifests"))}
    if "pytest" in frameworks or "pyproject.toml" in manifests or "pytest.ini" in manifests:
        return ["python -m pytest -q"]
    if "vitest" in frameworks:
        return ["npm test -- --run"]
    if "jest" in frameworks:
        return ["npm test -- --runInBand"]
    if "package.json" in manifests:
        return ["npm test"]
    return ["python -m compileall -q ."]


def _risk(snapshot: Mapping[str, Any]) -> str:
    findings = snapshot.get("findings", [])
    if isinstance(findings, list):
        for finding in findings:
            severity = finding.get("severity") if isinstance(finding, Mapping) else getattr(finding, "severity", "")
            if str(getattr(severity, "value", severity)).lower() in {"critical", "high"}:
                return "high"
    if snapshot.get("unknowns") or snapshot.get("truncated"):
        return "medium"
    return "low"


def _task_metadata(
    *,
    file_scope: list[str],
    criteria: list[str],
    commands: list[str],
    risk: str,
    rollback: str,
    lock_scope: str,
) -> dict[str, Any]:
    return {
        "file_scope": file_scope,
        "completion_criteria": criteria,
        "verification_commands": commands,
        "risk": risk,
        "rollback": rollback,
        "lock_scope": lock_scope,
    }
def _registered_planning_tools(preferred: list[str], agent: str | None = None) -> list[str]:
    """Select tools from the live registry and, when available, agent contract."""
    allowed: set[str] | None = None
    try:
        from backend.orchestrator.agent_capabilities import get_agent_capability

        allowed = set(get_agent_capability(agent).allowed_tools) if agent else None
    except Exception:
        allowed = None
    try:
        from backend.tools.registry import list_tools

        available = {str(spec.name) for spec in list_tools(enabled_only=True)}
        return [
            tool for tool in preferred
            if tool in available and (allowed is None or tool in allowed)
        ]
    except Exception:
        return [tool for tool in preferred if allowed is None or tool in allowed]




def build_deterministic_plan(
    objective: str,
    snapshot: Mapping[str, Any],
    session_id: str,
) -> ExecutionPlan:
    """Build the minimum concrete analyze/implement/verify proposal.

    The proposal is intentionally conservative.  It references measured
    snapshot paths and discovered commands, never fabricating a task such as
    ``Execute Objective`` or silently assuming a project root.
    """
    objective = str(objective or "").strip()
    files = _project_files(snapshot)
    commands = _commands(snapshot)
    risk = _risk(snapshot)
    title = objective.splitlines()[0][:100] if objective else "Project change"
    root = files[0]

    analyze = TaskNode(
        name=f"Analyze project scope: {title}",
        description=(
            f"Inspect the measured project snapshot and identify the smallest concrete changes for: {objective}\n"
            f"Observed scope: {', '.join(files[:8])}"
        ),
        agent="ANALYZER",
        model_key="reasoning",
        priority=TaskPriority.HIGH,
        allowed_tools=_registered_planning_tools(
            ["read_file", "list_dir", "search_in_files"], "ANALYZER"
        ),
        **_task_metadata(
            file_scope=files,
            criteria=[
                "Scope names concrete files or measured project paths",
                "Risks and out-of-scope work are recorded",
            ],
            commands=[],
            risk=risk,
            rollback="No writes; discard the analysis artifact.",
            lock_scope=f"read:{root}",
        ),
    )
    implement = TaskNode(
        name=f"Implement scoped change: {title}",
        description=f"Implement only the requested change in the analyzed scope: {objective}",
        agent="CODER",
        model_key="coder",
        priority=TaskPriority.HIGH,
        depends_on=[analyze.task_id],
        allowed_tools=_registered_planning_tools(
            ["read_file", "write_file", "execute_code"], "CODER"
        ),
        **_task_metadata(
            file_scope=files,
            criteria=[
                "Requested behavior is implemented",
                "Changes stay within the measured file scope",
            ],
            commands=[],
            risk=risk,
            rollback="Revert the implementation diff using the repository's version-control history.",
            lock_scope=f"write:{root}",
        ),
    )
    analyze.required_by.append(implement.task_id)
    verify = TaskNode(
        name=f"Verify scoped change: {title}",
        description=(
            f"Run the discovered verification command and report its exit status "
            f"and relevant output for: {objective}"
        ),
        agent="DEBUGGER",
        model_key="coder",
        priority=TaskPriority.HIGH,
        depends_on=[implement.task_id],
        allowed_tools=_registered_planning_tools(
            ["execute_code", "read_file"], "DEBUGGER"
        ),
        **_task_metadata(
            file_scope=files,
            criteria=[
                "Verification command completes",
                "Exit status and evidence are recorded",
                "All completion criteria pass",
            ],
            commands=commands,
            risk=risk,
            rollback="Do not change files; report failing evidence for explicit remediation.",
            lock_scope=f"read:{root}",
        ),
    )
    implement.required_by.append(verify.task_id)
    plan = ExecutionPlan.from_steps(
        title=title,
        description=objective,
        steps=[analyze, implement, verify],
        session_id=session_id,
    )
    plan.risk_level = risk
    plan.requires_approval = True
    plan.approved = False
    plan.estimated_duration_seconds = sum(step.timeout_seconds for step in plan.steps)
    return plan


def _metadata_values(task: TaskNode, field_name: str) -> list[str]:
    value = getattr(task, field_name)
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def validate_execution_plan(
    plan: ExecutionPlan,
    snapshot: Mapping[str, Any],
    max_steps: int,
) -> PlanValidationResult:
    """Validate every execution precondition without mutating or repairing it."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(plan, ExecutionPlan):
        return PlanValidationResult(False, ["plan is not an ExecutionPlan"], [])
    if not plan.steps:
        errors.append("plan has no steps")
    if len(plan.steps) > max_steps:
        errors.append(f"plan has {len(plan.steps)} steps; maximum is {max_steps}")

    known_agents = {
        "PLANNER", "ARCHITECT", "CODER", "ANALYZER", "DEBUGGER",
        "RESEARCHER", "DOCUMENTER", "OPTIMIZER", "DASHBOARD",
    }
    capability_matrix: dict[str, Any] = {}
    contract_validator: Any = None
    try:
        from backend.orchestrator.agent_capabilities import (
            capability_matrix as get_capability_matrix,
            validate_agent_contract,
        )

        capability_matrix = get_capability_matrix()
        contract_validator = validate_agent_contract
        if capability_matrix:
            known_agents = set(capability_matrix)
    except Exception as exc:
        warnings.append(f"agent capability matrix unavailable: {exc}")
    registered_tools: set[str] = set()
    try:
        from backend.tools.registry import list_tools

        registered_tools = {str(spec.name) for spec in list_tools(enabled_only=False)}
    except Exception:
        warnings.append("tool registry unavailable while validating plan")
    known_model_keys = {
        "micro", "fast", "coder", "reasoning", "deep",
        "analyzer", "debugger", "researcher", "documenter",
        "optimizer", "dashboard",
    }
    known_models = {
        model
        for capability in capability_matrix.values()
        for model in capability.allowed_models
    }
    known_model_keys.update(known_models)
    for task in plan.steps:
        if task.agent.upper() not in known_agents:
            errors.append(f"task {task.task_id} uses unknown agent {task.agent!r}")
        if task.model_key and task.model_key not in known_model_keys:
            errors.append(f"task {task.task_id} uses unknown model {task.model_key!r}")
        if not task.model_key:
            errors.append(f"task {task.task_id} is missing model")
        if "execute objective" in task.name.strip().lower() or "execute objective" in task.description.strip().lower():
            errors.append(f"task {task.task_id} is the generic Execute Objective fallback")
        if contract_validator is not None and task.agent.upper() in known_agents:
            errors.extend(
                f"task {task.task_id}: {error}"
                for error in contract_validator(
                    task.agent, task.model_key, task.allowed_tools
                )
            )
        for dep_id in task.depends_on:
            if dep_id not in task_ids:
                errors.append(f"task {task.task_id} depends on unknown task {dep_id}")
        if not _metadata_values(task, "file_scope"):
            errors.append(f"task {task.task_id} is missing file_scope")
        if not _metadata_values(task, "completion_criteria"):
            errors.append(f"task {task.task_id} is missing completion_criteria")
        if task.agent.upper() == "DEBUGGER" and not _metadata_values(task, "verification_commands"):
            errors.append(f"task {task.task_id} is missing verification_commands")
        if not str(task.risk).strip():
            errors.append(f"task {task.task_id} is missing risk")
        if not str(task.rollback).strip():
            errors.append(f"task {task.task_id} is missing rollback")
        if not str(task.lock_scope).strip():
            errors.append(f"task {task.task_id} is missing lock_scope")
        if registered_tools:
            for tool in task.allowed_tools:
                if tool not in registered_tools:
                    errors.append(f"task {task.task_id} uses unknown tool {tool!r}")

    if not any(task.agent.upper() == "DEBUGGER" and _metadata_values(task, "verification_commands") for task in plan.steps):
        errors.append("plan has no verification step")
    snapshot_files = set(_project_files(snapshot))
    if snapshot_files and any(
        scope not in snapshot_files and scope != "."
        for task in plan.steps
        for scope in _metadata_values(task, "file_scope")
    ):
        warnings.append("one or more task scopes are not present in the snapshot file list")
    return PlanValidationResult(not errors, errors, warnings)


__all__ = [
    "PlanningResult",
    "PlanningStatus",
    "PlanValidationResult",
    "build_deterministic_plan",
    "validate_execution_plan",
]
