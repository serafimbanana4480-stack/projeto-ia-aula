"""Tests for backend.tools.skills_tools."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.tools import skills_tools
from backend.tools.skills_tools import list_skills, load_skill


@pytest.fixture
def skills_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "skills"
    (root / "alpha").mkdir(parents=True)
    (root / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: Primeira skill de teste\n---\n\n# Alpha\n\nPassos aqui.\n",
        encoding="utf-8",
    )
    (root / "beta").mkdir(parents=True)
    (root / "beta" / "SKILL.md").write_text(
        "# Beta\n\nSem front matter; descrição na primeira linha útil.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(root))
    return root


class TestListSkills:
    async def test_lists_names_and_first_description_line(self, skills_root: Path) -> None:
        result = await list_skills()
        names = [skill["name"] for skill in result["skills"]]
        assert names == ["alpha", "beta"]
        assert result["skills"][0]["description"] == "Primeira skill de teste"
        assert "primeira linha útil" in result["skills"][1]["description"]

    async def test_reports_the_scanned_roots(self, skills_root: Path) -> None:
        result = await list_skills()
        assert result["roots"] == [str(skills_root)]

    async def test_env_override_replaces_defaults(
        self, skills_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        second = skills_root.parent / "more-skills"
        (second / "gamma").mkdir(parents=True)
        (second / "gamma" / "SKILL.md").write_text("description: gamma\n", encoding="utf-8")
        monkeypatch.setenv("NEXUS_SKILLS_DIRS", os.pathsep.join([str(skills_root), str(second)]))
        result = await list_skills()
        names = [skill["name"] for skill in result["skills"]]
        assert names == ["alpha", "beta", "gamma"]

    async def test_empty_dir_yields_no_skills(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(empty))
        result = await list_skills()
        assert result["skills"] == []

    async def test_missing_dir_yields_no_skills(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NEXUS_SKILLS_DIRS", str(tmp_path / "nao-existe"))
        result = await list_skills()
        assert result["skills"] == []


class TestLoadSkill:
    async def test_loads_content_with_header(self, skills_root: Path) -> None:
        result = await load_skill("alpha")
        assert result["ok"] is True
        assert result["content"].startswith("### Skill: alpha\n\n")
        assert "Passos aqui." in result["content"]
        assert result["truncated"] is False

    async def test_case_insensitive_fallback(self, skills_root: Path) -> None:
        result = await load_skill("ALPHA")
        assert result["ok"] is True
        assert result["name"] == "alpha"

    async def test_unknown_skill_is_a_clear_error(self, skills_root: Path) -> None:
        result = await load_skill("nao-existe")
        assert result["ok"] is False
        assert "not found" in result["error"]
        assert "alpha" in result["error"] and "beta" in result["error"]

    async def test_empty_name_is_an_error(self, skills_root: Path) -> None:
        result = await load_skill("   ")
        assert result["ok"] is False
        assert "name" in result["error"]

    async def test_long_skill_is_truncated_to_about_4000_chars(
        self, skills_root: Path
    ) -> None:
        long_text = "linha longa " * 500 + "\n" + "x" * 8000
        (skills_root / "big").mkdir()
        (skills_root / "big" / "SKILL.md").write_text(long_text, encoding="utf-8")

        result = await load_skill("big")
        assert result["ok"] is True
        assert result["truncated"] is True
        assert len(result["content"]) <= 4000 + 100
        assert result["content"].endswith(skills_tools._TRUNCATION_NOTE)

    async def test_active_project_skill_is_discovered_loaded_and_built_locally(
        self, skills_root: Path, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        built = await skills_tools.build_skill(
            request="Quero uma skill para fazer auditorias completas de projetos Python",
            project_path=str(project),
        )

        assert built["ok"] is True
        assert Path(built["path"]).is_relative_to(project / ".opencode" / "skills")
        listing = await list_skills(project_path=str(project))
        assert any(item["name"] == "python-project-audit" for item in listing["skills"])
        loaded = await load_skill("python-project-audit", project_path=str(project))
        assert loaded["ok"] is True
        assert loaded["version"] == "1.0.0"

    async def test_request_derived_skill_is_written_as_a_draft(self, tmp_path: Path) -> None:
        """A skill authored by the agent must never self-activate: only ACTIVE
        skills are injected into the system prompt on the next turn."""
        project = tmp_path / "project"
        project.mkdir()

        result = await skills_tools.build_skill(
            request="Quero uma skill para fazer auditorias completas de projetos Python",
            project_path=str(project),
        )

        assert result["ok"] is True
        assert result["status"] == "draft"
        assert result["validation"]["status"] == "draft"
        written = Path(result["path"]).read_text(encoding="utf-8")
        assert "status: draft" in written
        assert "status: active" not in written

    async def test_trace_derived_skill_is_also_a_draft(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()

        result = await skills_tools.build_skill(
            request="Repetir verificacao depois de editar ficheiros",
            name="repeat-verify-flow",
            observed_steps=["read_file", "run_tests", "report"],
            evidence=["frequency=3", "confidence=0.8"],
            project_path=str(project),
        )

        assert result["ok"] is True
        assert result["status"] == "draft"

    async def test_builder_rejects_symlinked_project_skill_root(
        self, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        outside = tmp_path / "outside"
        project.mkdir()
        outside.mkdir()
        try:
            os.symlink(outside, project / ".opencode", target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires privileges on this Windows setup")

        result = await skills_tools.build_skill(
            request="Quero uma skill para fazer auditorias completas de projetos Python",
            project_path=str(project),
        )

        assert result["ok"] is False
        assert "symbolic link" in result["error"]
        assert list(outside.iterdir()) == []


class TestSymlinkProtection:
    async def test_symlinked_skill_dir_is_ignored(self, skills_root: Path) -> None:
        outside = skills_root.parent / "fora"
        (outside / "secreta").mkdir(parents=True)
        (outside / "secreta" / "SKILL.md").write_text("segredo\n", encoding="utf-8")
        link = skills_root / "link"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation requires privileges on this Windows setup")

        result = await list_skills()
        names = [skill["name"] for skill in result["skills"]]
        assert "link" not in names
        assert "alpha" in names
