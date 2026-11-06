"""The spawn policy belongs to a RUN, and a write scope is a PATH.

Three defects are pinned here:

* the registry that shares the spawn policy between the runtime and the
  ``spawn_task`` tool was keyed by *session* id, so two concurrent runs of
  the same session shared (and cleared) each other's policy;
* ``spawn_task`` dropped the ``depends_on`` and the write scope of the
  proposal and never registered the worker, so the parallel cap was never
  approached and the dependency gate was inert for tool-driven spawns;
* a write scope was compared as a raw string, so a worker owning the
  directory ``src/`` and a proposal naming the file ``src/a.py`` were
  considered disjoint — and both wrote the same file at the same time.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.runtime.scheduler import RuntimeScheduler, RuntimeTask
from backend.runtime.spawn_policy import (
    SpawnPolicy,
    SpawnVerdict,
    SubagentProposal,
)


def _proposal(**overrides: Any) -> SubagentProposal:
    base: dict[str, Any] = {
        "name": "worker-a",
        "objective": "analisar o modulo de streaming do chat",
        "definition_of_done": "a lista de ficheiros com o defeito identificado",
        "estimated_seconds": 120.0,
    }
    base.update(overrides)
    return SubagentProposal(**base)


class _RecordingPolicy(SpawnPolicy):
    """A real policy that also remembers every proposal it evaluated."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.proposals: list[SubagentProposal] = []

    def evaluate(self, proposal: SubagentProposal):  # type: ignore[override]
        self.proposals.append(proposal)
        return super().evaluate(proposal)


class _StubLifecycle:
    """Minimal agent lifecycle: accepts the spawn and returns an instance id."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def spawn(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return "inst-stub-1"


@pytest.fixture()
def registered_policy(monkeypatch: pytest.MonkeyPatch):
    """A spawn policy published for one run, plus a stub agent lifecycle."""
    from backend.orchestrator.main import app
    from backend.runtime import spawn_registry
    from backend.runtime.run_context import reset_current_run_id, set_current_run_id

    policy = _RecordingPolicy()
    run_id = "run-spawn-policy-test"
    spawn_registry.register_policy(run_id, policy)
    token = set_current_run_id(run_id)
    lifecycle = _StubLifecycle()
    monkeypatch.setattr(app.state, "agent_lifecycle", lifecycle, raising=False)
    try:
        yield policy, lifecycle
    finally:
        reset_current_run_id(token)
        spawn_registry.clear_policy(run_id)
        spawn_registry.clear_run_project(run_id)


# ---------------------------------------------------------------------------
# D2 — the registry is keyed by run, not by session
# ---------------------------------------------------------------------------
def test_spawn_policy_is_keyed_by_run_not_session() -> None:
    from backend.runtime import spawn_registry

    policy_a = SpawnPolicy(max_parallel_workers=1)
    policy_b = SpawnPolicy(max_parallel_workers=2)
    spawn_registry.register_policy("run-a", policy_a)
    spawn_registry.register_policy("run-b", policy_b)
    try:
        assert spawn_registry.get_policy("run-a") is policy_a
        assert spawn_registry.get_policy("run-b") is policy_b

        # A run that finishes must not disarm the other run of the same
        # session: the second run keeps its parallel cap and its write-scope
        # serialisation.
        spawn_registry.clear_policy("run-a")
        assert spawn_registry.get_policy("run-a") is None
        assert spawn_registry.get_policy("run-b") is policy_b
    finally:
        spawn_registry.clear_policy("run-a")
        spawn_registry.clear_policy("run-b")


def test_two_runs_of_one_session_keep_their_own_policy() -> None:
    from backend.runtime import spawn_registry

    policy_a = SpawnPolicy(max_parallel_workers=1)
    policy_b = SpawnPolicy(max_parallel_workers=2)
    spawn_registry.register_policy("run-a", policy_a)
    spawn_registry.register_policy("run-b", policy_b)
    try:
        # Run A consults its own policy, never run B's.
        assert spawn_registry.get_policy("run-a").max_parallel_workers == 1
        assert spawn_registry.get_policy("run-b").max_parallel_workers == 2
    finally:
        spawn_registry.clear_policy("run-a")
        spawn_registry.clear_policy("run-b")


@pytest.mark.asyncio
async def test_spawn_tool_consults_the_policy_of_its_own_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two runs of one session must not share the tool's verdict."""
    from backend.orchestrator.main import app
    from backend.runtime import spawn_registry
    from backend.runtime.run_context import reset_current_run_id, set_current_run_id
    from backend.tools.task_spawner import spawn_task

    other_policy = _RecordingPolicy()
    own_policy = _RecordingPolicy()
    spawn_registry.register_policy("run-other", other_policy)
    spawn_registry.register_policy("run-own", own_policy)
    token = set_current_run_id("run-own")
    monkeypatch.setattr(app.state, "agent_lifecycle", _StubLifecycle(), raising=False)
    try:
        await spawn_task(
            name="worker-own-run",
            description="trabalho do run corrente",
            definition_of_done="o trabalho esta feito",
            session_id="s-two-runs",
        )
    finally:
        reset_current_run_id(token)
        spawn_registry.clear_policy("run-other")
        spawn_registry.clear_policy("run-own")

    assert own_policy.proposals, "the tool ignored the policy of its own run"
    assert not other_policy.proposals, "the tool consulted another run's policy"


