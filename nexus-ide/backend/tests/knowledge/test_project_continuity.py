"""Independent-session continuity, recovery, and freshness contracts."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from backend.knowledge.memory import Memory
from backend.knowledge.project_continuity import (
    MAX_CONTEXT_CHARS,
    ProjectContinuityStore,
    capture_project_snapshot,
)


def test_continuity_survives_new_store_after_failure_and_model_switch(tmp_path: Path) -> None:
    source = tmp_path / "src" / "cache.py"
    source.parent.mkdir()
    source.write_text("def get():\n    return None\n", encoding="utf-8")

    first_session = ProjectContinuityStore(tmp_path)
    first_snapshot = capture_project_snapshot(tmp_path)
    first_session.begin_run(
        session_id="session-a",
        run_id="run-a",
        objective="Implementar retries no cache",
        snapshot=first_snapshot,
        model="provider/model-a",
        now=1_000_000,
    )
    first_session.record_tool_event(
        session_id="session-a",
        run_id="run-a",
        tool_name="edit_file",
        phase="call",
        args={"path": "src/cache.py", "content": "sensitive payload must not be persisted"},
    )
    source.write_text("def get():\n    return retry()\n", encoding="utf-8")
    first_session.record_tool_event(
        session_id="session-a",
        run_id="run-a",
        tool_name="edit_file",
        phase="result",
        ok=True,
        result={"ok": True, "summary": "ficheiro alterado"},
    )
    first_session.record_tool_event(
        session_id="session-a",
        run_id="run-a",
        tool_name="run_tests",
        phase="call",
    )
    first_session.record_tool_event(
        session_id="session-a",
        run_id="run-a",
        tool_name="run_tests",
        phase="result",
        ok=False,
        error="timeout nos testes de cache",
    )
    first_session.finish_run(
        session_id="session-a",
        run_id="run-a",
        status="failed",
        verification={"ran": True, "ok": False, "summary": "timeout nos testes de cache"},
        changed_files=["src/cache.py"],
        model="provider/model-a",
        now=1_000_020,
    )
    first_session.record_decision(
        decision_key="cache-retry-policy",
        decision="Retries use bounded exponential backoff",
        rationale="Avoid an unbounded request loop",
        impact="Adds latency on transient failures but caps total attempts",
        session_id="session-a",
        run_id="run-a",
        evidence_paths=["src/cache.py"],
    )

    # A fresh object and a different provider/model represent a separate app
    # session with no chat history in memory.
    resumed_session = ProjectContinuityStore(tmp_path)
    resumed_session.begin_run(
        session_id="session-b",
        run_id="run-b",
        objective="Continua a correção do cache depois da falha",
        snapshot=capture_project_snapshot(tmp_path),
        model="local/model-b",
        now=1_000_020 + 86_400,
    )
    context = resumed_session.bootstrap_context(
        "cache retries timeout",
        snapshot=capture_project_snapshot(tmp_path),
        now=1_000_020 + 86_400,
    )
    empty_query_context = resumed_session.bootstrap_context(
        "", snapshot=capture_project_snapshot(tmp_path)
    )

    assert "timeout nos testes de cache" in context
    assert "não repetir" in context
    assert "Retries use bounded exponential backoff" in context
    assert "BLOQUEIOS" in context
    assert "verificado anteriormente" not in context
    assert "sem conclusão de código validada" in context
    assert "local/model-b" in empty_query_context
    assert len(context) <= MAX_CONTEXT_CHARS
    assert "sensitive payload must not be persisted" not in (tmp_path / ".nexus" / "project-state.md").read_text(encoding="utf-8")


def test_verified_change_becomes_stale_when_real_snapshot_changes(tmp_path: Path) -> None:
    source = tmp_path / "module.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    store = ProjectContinuityStore(tmp_path)
    before = capture_project_snapshot(tmp_path)
    store.begin_run(
        session_id="session-1",
        run_id="run-verified",
        objective="Atualizar o valor do módulo",
        snapshot=before,
        model="model-one",
    )
    store.record_tool_event(
        session_id="session-1",
        run_id="run-verified",
        tool_name="write_file",
        phase="call",
        args={"path": "module.py"},
    )
    source.write_text("VALUE = 200\n", encoding="utf-8")
    store.record_tool_event(
        session_id="session-1",
        run_id="run-verified",
        tool_name="write_file",
        phase="result",
        ok=True,
        result={"ok": True},
    )
    verified_snapshot = capture_project_snapshot(tmp_path)
    task = store.finish_run(
        session_id="session-1",
        run_id="run-verified",
        status="completed",
        verification={"ran": True, "ok": True, "summary": "focused test passed"},
        changed_files=["module.py"],
        snapshot=verified_snapshot,
    )
    assert task and task["status"] == "verified"

    current = store.bootstrap_context("alterar o módulo", snapshot=verified_snapshot)
    assert "verificado:" in current

    source.write_text("VALUE = 300\n", encoding="utf-8")
    changed_snapshot = capture_project_snapshot(tmp_path)
    stale = store.bootstrap_context("alterar o módulo", snapshot=changed_snapshot)
    assert "checkout mudou" in stale
    assert "O checkout mudou desde a última validação" in stale


def test_new_decision_supersedes_old_and_changed_evidence_requires_review(tmp_path: Path) -> None:
    source = tmp_path / "backend" / "api.py"
    source.parent.mkdir()
    source.write_text("ROUTE = '/v1'\n", encoding="utf-8")
    store = ProjectContinuityStore(tmp_path)
    store.record_decision(
        decision_key="public-api-version",
        decision="The public API uses v1",
        rationale="Existing clients depend on it",
        impact="New routes follow the current version",
        evidence_paths=["backend/api.py"],
    )
    store.record_decision(
        decision_key="public-api-version",
        decision="The public API uses v2",
        rationale="The migration was completed",
        impact="Clients must use the new route prefix",
        evidence_paths=["backend/api.py"],
    )

    with sqlite3.connect(store.db_path) as conn:
        rows = conn.execute(
            "SELECT decision, status FROM continuity_decisions ORDER BY created_at"
        ).fetchall()
    assert rows == [
        ("The public API uses v1", "superseded"),
        ("The public API uses v2", "active"),
    ]
    current = store.bootstrap_context("public API version", snapshot=capture_project_snapshot(tmp_path))
    assert "The public API uses v2" in current
    assert "The public API uses v1" not in current

    source.write_text("ROUTE = '/v3'\n", encoding="utf-8")
    reviewed = store.bootstrap_context("public API version", snapshot=capture_project_snapshot(tmp_path))
    assert "[rever;" in reviewed


def test_old_incomplete_run_is_recovered_without_replaying_full_history(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("project", encoding="utf-8")
    first = ProjectContinuityStore(tmp_path)
    first.begin_run(
        session_id="old-session",
        run_id="abandoned-run",
        objective="Implementar a pesquisa do projeto",
        snapshot=capture_project_snapshot(tmp_path),
        model="model-before-switch",
        now=1_000,
    )

    # New database object, empty prompt context and a later session recreate
    # a compact brief from SQLite alone after an unexpected process shutdown.
    later = ProjectContinuityStore(tmp_path)
    later.begin_run(
        session_id="new-session",
        run_id="resumed-run",
        objective="Continua a tarefa interrompida",
        snapshot=capture_project_snapshot(tmp_path),
        model="model-after-switch",
        now=1_000 + 3 * 86_400,
    )
    context = later.bootstrap_context(
        "", snapshot=capture_project_snapshot(tmp_path), now=1_000 + 3 * 86_400
    )

    assert "Implementar a pesquisa do projeto" in context
    assert "interrupted:" in context
    assert "model-after-switch" in context
    assert len(context) <= MAX_CONTEXT_CHARS


def test_project_memory_tool_updates_decisions_and_explicit_project_goal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.tools import memory_tools

    class MemorySink:
        async def store(self, content: str, **kwargs: Any) -> Memory:
            return Memory(content=content, memory_type=kwargs["memory_type"])

    monkeypatch.setattr(memory_tools, "get_memory_store", lambda: MemorySink())

    decision = asyncio.run(
        memory_tools.store_memory(
            content="The worker owns durable job retries",
            memory_type="project",
            project_path=str(tmp_path),
            decision_key="job-retry-owner",
            rationale="The worker already controls job lifecycle",
            impact="Retry policy stays consistent across APIs",
        )
    )
    goal = asyncio.run(
        memory_tools.store_memory(
            content="Keep NEXUS local-first and recoverable",
            memory_type="project",
            project_path=str(tmp_path),
            project_goal=True,
        )
    )

    context = ProjectContinuityStore(tmp_path).bootstrap_context("job retries")
    assert decision["decision_recorded"] is True
    assert goal["project_goal_recorded"] is True
    assert "Keep NEXUS local-first and recoverable" in context
    assert "The worker owns durable job retries" in context
