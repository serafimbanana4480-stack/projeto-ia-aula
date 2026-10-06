"""MLEngineerAgent — ML model development and deployment specialist."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from backend.agents.base import AgentBase, AgentRequest


class MLEngineerAgent(AgentBase):
    """Specialist agent for ML model engineering."""

    name = "ML_ENGINEER"
    model_key = "deep"
    prompt_file = "ml_engineer_system"
    supported_actions = set()

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        yield f"<event>ml_start|{request.query[:50]}</event>"

        query = request.query.lower()
        if "train" in query or "model" in query:
            yield "## ML Model Development\n\n"
            yield "### Pipeline\n"
            yield "1. Data preprocessing and validation\n"
            yield "2. Feature engineering\n"
            yield "3. Model selection and training\n"
            yield "4. Evaluation and metrics\n"
            yield "5. Deployment and monitoring\n"
        elif "deploy" in query or "serve" in query:
            yield "## Model Deployment\n\n"
            yield "- Containerize with Docker\n"
            yield "- Use ONNX for interoperability\n"
            yield "- Set up A/B testing infrastructure\n"
            yield "- Monitor drift and performance\n"
        else:
            yield "ML Engineer ready. Ask about training, deployment, or optimization.\n"

        yield "<event>ml_end</event>"

    def suggest_architecture(self, problem_type: str) -> dict[str, Any]:
        """Suggest model architecture for a problem type."""
        architectures = {
            "classification": {
                "models": ["Random Forest", "XGBoost", "Neural Network"],
                "metrics": ["accuracy", "precision", "recall", "f1"],
            },
            "regression": {
                "models": ["Linear Regression", "XGBoost", "Neural Network"],
                "metrics": ["mse", "mae", "r2"],
            },
            "nlp": {
                "models": ["BERT", "GPT", "T5"],
                "metrics": ["perplexity", "bleu", "rouge"],
            },
        }
        return architectures.get(problem_type, {
            "models": ["Neural Network"],
            "metrics": ["accuracy"],
        })
