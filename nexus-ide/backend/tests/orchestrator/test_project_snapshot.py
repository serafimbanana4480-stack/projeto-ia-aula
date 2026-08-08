"""Focused contract tests for deterministic Mission Control snapshots."""

from __future__ import annotations

import json
from pathlib import Path

from backend.config.settings import ProjectContextError, resolve_mission_project
from backend.orchestrator.mission_control import ProjectIntelligence


def test_snapshot_captures_project_context(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'fixture'\n", encoding="utf-8"
    )
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"test": "pytest", "build": "vite build"}}),
        encoding="utf-8",
    )
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").write_text(
        json.dumps({"scripts": {"lint": "eslint ."}}), encoding="utf-8"
    )
    (tmp_path / "test_example.py").write_text("def test_example(): pass\n", encoding="utf-8")
    (tmp_path / "runtime.log").write_text("ERROR fixture failure\n", encoding="utf-8")

    snapshot = ProjectIntelligence(tmp_path).scan()

    assert snapshot.absolute_path == str(tmp_path.resolve())
    assert snapshot.root == snapshot.absolute_path
    assert snapshot.commands["test"]
    assert snapshot.commands["build"] == ["npm run build"]
    assert snapshot.commands["lint"] == ["cd frontend && npm run lint"]
    assert snapshot.disk and snapshot.disk["total_bytes"] > 0
    assert snapshot.recent_errors and "ERROR fixture failure" in snapshot.recent_errors[0]
    assert {fact.classification for fact in snapshot.facts} >= {
        "measured", "inferred", "not_validated"
    }
    json.dumps(snapshot.to_dict())


def test_failed_manifest_probe_is_unknown(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text("[]", encoding="utf-8")

    snapshot = ProjectIntelligence(tmp_path).scan()

    assert "commands from package.json" in snapshot.unknowns
    command_fact = next(f for f in snapshot.facts if f.source == "manifest parsing")
    assert command_fact.classification == "unknown"


def test_missing_project_preserves_unknown_provenance(tmp_path: Path) -> None:
    missing = tmp_path / "missing"

    snapshot = ProjectIntelligence(missing).scan()

    assert snapshot.absolute_path == str(missing.resolve())
    assert "filesystem scan" in snapshot.unknowns
    assert any(f.classification == "unknown" for f in snapshot.facts)
    assert snapshot.findings and snapshot.findings[0].id == "scan-root-missing"


def test_mission_project_resolver_rejects_non_strings(tmp_path: Path) -> None:
    for project_path, session_project in ((None, str(tmp_path)), (str(tmp_path), 42)):
        try:
            resolve_mission_project(project_path, session_project)  # type: ignore[arg-type]
        except ProjectContextError as exc:
            assert exc.code == "BLOCKED_PROJECT_CONTEXT"
        else:
            raise AssertionError("non-string mission context was accepted")
