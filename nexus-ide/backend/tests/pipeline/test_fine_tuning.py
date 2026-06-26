"""Tests for FineTuningPipeline — automatic SLM fine-tuning."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from backend.pipeline.fine_tuning import (
    DataFormatter,
    FineTuner,
    FineTuningPipeline,
    FineTuneRun,
    ModelEvaluator,
    ModelRegistry,
    TrainingDataCollector,
    TrainingExample,
)


class TestTrainingDataCollector:
    """Tests for TrainingDataCollector."""

    def test_collect_from_successful_logs(self):
        collector = TrainingDataCollector()
        logs = [
            {
                "success": True,
                "tests_passed": True,
                "goal": "Create a REST API for users",
                "code_summary": "Generated FastAPI CRUD endpoints",
                "test_summary": "Unit tests with 95% coverage",
                "task_type": "code_gen",
                "stack": "python",
                "workflow_id": "wf-001",
            },
        ]
        examples = collector.collect_from_logs(logs)
        assert len(examples) == 1
        assert examples[0].instruction == "Create a REST API for users"
        assert examples[0].task_type == "code_gen"

    def test_skip_failed_logs(self):
        collector = TrainingDataCollector()
        logs = [
            {"success": False, "goal": "Create API", "task_type": "code_gen"},
            {"success": True, "tests_passed": False, "goal": "Create API", "task_type": "code_gen"},
        ]
        examples = collector.collect_from_logs(logs)
        assert len(examples) == 0

    def test_skip_empty_goals(self):
        collector = TrainingDataCollector()
        logs = [
            {"success": True, "tests_passed": True, "goal": "", "task_type": "code_gen"},
        ]
        examples = collector.collect_from_logs(logs)
        assert len(examples) == 0

    def test_filter_by_task_type(self):
        collector = TrainingDataCollector()
        logs = [
            {"success": True, "tests_passed": True, "goal": "Code task", "task_type": "code_gen"},
            {"success": True, "tests_passed": True, "goal": "Test task", "task_type": "test_gen"},
        ]
        collector.collect_from_logs(logs)
        code_examples = collector.get_examples("code_gen")
        test_examples = collector.get_examples("test_gen")
        assert len(code_examples) == 1
        assert len(test_examples) == 1

    def test_clear(self):
        collector = TrainingDataCollector()
        logs = [{"success": True, "tests_passed": True, "goal": "Task", "task_type": "code_gen"}]
        collector.collect_from_logs(logs)
        assert len(collector.get_examples()) == 1
        collector.clear()
        assert len(collector.get_examples()) == 0


class TestDataFormatter:
    """Tests for DataFormatter."""

    def test_format_chat(self):
        formatter = DataFormatter()
        examples = [
            TrainingExample(instruction="Build API", response="FastAPI code", task_type="code_gen"),
        ]
        formatted = formatter.format_chat(examples)
        assert len(formatted) == 1
        assert formatted[0]["instruction"] == "Build API"
        assert formatted[0]["response"] == "FastAPI code"

    def test_save_jsonl(self):
        formatter = DataFormatter()
        examples = [
            TrainingExample(instruction="Task 1", response="Code 1", task_type="code_gen"),
            TrainingExample(instruction="Task 2", response="Code 2", task_type="code_gen"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "data.jsonl")
            count = formatter.save_jsonl(examples, path)
            assert count == 2
            assert os.path.exists(path)

            with open(path, encoding="utf-8") as f:
                lines = f.readlines()
            assert len(lines) == 2


class TestFineTuner:
    """Tests for FineTuner."""

    def test_fine_tune_stub_raises_not_implemented(self):
        tuner = FineTuner(output_dir=tempfile.mkdtemp())
        with pytest.raises(NotImplementedError):
            tuner.fine_tune(
                data_path="dummy.jsonl",
                base_model="microsoft/phi-2",
                task_type="code_gen",
            )

    def test_fine_tune_raises_not_implemented(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create dummy data file
            data_path = os.path.join(tmpdir, "data.jsonl")
            with open(data_path, "w") as f:
                f.write('{"instruction": "test", "response": "test"}\n')

            tuner = FineTuner(output_dir=tmpdir)
            with pytest.raises(NotImplementedError):
                tuner.fine_tune(data_path, task_type="code_gen")


class TestModelEvaluator:
    """Tests for ModelEvaluator."""

    def test_evaluate_returns_metrics(self):
        evaluator = ModelEvaluator()
        run = FineTuneRun(
            run_id="test-1",
            model_base="phi-2",
            adapter_path="/tmp/test",
            task_type="code_gen",
            examples_count=100,
            started_at="2025-01-01T00:00:00Z",
        )
        metrics = evaluator.evaluate(run)
        assert "perplexity" in metrics
        assert "exact_match" in metrics
        assert isinstance(metrics["perplexity"], float)


class TestModelRegistry:
    """Tests for ModelRegistry."""

    def test_register_and_retrieve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ModelRegistry(f"{tmpdir}/registry.json")
            run = FineTuneRun(
                run_id="ft-001",
                model_base="phi-2",
                adapter_path="/tmp/adapters/ft-001",
                task_type="code_gen",
                examples_count=50,
                started_at="2025-01-01T00:00:00Z",
                completed_at="2025-01-01T01:00:00Z",
                eval_loss=0.4,
                improvement_pct=20.0,
                status="completed",
            )
            registry.register(run)
            best = registry.get_best_for_task("code_gen")
            assert best is not None
            assert best["run_id"] == "ft-001"

    def test_get_best_returns_lowest_loss(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ModelRegistry(f"{tmpdir}/registry.json")

            run1 = FineTuneRun(
                run_id="ft-001", model_base="phi-2", adapter_path="/tmp/1",
                task_type="code_gen", examples_count=50,
                started_at="2025-01-01T00:00:00Z", status="completed",
                eval_loss=0.6,
            )
            run2 = FineTuneRun(
                run_id="ft-002", model_base="phi-2", adapter_path="/tmp/2",
                task_type="code_gen", examples_count=100,
                started_at="2025-01-02T00:00:00Z", status="completed",
                eval_loss=0.3,
            )
            registry.register(run1)
            registry.register(run2)

            best = registry.get_best_for_task("code_gen")
            assert best["run_id"] == "ft-002"

    def test_list_models(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            registry = ModelRegistry(f"{tmpdir}/registry.json")
            run = FineTuneRun(
                run_id="ft-001", model_base="phi-2", adapter_path="/tmp/1",
                task_type="code_gen", examples_count=50,
                started_at="2025-01-01T00:00:00Z", status="completed",
            )
            registry.register(run)
            models = registry.list_models()
            assert len(models) == 1


class TestFineTuningPipeline:
    """Integration tests for FineTuningPipeline."""

    def test_pipeline_with_enough_data_raises_not_implemented(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = FineTuningPipeline(output_dir=tmpdir)

            logs = []
            for i in range(15):
                logs.append({
                    "success": True,
                    "tests_passed": True,
                    "goal": f"Task {i}: Create API endpoint",
                    "code_summary": f"Generated code for task {i}",
                    "task_type": "code_gen",
                    "stack": "python",
                    "workflow_id": f"wf-{i:03d}",
                })

            with pytest.raises(NotImplementedError):
                pipeline.run(logs, task_type="code_gen")

    def test_pipeline_with_insufficient_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            pipeline = FineTuningPipeline(output_dir=tmpdir)

            logs = [
                {"success": True, "tests_passed": True, "goal": "Only task",
                 "task_type": "code_gen", "stack": "python", "workflow_id": "wf-001"},
            ]

            run = pipeline.run(logs, task_type="code_gen")
            assert run is None