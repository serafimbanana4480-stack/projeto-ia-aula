"""StateManagerAgent — state architecture design specialist."""
from __future__ import annotations

from typing import Any, AsyncIterator

from backend.agents.base import AgentBase, AgentRequest


class StateManagerAgent(AgentBase):
    """Specialist agent for state management architecture."""

    name = "STATE_MANAGER"
    model_key = "pro"
    prompt_file = "state_manager_system"
    supported_actions = set()

    async def run(self, request: AgentRequest) -> AsyncIterator[str]:
        yield f"<event>state_start|{request.query[:50]}</event>"

        query = request.query.lower()
        if "zustand" in query:
            yield "## Zustand Store Architecture\n\n"
            yield self._zustand_template()
        elif "react query" in query or "tanstack" in query:
            yield "## React Query Integration\n\n"
            yield "- Use queries for server state\n"
            yield "- Mutations for data modifications\n"
            yield "- Prefetching for route navigation\n"
        elif "context" in query:
            yield "## Context API Usage\n\n"
            yield "- Use for theme/auth state\n"
            yield "- Avoid for high-frequency updates\n"
            yield "- Combine with useReducer for complex state\n"
        else:
            yield "State Manager ready. Ask about Zustand, React Query, or Context API.\n"

        yield "<event>state_end</event>"

    def _zustand_template(self) -> str:
        return """```ts
// stores/useAppStore.ts
import { create } from "zustand";

interface AppState {
  // State
  isLoading: boolean;
  data: any[];

  // Actions
  setLoading: (loading: boolean) => void;
  setData: (data: any[]) => void;
}

export const useAppStore = create<AppState>((set) => ({
  isLoading: false,
  data: [],
  setLoading: (loading) => set({ isLoading: loading }),
  setData: (data) => set({ data }),
}));
```
"""
