"""FineTuningPipeline — automatic SLM fine-tuning from successful execution logs.

Collects logs, formats training data, runs LoRA/QLoRA fine-tuning,
evaluates, and registers models.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TrainingExample:
    """A single instruction-response training pair."""

    instruction: str
    response: str
    task_type: str = ""  # code_gen, test_gen, review, etc.
    stack: str = ""  # python, typescript, go
    source_workflow_id: str = ""


@dataclass
class FineTuneRun:
    """Metadata for a fine-tuning run."""

    run_id: str
    model_base: str
    adapter_path: str
    task_type: str
    examples_count: int
    started_at: str
    completed_at: str = ""
    eval_loss: float = 0.0
    baseline_loss: float = 0.0
    improvement_pct: float = 0.0
    status: str = "running"  # running, completed, failed
    error: str = ""


class TrainingDataCollector:
    """Collects and filters training examples from execution logs."""

    def __init__(self, min_success_rate: float = 0.9) -> None:
        self._min_success_rate = min_success_rate
        self._examples: list[TrainingExample] = []

    def collect_from_logs(self, logs: list[dict[str, Any]]) -> list[TrainingExample]:
        """Extract training examples from execution logs.

        Args:
            logs: List of execution log entries.

        Returns:
            List of valid TrainingExamples.
        """
        examples: list[TrainingExample] = []

        for entry in logs:
            if not entry.get("success", False):
                continue
            if not entry.get("tests_passed", False):
                continue

            # Extract instruction from goal/story
            instruction = entry.get("goal", "") or entry.get("story", "")
            if not instruction:
                continue

            # Extract response from generated code summary
            response_parts = []
            if entry.get("code_summary"):
                response_parts.append(entry["code_summary"])
            if entry.get("test_summary"):
                response_parts.append(f"Tests: {entry['test_summary']}")
            response = "\n".join(response_parts) if response_parts else instruction

            example = TrainingExample(
                instruction=instruction,
                response=response,
                task_type=entry.get("task_type", "code_gen"),
                stack=entry.get("stack", "python"),
                source_workflow_id=entry.get("workflow_id", ""),
            )
            examples.append(example)

        self._examples.extend(examples)
        logger.info("Collected %d examples from %d logs", len(examples), len(logs))
        return examples

    def get_examples(self, task_type: str | None = None) -> list[TrainingExample]:
        """Get collected examples, optionally filtered by task type."""
        if task_type is None:
            return list(self._examples)
        return [e for e in self._examples if e.task_type == task_type]

    def clear(self) -> None:
        self._examples.clear()


class DataFormatter:
    """Formats training examples into model-ready datasets."""

    def format_chat(self, examples: list[TrainingExample]) -> list[dict[str, str]]:
        """Format as chat-style instruction-response pairs.

        Returns:
            List of {"messages": [{"role": "user", "content": ...}, {"role": "assistant", "content": ...}]}
        """
        formatted: list[dict[str, str]] = []
        for ex in examples:
            formatted.append({
                "instruction": ex.instruction,
                "response": ex.response,
                "task_type": ex.task_type,
            })
        return formatted

    def save_jsonl(self, examples: list[TrainingExample], path: str) -> int:
        """Save examples as JSONL file.

        Returns:
            Number of examples saved.
        """
        formatted = self.format_chat(examples)
        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        with open(filepath, "w", encoding="utf-8") as f:
            for item in formatted:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        logger.info("Saved %d examples to %s", len(formatted), path)
        return len(formatted)


class FineTuner:
    """Executes LoRA/QLoRA fine-tuning on a base model."""

    def __init__(self, output_dir: str = "./fine_tuned_models") -> None:
        self._output_dir = Path(output_dir)
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def fine_tune(self, data_path: str, base_model: str = "microsoft/phi-2",
                  task_type: str = "code_gen", num_epochs: int = 3,
                  lora_r: int = 8, lora_alpha: int = 16) -> FineTuneRun:
        """Run LoRA fine-tuning.

        This is a stub that documents the intended flow. In production,
        this would use transformers.Trainer with PEFT/LoRA config.

        Args:
            data_path: Path to JSONL training data.
            base_model: HuggingFace model ID.
            task_type: Task category for metadata.
            num_epochs: Training epochs.
            lora_r: LoRA rank.
            lora_alpha: LoRA alpha.

        Returns:
            FineTuneRun metadata.

        Raises:
            NotImplementedError: Fine-tuning not yet implemented.
        """
        raise NotImplementedError(
            "Fine-tuning not yet implemented. This is a design stub. "
            "To implement: integrate transformers.Trainer with PEFT/LoRA config, "
            "load training data, run training loop, save adapter weights."
        )

        # The code below documents the intended flow but is not executed
        run_id = f"ft-{task_type}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"
        adapter_path = str(self._output_dir / run_id)

        run = FineTuneRun(
            run_id=run_id,
            model_base=base_model,
            adapter_path=adapter_path,
            task_type=task_type,
            examples_count=self._count_examples(data_path),
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        try:
            # Placeholder for actual training
            # from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer, TrainingArguments
            # from peft import LoraConfig, get_peft_model
            # ... training loop ...

            # Create adapter directory as proof of execution
            os.makedirs(adapter_path, exist_ok=True)
            config = {
                "base_model": base_model,
                "task_type": task_type,
                "lora_r": lora_r,
                "lora_alpha": lora_alpha,
                "num_epochs": num_epochs,
            }
            with open(os.path.join(adapter_path, "config.json"), "w") as f:
                json.dump(config, f, indent=2)

            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc).isoformat()
            run.eval_loss = 0.5  # placeholder
            run.baseline_loss = 0.6  # placeholder
            run.improvement_pct = 16.7  # placeholder

        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            logger.error("Fine-tuning failed: %s", exc)

        return run

    def _count_examples(self, data_path: str) -> int:
        try:
            with open(data_path, encoding="utf-8") as f:
                return sum(1 for _ in f)
        except Exception:
            return 0


class ModelEvaluator:
    """Evaluates fine-tuned models against baseline."""

    def evaluate(self, run: FineTuneRun, eval_data_path: str = "") -> dict[str, float]:
        """Evaluate a fine-tuned model.

        Stub that returns placeholder metrics. In production, this
        would run inference on a held-out validation set.
        """
        return {
            "perplexity": 15.3,
            "exact_match": 0.72,
            "bleu_score": 0.85,
        }


class ModelRegistry:
    """Registers and tracks fine-tuned model versions."""

    def __init__(self, registry_path: str = "./fine_tuned_models/registry.json") -> None:
        self._path = Path(registry_path)
        self._models: dict[str, dict[str, Any]] = self._load()

    def register(self, run: FineTuneRun) -> None:
        """Register a completed fine-tuning run."""
        self._models[run.run_id] = {
            "run_id": run.run_id,
            "base_model": run.model_base,
            "adapter_path": run.adapter_path,
            "task_type": run.task_type,
            "examples_count": run.examples_count,
            "eval_loss": run.eval_loss,
            "improvement_pct": run.improvement_pct,
            "status": run.status,
            "completed_at": run.completed_at,
        }
        self._save()

    def get_best_for_task(self, task_type: str) -> dict[str, Any] | None:
        """Get the best model for a given task type."""
        candidates = [
            m for m in self._models.values()
            if m["task_type"] == task_type and m["status"] == "completed"
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda m: m["eval_loss"])

    def list_models(self) -> list[dict[str, Any]]:
        return list(self._models.values())

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return {}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._models, indent=2), encoding="utf-8")


class FineTuningPipeline:
    """Orchestrates the full fine-tuning lifecycle."""

    def __init__(self, output_dir: str = "./fine_tuned_models") -> None:
        self._collector = TrainingDataCollector()
        self._formatter = DataFormatter()
        self._tuner = FineTuner(output_dir)
        self._evaluator = ModelEvaluator()
        self._registry = ModelRegistry(f"{output_dir}/registry.json")

    def run(self, logs: list[dict[str, Any]], task_type: str = "code_gen",
            base_model: str = "microsoft/phi-2") -> FineTuneRun | None:
        """Execute the full fine-tuning pipeline.

        Args:
            logs: Execution logs to extract training data from.
            task_type: Task category to fine-tune for.
            base_model: Base model to fine-tune.

        Returns:
            FineTuneRun if successful, None if no data available.
        """
        # 1. Collect training examples
        examples = self._collector.collect_from_logs(logs)
        task_examples = self._collector.get_examples(task_type)

        if len(task_examples) < 10:
            logger.warning("Not enough examples for %s (need >=10, got %d)",
                         task_type, len(task_examples))
            return None

        # 2. Format and save training data
        data_path = f"{self._tuner._output_dir}/data_{task_type}.jsonl"
        self._formatter.save_jsonl(task_examples, data_path)

        # 3. Run fine-tuning
        run = self._tuner.fine_tune(data_path, base_model, task_type)

        # 4. Evaluate
        if run.status == "completed":
            metrics = self._evaluator.evaluate(run)
            logger.info("Evaluation metrics: %s", metrics)

        # 5. Register
        if run.status == "completed":
            self._registry.register(run)

        return run