"""Integration tests for the Evolution Engine API routes (FASE 10-11)."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.orchestrator.main import app
from backend.orchestrator.routes import evolution as evolution_routes


@pytest.fixture
def client(tmp_path: Path):
    """FastAPI test client with a temp evolution engine."""
    from backend.evolution.arena import Arena
    from backend.evolution.engine import EvolutionEngine
    from backend.evolution.failure_miner import FailureMiner
    from backend.evolution.registry import ChampionRegistry
    from backend.evolution.rollback import RollbackManager
    from backend.experience.lake import TraceLake
    from backend.experience.models import (
        ExperienceTrace,
        ModelInfo,
        TraceMetrics,
        TraceResult,
    )

    registry = ChampionRegistry(db_path=tmp_path / "test_evolution_api.db")
    lake = TraceLake(tmp_path / "test_trace_lake_api.db")

    # Seed a successful trace with trajectory
    trace = ExperienceTrace(
        prompt="Test task",
        task_type="coding",
        category="coding",
        model=ModelInfo(name="test", version="v1", temperature=0.0, tier="fast"),
    )
    trace.add_trajectory_entry(agent="CODER", action="read_file", tool="read", observation="ok")
    trace.add_trajectory_entry(agent="CODER", action="write_file", tool="write", observation="done")
    trace.add_trajectory_entry(agent="CODER", action="run_tests", tool="bash", observation="passed")
    trace.result = TraceResult(success=True, score=0.9)
    trace.metrics = TraceMetrics(latency_ms=100, tokens_input=100, tokens_output=50, tool_calls=3)
    lake.store_trace(trace)

    engine = EvolutionEngine(
        registry=registry,
        arena=Arena(registry, allow_simulation=True),
        failure_miner=FailureMiner(lake=lake, db_path=tmp_path / "test_evolution_api.db"),
        rollback=RollbackManager(registry),
    )

    # Patch the global engine
    evolution_routes._ENGINE = engine
    yield TestClient(app)
    evolution_routes._ENGINE = None


class TestEvolutionEndpoints:
    def test_get_components(self, client: TestClient) -> None:
        """GET /api/evolution/components returns evolvable component kinds."""
        resp = client.get("/api/evolution/components")
        assert resp.status_code == 200
        components = resp.json()
        assert "coder" in components
        assert "prompt" in components
        assert "planner" in components

    def test_get_state(self, client: TestClient) -> None:
        """GET /api/evolution/state returns engine state."""
        resp = client.get("/api/evolution/state")
        assert resp.status_code == 200
        data = resp.json()
        assert "version_tree" in data
        assert "experiments" in data
        assert "failure_summary" in data
        assert "rollbacks" in data
        assert "cycle_count" in data

    def test_get_champions_empty(self, client: TestClient) -> None:
        """GET /api/evolution/champions returns empty before bootstrap."""
        resp = client.get("/api/evolution/champions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_bootstrap(self, client: TestClient) -> None:
        """POST /api/evolution/bootstrap registers champions."""
        resp = client.post("/api/evolution/bootstrap")
        assert resp.status_code == 200
        data = resp.json()
        assert "registered" in data
        assert "count" in data
        assert data["count"] > 0

    def test_bootstrap_then_champions(self, client: TestClient) -> None:
        """After bootstrap, champions are listed."""
        client.post("/api/evolution/bootstrap")
        resp = client.get("/api/evolution/champions")
        assert resp.status_code == 200
        champions = resp.json()
        assert len(champions) > 0

    def test_register_champion(self, client: TestClient) -> None:
        """POST /api/evolution/register creates a new champion."""
        resp = client.post(
            "/api/evolution/register",
            json={
                "component_kind": "prompt",
                "config": {"prompt_text": "test prompt"},
                "changelog": "test registration",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["component_kind"] == "prompt"
        assert data["version"] == "v1"
        assert data["status"] == "champion"

    def test_run_evolution_simulation(self, client: TestClient) -> None:
        """POST /api/evolution/run executes a cycle with simulation."""
        client.post("/api/evolution/bootstrap")
        resp = client.post(
            "/api/evolution/run",
            json={
                "max_cycles": 1,
                "allow_simulation": True,
                "benchmark_task_ids": ["task_a", "task_b"],
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "candidates_generated" in data
        assert "experiments_run" in data
        assert "promoted" in data
        assert "rejected" in data

    def test_get_component_versions(self, client: TestClient) -> None:
        """GET /api/evolution/champions/{kind}/versions returns version history."""
        client.post("/api/evolution/bootstrap")
        resp = client.get("/api/evolution/champions/coder/versions")
        assert resp.status_code == 200
        versions = resp.json()
        assert len(versions) >= 1
        assert versions[0]["version"] == "v1"
        assert versions[0]["status"] == "champion"

    def test_get_component_versions_with_status_filter(self, client: TestClient) -> None:
        """Versions can be filtered by status."""
        client.post("/api/evolution/bootstrap")
        resp = client.get("/api/evolution/champions/coder/versions?status=champion")
        assert resp.status_code == 200
        versions = resp.json()
        assert len(versions) == 1
        assert versions[0]["status"] == "champion"

    def test_get_failures(self, client: TestClient) -> None:
        """GET /api/evolution/failures returns failure summary."""
        resp = client.get("/api/evolution/failures")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_classified" in data

    def test_get_rollbacks_empty(self, client: TestClient) -> None:
        """GET /api/evolution/rollbacks returns empty list initially."""
        resp = client.get("/api/evolution/rollbacks")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_get_registry_stats(self, client: TestClient) -> None:
        """GET /api/evolution/registry/stats returns component statistics."""
        client.post("/api/evolution/bootstrap")
        resp = client.get("/api/evolution/registry/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "components" in data
        assert "coder" in data["components"]
        assert data["components"]["coder"]["champions"] >= 1
