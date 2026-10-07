"""AITeamLead — coordinates AI/ML development tasks."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from backend.agents.ai_team.data_scientist_agent import DataScientistAgent
from backend.agents.ai_team.ml_engineer_agent import MLEngineerAgent
from backend.agents.ai_team.prompt_engineer_agent import PromptEngineerAgent
from backend.agents.base import AgentBase, AgentRequest


class AITeamLead(AgentBase):
    """Team lead for the AI/ML development team.

    Coordinates MLEngineerAgent, DataScientistAgent, and PromptEngineerAgent
    to deliver complete AI features.
    """

    name = "AI_LEAD"
    model_key = "deep"
    prompt_file = "ai_lead_system"
    supported_actions = set()

    def __init__(
        self,
        ml: MLEngineerAgent | None = None,
        ds: DataScientistAgent | None = None,
        pe: PromptEngineerAgent | None = None,
    ) -> None:
        super().__init__()
        self._ml = ml or MLEngineerAgent()
        self._ds = ds or DataScientistAgent()
        self._pe = pe or PromptEngineerAgent()

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        yield f"<event>ai_start|{request.query[:50]}</event>"

        query = request.query.lower()
        yield "## AI Team Coordination\n\n"

        if any(k in query for k in ["model", "train", "deploy", "serve"]):
            yield "→ Routing to ML Engineer...\n\n"
            async for chunk in self._ml.run(request):
                yield chunk
        elif any(k in query for k in ["data", "analyze", "eda", "experiment", "ab test"]):
            yield "→ Routing to Data Scientist...\n\n"
            async for chunk in self._ds.run(request):
                yield chunk
        elif any(k in query for k in ["prompt", "optimize", "llm", "template"]):
            yield "→ Routing to Prompt Engineer...\n\n"
            async for chunk in self._pe.run(request):
                yield chunk
        else:
            yield "AI Team Lead ready. Describe your AI feature:\n"
            yield "- ML Engineer: model training, deployment\n"
            yield "- Data Scientist: analysis, experiments\n"
            yield "- Prompt Engineer: LLM optimization\n"

        yield "<event>ai_end</event>"

    def get_team_status(self) -> dict[str, Any]:
        return {
            "team": "ai",
            "members": [
                self._ml.name,
                self._ds.name,
                self._pe.name,
            ],
            "lead": self.name,
        }
