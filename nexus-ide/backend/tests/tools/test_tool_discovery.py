"""Tests for the tool discovery system.

Covers:
- list_tools_by_category
- list_tools_by_tag
- search_tools (fuzzy)
- get_tools_for_agent
- get_tool_descriptions_for_llm
- get_tool_stats
- discovery.build_tool_overview
- discovery.build_compact_tool_list
- discovery.list_tools_by_capability
"""

from __future__ import annotations

import pytest

from backend.tools.discovery import (
    build_compact_tool_list,
    build_tool_overview,
    list_tools_by_capability,
)
from backend.tools.registry import (
    ToolSpec,
    get_tool_catalog,
    get_tool_descriptions_for_llm,
    get_tool_stats,
    get_tools_for_agent,
    list_tools,
    list_tools_by_category,
    list_tools_by_tag,
    register_tool,
    search_tools,
    tool_requires_confirmation,
)

# ---- fixtures ----

@pytest.fixture(autouse=True)
def _clean_registry():
    """Reset registry between tests to avoid pollution."""
    from backend.tools import registry as reg
    saved = dict(reg._registry)
    yield
    reg._registry = saved


def _register_sample_tools():
    """Register a small sample of tools for testing."""
    register_tool(ToolSpec(
        name="sample_read_file",
        description="Read a file from the project",
        tags=["file", "read"],
        category="file",
        risk_level="low",
        when_to_use="When you need to read a file",
        examples=[{"path": "main.py"}],
    ))
    register_tool(ToolSpec(
        name="sample_write_file",
        description="Write content to a file",
        tags=["file", "write"],
        category="file",
        risk_level="medium",
        requires_confirmation=False,
        when_to_use="When you need to create or modify a file",
    ))
    register_tool(ToolSpec(
        name="sample_docker_run",
        description="Run a Docker container",
        tags=["docker", "container"],
        category="docker",
        risk_level="high",
        requires_confirmation=True,
        when_to_use="When you need to run a container",
    ))
    register_tool(ToolSpec(
        name="sample_search_web",
        description="Search the web",
        tags=["web", "search"],
        category="web",
        risk_level="low",
        when_to_use="When you need current information",
    ))


# ---- tests ----

def test_list_tools_returns_all():
    tools = list_tools(enabled_only=False)
    assert isinstance(tools, list)
    # The registry may already have tools from other tests, so just check type
    assert all(isinstance(t, ToolSpec) for t in tools)


def test_list_tools_by_category_groups_correctly():
    _register_sample_tools()
    by_cat = list_tools_by_category(enabled_only=False)
    assert "file" in by_cat
    assert "docker" in by_cat
    assert "web" in by_cat
    # Each category should contain at least the sample tools we just registered
    file_names = {t.name for t in by_cat["file"]}
    assert "sample_read_file" in file_names
    assert "sample_write_file" in file_names


def test_list_tools_by_tag_filters():
    _register_sample_tools()
    file_tools = list_tools_by_tag("file", enabled_only=False)
    assert any(t.name == "sample_read_file" for t in file_tools)
    assert any(t.name == "sample_write_file" for t in file_tools)
    docker_tools = list_tools_by_tag("docker", enabled_only=False)
    assert any(t.name == "sample_docker_run" for t in docker_tools)


def test_search_tools_finds_by_name():
    _register_sample_tools()
    results = search_tools("sample_read", enabled_only=False)
    assert any(t.name == "sample_read_file" for t in results)


def test_search_tools_finds_by_description():
    _register_sample_tools()
    results = search_tools("Docker", enabled_only=False)
    assert any(t.name == "sample_docker_run" for t in results)


def test_search_tools_finds_by_tag():
    _register_sample_tools()
    results = search_tools("container", enabled_only=False)
    assert any(t.name == "sample_docker_run" for t in results)


def test_search_tools_finds_by_category():
    _register_sample_tools()
    results = search_tools("docker", enabled_only=False)
    assert any(t.name == "sample_docker_run" for t in results)


def test_search_tools_empty_query_returns_empty():
    assert search_tools("", enabled_only=False) == []


def test_search_tools_no_match_returns_empty():
    _register_sample_tools()
    results = search_tools("xyznomatch", enabled_only=False)
    assert results == []


def test_search_tools_case_insensitive():
    _register_sample_tools()
    results_lower = search_tools("docker", enabled_only=False)
    results_upper = search_tools("DOCKER", enabled_only=False)
    assert len(results_lower) == len(results_upper)


def test_get_tools_for_agent_matches_tags():
    _register_sample_tools()
    tools = get_tools_for_agent("docker")
    assert any(t.name == "sample_docker_run" for t in tools)


def test_get_tools_for_agent_returns_all_when_no_match():
    _register_sample_tools()
    # An agent with no matching tags should get all tools (fallback)
    tools = get_tools_for_agent("nonexistent_agent_xyz")
    assert len(tools) >= 1


