"""Skills must be discoverable and delivered, with and without a project.

These tests run against the skills that really exist on disk in the two
default roots (``nexus-ide/skills`` and ``.opencode/skills``), not against
fixtures, because that is the only way to prove the delivery path works.

The Hermes question is answered here too: Hermes is not a runtime component of
this backend. It is the opencode orchestrator that *authors* skills under
``.opencode/skills/``; what these tests prove is that skills written there are
picked up by the NEXUS runtime and reach the model without a restart.
"""

from __future__ import annotations

from pathlib import Path

from backend.contracts.skills import SkillStatus
from backend.core import skill_runtime

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ROOTS = (
    REPO_ROOT / "nexus-ide" / "skills",
    REPO_ROOT / ".opencode" / "skills",
)


def _on_disk_skills() -> set[str]:
    found: set[str] = set()
    for root in DEFAULT_ROOTS:
        if not root.is_dir():
            continue
        for entry in sorted(root.iterdir()):
            if entry.name.startswith("_"):
                continue
            manifest = entry / "SKILL.md"
            if not manifest.is_file():
                continue
            try:
                document = skill_runtime.parse_skill_markdown(
                    manifest.read_text(encoding="utf-8"), fallback_name=entry.name
                )
            except ValueError:
                continue
            if document.manifest.status is SkillStatus.ACTIVE:
                found.add(document.name)
    return found


def test_the_repository_really_has_active_skills() -> None:
    """Guards the tests below: an empty root would make them vacuous."""
    assert _on_disk_skills(), "no active SKILL.md found in the default roots"


def test_global_skills_are_discovered_without_a_project() -> None:
    names = {doc.name for doc in skill_runtime.discover_skills(None, active_only=True)}
    assert _on_disk_skills() <= names, _on_disk_skills() - names


def test_a_skill_written_by_hermes_is_discovered_and_delivered() -> None:
    """A skill authored by the Hermes workflow lives in .opencode/skills."""
    hermes_skills = set()
    opencode_root = REPO_ROOT / ".opencode" / "skills"
    if opencode_root.is_dir():
        for entry in sorted(opencode_root.iterdir()):
            if entry.name.startswith("_"):
                continue
            manifest = entry / "SKILL.md"
            if not manifest.is_file():
                continue
            try:
                document = skill_runtime.parse_skill_markdown(
                    manifest.read_text(encoding="utf-8"), fallback_name=entry.name
                )
            except ValueError:
                continue
            if document.manifest.status is SkillStatus.ACTIVE:
                hermes_skills.add(document.name)
    assert hermes_skills, "no active skill under .opencode/skills"

    # Every one of them is reachable with no project selected, and its body is
    # really read (not just its metadata).
    for name in sorted(hermes_skills):
        loaded = skill_runtime.load_skill_document(name, None, max_chars=4000)
        assert loaded.get("ok") is True, (name, loaded)
        assert loaded.get("path"), f"{name} has no file backing"
        assert len(str(loaded.get("content") or "")) > len(name)


def test_a_global_skill_is_selected_for_a_real_agent_without_a_project() -> None:
    from backend.agents.nexus_primary import NexusPrimaryAgent

    agent = NexusPrimaryAgent()
    agent.enable_memory = False
    # No explicit allowlist: the selector resolves the agent's real surface
    # (action surface plus the enabled registry), which is what a live run does.
    result = skill_runtime.select_skills_for_agent(
        "Audita este repositório de forma segura e só de leitura.",
        None,
        agent,
    )
    delivered = [entry["name"] for entry in result["skills"]]
    assert delivered, result
    assert result["context"], "a delivered skill must carry its body"
    assert "audit" in result["context"].casefold() or any(
        "audit" in name for name in delivered
    )
    # Every rejection must be a concrete, named cause — never a silent drop.
    for rejection in result["rejected"]:
        assert rejection["reason"], rejection
        assert rejection["name"], rejection


def test_a_new_skill_appears_without_a_restart(tmp_path, monkeypatch) -> None:
    """Same-process discovery: a freshly written SKILL.md is visible at once."""
    root = tmp_path / "skills"
    (root / "ephemeral-skill").mkdir(parents=True)
    (root / "ephemeral-skill" / "SKILL.md").write_text(
        "---\nname: ephemeral-skill\nstatus: draft\ndescription: skill de teste\n"
        "triggers:\n  - \"valida o efemero\"\n---\n\n## Workflow\n1. passo\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(root))

    # A draft is visible to management but never selected for a run.
    assert "ephemeral-skill" not in {
        doc.name for doc in skill_runtime.discover_skills(None, active_only=True)
    }
    assert "ephemeral-skill" in {
        doc.name for doc in skill_runtime.discover_skills(None)
    }

    skill_runtime._rewrite_skill_status(
        root / "ephemeral-skill" / "SKILL.md", SkillStatus.ACTIVE
    )
    assert "ephemeral-skill" in {
        doc.name for doc in skill_runtime.discover_skills(None, active_only=True)
    }

    result = skill_runtime.select_skills(
        "valida o efemero do projeto", None, available_tools={"read_file"}
    )
    assert [entry["name"] for entry in result["skills"]] == ["ephemeral-skill"]


def test_promotions_are_recorded_auditably(tmp_path, monkeypatch) -> None:
    from backend.core.skill_runtime import (
        _lifecycle_dir,
        _promotions_log_path,
        read_promotion_log,
    )

    monkeypatch.setenv("NEXUS_SKILLS_LIFECYCLE_DIR", str(tmp_path / "lifecycle"))
    assert read_promotion_log() == []
    assert _promotions_log_path().parent == _lifecycle_dir()

    skill_runtime._append_promotion_audit({"path": "x", "to": "active"})
    entries = read_promotion_log()
    assert len(entries) == 1
    assert entries[0]["to"] == "active"
    assert isinstance(_promotions_log_path().read_text(encoding="utf-8"), str)


def test_a_proposal_is_never_selected_before_promotion(tmp_path, monkeypatch) -> None:
    """The evolutionary writer only ever produces reviewable drafts."""
    from backend.evolution.skill_writer import SkillWriter

    destination = tmp_path / "proposed"
    SkillWriter(destination).write_proposals([
        {
            "name": "proposta evolutiva",
            "description": "Uma proposta automatica.",
            "steps": ["passo um", "passo dois"],
            "evidence": ["frequency=3"],
        }
    ])

    monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(tmp_path / "roots"))
    root = tmp_path / "roots"
    (root / "_proposed").mkdir(parents=True)
    for item in destination.iterdir():
        (root / "_proposed" / item.name).mkdir(parents=True, exist_ok=True)
        (root / "_proposed" / item.name / "SKILL.md").write_text(
            (item / "SKILL.md").read_text(encoding="utf-8"), encoding="utf-8"
        )

    proposals = [doc for doc in skill_runtime.discover_skills(None) if doc.source == "proposal"]
    assert proposals, "the writer produced no proposal"
    assert all(
        doc.manifest.status is SkillStatus.DRAFT for doc in proposals
    ), "a proposal must stay a draft until an explicit promotion"
