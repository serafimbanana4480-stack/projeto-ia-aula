"""Contract tests for the public SWARM request models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.swarm.api.routes import SwarmRunBody
from backend.swarm.core.types import AgentRole, OperationalMode, SwarmStrategy


def test_run_body_accepts_legacy_uppercase_agent_names() -> None:
    """Regression test for the payload that previously returned HTTP 422."""
    body = SwarmRunBody.model_validate(
        {
            "objective": "Audit and optimise the SWARM implementation",
            "mode": "INVESTIGATION",
            "strategy": "ADAPTIVE",
            "agents": [
                "RESEARCHER",
                "ARCHITECT",
                "ANALYZER",
                "OPTIMIZER",
                "REVIEWER",
            ],
        }
    )

    assert body.mode is OperationalMode.INVESTIGATION
    assert body.strategy is SwarmStrategy.ADAPTIVE
    assert body.agents == [
        AgentRole.RESEARCHER,
        AgentRole.ARCHITECT,
        AgentRole.INVESTIGATOR,
        AgentRole.IMPLEMENTER,
        AgentRole.REVIEWER,
    ]


def test_run_body_deduplicates_aliases_without_reordering_roles() -> None:
    body = SwarmRunBody.model_validate(
        {
            "objective": "Implement the approved proposal",
            "agents": ["CODER", "implementer", "ANALYZER", "investigator"],
        }
    )

    assert body.agents == [AgentRole.IMPLEMENTER, AgentRole.INVESTIGATOR]


def test_run_body_rejects_unknown_agents_with_actionable_message() -> None:
    with pytest.raises(ValidationError) as exc_info:
        SwarmRunBody.model_validate(
            {
                "objective": "Run a task",
                "agents": ["NOT_A_REAL_AGENT"],
            }
        )

    message = str(exc_info.value)
    assert "Unknown agent(s): NOT_A_REAL_AGENT" in message
    assert "Valid roles: coordinator, architect, researcher" in message


def test_run_body_treats_an_empty_agent_list_as_mode_defaults() -> None:
    body = SwarmRunBody.model_validate(
        {
            "objective": "Use the default team",
            "agents": [],
        }
    )

    assert body.agents is None


def test_run_body_defaults_to_autonomous_continuation() -> None:
    body = SwarmRunBody.model_validate({"objective": "Create and verify a report"})

    assert body.autonomous is True
