"""Tests for the evolvers (FASE 4)."""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from backend.evolution.evolvers import (
    MAX_PROMPT_CHARS,
    Candidate,
    CodeEvolver,
    MemoryEvolver,
    ModelEvolver,
    PromptEvolver,
    SkillEvolver,
    ToolEvolver,
    UnknownComponentError,
    WorkflowEvolver,
    candidate_validation_errors,
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

    def test_emits_structured_skill_payload(self, temp_registry: ChampionRegistry) -> None:
        """SkillEvolver must emit concrete skill_name/description/rules payloads."""
        champ = temp_registry.register_champion("skill", "v1", {"retrieval_k": 5})
        evolver = SkillEvolver(temp_registry)
        priorities = [_make_priority(FailureCategory.MEMORY_RETRIEVAL_ERROR)]
        candidates = evolver.generate(champ, priorities, n_candidates=2)
        assert candidates
        for c in candidates:
            payload = c.config["skill_payload"]
            assert isinstance(payload["skill_name"], str) and payload["skill_name"]
            assert isinstance(payload["description"], str) and len(payload["description"]) > 10
            assert isinstance(payload["rules"], list) and payload["rules"]
            assert all(isinstance(r, str) and r.strip() for r in payload["rules"])

    def test_skill_payload_params_match_mutation(self, temp_registry: ChampionRegistry) -> None:
        champ = temp_registry.register_champion("skill", "v1", {"retrieval_k": 5})
        evolver = SkillEvolver(temp_registry)
        priorities = [_make_priority(FailureCategory.MEMORY_RETRIEVAL_ERROR)]
        candidates = evolver.generate(champ, priorities, n_candidates=1)
        assert candidates[0].config["retrieval_k"] == 15


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
        """Non-strict mode (default): unknown kinds return None."""
        evolver = get_evolver("nonexistent", temp_registry)
        assert evolver is None

    def test_get_evolver_unknown_strict_raises_with_valid_keys(
        self, temp_registry: ChampionRegistry
    ) -> None:
        """Strict mode raises a clear error listing every valid component kind."""
        with pytest.raises(UnknownComponentError) as excinfo:
            get_evolver("planner", temp_registry, strict=True)
        message = str(excinfo.value)
        assert "planner" in message
        for kind in ("prompt", "skill", "workflow", "tool", "memory", "coder", "model"):
            assert kind in message

    def test_unknown_component_error_is_value_error(self, temp_registry: ChampionRegistry) -> None:
        with pytest.raises(ValueError):
            get_evolver("bogus", temp_registry, strict=True)

    def test_get_evolver_seed_passthrough(self, temp_registry: ChampionRegistry) -> None:
        evolver = get_evolver("prompt", temp_registry, seed=42)
        assert evolver is not None
        assert evolver.seed == 42

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


class TestDeterministicSeed:
    def test_same_seed_same_rng_sequence(self, temp_registry: ChampionRegistry) -> None:
        e1 = PromptEvolver(temp_registry, seed=123)
        e2 = PromptEvolver(temp_registry, seed=123)
        draws = [e1._rng.random() for _ in range(5)]
        assert draws == [e2._rng.random() for _ in range(5)]

    def test_different_seed_different_sequence(self, temp_registry: ChampionRegistry) -> None:
        e1 = PromptEvolver(temp_registry, seed=1)
        e2 = PromptEvolver(temp_registry, seed=2)
        assert e1._rng.random() != e2._rng.random()

    def test_generation_is_deterministic(self, temp_registry: ChampionRegistry) -> None:
        champ = temp_registry.register_champion("prompt", "v1", {"prompt_text": "Base"})
        priorities = [_make_priority(FailureCategory.HALLUCINATED_API)]
        runs = [
            [c.config["mutation_hash"] for c in PromptEvolver(temp_registry).generate(champ, priorities)]
            for _ in range(2)
        ]
        assert runs[0] == runs[1]


class TestCandidateValidation:
    def _candidate(self, config: dict) -> Candidate:
        return Candidate(
            component_kind="prompt",
            config=config,
            changelog="test",
            rationale="test",
            mutation_type="unit",
            targets=[],
        )

    def test_valid_candidate_passes(self) -> None:
        errors = candidate_validation_errors(self._candidate({
            "prompt_text": "A valid prompt.",
            "default_temperature": 0.7,
        }))
        assert errors == []

    @pytest.mark.parametrize("bad_prompt", ["", "   ", None, 42])
    def test_empty_or_non_string_prompt_rejected(self, bad_prompt: object) -> None:
        errors = candidate_validation_errors(self._candidate({"prompt_text": bad_prompt}))
        assert any("prompt_text" in e for e in errors)

    def test_oversized_prompt_rejected(self) -> None:
        errors = candidate_validation_errors(
            self._candidate({"prompt_text": "x" * (MAX_PROMPT_CHARS + 1)})
        )
        assert any("max" in e for e in errors)

    def test_max_length_prompt_accepted(self) -> None:
        errors = candidate_validation_errors(self._candidate({"prompt_text": "x" * MAX_PROMPT_CHARS}))
        assert errors == []

    @pytest.mark.parametrize("temp", [-0.1, 2.1, 99])
    def test_temperature_out_of_range_rejected(self, temp: float) -> None:
        errors = candidate_validation_errors(self._candidate({"default_temperature": temp}))
        assert any("outside" in e for e in errors)

    @pytest.mark.parametrize("temp", [0, 2, 1.5])
    def test_boundary_temperatures_accepted(self, temp: float) -> None:
        errors = candidate_validation_errors(self._candidate({"temperature": temp}))
        assert not any("temperature" in e for e in errors)

    def test_non_numeric_temperature_rejected(self) -> None:
        errors = candidate_validation_errors(self._candidate({"temperature": "hot"}))
        assert any("numeric" in e for e in errors)

    def test_non_dict_config_rejected(self) -> None:
        errors = candidate_validation_errors(self._candidate(config=None))  # type: ignore[arg-type]
        assert errors


class TestValidationRejectionPaths:
    def test_oversized_champion_prompt_yields_no_candidates(
        self,
        temp_registry: ChampionRegistry,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Candidates built on an oversized base prompt are rejected, not crashed."""
        huge = "x" * (MAX_PROMPT_CHARS + 10)
        champ = temp_registry.register_champion("prompt", "v1", {"prompt_text": huge})
        evolver = PromptEvolver(temp_registry)
        with caplog.at_level(logging.WARNING, logger="backend.evolution.evolvers"):
            candidates = evolver.generate(champ, [], n_candidates=2)
        assert candidates == []
        assert any("Rejected" in r.message and "prompt_text" in r.getMessage() for r in caplog.records)

    def test_invalid_inherited_temperature_rejected(
        self,
        temp_registry: ChampionRegistry,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An out-of-range temperature copied from the champion invalidates candidates."""
        champ = temp_registry.register_champion(
            "memory", "v1", {"retrieval_k": 5, "default_temperature": 3.5}
        )
        evolver = MemoryEvolver(temp_registry)
        priorities = [_make_priority(FailureCategory.MEMORY_RETRIEVAL_ERROR)]
        with caplog.at_level(logging.WARNING, logger="backend.evolution.evolvers"):
            candidates = evolver.generate(champ, priorities, n_candidates=2)
        assert candidates == []
        assert any("outside [0.0, 2.0]" in r.getMessage() for r in caplog.records)

    def test_valid_mutation_still_emitted_alongside_invalid(
        self, temp_registry: ChampionRegistry
    ) -> None:
        """Only the offending candidate is dropped; valid ones survive filtering."""
        champ = temp_registry.register_champion("model", "v1", {"default_model": "gpt-4o"})
        evolver = ModelEvolver(temp_registry)
        priorities = [_make_priority(FailureCategory.HALLUCINATED_API)]
        candidates = evolver.generate(champ, priorities, n_candidates=1)
        assert len(candidates) == 1
        assert 0.0 <= candidates[0].config["default_temperature"] <= 2.0


class TestNeverCrash:
    def test_crashing_mutate_returns_empty_list(
        self, temp_registry: ChampionRegistry, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A broken mutation hook must not propagate; generate() returns []."""

        def boom(*args: object, **kwargs: object) -> list[Candidate]:
            raise RuntimeError("mutation exploded")

        monkeypatch.setattr(PromptEvolver, "_mutate", boom)
        champ = temp_registry.register_champion("prompt", "v1", {"prompt_text": "Base"})
        candidates = PromptEvolver(temp_registry).generate(champ, [], n_candidates=2)
        assert candidates == []

    def test_unhandled_category_yields_no_candidates(self, temp_registry: ChampionRegistry) -> None:
        """Categories without mutations simply produce no workflow candidates."""
        champ = temp_registry.register_champion("workflow", "v1", {"workflow_steps": ["a"]})
        evolver = WorkflowEvolver(temp_registry)
        candidates = evolver.generate(champ, [_make_priority(FailureCategory.REGRESSION)], n_candidates=2)
        assert candidates == []


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
