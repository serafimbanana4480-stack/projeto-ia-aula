"""Tests for backend.orchestrator.registry."""

from __future__ import annotations

from backend.agents.coder import CoderAgent
from backend.agents.dashboard_agent import DashboardAgent
from backend.orchestrator.registry import build_default_registry, resolve


class TestRegistry:
    def test_default_registry_contains_core_agents(self) -> None:
        r = build_default_registry()
        for name in (
            "CODER",
            "ANALYZER",
            "DEBUGGER",
            "DOCUMENTER",
            "OPTIMIZER",
            "RESEARCHER",
            "ARCHITECT",
            "MICRO",
            "DASHBOARD",
        ):
            assert name in r, f"{name} missing from default registry"

    def test_resolve_returns_matching_agent(self) -> None:
        r = build_default_registry()
        assert isinstance(resolve(r, "CODER"), CoderAgent)

    def test_resolve_unknown_falls_back_to_coder(self) -> None:
        r = build_default_registry()
        # ROUTER is not user-invocable; must fall back to CODER.
        assert isinstance(resolve(r, "ROUTER"), CoderAgent)  # type: ignore[arg-type]

    def test_resolve_dashboard_returns_dashboard_agent(self) -> None:
        r = build_default_registry()
        # DASHBOARD is now invocable for metrics queries
        assert isinstance(resolve(r, "DASHBOARD"), DashboardAgent)
