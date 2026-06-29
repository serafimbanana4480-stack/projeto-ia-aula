"""PromptEngineerAgent — prompt engineering and optimization specialist."""
from __future__ import annotations

from typing import Any, AsyncIterator

from backend.agents.base import AgentBase, AgentRequest


class PromptEngineerAgent(AgentBase):
    """Specialist agent for prompt engineering and LLM optimization."""

    name = "PROMPT_ENGINEER"
    model_key = "deep"
    prompt_file = "prompt_engineer_system"
    supported_actions = set()

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        yield f"<event>pe_start|{request.query[:50]}</event>"

        query = request.query.lower()
        if "optimize" in query or "improve" in query:
            yield "## Prompt Optimization\n\n"
            yield "### Techniques\n"
            yield "- Chain-of-thought prompting\n"
            yield "- Few-shot examples\n"
            yield "- Role-based framing\n"
            yield "- Structured output formatting\n"
        elif "evaluate" in query or "test" in query:
            yield "## Prompt Evaluation\n\n"
            yield "- Test with diverse inputs\n"
            yield "- Measure consistency across runs\n"
            yield "- Check for bias and safety\n"
            yield "- Benchmark against baselines\n"
        else:
            yield "Prompt Engineer ready. Ask about optimization, evaluation, or templates.\n"

        yield "<event>pe_end</event>"

    def evaluate_prompt(self, prompt: str) -> dict[str, Any]:
        """Evaluate a prompt for quality."""
        score = 60
        issues = []
        strengths = []
        if len(prompt) < 50:
            issues.append("Prompt is too short — add context")
            score -= 20
        else:
            strengths.append("Adequate length")
            score += 5
        if "you are" in prompt.lower() or "role" in prompt.lower():
            strengths.append("Has role definition")
            score += 10
        else:
            issues.append("Consider adding a role definition")
        if "example" in prompt.lower() or "sample" in prompt.lower():
            strengths.append("Includes examples")
            score += 10
        else:
            issues.append("Consider adding examples (few-shot)")
        if "step" in prompt.lower():
            strengths.append("Clear step-by-step instructions")
            score += 5
        if "json" in prompt.lower() or "format" in prompt.lower():
            strengths.append("Structured output specified")
            score += 5
        return {
            "score": min(100, max(0, score)),
            "issues": issues,
            "strengths": [s for s in strengths if s],
        }
