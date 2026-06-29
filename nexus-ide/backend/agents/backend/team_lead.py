"""BackendTeamLead — coordinates backend development tasks."""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from backend.agents.base import AgentBase, AgentRequest
from backend.agents.backend.api_agent import APIAgent
from backend.agents.backend.database_agent import DatabaseAgent
from backend.agents.backend.infrastructure_agent import InfrastructureAgent

logger = logging.getLogger(__name__)


class BackendTeamLead(AgentBase):
    """Team lead for the backend development team.

    Coordinates APIAgent, DatabaseAgent, and InfrastructureAgent
    to deliver complete backend features. Routes queries to the
    appropriate specialist based on keywords.
    """

    name = "BACKEND_LEAD"
    model_key = "pro"
    prompt_file = "backend_lead_system"
    supported_actions = set()

    def __init__(
        self,
        api: APIAgent | None = None,
        database: DatabaseAgent | None = None,
        infrastructure: InfrastructureAgent | None = None,
    ) -> None:
        super().__init__()
        self._api = api or APIAgent()
        self._database = database or DatabaseAgent()
        self._infrastructure = infrastructure or InfrastructureAgent()

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        """Coordinate backend team agents and route queries to specialists."""
        yield f"<event>backend_start|{request.query[:50]}</event>"

        query = request.query.lower()
        yield "## Backend Team Coordination\n\n"

        # Route to appropriate specialist
        if any(k in query for k in ["api", "rest", "endpoint", "route", "auth", "validation"]):
            yield "→ Routing to API specialist...\n\n"
            async for chunk in self._api.run(request):
                yield chunk
        elif any(k in query for k in ["database", "schema", "query", "migration", "table", "sql", "index", "optimize db"]):
            yield "→ Routing to Database specialist...\n\n"
            async for chunk in self._database.run(request):
                yield chunk
        elif any(k in query for k in ["deploy", "docker", "kubernetes", "k8s", "monitor", "scale", "infrastructure", "ci/cd", "pipeline"]):
            yield "→ Routing to Infrastructure specialist...\n\n"
            async for chunk in self._infrastructure.run(request):
                yield chunk
        else:
            yield "Backend Team Lead ready. Describe your feature:\n"
            yield "- API: REST design, endpoints, auth, validation\n"
            yield "- Database: schema design, query optimization, migrations\n"
            yield "- Infrastructure: deployment, monitoring, scaling\n"

        yield "<event>backend_end</event>"

    def get_team_status(self) -> dict[str, Any]:
        """Return the current status of the backend team."""
        return {
            "team": "backend",
            "members": [
                self._api.name,
                self._database.name,
                self._infrastructure.name,
            ],
            "lead": self.name,
        }

    def get_team_stats(self) -> dict[str, Any]:
        """Return aggregated statistics from all backend team agents."""
        return {
            "lead": self.name,
            "api": self._api.stats(),
            "database": self._database.stats(),
            "infrastructure": self._infrastructure.stats(),
        }
