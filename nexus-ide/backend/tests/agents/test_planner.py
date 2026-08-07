"""Contract tests for the goal-decomposition planner agent."""

from backend.agents.base import AgentAction
from backend.agents.planner import PlannerAgent


def test_planner_coordinates_memory_specialists_and_verification() -> None:
    agent = PlannerAgent()

    assert agent.name == "PLANNER"
    assert agent.prompt_file == "planner"
    assert {
        AgentAction.RECALL_CONTEXT,
        AgentAction.STORE_MEMORY,
        AgentAction.CONSULT_AGENT,
        AgentAction.EXECUTE_CODE,
    } <= agent.supported_actions
