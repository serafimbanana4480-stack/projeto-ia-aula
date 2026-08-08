"""Tests for the evolvers (FASE 4)."""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.evolution.evolvers import (
    Candidate,
    CodeEvolver,
    MemoryEvolver,
    ModelEvolver,
    PromptEvolver,
    SkillEvolver,
    ToolEvolver,
    WorkflowEvolver,
    get_all_evolvers,
    get_evolver,
)
from backend.evolution.registry import (
    ChampionRegistry,
    FailureCategory,
    FailurePriority,
)


@pytest.fixture
def temp_registry(tmp_path: Path) -> ChampionRegistry:
    return ChampionRegistry(db_path=tmp_path / "test_evolution.db")


def _make_priority(category: FailureCategory, score: float = 0.5) -> FailurePriority:
    return FailurePriority(
        category=category,
        frequency=0.3,
        impact=0.8,
        repairability=0.7,
        priority_score=score,
        affected_tasks=["t1"],
        evidence="test evidence",
    )


class TestPromptEvolver:
    def test_generates_candidates_for_failures(self, temp_registry: ChampionRegistry) -> None:
        champ = temp_registry.register_champion("prompt", "v1", {"prompt_text": "Base prompt"})
        evolver = PromptEvolver(temp_registry)
        priorities = [_make_priority(FailureCategory.HALLUCINATED_API)]
        candidates = evolver.generate(champ, priorities, n_candidates=2)
        assert len(candidates) == 2
        for c in candidates:
            assert c.component_kind == "prompt"
            assert "mutation_hash" in c.config
            assert c.config["prompt_text"] != "Base prompt"

    def test_generic_candidates_when_no_priorities(self, temp_registry: ChampionRegistry) -> None:
        champ = temp_registry.register_champion("prompt", "v1", {"prompt_text": "Base"})
        evolver = PromptEvolver(temp_registry)
        candidates = evolver.generate(champ, [], n_candidates=2)
        assert len(candidates) == 2
        for c in candidates:
            assert c.config["prompt_text"] != "Base"


class TestSkillEvolver:
    def test_generates_skill_mutations(self, temp_registry: ChampionRegistry) -> None:
        champ = temp_registry.register_champion("skill", "v1", {"retrieval_k": 5, "timeout_sec": 30})
        evolver = SkillEvolver(temp_registry)
        priorities = [
            _make_priority(FailureCategory.MEMORY_RETRIEVAL_ERROR, 0.8),
            _make_priority(FailureCategory.TOO_MANY_CALLS, 0.5),
        ]
        candidates = evolver.generate(champ, priorities, n_candidates=3)
        assert len(candidates) >= 1
        for c in candidates:
            assert c.component_kind == "skill"


class TestWorkflowEvolver:
    def test_generates_workflow_changes(self, temp_registry: ChampionRegistry) -> None:
        base_config = {"workflow_steps": ["plan", "implement", "test"], "timeout_seconds": 300}
        champ = temp_registry.register_champion("workflow", "v1", base_config)
        evolver = WorkflowEvolver(temp_registry)
        priorities = [_make_priority(FailureCategory.BAD_PLANNING)]
        candidates = evolver.generate(champ, priorities, n_candidates=2)
        assert len(candidates) >= 1
        for c in candidates:
            assert c.component_kind == "workflow"
            assert len(c.config["workflow_steps"]) >= len(base_config["workflow_steps"])


class TestToolEvolver:
    def test_generates_tool_changes(self, temp_registry: ChampionRegistry) -> None:
        champ = temp_registry.register_champion("tool", "v1", {"timeout_sec": 30})
        evolver = ToolEvolver(temp_registry)
        priorities = [_make_priority(FailureCategory.TOO_MANY_CALLS)]
        candidates = evolver.generate(champ, priorities, n_candidates=2)
        assert len(candidates) >= 1


class TestMemoryEvolver:
    def test_generates_memory_changes(self, temp_registry: ChampionRegistry) -> None:
        champ = temp_registry.register_champion("memory", "v1", {"retrieval_k": 5})
        evolver = MemoryEvolver(temp_registry)
        priorities = [_make_priority(FailureCategory.MEMORY_RETRIEVAL_ERROR)]
        candidates = evolver.generate(champ, priorities, n_candidates=2)
        assert len(candidates) >= 1
        for c in candidates:
            assert c.config["retrieval_k"] >= 5


class TestCodeEvolver:
    def test_generates_code_changes(self, temp_registry: ChampionRegistry) -> None:
        champ = temp_registry.register_champion("code", "v1", {"max_iterations": 10})
        evolver = CodeEvolver(temp_registry)
        priorities = [_make_priority(FailureCategory.INCORRECT_CODE)]
        candidates = evolver.generate(champ, priorities, n_candidates=2)
        assert len(candidates) >= 1


class TestModelEvolver:
    def test_generates_model_changes(self, temp_registry: ChampionRegistry) -> None:
        champ = temp_registry.register_champion("model", "v1", {"default_model": "gpt-4o-mini", "default_tier": "micro"})
        evolver = ModelEvolver(temp_registry)
        priorities = [_make_priority(FailureCategory.HALLUCINATED_API)]
        candidates = evolver.generate(champ, priorities, n_candidates=2)
        assert len(candidates) >= 1


class TestEvolverFactory:
    def test_get_evolver(self, temp_registry: ChampionRegistry) -> None:
        evolver = get_evolver("prompt", temp_registry)
        assert isinstance(evolver, PromptEvolver)

    def test_get_evolver_unknown(self, temp_registry: ChampionRegistry) -> None:
        evolver = get_evolver("nonexistent", temp_registry)
        assert evolver is None

    def test_get_all_evolvers(self, temp_registry: ChampionRegistry) -> None:
        evolvers = get_all_evolvers(temp_registry)
        assert len(evolvers) >= 7
        kinds = [e.component_kind for e in evolvers]
        assert "prompt" in kinds
        assert "coder" in kinds
        assert "workflow" in kinds
        assert "tool" in kinds
        assert "memory" in kinds
        assert "model" in kinds


class TestCandidate:
    def test_candidate_creation(self) -> None:
        c = Candidate(
            component_kind="prompt",
            config={"prompt": "test"},
            changelog="Added constraint",
            rationale="Addresses hallucination",
            mutation_type="prompt_add_constraint",
            targets=["hallucinated_api"],
        )
        assert c.component_kind == "prompt"
        assert c.mutation_type == "prompt_add_constraint"
        assert c.targets == ["hallucinated_api"]
