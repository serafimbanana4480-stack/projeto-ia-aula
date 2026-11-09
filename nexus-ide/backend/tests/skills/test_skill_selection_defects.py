"""Selection-time defects of the skill runtime.

Covers the seeded skills that could never activate, the promotion gate that
disagreed with the selector, the hidden action-registry failure, the usage
counter that counted undelivered skills and the dropped skill version.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.agents.nexus_primary import NexusPrimaryAgent
from backend.core.skill_runtime import (
    DEFAULT_SKILL_ROOTS,
    clear_skill_cache,
    list_skill_summaries,
    promote_skill,
    reset_skill_metrics,
    select_skills,
    select_skills_for_agent,
)
from backend.core.skills_store import SkillsStore
from backend.tools import skills_tools


def _write_active_skill(
    root: Path,
    name: str,
    *,
    required_tools: str = "",
    version: str = "1.0.0",
    triggers: str = "[alpha task, auditoria de projeto]",
    status: str = "active",
) -> Path:
    """Write a skill that passes the promotion gate's schema check."""
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(
        f"""---
name: {name}
version: {version}
status: {status}
domain: general
description: Procedimento de teste para auditorias Python
triggers: {triggers}
tags: [python, audit]
required_tools: [{required_tools}]
---

# {name}

## Purpose

Procedimento de teste.

## Workflow

1. Reproduzir e isolar a falha.

## Rules

- Nao inventar evidencia.

## Verification

- Registar o resultado observado.

## Example

Pedido: faz uma auditoria python.
""",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def skills_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated skill root + audit directory with promotion flags off."""
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(root))
    monkeypatch.setenv("NEXUS_SKILLS_LIFECYCLE_DIR", str(tmp_path / "data"))
    for flag in ("NEXUS_SKILLS_AUTO_PROMOTE", "NEXUS_SKILLS_RUN_VALIDATION"):
        monkeypatch.delenv(flag, raising=False)
    monkeypatch.delenv("NEXUS_SKILLS_MIN_CONFIDENCE", raising=False)
    clear_skill_cache()
    reset_skill_metrics()
    return root


def test_seeded_skills_can_be_selected(monkeypatch: pytest.MonkeyPatch) -> None:
    """The three seeded product skills must be reachable.

    ``AgentAction`` has no ``SEARCH_IN_FILES``/``LIST_PROJECT_FILES``/
    ``INDEX_CODEBASE``/``INDEX_STATS`` entry, so the selector used to reject
    every seeded skill with ``missing_tools:…`` even though all the tools
    they need exist and are enabled in the tool registry.
    """
    monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(DEFAULT_SKILL_ROOTS[0]))
    clear_skill_cache()
    reset_skill_metrics()
    agent = NexusPrimaryAgent()

    expectations = {
        "audit repository before change": "audit-repo-readonly",
        "debug failing test with pytest": "debug-failing-test",
        "rag reindex and rebuild the search index": "rag-reindex",
    }
    for query, expected in expectations.items():
        result = select_skills_for_agent(query, None, agent)
        names = [entry["name"] for entry in result["skills"]]
        assert expected in names, (query, names, result["rejected"])
        assert expected not in {
            entry["name"] for entry in result["rejected"]
        }, result["rejected"]


def test_promotion_gate_matches_the_selection_surface(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gate must test what the selector tests.

    A tool that exists and is enabled but is missing from the agent's action
    surface used to pass the gate (the gate read the catalog) and then be
    unreachable (the selector read the action surface) — false assurance.
    """
    monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(skills_root))
    clear_skill_cache()

    # ``search_in_files`` exists and is enabled, but is not in the primary
    # agent's action surface.
    _write_active_skill(
        skills_root, "surface-skill", required_tools="search_in_files", status="draft"
    )
    clear_skill_cache()

    gate = promote_skill(
        "surface-skill", actor="tester", reason="reviewed", approved_by="operator"
    )
    assert gate["ok"] is True, gate

    selection = select_skills_for_agent(
        "faz uma auditoria python", None, NexusPrimaryAgent()
    )
    assert "surface-skill" in [entry["name"] for entry in selection["skills"]]

    # The converse also holds: a tool that does not exist is refused by the
    # gate AND rejected by the selector.
    _write_active_skill(
        skills_root,
        "ghost-skill",
        required_tools="tool_that_does_not_exist",
        status="draft",
    )
    _write_active_skill(
        skills_root,
        "ghost-active-skill",
        required_tools="tool_that_does_not_exist",
        status="active",
    )
    clear_skill_cache()

    ghost_gate = promote_skill(
        "ghost-skill", actor="tester", reason="reviewed", approved_by="operator"
    )
    assert ghost_gate["ok"] is False
    assert "missing_tools:tool_that_does_not_exist" in ghost_gate["error"]

    ghost_selection = select_skills_for_agent(
        "faz uma auditoria python", None, NexusPrimaryAgent()
    )
    assert "ghost-active-skill" not in [
        entry["name"] for entry in ghost_selection["skills"]
    ]
    assert {
        "name": "ghost-active-skill",
        "reason": "missing_tools:tool_that_does_not_exist",
    } in ghost_selection["rejected"]


