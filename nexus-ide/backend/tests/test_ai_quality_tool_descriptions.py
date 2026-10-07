"""AI-facing quality: what the model actually sees for a tool.

``AgentBase._openai_tool_schemas`` used to send, as the function ``description``,
only ``(mapping.when_to_use or f"Invoke {mapping.tool}.")[:512]`` from
``config/agent_actions.yaml`` — and never ``ToolSpec.description`` from the tool
itself.

The concrete cost: ``backend/tools/shell_runner.py`` documents its command
allow-list and the blocked commands (``rm -rf /``, ``dd``, ``mkfs``, ``format``,
``shutdown``) in exactly that ``ToolSpec.description``. The model was told
"Invoke run_shell." and had to discover the policy by trial and error, burning
ReAct iterations and sometimes attempting a forbidden command.

These tests pin the merged description, the deterministic ordering, the cap, the
argument schema that ``example_args`` now produces, and the cache-invalidation
contract.
"""

from __future__ import annotations

import json

import pytest

from backend.agents import base as base_module
from backend.agents.action_registry import get_action_registry, invalidate_action_registry
from backend.agents.base import AgentAction, AgentBase
from backend.agents.nexus_primary import NexusPrimaryAgent
from backend.tools.registry import get_tool, set_tool_enabled

#: The blocked-command list ``shell_runner.py`` declares in its own contract.
RUN_SHELL_BLOCKED_MARKERS = ("rm -rf /", "dd", "mkfs", "format", "shutdown")


class _ScriptedAgent(AgentBase):
    """Minimal concrete agent used to drive the schema builder in isolation."""

    name = "SCRIPTED"
    model_key = "nano"
    prompt_file = "router"
    supported_actions: set[AgentAction] = set()

    async def _execute(self, request):  # pragma: no cover - never called
        yield ""


@pytest.fixture(autouse=True)
def _clean_schema_cache():
    base_module.invalidate_tool_schema_cache()
    yield
    base_module.invalidate_tool_schema_cache()


def _descriptions(agent: AgentBase) -> dict[str, str]:
    schemas = agent._openai_tool_schemas() or []
    return {entry["function"]["name"]: entry["function"]["description"] for entry in schemas}


# ---------------------------------------------------------------------------
# Item 1: the tool's own contract reaches the model
# ---------------------------------------------------------------------------
class TestToolContractIsVisible:
    def test_run_shell_advertises_its_allow_and_block_lists(self) -> None:
        description = _descriptions(NexusPrimaryAgent())["run_shell"]
        assert "Dangerous commands" in description
        for marker in RUN_SHELL_BLOCKED_MARKERS:
            assert marker in description, f"{marker!r} missing from the run_shell description"

    def test_the_registry_hint_is_also_present(self) -> None:
        description = _descriptions(NexusPrimaryAgent())["run_shell"]
        assert "allow-listed project command" in description

    def test_order_is_guidance_then_contract(self) -> None:
        hint = get_action_registry().get("RUN_SHELL").when_to_use
        description = _descriptions(NexusPrimaryAgent())["run_shell"]
        assert description.startswith(hint[:40])
        assert get_tool("run_shell").description[:40] in description

    def test_no_tool_falls_back_to_the_generic_description(self) -> None:
        for name, description in _descriptions(NexusPrimaryAgent()).items():
            assert description.strip(), f"{name} has an empty description"
            assert not description.startswith(f"Invoke {name}."), (
                f"{name} fell back to the generic description — its "
                "ToolSpec.description was not merged"
            )

    def test_every_description_comes_from_a_real_source(self) -> None:
        """No invented text: a description is always a merge of two real strings."""
        descriptions = _descriptions(NexusPrimaryAgent())
        hints = [
            spec.when_to_use
            for spec in get_action_registry().all_actions().values()
            if spec.when_to_use and spec.tool in descriptions
        ]
        for name, description in descriptions.items():
            own = get_tool(name).description
            assert own[:60] in description or any(h[:60] in description for h in hints), name


