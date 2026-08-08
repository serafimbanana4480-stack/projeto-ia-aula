"""Regression tests for compact project-scoped bootstrap memory."""

from __future__ import annotations

from backend.knowledge.project_memory import (
    ensure_project_memory,
    read_project_memory,
    record_verified_session,
)


def test_project_memory_is_created_and_bounded(tmp_path) -> None:
    (tmp_path / "backend").mkdir()
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")

    path = ensure_project_memory(tmp_path)
    assert path == tmp_path / ".nexus" / "project-memory.md"
    assert "Arquitetura inicial" in path.read_text(encoding="utf-8")

    record_verified_session(
        tmp_path,
        session_id="s1",
        status="completed",
        topic="memory architecture",
        evidence="tests=passed",
    )
    content = read_project_memory(tmp_path)
    assert "`s1`" in content
    assert "tests=passed" in content
    assert len(content) <= 12_000
