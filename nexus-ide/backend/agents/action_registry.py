"""Registry for NEXUS agent ReAct actions.

This module replaces the hardcoded ``_ACTION_TOOLS`` mapping that used to live
on :class:`backend.agents.base.AgentBase`. The mapping is now declared in
``config/agent_actions.yaml`` and consumed through :class:`ActionRegistry`.

A single process-wide instance is exposed via :func:`get_action_registry`.
Loading is lazy: the YAML file is read the first time the registry is queried
and then memoised in memory.

``example_args`` is authored as a JSON **string** (YAML has no reason to force a
mapping here) but is parsed **once, at this boundary**, into a real ``dict``.
Before this, the loader coerced the value with ``str(...)`` and
``AgentBase._openai_tool_schemas`` required ``isinstance(..., dict)`` — so the
check was permanently ``False`` and every tool shipped with
``{"type": "object", "properties": {}}``. Parsing here fixes every consumer,
not just the schema builder.

Caching / invalidation
----------------------
The parsed actions are memoised, but the memo is keyed on the config file's
``(mtime_ns, size)``: editing ``config/agent_actions.yaml`` while the backend
runs is a supported operation, so a stale memo would be a silent correctness
bug. :meth:`ActionRegistry.invalidate` (and the module-level
:func:`invalidate_action_registry`) force a re-read for callers that know they
changed something the stat cannot see (same size, same mtime tick).
:func:`action_registry_epoch` exposes a monotonic token that changes on every
re-read, which lets downstream caches (e.g. the native tool schemas built by
``AgentBase``) invalidate without re-deriving anything themselves.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml  # PyYAML — declared in backend/requirements.txt
except ImportError:  # pragma: no cover - defensive fallback
    yaml = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


# Default location: <repo_root>/config/agent_actions.yaml
# File lives at <repo_root>/backend/agents/action_registry.py
_DEFAULT_CONFIG_PATH: Path = Path(__file__).resolve().parents[2] / "config" / "agent_actions.yaml"


def parse_example_args(action: str, raw: Any) -> tuple[dict[str, Any] | str, str | None]:
    """Parse one ``example_args`` value into a mapping.

    Returns ``(value, error)``. ``value`` is a ``dict`` on success. On failure
    the **raw text is preserved** and ``error`` explains why: a malformed entry
    must be visible (logged loudly and recorded in
    :attr:`ActionRegistry.parse_failures`), never silently degraded to "this
    tool takes no arguments" — that is exactly the failure mode this function
    exists to remove.
    """
    if isinstance(raw, Mapping):
        return {str(key): value for key, value in raw.items()}, None
    if raw is None:
        return {}, None
    if not isinstance(raw, str):
        return str(raw), (
            f"action {action!r}: example_args must be a JSON object string, "
            f"got {type(raw).__name__}"
        )
    text = raw.strip()
    if not text:
        return {}, None
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        return raw, f"action {action!r}: example_args is not valid JSON ({exc}): {text!r}"
    if not isinstance(parsed, dict):
        return raw, (
            f"action {action!r}: example_args must decode to a JSON object, "
            f"got {type(parsed).__name__}: {text!r}"
        )
    return parsed, None


@dataclass(frozen=True)
class ActionSpec:
    """Declarative description of a single ReAct action."""

    action: str
    tool: str
    #: Parsed at load time. A ``str`` here means the JSON failed to decode and
    #: the raw text is kept verbatim for diagnosis (see :func:`parse_example_args`).
    example_args: dict[str, Any] | str
    when_to_use: str = ""
    risk_level: str = "low"
    requires_confirmation: bool = False
    tags: tuple[str, ...] = ()
    examples: tuple[dict, ...] = ()

    def example_args_dict(self) -> dict[str, Any]:
        """Return the example arguments as a mapping (empty if unparsable)."""
        return self.example_args if isinstance(self.example_args, dict) else {}


class ActionRegistry:
    """In-memory cache of the ``config/agent_actions.yaml`` file."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path: Path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
        self._actions: dict[str, ActionSpec] | None = None
        self._token: tuple[int, int] | None = None
        self._parse_failures: list[str] = []

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _default_config_path(self) -> Path:
        return self._config_path

    def config_path(self) -> Path:
        """Public accessor for the YAML file backing this registry."""
        return self._config_path

    def _config_token(self) -> tuple[int, int] | None:
        """Cheap content token for the config file (``None`` when missing)."""
        try:
            stat_result = self._config_path.stat()
        except OSError:
            return None
        return (stat_result.st_mtime_ns, stat_result.st_size)

    def _load(self) -> dict[str, ActionSpec]:
        """Read the YAML file and return the parsed action map."""
        path = self._default_config_path()
        if not path.is_file():
            raise FileNotFoundError(f"Agent action registry file not found: {path}")

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

        failures: list[str] = []
        specs: dict[str, ActionSpec] = {}
        for name, spec in actions_raw.items():
            if not isinstance(spec, dict):
                raise ValueError(f"Invalid spec for action {name!r} in {path}: expected mapping.")
            tool = str(spec.get("tool", "")).strip()
            if not tool:
                raise ValueError(f"Invalid spec for action {name!r} in {path}: 'tool' is required.")
            example_args, error = parse_example_args(str(name), spec.get("example_args", ""))
            if error:
                failures.append(f"{path}: {error}")
                logger.error("agent_actions.yaml: %s", error)
            raw_tags = spec.get("tags", ())
            raw_examples = spec.get("examples", ())
            specs[str(name)] = ActionSpec(
                action=str(name),
                tool=tool,
                example_args=example_args,
                when_to_use=str(spec.get("when_to_use", "")).strip(),
                risk_level=str(spec.get("risk_level", "low")).strip().lower(),
                requires_confirmation=bool(spec.get("requires_confirmation", False)),
                tags=tuple(str(tag) for tag in raw_tags) if isinstance(raw_tags, list) else (),
                examples=(
                    tuple(dict(example) for example in raw_examples if isinstance(example, dict))
                    if isinstance(raw_examples, list)
                    else ()
                ),
            )
        self._parse_failures = failures
        return specs

    def _ensure_loaded(self) -> dict[str, ActionSpec]:
        """Return the action map, re-reading it when the file changed.

        The memo is keyed on ``(mtime_ns, size)`` so a live edit of
        ``config/agent_actions.yaml`` takes effect without a restart. A stat
        call is ~microseconds and this runs once per LLM call at worst; the
        alternative (re-reading and re-parsing 63 JSON blobs every turn) is
        both slower and no more correct.
        """
        token = self._config_token()
        if self._actions is None or self._token != token:
            self._actions = self._load()
            self._token = token
            _bump_epoch()
        return self._actions

    def invalidate(self) -> None:
        """Force the next query to re-read ``config/agent_actions.yaml``.

        Needed when the file changed without ``(mtime_ns, size)`` moving — a
        same-size edit inside one filesystem timestamp tick, a test fixture, or
        a registry rebuilt against a different path.
        """
        self._actions = None
        self._token = None
        self._parse_failures = []
        _bump_epoch()

    def epoch(self) -> int:
        """Monotonic token that changes whenever the parsed actions change."""
        self._ensure_loaded()
        return _EPOCH[0]

    @property
    def parse_failures(self) -> list[str]:
        """Human-readable reasons an ``example_args`` block failed to parse."""
        self._ensure_loaded()
        return list(self._parse_failures)

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

    def example_args_for(self, action: str) -> dict[str, Any] | str | None:
        """Convenience: return the parsed example args for *action*.

        A ``dict`` is the normal return. A ``str`` means the stored JSON was
        malformed and the raw text is being handed back so the caller can
        report it instead of pretending the tool takes no arguments.
        """
        spec = self.get(action)
        return spec.example_args if spec else None

    def all_actions(self) -> dict[str, ActionSpec]:
        """Return the full mapping of action name -> :class:`ActionSpec`."""
        return dict(self._ensure_loaded())


