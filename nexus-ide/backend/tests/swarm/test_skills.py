"""Unit tests for the SWARM skills system + workflow loader."""

from __future__ import annotations

import pytest

from backend.swarm.skills.skills import (
    SKILL_CATALOGUE,
    Skill,
    all_skills,
    by_category,
    get_skill,
)
from backend.swarm.skills.workflow_loader import (
    _parse_agent,
    _parse_mode,
    _parse_strategy,
    load_workflows,
    merged_catalogue,
)

# ---------------------------------------------------------------------------
# Built-in skills
# ---------------------------------------------------------------------------


def test_builtin_catalogue_not_empty() -> None:
    assert len(SKILL_CATALOGUE) >= 5
    # All have unique ids
    ids = [s.id for s in SKILL_CATALOGUE]
    assert len(set(ids)) == len(ids)


def test_get_skill_by_id() -> None:
    s = get_skill("security-audit")
    assert s is not None
    assert s.id == "security-audit"
    assert s.mode.value == "review"


def test_get_skill_returns_none_for_missing() -> None:
    assert get_skill("nope") is None


def test_by_category_groups() -> None:
    grouped = by_category()
    assert "code-quality" in grouped
    assert "architecture" in grouped
    assert "docs" in grouped
    assert "research" in grouped
    assert "debug" in grouped
    # All groups are lists
    for _cat, items in grouped.items():
        assert all(isinstance(s, Skill) for s in items)


def test_skill_render_objective() -> None:
    s = get_skill("bugfix-investigation")
    assert s is not None
    obj = s.render_objective(
        {
            "symptom": "Login returns 500",
            "repro": "POST /login with empty body",
            "project_path": "/tmp/proj",
        }
    )
    assert "Login returns 500" in obj
    assert "POST /login with empty body" in obj
    assert "/tmp/proj" in obj


def test_skill_render_objective_missing_var_raises() -> None:
    s = get_skill("security-audit")
    assert s is not None
    with pytest.raises(ValueError):
        s.render_objective({})  # missing 'file_path'


def test_skill_variables_have_required_field() -> None:
    for s in all_skills():
        for v in s.variables:
            assert v.name
            assert v.label


def test_skill_to_dict_round_trip() -> None:
    s = get_skill("refactor-clean")
    assert s is not None
    d = s.to_dict()
    assert d["id"] == "refactor-clean"
    assert d["mode"] == "implementation"
    assert d["strategy"] == "pipeline"
    # Agents should be at least investigator + implementer + reviewer
    assert {"investigator", "implementer", "reviewer"} <= set(d["agents"])
    # All variable names are present
    var_names = {v["name"] for v in d["variables"]}
    assert "file_path" in var_names


# ---------------------------------------------------------------------------
# Workflow loader
# ---------------------------------------------------------------------------


def test_parse_mode_known() -> None:
    from backend.swarm.core.types import OperationalMode

    assert _parse_mode("review") == OperationalMode.REVIEW
    assert _parse_mode("ARCHITECTURE") == OperationalMode.ARCHITECTURE


def test_parse_mode_unknown_raises() -> None:
    with pytest.raises(ValueError):
        _parse_mode("nope")


def test_parse_strategy_known() -> None:
    from backend.swarm.core.types import SwarmStrategy

    assert _parse_strategy("debate") == SwarmStrategy.DEBATE


def test_parse_agent_alias_coder() -> None:
    from backend.swarm.core.types import AgentRole

    assert _parse_agent("coder") == AgentRole.IMPLEMENTER
    assert _parse_agent("analyzer") == AgentRole.INVESTIGATOR
    assert _parse_agent("ARCHITECT") == AgentRole.ARCHITECT


def test_load_workflows_from_real_dir() -> None:
    """Loads the YAML workflows shipped in config/workflows/."""
    workflows = load_workflows()
    ids = {w.id for w in workflows}
    assert "fullstack-feature" in ids
    assert "dependency-upgrade" in ids
    assert "incident-response" in ids


def test_merged_catalogue_includes_both() -> None:
    catalogue = merged_catalogue()
    ids = {s.id for s in catalogue}
    # built-in
    assert "security-audit" in ids
    # yaml
    assert "fullstack-feature" in ids
    # No duplicates
    assert len(ids) == len(catalogue)
