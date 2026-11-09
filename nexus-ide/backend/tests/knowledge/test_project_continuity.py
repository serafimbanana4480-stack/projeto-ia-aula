"""Independent-session continuity, recovery, and freshness contracts."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from backend.knowledge.memory import Memory
from backend.knowledge.project_continuity import (
    MAX_CONTEXT_CHARS,
    ProjectContinuityStore,
    capture_project_snapshot,
    load_project_continuity,
)


def _seed_legacy_continuity_state(
    store: ProjectContinuityStore, state: dict[str, Any]
) -> str:
    raw_state = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    with sqlite3.connect(store.db_path) as conn:
        conn.execute(
            """INSERT INTO continuity_state(project_key, state_json, updated_at)
               VALUES (?, ?, ?) ON CONFLICT(project_key) DO UPDATE SET
               state_json=excluded.state_json, updated_at=excluded.updated_at""",
            (store.project_key, raw_state, 1.0),
        )
    return raw_state


def _load_task(
    store: ProjectContinuityStore, *, session_id: str, run_id: str
) -> dict[str, Any] | None:
    conn = store._connect()
    try:
        return store._get_task(conn, session_id=session_id, run_id=run_id)
    finally:
        conn.close()


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


def test_continuity_is_private_per_owner_while_project_decisions_are_shared(
    tmp_path: Path,
) -> None:
    alice = ProjectContinuityStore(tmp_path, owner_id="alice")
    alice.begin_run(
        session_id="alice-session-1",
        run_id="alice-run-1",
        objective="Investigar o endpoint privado de autenticação",
        model="alice/private-model",
    )
    alice.record_tool_event(
        session_id="alice-session-1",
        run_id="alice-run-1",
        tool_name="run_tests",
        phase="result",
        ok=False,
        error="detalhe privado da falha de autenticação",
    )
    alice.finish_run(
        session_id="alice-session-1",
        run_id="alice-run-1",
        status="failed",
        error="detalhe privado da falha de autenticação",
        model="alice/private-model",
    )
    alice.record_decision(
        decision_key="shared-session-storage",
        decision="Sessões de projeto guardam estado recuperável",
        rationale="A retoma precisa sobreviver a reinícios",
        impact="O trabalho pode continuar depois de uma interrupção",
        session_id="alice-session-1",
        run_id="alice-run-1",
    )

    alice_next = ProjectContinuityStore(tmp_path, owner_id="alice")
    alice_next.begin_run(
        session_id="alice-session-2",
        run_id="alice-run-2",
        objective="Continua a investigação do endpoint privado de autenticação",
        model="alice/new-model",
    )
    alice_context = alice_next.bootstrap_context(
        "autenticação endpoint falha", session_id="alice-session-2"
    )

    bob = ProjectContinuityStore(tmp_path, owner_id="bob")
    bob.begin_run(
        session_id="bob-session-1",
        run_id="bob-run-1",
        objective="Atualizar a documentação pública",
        model="bob/public-model",
    )
    bob_context = bob.bootstrap_context(
        "documentação pública", session_id="bob-session-1"
    )

    assert "endpoint privado de autenticação" in alice_context
    assert "detalhe privado da falha de autenticação" in alice_context
    assert "alice/private-model" not in bob_context
    assert "endpoint privado de autenticação" not in bob_context
    assert "detalhe privado da falha de autenticação" not in bob_context
    assert "Sessões de projeto guardam estado recuperável" in bob_context

    alice_brief = (tmp_path / ".nexus" / f"project-state-{alice.owner_key}.md").read_text(
        encoding="utf-8"
    )
    bob_brief = (tmp_path / ".nexus" / f"project-state-{bob.owner_key}.md").read_text(
        encoding="utf-8"
    )
    assert "endpoint privado de autenticação" in alice_brief
    assert "endpoint privado de autenticação" not in bob_brief
    assert not (tmp_path / ".nexus" / "project-state.md").exists()


def test_project_context_loader_includes_the_new_run_and_selected_model(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("project", encoding="utf-8")

    _snapshot, context = load_project_continuity(
        str(tmp_path),
        query="Implementar uma correção",
        session_id="session-current",
        run_id="run-current",
        model="provider/model-current",
    )

    assert "TAREFA ATUAL: in_progress — Implementar uma correção" in context
    assert "MODELO DA TAREFA: provider/model-current" in context


def test_legacy_project_task_is_migrated_into_resumable_project_history(
    tmp_path: Path,
) -> None:
    store = ProjectContinuityStore(tmp_path)
    legacy_task = {
        "run_id": "legacy-run",
        "session_id": "legacy-session",
        "objective": "Continuar o parser depois de uma falha",
        "status": "interrupted",
        "started_at": 10.0,
        "updated_at": 20.0,
        "model": "old/model",
        "actions": [],
    }
    legacy_state = {
        "schema_version": 1,
        "project_path": str(tmp_path),
        "project_goal": "",
        "current_task": legacy_task,
        "completed": [],
        "blocked": [],
        "recent_tasks": [],
        "last_session": {"session_id": "legacy-session", "run_id": "legacy-run"},
    }
    _seed_legacy_continuity_state(store, legacy_state)

    migrated_store = ProjectContinuityStore(tmp_path)
    context = migrated_store.bootstrap_context("parser", session_id="new-session")

    assert "Continuar o parser depois de uma falha" in context
    assert "interrupted" in context


def test_legacy_task_migration_is_idempotent_and_resume_keeps_full_snapshot(
    tmp_path: Path,
) -> None:
    owner_store = ProjectContinuityStore(tmp_path, owner_id="alice")
    before_snapshot = {
        "exists": True,
        "fingerprint": "legacy-fingerprint",
        "file_states": {"src/parser.py": "sha256:full-before-state"},
        "tree": ["src/parser.py", "src/tokenizer.py"],
        "metadata": {"capture": "complete", "nested": [1, 2, 3]},
    }
    legacy_task = {
        "run_id": "legacy-resume-run",
        "session_id": "legacy-resume-session",
        "owner_key": owner_store.owner_key,
        "objective": "Implementar o parser sem perder o checkpoint",
        "status": "interrupted",
        "started_at": 10.0,
        "updated_at": 20.0,
        "model": "old/model",
        "before_snapshot": before_snapshot,
        "actions": [{"tool": "edit_file", "status": "started", "paths": ["src/parser.py"]}],
    }
    _seed_legacy_continuity_state(
        owner_store,
        {
            "schema_version": 2,
            "project_path": str(tmp_path),
            "project_goal": "",
            "current_task": {
                **legacy_task,
                "status": "in_progress",
                "updated_at": 15.0,
                "actions": [{"tool": "edit_file", "status": "started", "paths": ["old.py"]}],
            },
            "session_tasks": {"legacy-resume-session": {"legacy-resume-run": legacy_task}},
            "completed": [],
            "blocked": [],
            "recent_tasks": [],
            "last_session": {},
        },
    )

    migrated = ProjectContinuityStore(tmp_path, owner_id="alice")
    with sqlite3.connect(migrated.db_path) as conn:
        first_rows = conn.execute(
            "SELECT owner_key, session_id, run_id, task_json FROM continuity_tasks"
        ).fetchall()
        state_json = conn.execute(
            "SELECT state_json FROM continuity_state WHERE project_key=?",
            (migrated.project_key,),
        ).fetchone()[0]
        projection_rows = conn.execute(
            "SELECT projection_json FROM continuity_task_legacy_projections"
        ).fetchall()
    assert len(first_rows) == 1
    assert first_rows[0][:3] == (
        migrated.owner_key,
        "legacy-resume-session",
        "legacy-resume-run",
    )
    assert json.loads(first_rows[0][3]) == legacy_task
    assert len(projection_rows) == 1
    assert json.loads(projection_rows[0][0]) == {
        **legacy_task,
        "status": "in_progress",
        "updated_at": 15.0,
        "actions": [{"tool": "edit_file", "status": "started", "paths": ["old.py"]}],
    }
    assert "session_tasks" not in json.loads(state_json)

    # Reopening simulates a process restart; a repeated migration is a no-op.
    restarted = ProjectContinuityStore(tmp_path, owner_id="alice")
    with sqlite3.connect(restarted.db_path) as conn:
        repeated_rows = conn.execute(
            "SELECT owner_key, session_id, run_id, task_json FROM continuity_tasks"
        ).fetchall()
        repeated_projections = conn.execute(
            "SELECT projection_json FROM continuity_task_legacy_projections"
        ).fetchall()
    assert repeated_rows == first_rows
    assert repeated_projections == projection_rows

    restarted.begin_run(
        session_id="new-resume-session",
        run_id="new-resume-run",
        objective="Continua o parser depois do reinício",
        snapshot={"exists": True, "fingerprint": "new-checkout"},
        model="new/model",
        now=30.0,
    )
    resumed_task = _load_task(
        restarted, session_id="new-resume-session", run_id="new-resume-run"
    )
    assert resumed_task is not None
    assert resumed_task["resume_from_run_id"] == "legacy-resume-run"
    assert resumed_task["resume_from_session_id"] == "legacy-resume-session"
    with sqlite3.connect(restarted.db_path) as conn:
        archived_payload = conn.execute(
            """SELECT task_json FROM continuity_tasks
               WHERE project_key=? AND owner_key=? AND session_id=? AND run_id=?""",
            (
                restarted.project_key,
                restarted.owner_key,
                "legacy-resume-session",
                "legacy-resume-run",
            ),
        ).fetchone()[0]
    assert json.loads(archived_payload) == legacy_task
    assert json.loads(archived_payload)["before_snapshot"] == before_snapshot

    restarted.record_tool_event(
        session_id="new-resume-session",
        run_id="new-resume-run",
        tool_name="run_tests",
        phase="result",
        ok=True,
        result={"ok": True, "summary": "parser tests passed"},
    )
    updated = _load_task(
        restarted, session_id="new-resume-session", run_id="new-resume-run"
    )
    assert updated is not None
    assert updated["actions"][0]["tool"] == "run_tests"
    assert updated["actions"][0]["status"] == "completed"


def test_failed_legacy_task_migration_rolls_back_without_losing_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = ProjectContinuityStore(tmp_path, owner_id="alice")
    legacy_task = {
        "run_id": "rollback-run",
        "session_id": "rollback-session",
        "owner_key": store.owner_key,
        "objective": "Keep this complete checkpoint",
        "status": "interrupted",
        "started_at": 10.0,
        "updated_at": 20.0,
        "before_snapshot": {"file_states": {"module.py": "sha256:unchanged"}},
    }
    original_state = {
        "schema_version": 2,
        "project_path": str(tmp_path),
        "project_goal": "",
        "current_task": None,
        "session_tasks": {"rollback-session": {"rollback-run": legacy_task}},
        "completed": [],
        "blocked": [],
        "recent_tasks": [],
        "last_session": {},
    }
    raw_state = _seed_legacy_continuity_state(store, original_state)
    original_copy = ProjectContinuityStore._persist_and_verify_legacy_tasks

    def fail_after_copy(
        self: ProjectContinuityStore,
        conn: sqlite3.Connection,
        records: list[dict[str, Any]],
        *,
        legacy_projection: dict[str, Any] | None = None,
    ) -> None:
        original_copy(self, conn, records, legacy_projection=legacy_projection)
        raise RuntimeError("simulated migration interruption")

    with monkeypatch.context() as patch_context:
        patch_context.setattr(ProjectContinuityStore, "_persist_and_verify_legacy_tasks", fail_after_copy)
        with pytest.raises(RuntimeError, match="simulated migration interruption"):
            ProjectContinuityStore(tmp_path, owner_id="alice")

    with sqlite3.connect(store.db_path) as conn:
        stored_state = conn.execute(
            "SELECT state_json FROM continuity_state WHERE project_key=?",
            (store.project_key,),
        ).fetchone()[0]
        task_count = conn.execute(
            "SELECT COUNT(*) FROM continuity_tasks WHERE project_key=?",
            (store.project_key,),
        ).fetchone()[0]
        projection_count = conn.execute(
            "SELECT COUNT(*) FROM continuity_task_legacy_projections WHERE project_key=?",
            (store.project_key,),
        ).fetchone()[0]
    assert stored_state == raw_state
    assert task_count == 0
    assert projection_count == 0

    recovered = ProjectContinuityStore(tmp_path, owner_id="alice")
    preserved = _load_task(
        recovered, session_id="rollback-session", run_id="rollback-run"
    )
    assert preserved == legacy_task


def test_continuity_task_table_keeps_same_run_isolated_by_owner(tmp_path: Path) -> None:
    alice = ProjectContinuityStore(tmp_path, owner_id="alice")
    bob = ProjectContinuityStore(tmp_path, owner_id="bob")
    alice.begin_run(
        session_id="shared-session",
        run_id="shared-run",
        objective="Alice private task",
        model="alice/model",
    )
    bob.begin_run(
        session_id="shared-session",
        run_id="shared-run",
        objective="Bob private task",
        model="bob/model",
    )
    alice.begin_run(
        session_id="alice-legacy-session",
        run_id="alice-legacy-run",
        objective="Alice legacy task",
        model="alice/model",
    )
    with sqlite3.connect(alice.db_path) as conn:
        conn.executemany(
            """INSERT INTO continuity_events
               (event_id, project_key, session_id, run_id, owner_key, event_type,
                status, content, payload_json, created_at)
               VALUES (?, ?, ?, ?, '', 'failure', 'failed', ?, '{}', ?)""",
            [
                (
                    "ambiguous-legacy-event",
                    alice.project_key,
                    "shared-session",
                    "shared-run",
                    "ambiguous legacy private diagnostic",
                    10.0,
                ),
                (
                    "alice-only-legacy-event",
                    alice.project_key,
                    "alice-legacy-session",
                    "alice-legacy-run",
                    "Alice only legacy private diagnostic",
                    11.0,
                ),
            ],
        )

    alice_task = _load_task(alice, session_id="shared-session", run_id="shared-run")
    bob_task = _load_task(bob, session_id="shared-session", run_id="shared-run")
    assert alice_task is not None and alice_task["objective"] == "Alice private task"
    assert bob_task is not None and bob_task["objective"] == "Bob private task"
    assert "Alice private task" in alice.bootstrap_context("private", session_id="shared-session")
    bob_context = bob.bootstrap_context("private", session_id="shared-session")
    assert "Bob private task" in bob_context
    assert "Alice private task" not in bob_context
    assert "Alice only legacy private diagnostic" in alice.bootstrap_context(
        "private", session_id="shared-session"
    )
    assert "Alice only legacy private diagnostic" not in bob_context
    assert "ambiguous legacy private diagnostic" not in bob_context


def test_new_session_does_not_reclassify_a_live_run_as_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from backend.runtime import events

    store = ProjectContinuityStore(tmp_path)
    store.begin_run(
        session_id="session-active",
        run_id="run-active",
        objective="Terminar a migração",
        now=1_000,
    )
    monkeypatch.setattr(store, "_run_record", lambda _run_id: {"status": "running"})
    monkeypatch.setattr(events, "get_active_run_event_stream", lambda _run_id: object())

    store.begin_run(
        session_id="session-next",
        run_id="run-next",
        objective="Continua a tarefa interrompida",
        now=1_000 + 10 * 86_400,
    )

    active_context = store.bootstrap_context("migração", session_id="session-active")
    assert "TAREFA ATUAL: in_progress — Terminar a migração" in active_context


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
            user_id="test-user",
        )
    )
    goal = asyncio.run(
        memory_tools.store_memory(
            content="Keep NEXUS local-first and recoverable",
            memory_type="project",
            project_path=str(tmp_path),
            project_goal=True,
            user_id="test-user",
        )
    )

    continuity = ProjectContinuityStore(tmp_path, owner_id="test-user")
    context = continuity.bootstrap_context("job retries")
    assert decision["decision_recorded"] is True
    assert goal["project_goal_recorded"] is True
    assert "Keep NEXUS local-first and recoverable" in context
    assert "The worker owns durable job retries" in context
    assert (tmp_path / ".nexus" / f"project-state-{continuity.owner_key}.md").exists()
    assert not (tmp_path / ".nexus" / "project-state.md").exists()
