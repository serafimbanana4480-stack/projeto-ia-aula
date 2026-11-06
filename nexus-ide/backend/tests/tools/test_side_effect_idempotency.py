"""Side-effect idempotency at the tool boundary (Fase 1c).

``backend/runtime/primary.py`` owns the ledger and the primary lane keeps its
own tracker, but the guarantee a run needs is **lane-agnostic**: the engine and
swarm lanes reach tools through the very same ``execute_tool``. These tests pin
the four behaviours of that boundary:

1. an identical side effect already confirmed in the run is *replayed*, not
   re-run — the handler is never called a second time;
2. a different action (different arguments) is a different action;
3. a tool called with no active run has no ledger to consult and just runs;
4. a coordinator that fails never breaks the tool: fail-open, logged, and only
   for the ledger — never for the budget hook.

Every test runs against a fresh temporary database, so the ledger rows below
are the real ones ``RunCoordinator`` writes.
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any

import pytest

from backend.runtime import primary as runtime_primary
from backend.runtime.primary import RunLifecycle, side_effect_idempotency_key
from backend.runtime.run_context import active_run
from backend.runtime.run_coordinator import RunCoordinator
from backend.tools import registry
from backend.tools.registry import (
    ToolSpec,
    execute_tool,
    register_tool,
    reset_tool_failures,
)

SESSION = "sess-side-effect"


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Keep these fakes out of the process-wide tool registry.

    ``write_file`` is a real production tool: replacing it without restoring
    would leave later modules executing this spy instead of the real handler.
    The cached coordinator is dropped for the same reason the registry copy is
    — it is keyed by the database path, and each test has its own one.
    """
    registry_before = registry._registry.copy()
    registry._budget_coordinator = None
    registry._budget_coordinator_path = None
    runtime_primary.reset_run_coordinator()
    reset_tool_failures()
    yield
    registry._registry.clear()
    registry._registry.update(registry_before)
    registry._budget_coordinator = None
    registry._budget_coordinator_path = None
    runtime_primary.reset_run_coordinator()
    reset_tool_failures()


