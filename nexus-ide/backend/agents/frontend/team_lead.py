"""FrontendTeamLead — coordinates frontend development tasks."""
from __future__ import annotations

from typing import Any, AsyncIterator

from backend.agents.base import AgentBase, AgentRequest
from backend.agents.frontend.uiux_agent import UIUXAgent
from backend.agents.frontend.component_agent import ComponentAgent
from backend.agents.frontend.state_manager_agent import StateManagerAgent


class FrontendTeamLead(AgentBase):
    """Team lead for the frontend development team.

    Coordinates UIUXAgent, ComponentAgent, and StateManagerAgent
    to deliver complete frontend features.
    """

    name = "FRONTEND_LEAD"
    model_key = "pro"
    prompt_file = "frontend_lead_system"
    supported_actions = set()

    def __init__(
        self,
        uiux: UIUXAgent | None = None,
        component: ComponentAgent | None = None,
        state: StateManagerAgent | None = None,
    ) -> None:
        super().__init__()
        self._uiux = uiux or UIUXAgent()
        self._component = component or ComponentAgent()
        self._state = state or StateManagerAgent()

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        yield f"<event>frontend_start|{request.query[:50]}</event>"

        query = request.query.lower()
        yield "## Frontend Team Coordination\n\n"

        # Route to appropriate specialist
        if any(k in query for k in ["design", "color", "layout", "accessibility"]):
            yield "→ Routing to UI/UX specialist...\n\n"
            async for chunk in self._uiux.run(request):
                yield chunk
        elif any(k in query for k in ["component", "react", "tsx", "jsx"]):
            yield "→ Routing to Component specialist...\n\n"
            async for chunk in self._component.run(request):
                yield chunk
        elif any(k in query for k in ["state", "store", "zustand", "query", "context"]):
            yield "→ Routing to State Manager...\n\n"
            async for chunk in self._state.run(request):
                yield chunk
        else:
            yield "Frontend Team Lead ready. Describe your feature:\n"
            yield "- UI/UX: design, colors, accessibility\n"
            yield "- Components: React, TSX, JSX generation\n"
            yield "- State: Zustand, React Query, Context\n"

        yield "<event>frontend_end</event>"

    def get_team_status(self) -> dict[str, Any]:
        return {
            "team": "frontend",
            "members": [
                self._uiux.name,
                self._component.name,
                self._state.name,
            ],
            "lead": self.name,
        }