def test_broken_action_registry_is_reported_not_hidden(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A broken ``config/agent_actions.yaml`` must be visible.

    The whole registry lookup used to be wrapped in ``except Exception`` that
    only logged, so the available tool set silently became empty and every
    tool-dependent skill was dropped with no error the caller could see.
    """
    import backend.agents.action_registry as action_registry_module

    def broken_registry() -> object:
        raise RuntimeError("agent_actions.yaml is broken")

    monkeypatch.setattr(action_registry_module, "get_action_registry", broken_registry)
    _write_active_skill(skills_root, "registry-skill", required_tools="read_file")
    clear_skill_cache()

    with caplog.at_level(logging.ERROR):
        result = select_skills_for_agent(
            "faz uma auditoria python", None, NexusPrimaryAgent()
        )

    reasons = [entry["reason"] for entry in result["rejected"]]
    assert any("action_surface_unavailable" in reason for reason in reasons), result
    assert any("agent_actions.yaml is broken" in reason for reason in reasons), result
    assert any(
        record.levelno >= logging.ERROR
        and "action surface" in record.getMessage()
        for record in caplog.records
    ), caplog.records


def test_usage_count_only_counts_delivered_skills(skills_root: Path) -> None:
    """A skill dropped by the context budget was never delivered.

    ``usage_count`` feeds the promotion-confidence gate, so counting a skill
    that never reached the context inflates the measured usage.
    """
    _write_active_skill(skills_root, "budget-first", triggers="[budget task, auditoria]")
    _write_active_skill(skills_root, "budget-second", triggers="[budget task, auditoria]")
    clear_skill_cache()
    reset_skill_metrics()

    result = select_skills(
        "budget task",
        available_tools={"read_file"},
        include_memory=False,
        max_chars=200,
    )

    assert [entry["name"] for entry in result["skills"]] == ["budget-first"]
    assert result["skipped"]["budget-second"] == "context_budget"

    counts = {item["name"]: item["usage_count"] for item in list_skill_summaries()}
    assert counts["budget-first"] == 1
    assert counts["budget-second"] == 0


def test_draft_version_does_not_hide_active_version(skills_root: Path) -> None:
    active = _write_active_skill(skills_root, "shared-skill", version="1.0.0")
    draft = _write_active_skill(skills_root, "new-version", version="2.0.0", status="draft")
    draft.write_text(draft.read_text(encoding="utf-8").replace(
        "name: new-version", "name: shared-skill"
    ), encoding="utf-8")
    clear_skill_cache()

    result = select_skills("alpha task", include_memory=False)

    assert [(item["name"], item["version"]) for item in result["skills"]] == [
        ("shared-skill", "1.0.0")
    ]
    assert active.exists() and draft.exists()
    assert list_skill_summaries()[0]["status"] == "draft"


@pytest.mark.parametrize("status", ["draft", "disabled", "deprecated", "", None])
def test_non_active_memory_skills_are_not_automatically_selected(
    skills_root: Path, monkeypatch: pytest.MonkeyPatch, status: str | None
) -> None:
    skill = SimpleNamespace(
        id="one", name="alpha task", status=status, auto_apply=True, confidence=1.0
    )
    store = SimpleNamespace(list_skills=lambda **kwargs: [skill])
    monkeypatch.setattr(SkillsStore, "_instance", store)

    assert select_skills("alpha task", user_id="owner")["skills"] == []


@pytest.mark.asyncio
async def test_load_skill_keeps_the_version(skills_root: Path) -> None:
    """``load_skill`` must not drop the version the loader produced."""
    _write_active_skill(skills_root, "versioned-skill", version="2.3.4")
    clear_skill_cache()

    loaded = await skills_tools.load_skill("versioned-skill")

    assert loaded["ok"] is True
    assert loaded["version"] == "2.3.4"
    assert loaded["content"].startswith("### Skill: versioned-skill (v2.3.4)\n\n")
