"""Runtime capability matrix and in-process task scope locks.

The matrix is derived lazily from the canonical agent class registry.  Keeping
this module declarative at import time avoids importing every provider and
agent during backend startup while still giving the planner a single contract
surface to validate before an agent is spawned.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentCapability:
    name: str
    allowed_models: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    max_concurrency: int
    task_types: tuple[str, ...]
    success_criteria: tuple[str, ...]


_CAPABILITY_MATRIX: dict[str, AgentCapability] | None = None
_MATRIX_LOCK = threading.Lock()


def _tool_names(agent_class: Any) -> tuple[str, ...]:
    """Resolve an agent's action declarations into executable tool names."""
    try:
        from backend.agents.action_registry import get_action_registry

        actions = get_action_registry()
        names = {
            spec.tool
            for action in getattr(agent_class, "supported_actions", set())
            if (spec := actions.get(getattr(action, "name", str(action)))) is not None
        }
    except Exception:
        names = set()
    # Agents can add a narrow explicit declaration without changing the action
    # YAML.  This is intentionally additive and keeps old classes compatible.
    names.update(str(item) for item in getattr(agent_class, "allowed_tools", ()) or ())
    return tuple(sorted(name for name in names if name))


def _model_names(agent_class: Any) -> tuple[str, ...]:
    key = str(getattr(agent_class, "model_key", "")).strip()
    names = {key} if key else set()
    if key:
        try:
            from backend.config.settings import get_model_config

            configured = get_model_config(key)
            for field in ("id", "fallback_id"):
                value = configured.get(field)
                if value:
                    names.add(str(value))
        except Exception:
            # An invalid model is reported by validate_agent_contract rather
            # than being hidden by a best-effort matrix build.
            pass
    return tuple(sorted(names))


def _build_matrix() -> dict[str, AgentCapability]:
    from backend.orchestrator import registry

    classes = registry._get_agent_classes()
    matrix: dict[str, AgentCapability] = {}
    for registered_name, agent_class in classes.items():
        name = str(getattr(agent_class, "name", registered_name)).upper()
        lowered = name.lower()
        if "research" in lowered:
            task_types = ("research", "analysis")
        elif "test" in lowered or "debug" in lowered or "bug" in lowered:
            task_types = ("testing", "debugging", "validation")
        elif "architect" in lowered or "planner" in lowered:
            task_types = ("planning", "architecture", "analysis")
        elif "document" in lowered:
            task_types = ("documentation",)
        elif "review" in lowered or "analy" in lowered or "advisor" in lowered:
            task_types = ("analysis", "validation")
        else:
            task_types = ("general",)
        criteria = ("agent response is complete", "required tool evidence is present")
        matrix[name] = AgentCapability(
            name=name,
            allowed_models=_model_names(agent_class),
            allowed_tools=_tool_names(agent_class),
            # A single agent instance is shared by requests; the scheduler,
            # not the model provider, owns safe parallelism.
            max_concurrency=1,
            task_types=task_types,
            success_criteria=criteria,
        )
    return matrix


def capability_matrix() -> dict[str, AgentCapability]:
    """Return a copy of the lazily built capability matrix."""
    global _CAPABILITY_MATRIX
    if _CAPABILITY_MATRIX is None:
        with _MATRIX_LOCK:
            if _CAPABILITY_MATRIX is None:
                _CAPABILITY_MATRIX = _build_matrix()
    return dict(_CAPABILITY_MATRIX)


def get_agent_capability(name: str) -> AgentCapability:
    """Return the contract for *name*, raising for unknown agents."""
    normalized = str(name or "").strip().upper()
    capability = capability_matrix().get(normalized)
    if capability is None:
        raise KeyError(f"Unknown agent: {name}")
    return capability


def validate_agent_contract(name: str, model: str, tools: list[str] | tuple[str, ...] | None) -> list[str]:
    """Return deterministic contract violations; an empty list means valid."""
    errors: list[str] = []
    try:
        capability = get_agent_capability(name)
    except KeyError as exc:
        return [str(exc)]
    requested_model = str(model or "").strip()
    if requested_model and requested_model not in capability.allowed_models:
        errors.append(
            f"agent {capability.name} does not allow model {requested_model!r}; "
            f"allowed: {', '.join(capability.allowed_models) or 'none'}"
        )
    try:
        from backend.tools.registry import get_tool

        for raw_tool in tools or ():
            tool = str(raw_tool).strip()
            if not tool:
                errors.append("tool name must not be empty")
                continue
            if tool not in capability.allowed_tools:
                errors.append(f"agent {capability.name} does not allow tool {tool!r}")
                continue
            spec = get_tool(tool)
            if spec is None:
                errors.append(f"tool {tool!r} is not registered")
            elif not spec.available or not spec.enabled:
                reason = spec.unavailable_reason or spec.missing_dependency or "disabled"
                errors.append(f"tool {tool!r} is unavailable: {reason}")
    except Exception as exc:
        errors.append(f"tool contract lookup failed: {exc}")
    return errors


class FileLockRegistry:
    """Small process-local ownership registry for task file/scope locks."""

    def __init__(self) -> None:
        self._owners: dict[str, str] = {}
        self._lock = threading.Lock()

    def acquire(self, scope: str, run_id: str) -> bool:
        scope = str(scope or "").strip()
        run_id = str(run_id or "").strip()
        if not scope or not run_id:
            return False
        with self._lock:
            if scope in self._owners:
                return False
            self._owners[scope] = run_id
            return True

    def release(self, scope: str, run_id: str) -> None:
        scope = str(scope or "").strip()
        with self._lock:
            if self._owners.get(scope) == str(run_id or "").strip():
                self._owners.pop(scope, None)

    def owner(self, scope: str) -> str | None:
        with self._lock:
            return self._owners.get(str(scope or "").strip())


file_locks = FileLockRegistry()

__all__ = [
    "AgentCapability",
    "FileLockRegistry",
    "capability_matrix",
    "file_locks",
    "get_agent_capability",
    "validate_agent_contract",
]
