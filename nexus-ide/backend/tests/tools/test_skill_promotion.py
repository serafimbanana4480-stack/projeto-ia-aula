"""Tests for the skill promotion lifecycle: create → gate → ACTIVE → measure.

Covers ``skill_runtime.promote_skill`` state machine and gate, the audited
transitions, the ``promote_skill``/``report_skill_outcome`` tools, seed-skill
discovery, and the REST route wiring. Hermetic: every test redirects the skill
roots and the promotion audit log into ``tmp_path`` so nothing is written into
the repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.skill_runtime import (
    DEFAULT_SKILL_ROOTS,
    clear_skill_cache,
    deprecate_skill,
    disable_skill,
    discover_skills,
    list_skill_summaries,
    promote_skill,
    read_promotion_log,
    record_skill_outcome,
    record_skill_usage,
    reset_skill_metrics,
    select_skills,
)
from backend.tools import skills_tools
from backend.tools.registry import get_tool

_AUDIT_FIELDS = ("skill_id", "from", "to", "actor", "reason", "timestamp")


def _write_draft(root: Path, name: str = "my-draft") -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    path.write_text(
        f"""---
name: {name}
version: 1.0.0
status: draft
domain: general
description: draft procedure for python audit tasks
triggers: [python audit, auditoria de projeto]
tags: [python, audit]
required_tools: [run_lint, read_file]
---

# {name}

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


def _status_of(name: str) -> str:
    for doc in discover_skills():
        if doc.name.casefold() == name.casefold():
            return doc.manifest.status.value
    return "missing"