# ---------------------------------------------------------------------------
# D3 — the tool forwards the proposal and registers the worker
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_spawn_tool_forwards_depends_on(registered_policy) -> None:
    from backend.tools.task_spawner import spawn_task

    policy, _lifecycle = registered_policy
    result = await spawn_task(
        name="worker-depends",
        description="esperar pelo trabalho do pai",
        definition_of_done="o ficheiro derivado existe",
        depends_on=["ParentTask"],
        session_id="s-spawn-depends",
    )

    assert policy.proposals, "the tool must consult the policy of the run"
    proposal = policy.proposals[0]
    assert proposal.depends_on == frozenset({"ParentTask"})
    assert result["depends_on"] == ["ParentTask"]
    # The dependency is a real gate: the delegation is queued, not started.
    assert result["status"] == "queued"
    assert result["spawned"] is False


@pytest.mark.asyncio
async def test_spawn_tool_registers_the_worker(registered_policy) -> None:
    from backend.tools.task_spawner import spawn_task

    policy, _lifecycle = registered_policy
    result = await spawn_task(
        name="worker-registered",
        description="fazer o trabalho delegavel",
        definition_of_done="o ficheiro existe e o teste passa",
        session_id="s-spawn-register",
    )

    assert result["status"] == "spawned"
    # The worker is live: it owns its slot and it counts against the cap.
    assert policy.live_workers == 1


@pytest.mark.asyncio
async def test_spawn_tool_forwards_a_write_scope(registered_policy) -> None:
    from backend.tools.registry import get_tool
    from backend.tools.task_spawner import spawn_task

    policy, _lifecycle = registered_policy
    await spawn_task(
        name="worker-scope",
        description="mexer num ficheiro do projeto",
        definition_of_done="o ficheiro esta alterado",
        write_scope=["src/app.py"],
        session_id="s-spawn-scope",
    )

    assert policy.proposals, "the tool must consult the policy of the run"
    assert policy.proposals[0].write_scope == frozenset({"src/app.py"})

    # The schema has to publish the argument, or the model cannot send it.
    spec = get_tool("spawn_task")
    assert spec is not None
    properties = spec.schema.get("properties", {})
    assert "write_scope" in properties
    assert "depends_on" in properties


