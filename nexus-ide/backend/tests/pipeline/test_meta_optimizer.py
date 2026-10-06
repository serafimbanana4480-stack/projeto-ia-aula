"""Tests for MetaOptimizer — RL-driven orchestrator parameter tuning."""
from __future__ import annotations

from backend.pipeline.meta_optimizer import MetaOptimizer, OptimizationResult


class TestMetaOptimizer:
    """Tests for MetaOptimizer class."""

    def test_initialization(self):
        optimizer = MetaOptimizer(exploration_rate=0.2)
        assert optimizer._rl._epsilon == 0.2

    def test_get_parameters_returns_optimization_result(self):
        optimizer = MetaOptimizer()
        result = optimizer.get_parameters(task_complexity="medium", phase="code_gen")
        assert isinstance(result, OptimizationResult)
        assert 1 <= result.num_agents <= 8
        assert result.model_tier in ("mini", "balanced", "opus")
        assert result.max_retries in (1, 3, 5)

    def test_get_parameters_different_contexts(self):
        optimizer = MetaOptimizer()
        result1 = optimizer.get_parameters("simple", "code_gen")
        result2 = optimizer.get_parameters("complex", "deploy")
        assert isinstance(result1, OptimizationResult)
        assert isinstance(result2, OptimizationResult)

    def test_record_successful_outcome(self):
        optimizer = MetaOptimizer()
        params = OptimizationResult(num_agents=5, model_tier="balanced", max_retries=3)
        optimizer.record_outcome("medium", "code_gen", params, success=True, tests_passed=True)
        assert optimizer._workflow_count == 1

    def test_record_failed_outcome(self):
        optimizer = MetaOptimizer()
        params = OptimizationResult(num_agents=3, model_tier="mini", max_retries=1)
        optimizer.record_outcome("simple", "test", params, success=False, tests_passed=False)
        assert optimizer._workflow_count == 1

    def test_record_outcome_tests_only(self):
        optimizer = MetaOptimizer()
        params = OptimizationResult(num_agents=8, model_tier="opus", max_retries=5)
        optimizer.record_outcome("complex", "deploy", params, success=False, tests_passed=True)
        assert optimizer._workflow_count == 1

    def test_multiple_outcomes_update_q_values(self):
        optimizer = MetaOptimizer()
        params = OptimizationResult(num_agents=5, model_tier="balanced", max_retries=3)

        # Record several successful outcomes
        for _ in range(5):
            optimizer.record_outcome("medium", "code_gen", params, success=True, tests_passed=True)

        q_values = optimizer.get_q_values()
        assert len(q_values) > 0

    def test_get_best_parameters_after_learning(self):
        optimizer = MetaOptimizer()
        good_params = OptimizationResult(num_agents=8, model_tier="opus", max_retries=5)
        bad_params = OptimizationResult(num_agents=3, model_tier="mini", max_retries=1)

        # Reward good configuration
        for _ in range(5):
            optimizer.record_outcome("medium", "code_gen", good_params, success=True, tests_passed=True)

        # Penalize bad configuration
        for _ in range(3):
            optimizer.record_outcome("medium", "code_gen", bad_params, success=False, tests_passed=False)

        best = optimizer.get_best_parameters()
        assert isinstance(best, dict)

    def test_exploration_decay(self):
        optimizer = MetaOptimizer(exploration_rate=0.1)
        params = OptimizationResult()

        # Record 60 outcomes to trigger decay
        for _i in range(60):
            optimizer.record_outcome("medium", "code_gen", params, success=True, tests_passed=True)

        # After 50 workflows, epsilon should have decayed
        assert optimizer._rl._epsilon < 0.1

    def test_confidence_increases_with_data(self):
        optimizer = MetaOptimizer()
        result_initial = optimizer.get_parameters("medium", "code_gen")
        assert 0.0 <= result_initial.confidence <= 1.0

        params = OptimizationResult(num_agents=5, model_tier="balanced", max_retries=3)
        for _ in range(10):
            optimizer.record_outcome("medium", "code_gen", params, success=True, tests_passed=True)

        result_after = optimizer.get_parameters("medium", "code_gen")
        assert result_after.confidence >= result_initial.confidence

    def test_q_values_persistence(self):
        optimizer = MetaOptimizer()
        params = OptimizationResult(num_agents=5, model_tier="balanced", max_retries=3)
        optimizer.record_outcome("medium", "code_gen", params, success=True, tests_passed=True)

        q_values = optimizer.get_q_values()
        assert isinstance(q_values, dict)


class TestOptimizationResult:
    """Tests for OptimizationResult dataclass."""

    def test_default_values(self):
        result = OptimizationResult()
        assert result.num_agents == 5
        assert result.model_tier == "balanced"
        assert result.max_retries == 3
        assert result.confidence == 0.5

    def test_custom_values(self):
        result = OptimizationResult(num_agents=8, model_tier="opus", max_retries=5, confidence=0.9)
        assert result.num_agents == 8
        assert result.model_tier == "opus"
        assert result.max_retries == 5
        assert result.confidence == 0.9