@pytest.fixture
def lifecycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated skill root + audit dir with promotion flags defaulted off."""
    root = tmp_path / "skills"
    root.mkdir()
    monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(root))
    monkeypatch.setenv("NEXUS_SKILLS_LIFECYCLE_DIR", str(tmp_path / "data"))
    for flag in ("NEXUS_SKILLS_AUTO_PROMOTE", "NEXUS_SKILLS_RUN_VALIDATION"):
        monkeypatch.delenv(flag, raising=False)
    monkeypatch.delenv("NEXUS_SKILLS_MIN_CONFIDENCE", raising=False)
    monkeypatch.delenv("NEXUS_SKILLS_STORE_EXPERIENCE", raising=False)
    clear_skill_cache()
    reset_skill_metrics()
    return root


class TestPromotionGate:
    def test_draft_skill_is_not_selected(self, lifecycle: Path) -> None:
        _write_draft(lifecycle)
        clear_skill_cache()

        result = select_skills(
            "python audit", available_tools={"run_lint", "read_file"}, include_memory=False
        )

        assert result["skills"] == []
        assert "my-draft" not in result["rejected"]

    def test_promotion_without_approval_is_refused_and_state_is_kept(
        self, lifecycle: Path
    ) -> None:
        _write_draft(lifecycle)
        clear_skill_cache()

        result = promote_skill("my-draft", actor="tester", reason="reviewed")

        assert result["ok"] is False
        assert "approval" in result["error"].lower()
        # Rejected before any write: the file stays a draft, nothing audited.
        assert _status_of("my-draft") == "draft"
        assert read_promotion_log() == []

    def test_promotion_with_approval_activates_and_writes_audit(
        self, lifecycle: Path
    ) -> None:
        _write_draft(lifecycle)
        clear_skill_cache()

        result = promote_skill(
            "my-draft", actor="tester", reason="reviewed and correct", approved_by="operator"
        )

        assert result["ok"] is True
        assert result["from"] == "draft"
        assert result["to"] == "active"
        assert _status_of("my-draft") == "active"
        audit = read_promotion_log()
        assert len(audit) == 1
        record = audit[-1]
        for field in _AUDIT_FIELDS:
            assert record.get(field), field
        assert record["skill_id"] == "my-draft"
        assert record["from"] == "draft" and record["to"] == "active"
        assert record["approved_by"] == "operator"
        assert record["actor"] == "tester"

    def test_active_skill_is_selected_with_matching_context(self, lifecycle: Path) -> None:
        _write_draft(lifecycle)
        clear_skill_cache()
        promote_skill("my-draft", actor="tester", reason="ok", approved_by="operator")

        result = select_skills(
            "Faz uma auditoria python", available_tools={"run_lint", "read_file"}, include_memory=False
        )

        names = [entry["name"] for entry in result["skills"]]
        assert names == ["my-draft"]
        assert "Reproduzir e isolar" in result["context"]

    def test_gate_fails_when_required_tools_are_unavailable(self, lifecycle: Path) -> None:
        _write_draft(lifecycle)
        clear_skill_cache()

        result = promote_skill(
            "my-draft",
            actor="tester",
            reason="ok",
            approved_by="operator",
            available_tools={"read_file"},  # run_lint missing
        )

        assert result["ok"] is False
        assert "missing_tools:run_lint" in result["error"]
        assert _status_of("my-draft") == "draft"

    def test_promotion_requires_a_discoverable_file_skill(self, lifecycle: Path) -> None:
        result = promote_skill("does-not-exist", actor="tester", reason="ok", approved_by="op")
        assert result["ok"] is False
        assert "not a discoverable file skill" in result["error"]


class TestStateTransitions:
    def _active(self) -> None:
        promote_skill("my-draft", actor="tester", reason="ok", approved_by="operator")

    def test_promote_is_idempotent_rejects_already_active(self, lifecycle: Path) -> None:
        _write_draft(lifecycle)
        clear_skill_cache()
        self._active()

        again = promote_skill("my-draft", actor="tester", reason="ok", approved_by="operator")

        assert again["ok"] is False
        assert "already active" in again["error"]

    def test_active_to_deprecated_then_disabled(self, lifecycle: Path) -> None:
        _write_draft(lifecycle)
        clear_skill_cache()
        self._active()

        deprecated = deprecate_skill("my-draft", actor="tester", reason="superseded")
        assert deprecated["ok"] is True
        assert deprecated["to"] == "deprecated"
        assert _status_of("my-draft") == "deprecated"

        disabled = disable_skill("my-draft", actor="tester", reason="unsafe")
        assert disabled["ok"] is True
        assert disabled["to"] == "disabled"
        assert _status_of("my-draft") == "disabled"

    def test_disable_is_a_kill_switch_from_any_state(self, lifecycle: Path) -> None:
        _write_draft(lifecycle)  # still a DRAFT
        clear_skill_cache()

        disabled = disable_skill("my-draft", actor="tester", reason="emergency")

        assert disabled["ok"] is True
        assert disabled["from"] == "draft"
        assert disabled["to"] == "disabled"

    def test_draft_cannot_be_promoted_from_deprecated(self, lifecycle: Path) -> None:
        _write_draft(lifecycle)
        clear_skill_cache()
        self._active()
        deprecate_skill("my-draft", actor="tester", reason="old")

        again = promote_skill("my-draft", actor="tester", reason="ok", approved_by="operator")

        assert again["ok"] is False
        assert "invalid transition deprecated -> active" in again["error"]

    def test_transition_requires_actor_and_reason(self, lifecycle: Path) -> None:
        _write_draft(lifecycle)
        clear_skill_cache()
        assert promote_skill("my-draft", actor="", reason="ok", approved_by="op")["ok"] is False
        assert promote_skill("my-draft", actor="t", reason="", approved_by="op")["ok"] is False


class TestAutoPromoteAndConfidence:
    def test_auto_promote_is_off_by_default(self, lifecycle: Path) -> None:
        _write_draft(lifecycle)
        clear_skill_cache()

        # High confidence but no approval and no auto-promote flag: still refused.
        result = promote_skill(
            "my-draft", actor="tester", reason="ok", confidence=0.95
        )

        assert result["ok"] is False
        assert "approval" in result["error"].lower()
        assert _status_of("my-draft") == "draft"

    def test_auto_promote_requires_measured_confidence(
        self, lifecycle: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NEXUS_SKILLS_AUTO_PROMOTE", "1")
        _write_draft(lifecycle)
        clear_skill_cache()

        missing = promote_skill("my-draft", actor="tester", reason="ok")

        assert missing["ok"] is False
        assert "measured confidence" in missing["error"]

    def test_auto_promote_succeeds_above_threshold(
        self, lifecycle: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NEXUS_SKILLS_AUTO_PROMOTE", "1")
        _write_draft(lifecycle)
        clear_skill_cache()

        result = promote_skill("my-draft", actor="tester", reason="ok", confidence=0.72)

        assert result["ok"] is True
        assert result["audit"]["auto_promote"] is True
        assert _status_of("my-draft") == "active"

    def test_auto_promote_below_threshold_is_refused(
        self, lifecycle: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NEXUS_SKILLS_AUTO_PROMOTE", "1")
        _write_draft(lifecycle)
        clear_skill_cache()

        result = promote_skill("my-draft", actor="tester", reason="ok", confidence=0.4)

        assert result["ok"] is False
        assert "below the minimum" in result["error"]

    def test_approved_promotion_below_confidence_is_refused(
        self, lifecycle: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NEXUS_SKILLS_MIN_CONFIDENCE", "0.9")
        _write_draft(lifecycle)
        clear_skill_cache()

        result = promote_skill(
            "my-draft", actor="tester", reason="ok", approved_by="operator", confidence=0.5
        )

        assert result["ok"] is False
        assert "below the minimum" in result["error"]


class TestMeasurement:
    def test_usage_increments_on_selection_and_success_rate_is_listed(
        self, lifecycle: Path
    ) -> None:
        _write_draft(lifecycle)
        clear_skill_cache()
        promote_skill("my-draft", actor="tester", reason="ok", approved_by="operator")

        select_skills("python audit", available_tools={"run_lint", "read_file"}, include_memory=False)
        select_skills("python audit", available_tools={"run_lint", "read_file"}, include_memory=False)
        record_skill_outcome("my-draft", True)
        record_skill_outcome("my-draft", False)

        summary = next(
            item for item in list_skill_summaries() if item["name"] == "my-draft"
        )
        assert summary["usage_count"] == 2
        assert summary["success_count"] == 1
        assert summary["failure_count"] == 1
        assert summary["success_rate"] == 0.5

    def test_record_usage_and_outcome_are_counted(self, lifecycle: Path) -> None:
        record_skill_usage("alpha")
        record_skill_usage("alpha")
        record_skill_outcome("alpha", True)

        summary = record_skill_outcome("alpha", True)
        assert summary["ok"] is True
        assert summary["success_rate"] == 1.0


class TestSkillsTools:
    def test_promote_and_outcome_tools_are_registered(self) -> None:
        promote = get_tool("promote_skill")
        report = get_tool("report_skill_outcome")
        assert promote is not None and promote.risk_level == "high"
        assert promote.requires_confirmation is True
        assert report is not None and report.risk_level == "low"

    @pytest.mark.asyncio
    async def test_build_then_promote_via_tools(self, lifecycle: Path) -> None:
        built = await skills_tools.build_skill(
            request="Quero uma skill para fazer auditorias completas de projetos Python"
        )
        assert built["ok"] is True
        assert built["status"] == "draft"
        assert built["promotion"].startswith("draft;")

        promote_tool = get_tool("promote_skill").handler
        blocked = await promote_tool(skill_id="python-project-audit")
        assert blocked["ok"] is False  # no approval yet

        promoted = await promote_tool(
            skill_id="python-project-audit", reason="reviewed", approved_by="operator"
        )
        assert promoted["ok"] is True
        assert promoted["to"] == "active"

        selected = select_skills(
            "Faz uma auditoria completa ao projeto Python",
            available_tools={"list_dir", "read_file", "run_tests", "run_lint", "type_check"},
            include_memory=False,
        )
        assert [entry["name"] for entry in selected["skills"]] == ["python-project-audit"]

    @pytest.mark.asyncio
    async def test_report_outcome_tool(self, lifecycle: Path) -> None:
        result = await skills_tools.report_skill_outcome(skill_id="my-draft", success=True)
        assert result["ok"] is True
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_build_registers_experience_skill_in_store_when_enabled(
        self, lifecycle: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from types import SimpleNamespace

        monkeypatch.setenv("NEXUS_SKILLS_STORE_EXPERIENCE", "1")
        monkeypatch.setattr(
            skills_tools,
            "_discover_experience_candidates",
            lambda _c, _l: [
                {
                    "name": "repeat-verify-flow",
                    "description": "Repeated verification sequence",
                    "action_sequence": ["read_file", "run_tests"],
                    "frequency": 5,
                    "confidence": 0.9,
                    "example_tasks": ["trace-a"],
                    "component_kinds": ["primary"],
                }
            ],
        )
        created: dict[str, SimpleNamespace] = {}

        class FakeStore:
            def create_skill(self, **kwargs: object) -> SimpleNamespace:
                skill = SimpleNamespace(id="skill_store_1", **kwargs)
                created["skill"] = skill
                return skill

        from backend.core.skills_store import SkillsStore

        monkeypatch.setattr(SkillsStore, "_instance", FakeStore())

        built = await skills_tools.build_skill(experience_candidate="repeat-verify-flow")

        assert built["ok"] is True
        assert built["store_skill_id"] == "skill_store_1"
        assert created["skill"].source == "experience_candidate"
        assert created["skill"].auto_apply is False


class TestSeedSkills:
    def test_repository_seeds_are_discovered_and_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(DEFAULT_SKILL_ROOTS[0]))
        clear_skill_cache()

        documents = discover_skills()
        names = {document.name for document in documents}
        for seed in ("audit-repo-readonly", "debug-failing-test", "rag-reindex"):
            assert seed in names
            document = next(d for d in documents if d.name == seed)
            assert document.manifest.status.value == "active"
            assert document.manifest.triggers
            assert document.manifest.required_tools

        assert {"audit-repo-readonly", "debug-failing-test", "rag-reindex"} <= names

        # A seed must be selectable, not merely discoverable.
        reset_skill_metrics()
        result = select_skills(
            "audit repository before change",
            available_tools={
                "list_project_files",
                "read_file",
                "search_in_files",
                "run_lint",
                "type_check",
            },
            include_memory=False,
        )
        assert [entry["name"] for entry in result["skills"]] == ["audit-repo-readonly"]
        assert "audit repository" in result["skills"][0]["reason"]


class TestRouteWiring:
    def test_promotion_routes_are_registered(self) -> None:
        from backend.orchestrator.routes import skills as skills_routes

        paths = [(sorted(route.methods), route.path) for route in skills_routes.router.routes]
        methods_for = {}
        for methods, path in paths:
            methods_for.setdefault(path, set()).update(methods)

        assert "POST" in methods_for.get("/skills/{skill_id}/promote", set())
        assert "POST" in methods_for.get("/skills/{skill_id}/deprecate", set())
        assert "POST" in methods_for.get("/skills/{skill_id}/disable", set())
        assert "GET" in methods_for.get("/skills/promotions", set())