# ---------------------------------------------------------------------------
# The merge function itself
# ---------------------------------------------------------------------------
class TestMergeToolDescription:
    def test_both_sources_guidance_first(self) -> None:
        assert (
            AgentBase._merge_tool_description("t", "Use it for X.", "It can do Y.")
            == "Use it for X. It can do Y."
        )

    def test_contract_only(self) -> None:
        assert AgentBase._merge_tool_description("t", "", "Only contract.") == "Only contract."

    def test_hint_only(self) -> None:
        assert AgentBase._merge_tool_description("t", "Only hint.", "") == "Only hint."

    def test_generic_fallback_when_both_are_empty(self) -> None:
        assert AgentBase._merge_tool_description("mytool", "", "") == "Invoke mytool."

    def test_whitespace_is_collapsed(self) -> None:
        merged = AgentBase._merge_tool_description("t", "a\n\n  b", "c\t\td")
        assert "\n" not in merged
        assert merged == "a b c d"

    def test_a_verbose_hint_cannot_crowd_out_the_contract(self) -> None:
        """The safety-relevant half must always survive the cap."""
        merged = AgentBase._merge_tool_description("t", "h" * 5000, "rm -rf / is blocked.")
        assert "rm -rf / is blocked." in merged
        assert len(merged) <= base_module._TOOL_DESCRIPTION_CAP

    def test_result_is_capped(self) -> None:
        merged = AgentBase._merge_tool_description("t", "h" * 400, "b" * 4000)
        assert len(merged) <= base_module._TOOL_DESCRIPTION_CAP
        assert merged.endswith("...")

    def test_newlines_cannot_be_injected_through_the_registry(self) -> None:
        merged = AgentBase._merge_tool_description("t", "first\n## NEW SECTION", "body")
        assert "\n" not in merged

    @pytest.mark.parametrize("limit", [0, 1, 2, 3, 4, 10])
    def test_cap_helper_never_exceeds_the_limit(self, limit: int) -> None:
        assert len(AgentBase._cap_text("abcdefghij", limit)) <= limit

    def test_no_shipped_hint_is_long_enough_to_be_truncated(self) -> None:
        """A silently truncated hint is a silent loss of the disambiguation."""
        for name, spec in get_action_registry().all_actions().items():
            assert len(spec.when_to_use) <= base_module._TOOL_GUIDANCE_CAP, (
                f"{name}: when_to_use is {len(spec.when_to_use)} chars and would be "
                f"truncated at {base_module._TOOL_GUIDANCE_CAP}"
            )


# ---------------------------------------------------------------------------
# Determinism: the prompt is part of the provider cache key
# ---------------------------------------------------------------------------
class TestDeterministicOutput:
    def test_two_actions_sharing_a_tool_merge_both_hints(self) -> None:
        """READ_FILE and READ_DOCS both map to read_file.

        Previously the winner was whichever came first in ``set`` iteration
        order, which depends on per-process string hashing: identical code
        produced a different ``read_file`` description under different
        PYTHONHASHSEED values, i.e. a different prompt prefix on every restart.
        """
        description = _descriptions(NexusPrimaryAgent())["read_file"]
        assert "documentation" in description, "the READ_DOCS hint is missing"
        assert "INSIDE the project" in description, "the READ_FILE hint is missing"

    def test_a_tool_is_listed_once_not_once_per_action(self) -> None:
        names = [entry["function"]["name"] for entry in NexusPrimaryAgent()._openai_tool_schemas()]
        assert len(names) == len(set(names))

    def test_repeated_calls_are_byte_identical(self) -> None:
        agent = NexusPrimaryAgent()
        first = json.dumps(agent._openai_tool_schemas(), sort_keys=True)
        second = json.dumps(agent._openai_tool_schemas(), sort_keys=True)
        assert first == second

    def test_order_does_not_depend_on_set_iteration(self) -> None:
        agent = NexusPrimaryAgent()
        original = agent.supported_actions
        try:
            agent.supported_actions = set(reversed(list(original)))
            reordered = json.dumps(agent._openai_tool_schemas(), sort_keys=True)
        finally:
            agent.supported_actions = original
            agent.invalidate_tool_schema_cache()
        assert json.dumps(agent._openai_tool_schemas(), sort_keys=True) == reordered

    def test_the_prompt_side_tool_listing_is_sorted_and_deduplicated(self) -> None:
        listing = NexusPrimaryAgent()._tool_listing()
        tools = [line.split(" — ", 1)[0].strip() for line in listing.splitlines()]
        assert tools == sorted(tools)
        assert len(tools) == len(set(tools))


