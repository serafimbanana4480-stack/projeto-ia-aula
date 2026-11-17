"""Tests for SkillWriter (proposed SKILL.md rendering) + engine wiring."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.evolution.engine import EvolutionConfig, EvolutionEngine
from backend.evolution.skill_writer import MAX_FILE_LINES, SkillProposal, SkillWriter


@pytest.fixture
def proposals_dir(tmp_path: Path) -> Path:
    return tmp_path / ".opencode" / "skills" / "_proposed"


@pytest.fixture
def writer(proposals_dir: Path) -> SkillWriter:
    return SkillWriter(base_dir=proposals_dir)


def _candidate() -> dict:
    return {
        "name": "Read File Write File",
        "description": 'Automated sequence of 3 actions: read -> "edit" -> run_tests',
        "action_sequence": ["read", "write", "run_tests"],
        "frequency": 5,
        "confidence": 1.0,
        "example_tasks": ["t1", "t2"],
        "component_kinds": ["coder"],
    }


class TestKebabSlug:
    def test_slugify(self) -> None:
        from backend.evolution.skill_writer import _kebab

        assert _kebab("Read File Write") == "read-file-write"
        assert _kebab("skill_read_edit") == "skill-read-edit"
        assert _kebab("  Weird__Name!! ") == "weird-name"
        assert _kebab("") == "discovered-skill"


class TestWriteProposal:
    def test_proposal_reaches_review_gate_without_automatic_activation(
        self, proposals_dir: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from backend.core.skill_runtime import (
            list_skill_summaries,
            load_skill_document,
            promote_skill,
            select_skills,
        )

        monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(proposals_dir.parent))
        monkeypatch.setenv("NEXUS_SKILLS_LIFECYCLE_DIR", str(tmp_path / "lifecycle"))
        monkeypatch.delenv("NEXUS_SKILLS_AUTO_PROMOTE", raising=False)
        path = SkillWriter(base_dir=proposals_dir).write_proposal(_candidate())
        summaries = list_skill_summaries()
        proposal = next(item for item in summaries if item["path"] == str(path.resolve()))
        assert proposal["status"] == "draft"
        assert proposal["source"] == "proposal"
        assert select_skills("read file write file", include_memory=False)["skills"] == []
        assert not load_skill_document(proposal["skill_id"])["ok"]
        result = promote_skill(
            proposal["skill_id"], actor="tester", reason="review", approved_by="operator"
        )
        assert not result["ok"]
        assert "promotion gate rejected" in result["error"]
        assert "status: draft" in path.read_text(encoding="utf-8")

        # A reviewer must complete the procedural contract before approval.
        path.write_text(
            "---\nname: read-file-workflow\ndescription: read file workflow\n"
            "status: draft\ntriggers: [read file workflow, verify file workflow]\n---\n"
            "# Read file workflow\n\n## Workflow\n\n1. Read the file.\n\n"
            "## Rules\n\n- Keep evidence.\n\n## Verification\n\n"
            "- Check the result.\n\n## Example\n\nRead file workflow.\n",
            encoding="utf-8",
        )
        refused = promote_skill(proposal["skill_id"], actor="tester", reason="review")
        assert not refused["ok"]
        assert "approval" in refused["error"]
        with monkeypatch.context() as isolated:
            isolated.setattr("backend.core.skill_runtime._append_promotion_audit", lambda _: None)
            unaudited = promote_skill(
                proposal["skill_id"], actor="tester", reason="reviewed", approved_by="operator"
            )
        assert not unaudited["ok"]
        assert not load_skill_document(proposal["skill_id"])["ok"]
        assert next(item for item in list_skill_summaries() if item["path"] == str(path.resolve()))["status"] == "draft"
        promoted = promote_skill(
            proposal["skill_id"], actor="tester", reason="reviewed", approved_by="operator"
        )
        assert promoted["ok"]
        assert load_skill_document(proposal["skill_id"])["ok"]
        selected = select_skills("read file workflow", include_memory=False)
        assert any(item["name"] == "read-file-workflow" for item in selected["skills"])
        path.write_text(path.read_text(encoding="utf-8") + "\nchanged after approval\n", encoding="utf-8")
        assert not load_skill_document(proposal["skill_id"])["ok"]
        assert select_skills("read file workflow", include_memory=False)["skills"] == []
        assert not promote_skill(proposal["skill_id"], actor="tester", reason="review again")["ok"]
        assert promote_skill(
            proposal["skill_id"], actor="tester", reason="review again", approved_by="operator"
        )["ok"]
        assert load_skill_document(proposal["skill_id"])["ok"]

    def test_repeated_proposals_remain_separately_reviewable(
        self, proposals_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.core.skill_runtime import list_skill_summaries

        monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(proposals_dir.parent))
        writer = SkillWriter()
        paths = {str(writer.write_proposal(_candidate()).resolve()) for _ in range(2)}
        proposals = [item for item in list_skill_summaries() if item["path"] in paths]
        assert len(proposals) == 2
        assert len({item["skill_id"] for item in proposals}) == 2

    def test_windows_unsafe_chars_removed(self, writer: SkillWriter) -> None:
        path = writer.write_proposal({"name": 'a<b>:"c"', "description": "d"})
        assert path.parent.name == "a-b-c"
        assert path.exists()

    def test_writes_skill_md(self, writer: SkillWriter, proposals_dir: Path) -> None:
        path = writer.write_proposal(_candidate())
        expected = proposals_dir / "read-file-write-file" / "SKILL.md"
        assert path == expected
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        assert lines[0] == "---"
        assert any(line.startswith('name: "') for line in lines[:4])
        assert any(line.startswith('description: "') for line in lines[:4])
        from backend.core.skill_runtime import parse_skill_markdown

        assert parse_skill_markdown(content).manifest.status.value == "draft"
        assert "1. read" in lines
        assert "2. write" in lines
        assert "3. run_tests" in lines
        assert any("frequency=5 confidence=1.0" in line for line in lines)
        assert any("tasks=t1, t2" in line for line in lines)

    def test_never_overwrites_versions_dirs(
        self, writer: SkillWriter, proposals_dir: Path
    ) -> None:
        first = writer.write_proposal(_candidate())
        second = writer.write_proposal(_candidate())
        third = writer.write_proposal(_candidate())
        assert first.parent.name == "read-file-write-file"
        assert second.parent.name == "read-file-write-file-v2"
        assert third.parent.name == "read-file-write-file-v3"
        contents = {p.read_text(encoding="utf-8").count("## Rules") for p in (first, second, third)}
        assert contents == {1}

    def test_accepts_skill_proposal_instance(self, writer: SkillWriter) -> None:
        proposal = SkillProposal(name="Manual Skill", description="d", steps=["s1"], evidence=["ev"])
        path = writer.write_proposal(proposal)
        assert path.parent.name == "manual-skill"

    def test_write_text_uses_lf_newlines(self, writer: SkillWriter) -> None:
        raw = (writer.write_proposal(_candidate())).read_bytes()
        assert b"\r\n" not in raw


class TestRender:
    def test_line_cap_with_many_steps(self, writer: SkillWriter) -> None:
        candidate = {
            "name": "big",
            "description": "many steps",
            "action_sequence": [f"step_{i}" for i in range(200)],
            "example_tasks": [f"t{i}" for i in range(20)],
        }
        path = writer.write_proposal(candidate)
        lines = path.read_text(encoding="utf-8").splitlines()
        assert len(lines) <= MAX_FILE_LINES
        assert any("more steps omitted" in line for line in lines)

    def test_empty_steps_placeholder(self, writer: SkillWriter) -> None:
        content = writer.render(SkillProposal(name="x", description="y"))
        assert "1. (no steps recorded)" in content.splitlines()

    def test_description_quotes_escaped_and_single_line(self, writer: SkillWriter) -> None:
        content = writer.render(SkillProposal(name="x", description='has "quotes"\nand newline'))
        frontmatter = content.splitlines()[2]
        assert '\n' not in frontmatter
        assert '\\"quotes\\"' in frontmatter


class TestFromDiscovered:
    def test_maps_discovery_dict(self) -> None:
        proposal = SkillProposal.from_discovered(_candidate())
        assert proposal.steps == ["read", "write", "run_tests"]
        assert proposal.evidence[0] == "source=NEXUS SkillDiscovery"
        assert any("components=coder" in e for e in proposal.evidence)


class TestEngineWiring:
    @pytest.fixture
    def temp_engine(self, tmp_path: Path) -> EvolutionEngine:
        from backend.evolution.arena import Arena
        from backend.evolution.failure_miner import FailureMiner
        from backend.evolution.registry import ChampionRegistry
        from backend.evolution.regression_guard import RegressionGuard
        from backend.evolution.rollback import RollbackManager
        from backend.experience.lake import TraceLake

        registry = ChampionRegistry(db_path=tmp_path / "test_evolution.db")
        lake = TraceLake(tmp_path / "test_trace_lake.db")
        miner = FailureMiner(lake=lake, db_path=tmp_path / "test_evolution.db")
        return EvolutionEngine(
            registry=registry,
            arena=Arena(registry, allow_simulation=True),
            failure_miner=miner,
            guard=RegressionGuard(),
            rollback=RollbackManager(registry),
        )

    def test_config_flag_defaults_off(self) -> None:
        assert EvolutionConfig().write_skill_proposals is False

    def test_evolve_skips_proposals_by_default(
        self, temp_engine: EvolutionEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[bool] = []
        monkeypatch.setattr(
            EvolutionEngine, "_propose_discovered_skills", lambda self: calls.append(True) or []
        )
        temp_engine.evolve(EvolutionConfig(max_cycles=1))
        assert calls == []

    def test_evolve_calls_proposer_when_enabled(
        self, temp_engine: EvolutionEngine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[bool] = []

        def fake(self: EvolutionEngine) -> list[Path]:
            calls.append(True)
            return []

        monkeypatch.setattr(EvolutionEngine, "_propose_discovered_skills", fake)
        temp_engine.evolve(EvolutionConfig(max_cycles=1, write_skill_proposals=True))
        assert calls == [True]

    def test_propose_end_to_end_with_fake_discovery(
        self, temp_engine: EvolutionEngine, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        class FakeDiscovery:
            def __init__(self, *args: object, **kwargs: object) -> None:
                pass

            def discover(self, *args: object, **kwargs: object) -> list[dict]:
                return [_candidate()]

        monkeypatch.setattr(
            "backend.evolution.skill_discovery.SkillDiscovery", FakeDiscovery
        )
        out_dir = tmp_path / "proposals"
        paths = temp_engine._propose_discovered_skills(skills_dir=out_dir)
        assert len(paths) == 1
        assert paths[0].exists()
        assert paths[0].name == "SKILL.md"