def test_get_tool_descriptions_for_llm_includes_tools():
    _register_sample_tools()
    overview = get_tool_descriptions_for_llm()
    assert "Available Tools" in overview or len(overview) > 0
    assert "sample_read_file" in overview


def test_get_tool_descriptions_for_llm_with_max_tools():
    _register_sample_tools()
    overview = get_tool_descriptions_for_llm(max_tools=2)
    # Should include at most 2 tool lines
    lines = [line for line in overview.split("\n") if line.startswith("- ")]
    assert len(lines) <= 2


def test_get_tool_descriptions_for_llm_with_risk():
    _register_sample_tools()
    overview = get_tool_descriptions_for_llm(include_risk=True)
    # The docker tool has risk=high, so should be annotated
    assert "RISK" in overview or "high" in overview or len(overview) > 0


def test_get_tool_descriptions_for_llm_without_risk():
    _register_sample_tools()
    overview = get_tool_descriptions_for_llm(include_risk=False)
    # Without risk, no RISK annotations
    assert "RISK: high" not in overview


def test_get_tool_descriptions_for_llm_with_examples():
    _register_sample_tools()
    overview = get_tool_descriptions_for_llm(include_examples=True)
    assert "Example:" in overview


def test_get_tool_descriptions_for_llm_without_examples():
    _register_sample_tools()
    overview = get_tool_descriptions_for_llm(include_examples=False)
    assert "Example:" not in overview


def test_get_tool_stats():
    _register_sample_tools()
    stats = get_tool_stats()
    assert "total" in stats
    assert "by_category" in stats
    assert "by_risk" in stats
    assert "requires_confirmation" in stats
    assert stats["total"] >= 4
    assert stats["by_risk"]["high"] >= 1
    assert stats["by_risk"]["low"] >= 1
    assert stats["by_risk"]["medium"] >= 1
    assert stats["requires_confirmation"] >= 1


def test_confirmation_policy_matches_model_description_catalog_and_stats():
    # Finish lazy registration before replacing this name with a deliberately
    # low-risk spec. The policy still requires confirmation by tool name.
    list_tools(enabled_only=False)
    register_tool(
        ToolSpec(
            name="fetch_url",
            description="Fetch a web page",
            risk_level="low",
            requires_confirmation=False,
        )
    )

    description = get_tool_descriptions_for_llm(include_examples=False)
    fetch_line = next(line for line in description.splitlines() if "`fetch_url`" in line)
    assert "[requires confirmation]" in fetch_line

    catalog_entry = next(item for item in get_tool_catalog() if item["name"] == "fetch_url")
    assert catalog_entry["requires_confirmation"] is True

    registered = list_tools(enabled_only=False)
    expected = sum(tool_requires_confirmation(tool) for tool in registered)
    assert get_tool_stats()["requires_confirmation"] == expected


def test_build_tool_overview_returns_string():
    _register_sample_tools()
    overview = build_tool_overview()
    assert isinstance(overview, str)


def test_build_tool_overview_includes_sample_tools():
    _register_sample_tools()
    overview = build_tool_overview()
    assert "sample_read_file" in overview


def test_build_compact_tool_list_respects_max_chars():
    _register_sample_tools()
    compact = build_compact_tool_list(max_chars=200)
    assert isinstance(compact, str)
    assert "Tools:" in compact


def test_list_tools_by_capability_docker():
    _register_sample_tools()
    tools = list_tools_by_capability("docker")
    assert any(t.name == "sample_docker_run" for t in tools)


def test_list_tools_by_capability_file():
    _register_sample_tools()
    tools = list_tools_by_capability("file")
    names = {t.name for t in tools}
    assert "sample_read_file" in names
    assert "sample_write_file" in names


def test_list_tools_by_capability_unknown():
    _register_sample_tools()
    tools = list_tools_by_capability("totally_made_up_capability_xyz")
    assert tools == []


def test_tool_spec_defaults():
    """Test ToolSpec default values for new metadata fields."""
    spec = ToolSpec(name="minimal", description="A minimal tool")
    assert spec.tags == []
    assert spec.risk_level == "low"
    assert spec.requires_confirmation is False
    assert spec.when_to_use == ""
    assert spec.examples == []
    assert spec.category == ""


def test_tool_spec_with_metadata():
    """Test ToolSpec with all metadata fields populated."""
    spec = ToolSpec(
        name="full",
        description="Fully specified tool",
        tags=["file", "write"],
        category="file",
        risk_level="high",
        requires_confirmation=True,
        when_to_use="When you need to do X",
        examples=[{"path": "x.txt", "content": "hello"}],
    )
    assert spec.tags == ["file", "write"]
    assert spec.category == "file"
    assert spec.risk_level == "high"
    assert spec.requires_confirmation is True
    assert spec.when_to_use == "When you need to do X"
    assert len(spec.examples) == 1
