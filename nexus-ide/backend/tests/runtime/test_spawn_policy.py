"""Spawning an agent is an expensive operation, not the default method."""

from __future__ import annotations

from backend.runtime.spawn_policy import (
    SpawnPolicy,
    SpawnVerdict,
    SubagentProposal,
)


def _proposal(**overrides) -> SubagentProposal:
    base = {
        "name": "worker-a",
        "objective": "analisar o frontend do streaming SSE",
        "definition_of_done": "lista de ficheiros que renderizam eventos, com o defeito identificado",
        "estimated_seconds": 120.0,
    }
    base.update(overrides)
    return SubagentProposal(**base)


def test_a_short_task_is_done_by_the_primary_agent() -> None:
    decision = SpawnPolicy().evaluate(_proposal(estimated_seconds=5.0))
    assert decision.verdict is SpawnVerdict.PRIMARY_AGENT_ONLY
    assert not decision.allowed
    assert "spawn overhead" in decision.reason


def test_a_proposal_without_a_definition_of_done_is_refused() -> None:
    decision = SpawnPolicy().evaluate(_proposal(definition_of_done=""))
    assert decision.verdict is SpawnVerdict.PRIMARY_AGENT_ONLY
    assert "no definition of done" in decision.failed_conditions


def test_a_proposal_without_an_objective_is_refused() -> None:
    decision = SpawnPolicy().evaluate(_proposal(objective="   "))
    assert "no concrete objective" in decision.failed_conditions


def test_genuinely_parallel_independent_work_is_allowed() -> None:
    decision = SpawnPolicy().evaluate(_proposal())
    assert decision.verdict is SpawnVerdict.SPAWN
    assert decision.allowed


def test_deep_exploration_beats_the_duration_heuristic() -> None:
    decision = SpawnPolicy().evaluate(
        _proposal(estimated_seconds=5.0, requires_deep_exploration=True)
    )
    assert decision.verdict is SpawnVerdict.SPAWN


def test_overlapping_write_scopes_are_queued_not_raced() -> None:
    policy = SpawnPolicy()
    first = _proposal(name="w1", write_scope=frozenset({"backend/runtime/scheduler.py"}))
    assert policy.evaluate(first).allowed
    policy.register(first)

    second = _proposal(
        name="w2",
        objective="outra coisa completamente diferente",
        write_scope=frozenset({"backend/runtime/scheduler.py"}),
    )
    decision = policy.evaluate(second)
    assert decision.verdict is SpawnVerdict.QUEUE
    assert "overlaps worker" in decision.reason


def test_disjoint_write_scopes_are_allowed_together() -> None:
    policy = SpawnPolicy()
    first = _proposal(name="w1", write_scope=frozenset({"a.py"}))
    policy.register(first)
    second = _proposal(name="w2", objective="outro objetivo", write_scope=frozenset({"b.py"}))
    assert policy.evaluate(second).allowed


def test_duplicate_investigations_are_not_spawned_twice() -> None:
    policy = SpawnPolicy()
    first = _proposal(name="w1")
    policy.register(first)
    duplicate = _proposal(name="w2", objective="  Analisar o FRONTEND do streaming SSE ")
    decision = policy.evaluate(duplicate)
    assert decision.verdict is SpawnVerdict.PRIMARY_AGENT_ONLY
    assert "already investigating" in decision.reason


def test_backpressure_caps_the_number_of_live_workers() -> None:
    policy = SpawnPolicy(max_parallel_workers=2)
    for index in range(2):
        proposal = _proposal(name=f"w{index}", objective=f"objetivo {index}")
        assert policy.evaluate(proposal).allowed
        policy.register(proposal)

    decision = policy.evaluate(_proposal(name="w3", objective="objetivo 3"))
    assert decision.verdict is SpawnVerdict.QUEUE
    assert "cap 2" in decision.reason


def test_unmet_dependencies_queue_instead_of_spawning() -> None:
    policy = SpawnPolicy()
    decision = policy.evaluate(_proposal(depends_on=frozenset({"investigacao"})))
    assert decision.verdict is SpawnVerdict.QUEUE
    assert "waiting for investigacao" in decision.reason

    policy.completed_tasks.add("investigacao")
    assert policy.evaluate(_proposal(depends_on=frozenset({"investigacao"}))).allowed


def test_releasing_a_worker_frees_its_write_scope() -> None:
    policy = SpawnPolicy()
    first = _proposal(name="w1", write_scope=frozenset({"x.py"}))
    policy.register(first)
    policy.release("w1")
    assert policy.live_workers == 0
    second = _proposal(name="w2", objective="outro", write_scope=frozenset({"x.py"}))
    assert policy.evaluate(second).allowed