# ---------------------------------------------------------------------------
# Item 2 seen end to end: a real argument schema reaches the model
# ---------------------------------------------------------------------------
class TestArgumentSchemas:
    def test_example_args_reach_the_schema_when_the_tool_declares_none(self) -> None:
        """The latent trap: a tool with no ``ToolSpec.schema`` must still ship args.

        All 46 tools currently advertised declare a real schema, so the
        example-derived path is a fallback. Before the loader fix it produced
        ``properties: {}`` for every one of them.
        """
        spec = get_tool("search_symbols")
        saved = dict(spec.schema)
        agent = _ScriptedAgent()
        agent.supported_actions = {AgentAction.SEARCH_SYMBOLS}
        try:
            spec.schema = {}
            base_module.invalidate_tool_schema_cache()
            parameters = (agent._openai_tool_schemas() or [])[0]["function"]["parameters"]
        finally:
            spec.schema = saved
            base_module.invalidate_tool_schema_cache()
        assert parameters["properties"], "example_args must produce a properties block"
        assert set(parameters["properties"]) == set(
            get_action_registry().get("SEARCH_SYMBOLS").example_args_dict()
        )

    def test_a_registered_tool_schema_still_wins(self) -> None:
        schemas = NexusPrimaryAgent()._openai_tool_schemas() or []
        read_file = next(e for e in schemas if e["function"]["name"] == "read_file")
        assert "project_path" in read_file["function"]["parameters"]["properties"]

    def test_no_shipped_schema_is_an_empty_properties_object(self) -> None:
        empty = [
            entry["function"]["name"]
            for entry in (NexusPrimaryAgent()._openai_tool_schemas() or [])
            if not entry["function"]["parameters"].get("properties")
        ]
        assert not empty, f"tools shipping an empty properties object: {empty}"

    def test_derived_property_types_are_json_schema_types(self) -> None:
        agent = _ScriptedAgent()
        agent.supported_actions = {AgentAction.RUN_TESTS}
        parameters = (agent._openai_tool_schemas() or [])[0]["function"]["parameters"]
        types = {k: v["type"] for k, v in parameters["properties"].items()}
        assert types["coverage"] == "boolean"
        assert types["test_path"] == "string"


