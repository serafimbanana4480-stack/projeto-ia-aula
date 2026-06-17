"""Registry for NEXUS agent ReAct actions.

This module replaces the hardcoded ``_ACTION_TOOLS`` mapping that used to live
on :class:`backend.agents.base.AgentBase`. The mapping is now declared in
``config/agent_actions.yaml`` and consumed through :class:`ActionRegistry`.

A single process-wide instance is exposed via :func:`get_action_registry`.
Loading is lazy: the YAML file is read the first time the registry is queried
and then memoised in memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # PyYAML — declared in backend/requirements.txt
except ImportError:  # pragma: no cover - defensive fallback
    yaml = None  # type: ignore[assignment]


# Default location: <repo_root>/config/agent_actions.yaml
# File lives at <repo_root>/backend/agents/action_registry.py
_DEFAULT_CONFIG_PATH: Path = Path(__file__).resolve().parents[2] / "config" / "agent_actions.yaml"


@dataclass(frozen=True)
class ActionSpec:
    """Declarative description of a single ReAct action."""

    action: str
    tool: str
    example_args: str


class ActionRegistry:
    """In-memory cache of the ``config/agent_actions.yaml`` file."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path: Path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
        self._actions: dict[str, ActionSpec] | None = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _default_config_path(self) -> Path:
        return self._config_path

    def _load(self) -> dict[str, ActionSpec]:
        """Read the YAML file and return the parsed action map."""
        path = self._default_config_path()
        if not path.is_file():
            raise FileNotFoundError(
                f"Agent action registry file not found: {path}"
            )

        raw: Any
        if yaml is not None:
            with path.open("r", encoding="utf-8") as fh:
                loaded = yaml.safe_load(fh) or {}
            actions_raw = loaded.get("actions", {}) if isinstance(loaded, dict) else {}
        else:
            actions_raw = _parse_simple_yaml(path)

        if not isinstance(actions_raw, dict):
            raise ValueError(
                f"Invalid action registry format in {path}: "
                "'actions' must be a mapping of action names to specs."
            )

        specs: dict[str, ActionSpec] = {}
        for name, spec in actions_raw.items():
            if not isinstance(spec, dict):
                raise ValueError(
                    f"Invalid spec for action {name!r} in {path}: expected mapping."
                )
            tool = str(spec.get("tool", "")).strip()
            example_args = str(spec.get("example_args", "")).strip()
            if not tool:
                raise ValueError(
                    f"Invalid spec for action {name!r} in {path}: 'tool' is required."
                )
            specs[str(name)] = ActionSpec(
                action=str(name),
                tool=tool,
                example_args=example_args,
            )
        return specs

    def _ensure_loaded(self) -> dict[str, ActionSpec]:
        if self._actions is None:
            self._actions = self._load()
        return self._actions

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def get(self, action: str) -> ActionSpec | None:
        """Return the spec for *action* or ``None`` if not registered."""
        return self._ensure_loaded().get(action)

    def tool_for(self, action: str) -> str | None:
        """Convenience: return only the tool name for *action*."""
        spec = self.get(action)
        return spec.tool if spec else None

    def example_args_for(self, action: str) -> str | None:
        """Convenience: return only the example args string for *action*."""
        spec = self.get(action)
        return spec.example_args if spec else None

    def all_actions(self) -> dict[str, ActionSpec]:
        """Return the full mapping of action name -> :class:`ActionSpec`."""
        return dict(self._ensure_loaded())


# ----------------------------------------------------------------------
# Process-wide singleton
# ----------------------------------------------------------------------
_singleton: ActionRegistry | None = None


def get_action_registry() -> ActionRegistry:
    """Return a process-wide cached :class:`ActionRegistry` instance."""
    global _singleton
    if _singleton is None:
        _singleton = ActionRegistry()
    return _singleton


# ----------------------------------------------------------------------
# Minimal hand-rolled fallback parser
# ----------------------------------------------------------------------
def _parse_simple_yaml(path: Path) -> dict[str, dict[str, str]]:
    """Parse the very small subset of YAML used by ``agent_actions.yaml``.

    This exists so the registry still works if PyYAML is somehow not
    available. It supports only the structure produced by the configuration
    file: a top-level ``actions:`` mapping of one-level string values.
    """
    actions: dict[str, dict[str, str]] = {}
    current_action: str | None = None
    current_spec: dict[str, str] = {}

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if not line.startswith(" "):
            # Top-level key.
            key, _, value = stripped.partition(":")
            if key.strip() == "actions":
                continue
            if current_action is not None:
                actions[current_action] = current_spec
            current_action = key.strip()
            current_spec = {}
            if value.strip():
                # Should not occur in our file, but be tolerant.
                continue
            continue

        # Nested key under an action.
        if current_action is None:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip()
        if not value:
            continue
        # Strip surrounding quotes if present.
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]
        current_spec[key] = value

    if current_action is not None:
        actions[current_action] = current_spec
    return actions
