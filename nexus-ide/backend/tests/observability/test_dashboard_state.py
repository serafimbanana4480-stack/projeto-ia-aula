"""Tests for DashboardState."""
import asyncio

import pytest

from backend.observability.dashboard_state import AgentStatus, DashboardState, SystemHealth
from backend.observability.event_bus import EventBus
from backend.observability.events import Event


class TestDashboardState:
    @pytest.mark.asyncio
    async def test_agent_state_tracking(self) -> None:
        bus = EventBus()
        state = DashboardState(event_bus=bus)
        await state.start()

        # Wait for subscriber to be ready
        await asyncio.sleep(0.1)

        await bus.publish(Event(type="agent.started", agent="coder", payload={"task": "gen-api"}))
        await asyncio.sleep(0.1)

        data = await state.get_state()
        assert data["agents"]["coder"]["state"] == "busy"
        assert data["agents"]["coder"]["current_task"] == "gen-api"

        await bus.publish(Event(type="agent.completed", agent="coder"))
        await asyncio.sleep(0.1)

        data = await state.get_state()
        assert data["agents"]["coder"]["state"] == "idle"
        assert data["agents"]["coder"]["tasks_completed"] == 1

        await state.stop()

    @pytest.mark.asyncio
    async def test_health_recomputed(self) -> None:
        bus = EventBus()
        state = DashboardState(event_bus=bus)
        await state.start()
        await asyncio.sleep(0.1)

        await bus.publish(Event(type="agent.started", agent="a1"))
        await bus.publish(Event(type="agent.started", agent="a2"))
        await asyncio.sleep(0.1)

        data = await state.get_state()
        assert data["health"]["active_agents"] == 2
        assert data["health"]["busy_agents"] == 2

        await state.stop()

    @pytest.mark.asyncio
    async def test_offline_detection(self) -> None:
        state = DashboardState()
        # Directly add agent without bus
        state._agents["old"] = AgentStatus(name="old", state="idle")
        state._agents["old"].last_seen = 0
        state._recompute_health()

        assert state._agents["old"].state == "offline"

    @pytest.mark.asyncio
    async def test_system_error_tracking(self) -> None:
        bus = EventBus()
        state = DashboardState(event_bus=bus)
        await state.start()
        await asyncio.sleep(0.1)

        await bus.publish(Event(type="system.error", payload={"msg": "db-down"}))
        await asyncio.sleep(0.1)

        data = await state.get_state()
        assert data["health"]["status"] == "degraded"
        assert data["health"]["error_count"] == 1

        await state.stop()