# ---------------------------------------------------------------------------
# The cache: fast, bounded, and never stale
# ---------------------------------------------------------------------------
class TestSchemaCache:
    def test_the_second_call_reuses_the_cached_derivation(self) -> None:
        agent = NexusPrimaryAgent()
        agent._openai_tool_schemas()
        assert len(base_module._TOOL_SCHEMA_CACHE) == 1
        entry = next(iter(base_module._TOOL_SCHEMA_CACHE.values()))
        agent._openai_tool_schemas()
        assert next(iter(base_module._TOOL_SCHEMA_CACHE.values())) is entry

    def test_a_different_runtime_contract_gets_its_own_entry(self) -> None:
        agent = NexusPrimaryAgent()
        agent._openai_tool_schemas()
        agent._openai_tool_schemas(only=frozenset({"read_file", "write_file"}))
        assert len(base_module._TOOL_SCHEMA_CACHE) == 2

    def test_disabling_a_tool_invalidates_immediately(self) -> None:
        agent = NexusPrimaryAgent()
        assert "run_shell" in _descriptions(agent)
        try:
            set_tool_enabled("run_shell", False)
            assert "run_shell" not in _descriptions(agent)
        finally:
            set_tool_enabled("run_shell", True)
        assert "run_shell" in _descriptions(agent)

    def test_reenabling_a_previously_unavailable_tool_is_noticed(self) -> None:
        agent = NexusPrimaryAgent()
        try:
            set_tool_enabled("index_symbols", False)
            assert "index_symbols" not in _descriptions(agent)
        finally:
            set_tool_enabled("index_symbols", True)
        assert "index_symbols" in _descriptions(agent)

    def test_reregistering_a_tool_invalidates_immediately(self) -> None:
        from backend.tools.registry import ToolSpec, register_tool

        agent = NexusPrimaryAgent()
        before = _descriptions(agent)["run_shell"]
        spec = get_tool("run_shell")
        try:
            register_tool(
                ToolSpec(
                    name="run_shell",
                    description="A COMPLETELY DIFFERENT CONTRACT",
                    schema=dict(spec.schema),
                    handler=spec.handler,
                )
            )
            assert "COMPLETELY DIFFERENT" in _descriptions(agent)["run_shell"]
        finally:
            register_tool(spec)
        assert _descriptions(agent)["run_shell"] == before

    def test_invalidating_the_action_registry_invalidates_the_schemas(self) -> None:
        agent = NexusPrimaryAgent()
        registry = get_action_registry()
        agent._openai_tool_schemas()
        epoch_before = registry.epoch()
        assert (agent.name, epoch_before, None) in base_module._TOOL_SCHEMA_CACHE

        invalidate_action_registry()
        agent._openai_tool_schemas()
        epoch_after = registry.epoch()

        # The epoch is part of the key, so the call after an invalidation is
        # forced to re-derive. The superseded entry stays in the bounded dict
        # until eviction; it can never be served again because no lookup can
        # produce its key.
        assert epoch_after != epoch_before
        assert (agent.name, epoch_after, None) in base_module._TOOL_SCHEMA_CACHE

    def test_explicit_invalidation_hook_clears_everything(self) -> None:
        agent = NexusPrimaryAgent()
        agent._openai_tool_schemas()
        assert base_module._TOOL_SCHEMA_CACHE
        AgentBase.invalidate_tool_schema_cache()
        assert base_module._TOOL_SCHEMA_CACHE == {}

    def test_the_cache_is_bounded(self) -> None:
        agent = NexusPrimaryAgent()
        for index in range(base_module._TOOL_SCHEMA_CACHE_MAX + 8):
            agent._openai_tool_schemas(only=frozenset({f"tool_{index}"}))
        assert len(base_module._TOOL_SCHEMA_CACHE) <= base_module._TOOL_SCHEMA_CACHE_MAX

    def test_callers_cannot_poison_the_cache(self) -> None:
        """A provider that mutates the payload must not affect the next caller."""
        agent = NexusPrimaryAgent()
        first = agent._openai_tool_schemas() or []
        first.append({"type": "function", "function": {"name": "injected", "parameters": {}}})
        first[0]["function"]["description"] = "MUTATED"
        first[0]["function"]["parameters"].pop("type", None)
        second = agent._openai_tool_schemas() or []
        assert "injected" not in {e["function"]["name"] for e in second}
        assert second[0]["function"]["description"] != "MUTATED"
        assert second[0]["function"]["parameters"].get("type") == "object"

    def test_an_agent_without_actions_ships_no_schemas(self) -> None:
        agent = _ScriptedAgent()
        assert agent.supported_actions == set()
        assert agent._openai_tool_schemas() is None

    def test_the_runtime_contract_still_restricts_the_schema_list(self) -> None:
        agent = NexusPrimaryAgent()
        names = {
            entry["function"]["name"]
            for entry in (agent._openai_tool_schemas(only=frozenset({"read_file"})) or [])
        }
        assert names == {"read_file"}


class TestLivenessHelper:
    def test_a_live_entry_passes(self) -> None:
        agent = NexusPrimaryAgent()
        entries = agent._derive_tool_schema_entries(
            sorted(agent.supported_actions, key=lambda item: item.name),
            get_action_registry(),
            None,
        )
        assert base_module._tool_schema_cache_is_live(entries)

    def test_a_foreign_entry_object_fails(self) -> None:
        agent = NexusPrimaryAgent()
        entries = agent._derive_tool_schema_entries(
            sorted(agent.supported_actions, key=lambda item: item.name),
            get_action_registry(),
            None,
        )
        entries[0] = type(entries[0])(
            tool=entries[0].tool,
            spec=object(),  # type: ignore[arg-type]
            advertised=entries[0].advertised,
            description="",
            parameters={},
        )
        assert not base_module._tool_schema_cache_is_live(entries)