def _spy_write_file(calls: list[dict[str, Any]]) -> None:
    """Register a ``write_file`` whose only job is to count executions."""

    async def handler(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return {"written": True, "path": str(kwargs.get("path", "")), **kwargs}

    register_tool(
        ToolSpec(
            name="write_file",
            description="spy for the side-effect ledger tests",
            handler=handler,
            schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        )
    )


def _coordinator() -> RunCoordinator:
    coordinator = runtime_primary.get_run_coordinator()
    assert coordinator is not None
    return coordinator


def _rows(sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
    conn = sqlite3.connect(str(_coordinator().db_path))
    conn.row_factory = sqlite3.Row
    try:
        return list(conn.execute(sql, params))
    finally:
        conn.close()


def _run() -> str:
    lifecycle = RunLifecycle.begin(goal="Escrever o relatorio", session_id=SESSION)
    assert lifecycle is not None, "the durable run is what the ledger keys on"
    return lifecycle.run_id


async def test_replayed_side_effect_is_never_executed_twice(temp_db: None) -> None:
    calls: list[dict[str, Any]] = []
    _spy_write_file(calls)
    run_id = _run()
    args = {"path": "relatorio.md", "content": "conteudo original"}

    with active_run(run_id):
        first = await execute_tool("write_file", SESSION, dict(args))
        second = await execute_tool("write_file", SESSION, dict(args))

    assert first["ok"] is True
    assert not first.get("idempotent_replay")
    assert len(calls) == 1, "one confirmed side effect means exactly one handler run"
    assert second["ok"] is True
    assert second["idempotent_replay"] is True
    assert second["tool"] == "write_file"
    assert second["message"] == (
        "side effect already confirmed in this run; execution skipped"
    )

    key = side_effect_idempotency_key(run_id, "", "write_file", args)
    assert second["idempotency_key"] == key
    stored = _coordinator().get_side_effect(run_id, key)
    assert stored is not None
    assert stored["kind"] == "write_file"
    assert len(_rows("SELECT idempotency_key FROM run_side_effects")) == 1


async def test_a_failed_side_effect_is_not_recorded(temp_db: None) -> None:
    """A rejected write must not close the ledger a replay would check."""
    calls: list[dict[str, Any]] = []
    run_id = _run()
    args = {"path": "protegido.md", "content": "nao deve ser escrito"}

    async def refusing_handler(**kwargs: Any) -> dict[str, Any]:
        calls.append(dict(kwargs))
        return {"written": False, "error": "Operation rejected."}

    register_tool(
        ToolSpec(
            name="write_file",
            description="always fails",
            handler=refusing_handler,
            schema={"type": "object", "properties": {"path": {"type": "string"}}},
        )
    )

    with active_run(run_id):
        first = await execute_tool("write_file", SESSION, dict(args))
        second = await execute_tool("write_file", SESSION, dict(args))

    assert first["ok"] is False
    assert second["ok"] is False, "a failed write must not be replayed as a success"
    assert not second.get("idempotent_replay")
    assert len(calls) == 2, "no success means no ledger entry, so both calls reach the handler"


async def test_different_arguments_are_a_different_side_effect(temp_db: None) -> None:
    calls: list[dict[str, Any]] = []
    _spy_write_file(calls)
    run_id = _run()

    with active_run(run_id):
        first = await execute_tool("write_file", SESSION, {"path": "a.md", "content": "1"})
        other = await execute_tool("write_file", SESSION, {"path": "b.md", "content": "1"})
        again = await execute_tool("write_file", SESSION, {"path": "a.md", "content": "1"})

    assert first["ok"] is True
    assert other["ok"] is True
    assert not other.get("idempotent_replay")
    assert again["idempotent_replay"] is True
    assert len(calls) == 2, "only the two distinct actions were executed"
    assert len(_rows("SELECT idempotency_key FROM run_side_effects")) == 2


async def test_without_an_active_run_the_tool_just_runs(temp_db: None) -> None:
    calls: list[dict[str, Any]] = []
    _spy_write_file(calls)
    args = {"path": "sem-run.md", "content": "x"}

    first = await execute_tool("write_file", SESSION, dict(args))
    second = await execute_tool("write_file", SESSION, dict(args))

    assert first["ok"] is True
    assert second["ok"] is True
    assert not second.get("idempotent_replay")
    assert len(calls) == 2, "no active run means no ledger, so nothing is a replay"
    assert _rows("SELECT idempotency_key FROM run_side_effects") == []


async def test_a_broken_ledger_never_blocks_the_tool(
    temp_db: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Fail-open for the ledger only — the tool must still do its work."""
    calls: list[dict[str, Any]] = []
    _spy_write_file(calls)
    run_id = _run()
    args = {"path": "resiliente.md", "content": "y"}

    def explode(self: RunCoordinator, run_id: str, key: str) -> bool:
        raise RuntimeError("ledger unavailable")

    monkeypatch.setattr(RunCoordinator, "is_side_effect_confirmed", explode)
    with active_run(run_id), caplog.at_level(logging.WARNING, logger="backend.tools.registry"):
        result = await execute_tool("write_file", SESSION, dict(args))

    assert result["ok"] is True
    assert len(calls) == 1, "an unreadable ledger must not stop the tool"
    assert not result.get("idempotent_replay")
    assert any(
        "could not check the ledger" in record.getMessage()
        for record in caplog.records
    ), "the degradation has to be observable, not silent"


async def test_budget_exhaustion_still_blocks_before_the_ledger(
    temp_db: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The budget hook keeps its authority; idempotency must not bypass it.

    A repeated side effect is the natural candidate for a replay, so this is
    where a wrong order would hide: if the ledger were consulted first, the
    second call would come back ``idempotent_replay`` and the exhausted budget
    would never be reported.
    """
    calls: list[dict[str, Any]] = []
    _spy_write_file(calls)
    monkeypatch.setenv("NEXUS_RUN_MAX_TOOL_CALLS", "1")
    lifecycle = RunLifecycle.begin(goal="orcamento esgotado", session_id=SESSION)
    assert lifecycle is not None
    args = {"path": "limite.md", "content": "1"}

    with active_run(lifecycle.run_id):
        first = await execute_tool("write_file", SESSION, dict(args))
        second = await execute_tool("write_file", SESSION, dict(args))

    assert first["ok"] is True
    assert len(calls) == 1
    assert second["ok"] is False
    assert second["error_category"] == "budget_exceeded"
    assert not second.get("idempotent_replay")


async def test_ledger_is_keyed_per_run(temp_db: None) -> None:
    """A confirmed side effect belongs to its run, never to a sibling."""
    calls: list[dict[str, Any]] = []
    _spy_write_file(calls)
    first_run = _run()
    other_run = RunLifecycle.begin(goal="Outro objetivo", session_id="outra-sessao")
    assert other_run is not None
    args = {"path": "partilhado.md", "content": "1"}

    with active_run(first_run):
        await execute_tool("write_file", SESSION, dict(args))

    with active_run(other_run.run_id):
        result = await execute_tool("write_file", SESSION, dict(args))

    assert result["ok"] is True
    assert not result.get("idempotent_replay")
    assert len(calls) == 2, "the second run has its own ledger"
