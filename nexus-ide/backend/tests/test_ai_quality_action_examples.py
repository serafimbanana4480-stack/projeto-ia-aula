"""AI-facing quality: every ``example_args`` block must reach the model.

``config/agent_actions.yaml`` stores ``example_args`` as a JSON **string**.
Until this was fixed at the loader boundary, ``ActionSpec.example_args`` was
coerced with ``str(...)`` and ``AgentBase._openai_tool_schemas`` required
``isinstance(..., dict)`` — a check that was therefore permanently ``False``.
The derived ``properties`` object was consequently always empty, so the
example-derived argument schema was unreachable::

    {"type": "object", "properties": {}, "additionalProperties": true}

Measured impact today: **nil for the 46 tools actually advertised to a model**,
because every one of them declares a real ``ToolSpec.schema`` and that schema
wins. The defect is a latent trap, not an active one: a tool registered without
a schema ships argument-less (``mcp_project_status`` is exactly such a tool),
and a typo in one JSON blob degrades silently into "this tool takes no
arguments".

These tests lock the fix and the invariant. A malformed entry must fail
*loudly* (logged and recorded), never degrade silently.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from backend.agents.action_registry import (
    ActionRegistry,
    ActionSpec,
    get_action_registry,
    invalidate_action_registry,
    parse_example_args,
)

#: Tools that genuinely take no model-supplied arguments. Their
#: ``example_args`` is an explicit empty object, which is correct — asserting
#: "non-empty" for these would be asserting a bug.
ZERO_ARG_TOOLS = frozenset({"list_skills", "db_schema", "db_tables"})

#: A tool property is exempt from the "must have an example" rule when the
#: tool's own schema says NEXUS injects it and the model must omit it
#: (``AgentBase._prepare_tool_call`` overwrites it for skill tools). The
#: exemption is derived from the schema text, not hardcoded per tool, so a new
#: injected-only argument is covered without editing this file.
INJECTED_MARKER = "omit this field"


@pytest.fixture
def registry() -> ActionRegistry:
    return get_action_registry()


# ---------------------------------------------------------------------------
# The shipped configuration file
# ---------------------------------------------------------------------------
class TestShippedExampleArgs:
    def test_no_action_failed_to_parse(self, registry: ActionRegistry) -> None:
        failures = registry.parse_failures
        assert not failures, "malformed example_args in config/agent_actions.yaml:\n" + "\n".join(
            failures
        )

    def test_every_example_args_is_a_mapping(self, registry: ActionRegistry) -> None:
        offenders = {
            name: spec.example_args
            for name, spec in registry.all_actions().items()
            if not isinstance(spec.example_args, dict)
        }
        assert not offenders, f"example_args still a raw string: {sorted(offenders)}"

    def test_expected_number_of_actions_is_present(self, registry: ActionRegistry) -> None:
        """A truncated YAML must fail here, not as a mysteriously tool-less agent."""
        assert len(registry.all_actions()) == 63

    def test_every_tool_with_arguments_declares_a_non_empty_example(
        self, registry: ActionRegistry
    ) -> None:
        """The real assertion: no tool ships argument-less when it takes arguments.

        Derived from the tool's own registered schema, so adding a tool with a
        schema and forgetting its example fails the test.
        """
        from backend.tools.registry import get_tool

        offenders: list[str] = []
        for name, spec in sorted(registry.all_actions().items()):
            tool_spec = get_tool(spec.tool)
            properties = (tool_spec.schema or {}).get("properties", {}) if tool_spec else {}
            supplied = {
                key: value
                for key, value in properties.items()
                if INJECTED_MARKER not in str(value.get("description", "")).lower()
            }
            if supplied and not spec.example_args_dict():
                offenders.append(
                    f"{name} -> {spec.tool} takes {sorted(supplied)} but declares no example_args"
                )
        assert not offenders, "\n".join(offenders)

    def test_zero_argument_tools_declare_an_explicit_empty_object(
        self, registry: ActionRegistry
    ) -> None:
        for name, spec in sorted(registry.all_actions().items()):
            if spec.tool in ZERO_ARG_TOOLS:
                assert spec.example_args == {}, (
                    f"{name} -> {spec.tool} takes no arguments; declare "
                    f"example_args: '{{}}' explicitly instead of leaving it out"
                )

    def test_example_keys_are_plausible_for_the_tool_schema(
        self, registry: ActionRegistry
    ) -> None:
        """An example that names arguments the tool does not accept is a lie."""
        from backend.tools.registry import get_tool

        unknown: list[str] = []
        for name, spec in sorted(registry.all_actions().items()):
            tool_spec = get_tool(spec.tool)
            if tool_spec is None:
                continue
            declared = (tool_spec.schema or {}).get("properties", {})
            if not declared:
                continue  # tool declares no schema — nothing to check against
            for key in spec.example_args_dict():
                if key not in declared:
                    unknown.append(f"{name} -> {spec.tool}: example key {key!r} not in schema")
        assert not unknown, "\n".join(unknown)

    def test_parsed_args_equal_json_loads_of_the_authored_text(
        self, registry: ActionRegistry
    ) -> None:
        """Parsing must not reorder, coerce or drop anything."""
        import yaml

        raw = yaml.safe_load(Path(registry.config_path()).read_text(encoding="utf-8"))
        for name, spec in sorted(registry.all_actions().items()):
            authored = raw["actions"][name]["example_args"]
            assert spec.example_args_dict() == json.loads(authored), name



# ---------------------------------------------------------------------------
# The boundary parser itself
# ---------------------------------------------------------------------------
class TestParseExampleArgs:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ('{"path": "a.py"}', {"path": "a.py"}),
            ("{}", {}),
            ("   ", {}),
            ("", {}),
            (None, {}),
            ({"path": "a.py"}, {"path": "a.py"}),
        ],
        ids=["json", "empty-object", "spaces", "blank", "none", "already-a-dict"],
    )
    def test_accepts_every_valid_shape(self, raw: Any, expected: dict[str, Any]) -> None:
        value, error = parse_example_args("X", raw)
        assert error is None
        assert value == expected

    @pytest.mark.parametrize(
        "raw",
        ['{"path": "a.py"', "{path: a.py}", "[1, 2]", '"just a string"', "42"],
        ids=["truncated", "unquoted-keys", "array", "scalar-string", "number"],
    )
    def test_rejects_malformed_json_and_keeps_the_raw_text(self, raw: str) -> None:
        value, error = parse_example_args("X", raw)
        assert error is not None, f"{raw!r} should not parse"
        assert value == raw, "the raw text must survive so the typo is visible"
        assert "example_args" in error

    def test_wrong_python_type_is_reported(self) -> None:
        value, error = parse_example_args("X", 42)
        assert error is not None
        assert "int" in error
        assert value == "42"

    def test_error_names_the_offending_action(self) -> None:
        _, error = parse_example_args("RUN_SHELL", "{oops}")
        assert error is not None
        assert "RUN_SHELL" in error


# ---------------------------------------------------------------------------
# Failure is loud, and the failure is recoverable
# ---------------------------------------------------------------------------
_MINIMAL_YAML = """\
actions:
  GOOD:
    tool: read_file
    example_args: '{"path": "a.py"}'
    when_to_use: "read a file"