@pytest.mark.asyncio
async def test_spawn_tool_denies_a_second_worker_with_the_same_write_scope(
    registered_policy,
) -> None:
    from backend.tools.task_spawner import spawn_task

    policy, _lifecycle = registered_policy
    first = await spawn_task(
        name="worker-first",
        description="primeiro worker sobre a pasta src",
        definition_of_done="a primeira alteracao esta feita",
        write_scope=["src"],
        session_id="s-spawn-conflict",
    )
    assert first["status"] == "spawned"

    second = await spawn_task(
        name="worker-second",
        description="segundo worker sobre um ficheiro da mesma pasta",
        definition_of_done="a segunda alteracao esta feita",
        write_scope=["src/app.py"],
        session_id="s-spawn-conflict",
    )

    # "src" and "src/app.py" are the same area: the second one is serialised
    # instead of racing on the same file.
    assert second["status"] == "queued"
    assert second["spawned"] is False
    assert policy.live_workers == 1


# ---------------------------------------------------------------------------
# D4 — write scopes are paths, not strings
# ---------------------------------------------------------------------------
def test_directory_scope_conflicts_with_a_file_inside_it(tmp_path) -> None:
    policy = SpawnPolicy(scope_root=str(tmp_path))

    first = _proposal(name="w1", write_scope=frozenset({"src"}))
    assert policy.evaluate(first).allowed
    policy.register(first)

    second = _proposal(
        name="w2",
        objective="outra coisa completamente diferente",
        write_scope=frozenset({"src/app.py"}),
    )
    decision = policy.evaluate(second)
    assert decision.verdict is SpawnVerdict.QUEUE
    assert "overlaps worker" in decision.reason


def test_a_file_scope_conflicts_with_the_directory_that_contains_it(tmp_path) -> None:
    policy = SpawnPolicy(scope_root=str(tmp_path))

    first = _proposal(name="w1", write_scope=frozenset({"src/app.py"}))
    assert policy.evaluate(first).allowed
    policy.register(first)

    second = _proposal(
        name="w2",
        objective="outra coisa completamente diferente",
        write_scope=frozenset({"src"}),
    )
    decision = policy.evaluate(second)
    assert decision.verdict is SpawnVerdict.QUEUE
    assert "overlaps worker" in decision.reason


def test_a_trailing_slash_does_not_hide_the_conflict(tmp_path) -> None:
    policy = SpawnPolicy(scope_root=str(tmp_path))

    first = _proposal(name="w1", write_scope=frozenset({"src/"}))
    assert policy.evaluate(first).allowed
    policy.register(first)

    second = _proposal(
        name="w2",
        objective="outra coisa completamente diferente",
        write_scope=frozenset({"src/app.py"}),
    )
    assert policy.evaluate(second).verdict is SpawnVerdict.QUEUE


def test_sibling_directories_do_not_conflict(tmp_path) -> None:
    policy = SpawnPolicy(scope_root=str(tmp_path))

    first = _proposal(name="w1", write_scope=frozenset({"src"}))
    policy.register(first)
    second = _proposal(
        name="w2",
        objective="outra coisa completamente diferente",
        write_scope=frozenset({"src2/app.py"}),
    )
    assert policy.evaluate(second).allowed


@pytest.mark.asyncio
async def test_scheduler_serialises_overlapping_write_scopes(tmp_path) -> None:
    order: list[str] = []

    async def _work(task: RuntimeTask) -> str:
        order.append(f"start:{task.name}")
        await asyncio.sleep(0.05)
        order.append(f"end:{task.name}")
        return task.name

    scheduler = RuntimeScheduler(max_parallel=2)
    report = await scheduler.run(
        [
            RuntimeTask(
                name="writer-dir",
                run=_work,
                write_scope=frozenset({str(tmp_path / "src")}),
            ),
            RuntimeTask(
                name="writer-file",
                run=_work,
                write_scope=frozenset({str(tmp_path / "src" / "app.py")}),
            ),
        ]
    )

    # The directory owner and the file writer touch the same bytes, so they
    # are serialised instead of running at the same time.
    assert order == [
        "start:writer-dir",
        "end:writer-dir",
        "start:writer-file",
        "end:writer-file",
    ]
    assert report.peak_parallelism == 1
    assert not report.errors