# ----------------------------------------------------------------------
# Process-wide singleton
# ----------------------------------------------------------------------
_singleton: ActionRegistry | None = None

#: Bumped on every (re)load and every explicit invalidation. Downstream caches
#: include it in their key so they can never serve a description built from a
#: previous version of the action map.
_EPOCH = [0]


def _bump_epoch() -> None:
    _EPOCH[0] += 1


def action_registry_epoch() -> int:
    """Current action-registry epoch (see :data:`_EPOCH`)."""
    return _EPOCH[0]


def get_action_registry() -> ActionRegistry:
    """Return a process-wide cached :class:`ActionRegistry` instance."""
    global _singleton
    if _singleton is None:
        _singleton = ActionRegistry()
    return _singleton


def invalidate_action_registry() -> None:
    """Drop the process-wide registry so the next query re-reads the YAML.

    This is the explicit invalidation hook for callers that mutate
    ``config/agent_actions.yaml`` (tests, a config-reload endpoint) and for
    downstream caches that want to be told "assume nothing is cached".
    """
    global _singleton
    if _singleton is not None:
        _singleton.invalidate()
    else:
        _bump_epoch()


# ----------------------------------------------------------------------
# Minimal hand-rolled fallback parser
# ----------------------------------------------------------------------
def _parse_simple_yaml(path: Path) -> dict[str, dict[str, str]]:
    """Parse the very small subset of YAML used by ``agent_actions.yaml``.

    This exists so the registry still works if PyYAML is somehow not
    available. It supports only the structure produced by the configuration
    file: an ``actions:`` mapping whose members are one level of scalar values.

    Two details matter for correctness rather than elegance:

    * ``actions:`` is a *container*, not a member. Treating it as a member (as
      an earlier version did) left ``current_action`` unset, every nested key was
      then discarded and the registry silently returned **zero** actions — a
      capability loss with no error anywhere.
    * Only keys indented exactly one level below the action name are read, so
      list items under ``examples:`` cannot leak in as bogus ``- path`` keys.
    """
    actions: dict[str, dict[str, str]] = {}
    current_action: str | None = None
    current_spec: dict[str, str] = {}
    in_actions = False
    member_indent: int | None = None
    key_indent: int | None = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if not line.strip() or line.strip().startswith("#"):
            continue

        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()

        if indent == 0:
            key, _, value = stripped.partition(":")
            key = key.strip()
            if key == "actions" and not value.strip():
                in_actions = True
                current_action = None
                continue
            if not in_actions:
                continue
            # A new top-level member inside ``actions:`` is an action name.
            if current_action is not None:
                actions[current_action] = current_spec
            current_action = key
            current_spec = {}
            member_indent = None
            key_indent = None
            continue

        if not in_actions:
            continue
        if member_indent is None:
            member_indent = indent
        if current_action is None:
            # First member of the ``actions:`` block.
            current_action = stripped.partition(":")[0].strip()
            current_spec = {}
            continue
        if indent == member_indent:
            actions[current_action] = current_spec
            current_action = stripped.partition(":")[0].strip()
            current_spec = {}
            key_indent = None
            continue
        if key_indent is None:
            key_indent = indent
        if indent != key_indent:
            # Deeper nesting (list items) is not part of the scalar subset.
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