"""


class TestMalformedEntryIsLoud:
    def test_parse_failure_is_recorded_not_swallowed(self, tmp_path: Path) -> None:
        path = tmp_path / "agent_actions.yaml"
        path.write_text(
            _MINIMAL_YAML
            + "  BROKEN:\n"
            + "    tool: write_file\n"
            + "    example_args: '{not json}'\n",
            encoding="utf-8",
        )
        reg = ActionRegistry(path)
        specs = reg.all_actions()
        assert set(specs) == {"GOOD", "BROKEN"}, "a broken entry must not drop the action"
        assert isinstance(specs["GOOD"].example_args, dict)
        assert specs["BROKEN"].example_args == '{not json}'
        assert len(reg.parse_failures) == 1
        assert "BROKEN" in reg.parse_failures[0]

    def test_a_malformed_entry_does_not_break_the_good_ones(self, tmp_path: Path) -> None:
        path = tmp_path / "agent_actions.yaml"
        path.write_text(
            _MINIMAL_YAML
            + "  BROKEN:\n"
            + "    tool: write_file\n"
            + "    example_args: 'nope'\n",
            encoding="utf-8",
        )
        spec = ActionRegistry(path).get("GOOD")
        assert spec is not None
        assert spec.example_args_dict() == {"path": "a.py"}


# ---------------------------------------------------------------------------
# Invalidation: the config file is editable at runtime
# ---------------------------------------------------------------------------
class TestRuntimeReload:
    def test_editing_the_file_is_picked_up(self, tmp_path: Path) -> None:
        path = tmp_path / "agent_actions.yaml"
        path.write_text(_MINIMAL_YAML, encoding="utf-8")
        reg = ActionRegistry(path)
        first = reg.epoch()
        assert reg.get("GOOD").example_args_dict() == {"path": "a.py"}

        # A different size guarantees the content token moves even on a
        # filesystem with coarse timestamps.
        path.write_text(
            _MINIMAL_YAML.replace('"a.py"', '"a/much/longer/path.py"'),
            encoding="utf-8",
        )
        assert reg.get("GOOD").example_args_dict() == {"path": "a/much/longer/path.py"}
        assert reg.epoch() != first, "the epoch must move so downstream caches rebuild"

    def test_explicit_invalidate_forces_a_reread(self, tmp_path: Path) -> None:
        path = tmp_path / "agent_actions.yaml"
        path.write_text(_MINIMAL_YAML, encoding="utf-8")
        reg = ActionRegistry(path)
        assert reg.get("GOOD") is not None
        before = reg.epoch()
        reg.invalidate()
        assert reg.epoch() != before
        assert reg.get("GOOD") is not None

    def test_module_level_invalidate_bumps_the_shared_epoch(self) -> None:
        reg = get_action_registry()
        reg.get("READ_FILE")
        before = reg.epoch()
        invalidate_action_registry()
        assert reg.epoch() != before
        # And the registry is still usable afterwards.
        assert reg.get("READ_FILE") is not None

    def test_missing_file_fails_loudly(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            ActionRegistry(tmp_path / "does-not-exist.yaml").all_actions()


# ---------------------------------------------------------------------------
# The hand-rolled fallback parser (used only when PyYAML is missing)
# ---------------------------------------------------------------------------
class TestFallbackYamlParser:
    def test_it_finds_the_actions_block(self) -> None:
        from backend.agents.action_registry import _parse_simple_yaml

        path = Path(get_action_registry().config_path())
        parsed = _parse_simple_yaml(path)
        assert len(parsed) == 63, (
            "the fallback parser must not silently return zero actions — that "
            "would cost every agent its entire tool surface with no error"
        )

    def test_its_example_args_still_parse(self) -> None:
        from backend.agents.action_registry import _parse_simple_yaml

        path = Path(get_action_registry().config_path())
        failures = [
            error
            for name, spec in _parse_simple_yaml(path).items()
            for _, error in [parse_example_args(name, spec.get("example_args"))]
            if error
        ]
        assert not failures, failures

    def test_list_items_do_not_leak_in_as_keys(self) -> None:
        from backend.agents.action_registry import _parse_simple_yaml

        path = Path(get_action_registry().config_path())
        parsed = _parse_simple_yaml(path)
        assert not [key for spec in parsed.values() for key in spec if key.startswith("-")]


# ---------------------------------------------------------------------------
# The dataclass contract
# ---------------------------------------------------------------------------
def test_example_args_dict_is_empty_for_an_unparsable_spec() -> None:
    spec = ActionSpec(action="X", tool="read_file", example_args="{bad")
    assert spec.example_args_dict() == {}
