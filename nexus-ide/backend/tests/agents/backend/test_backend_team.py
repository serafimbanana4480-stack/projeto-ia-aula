"""Tests for Backend Team agents."""
from __future__ import annotations

import pytest

from backend.agents.backend.api_agent import APIAgent, APIReviewResult
from backend.agents.backend.database_agent import DatabaseAgent, SchemaSuggestion
from backend.agents.backend.infrastructure_agent import DeploymentStack, InfrastructureAgent
from backend.agents.backend.team_lead import BackendTeamLead


# ---------------------------------------------------------------------------
# APIAgent
# ---------------------------------------------------------------------------
class TestAPIAgent:
    def test_name_and_model_key(self) -> None:
        agent = APIAgent()
        assert agent.name == "API"
        assert agent.model_key == "coder"
        assert agent.prompt_file == "api_system"

    def test_review_api_passes_with_good_code(self) -> None:
        agent = APIAgent()
        code = """
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from auth import get_current_user

class ItemCreate(BaseModel):
    name: str

@router.post("/items/")
async def create_item(body: ItemCreate, user=Depends(get_current_user)):
    try:
        return {"id": 1}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
"""
        result = agent.review_api(code)
        assert isinstance(result, APIReviewResult)
        assert result.passed is True
        assert result.score == 100
        assert result.auth_check is True
        assert result.validation_check is True
        assert result.error_handling_check is True
        assert result.issues == []

    def test_review_api_fails_without_auth(self) -> None:
        agent = APIAgent()
        code = """
from fastapi import APIRouter

@router.post("/items/")
async def create_item(body):
    return {"id": 1}
"""
        result = agent.review_api(code)
        assert result.passed is False
        assert result.auth_check is False
        assert result.validation_check is False
        assert result.error_handling_check is False
        assert len(result.issues) == 3
        assert any("authentication" in i.lower() for i in result.issues)

    def test_review_api_fails_without_validation(self) -> None:
        agent = APIAgent()
        code = """
from fastapi import APIRouter, HTTPException, Depends
from auth import get_current_user

@router.post("/items/")
async def create_item(body, user=Depends(get_current_user)):
    try:
        return {"id": 1}
    except Exception:
        raise HTTPException(status_code=500)
"""
        result = agent.review_api(code)
        assert result.validation_check is False
        assert any("validation" in i.lower() for i in result.issues)

    def test_stats_tracks_requests(self) -> None:
        agent = APIAgent()
        assert agent.stats()["total_requests"] == 0
        agent._stats["design_requests"] += 1
        assert agent.stats()["design_requests"] == 1
        assert agent.stats()["total_requests"] == 1

    @pytest.mark.asyncio
    async def test_run_yields_events(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        agent = APIAgent()
        req = AgentRequest(session_id="s1", query="design a REST API", client=ollama_client)
        chunks = [c async for c in agent.run(req)]
        assert any("api_start" in c for c in chunks)
        assert any("api_end" in c for c in chunks)
        assert any("REST API Design" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_run_endpoint_generation(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        agent = APIAgent()
        req = AgentRequest(session_id="s1", query="generate an order endpoint", client=ollama_client)
        chunks = [c async for c in agent.run(req)]
        assert any("Endpoint Generation" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_run_review_branch(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        agent = APIAgent()
        req = AgentRequest(session_id="s1", query="review my api code", client=ollama_client)
        chunks = [c async for c in agent.run(req)]
        assert any("API Review" in c for c in chunks)


# ---------------------------------------------------------------------------
# DatabaseAgent
# ---------------------------------------------------------------------------
class TestDatabaseAgent:
    def test_name_and_model_key(self) -> None:
        agent = DatabaseAgent()
        assert agent.name == "DATABASE"
        assert agent.model_key == "coder"
        assert agent.prompt_file == "database_system"

    def test_suggest_schema_with_users(self) -> None:
        agent = DatabaseAgent()
        result = agent.suggest_schema("We need users and orders")
        assert isinstance(result, SchemaSuggestion)
        table_names = {t["name"] for t in result.tables}
        assert "users" in table_names
        assert "orders" in table_names
        assert len(result.indexes) > 0
        assert any("user" in i.lower() for i in result.indexes)

    def test_suggest_schema_with_products(self) -> None:
        agent = DatabaseAgent()
        result = agent.suggest_schema("Product catalog with items")
        table_names = {t["name"] for t in result.tables}
        assert "products" in table_names
        assert any("sku" in str(t["columns"]).lower() for t in result.tables if t["name"] == "products")

    def test_suggest_schema_generic_fallback(self) -> None:
        agent = DatabaseAgent()
        result = agent.suggest_schema("something abstract")
        assert len(result.tables) >= 1
        assert any("generic" in n.lower() for n in result.notes)

    def test_stats_tracks_requests(self) -> None:
        agent = DatabaseAgent()
        assert agent.stats()["total_requests"] == 0
        agent._stats["schema_requests"] += 2
        agent._stats["query_opt_requests"] += 1
        assert agent.stats()["total_requests"] == 3

    @pytest.mark.asyncio
    async def test_run_schema_branch(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        agent = DatabaseAgent()
        req = AgentRequest(session_id="s1", query="design a database schema", client=ollama_client)
        chunks = [c async for c in agent.run(req)]
        assert any("database_start" in c for c in chunks)
        assert any("database_end" in c for c in chunks)
        assert any("Schema Design" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_run_query_opt_branch(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        agent = DatabaseAgent()
        req = AgentRequest(session_id="s1", query="optimize slow query", client=ollama_client)
        chunks = [c async for c in agent.run(req)]
        assert any("Query Optimization" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_run_migration_branch(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        agent = DatabaseAgent()
        req = AgentRequest(session_id="s1", query="plan migrations", client=ollama_client)
        chunks = [c async for c in agent.run(req)]
        assert any("Migration Planning" in c for c in chunks)


# ---------------------------------------------------------------------------
# InfrastructureAgent
# ---------------------------------------------------------------------------
class TestInfrastructureAgent:
    def test_name_and_model_key(self) -> None:
        agent = InfrastructureAgent()
        assert agent.name == "INFRASTRUCTURE"
        assert agent.model_key == "coder"
        assert agent.prompt_file == "infrastructure_system"

    def test_suggest_deployment_stack(self) -> None:
        agent = InfrastructureAgent()
        stack = agent.suggest_deployment_stack()
        assert isinstance(stack, DeploymentStack)
        assert "kubernetes" in stack.orchestration.lower() or "k8s" in stack.orchestration.lower()
        assert "docker" in stack.containerization.lower()
        assert "prometheus" in stack.monitoring.lower()
        assert len(stack.notes) > 0

    def test_stats_tracks_requests(self) -> None:
        agent = InfrastructureAgent()
        assert agent.stats()["total_requests"] == 0
        agent._stats["scaling_requests"] += 1
        assert agent.stats()["scaling_requests"] == 1

    @pytest.mark.asyncio
    async def test_run_deployment_branch(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        agent = InfrastructureAgent()
        req = AgentRequest(session_id="s1", query="deploy with docker", client=ollama_client)
        chunks = [c async for c in agent.run(req)]
        assert any("infrastructure_start" in c for c in chunks)
        assert any("infrastructure_end" in c for c in chunks)
        assert any("Deployment Strategy" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_run_monitoring_branch(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        agent = InfrastructureAgent()
        req = AgentRequest(session_id="s1", query="monitoring setup", client=ollama_client)
        chunks = [c async for c in agent.run(req)]
        assert any("Monitoring & Observability" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_run_scaling_branch(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        agent = InfrastructureAgent()
        req = AgentRequest(session_id="s1", query="scaling strategy", client=ollama_client)
        chunks = [c async for c in agent.run(req)]
        assert any("Scaling Recommendations" in c for c in chunks)


# ---------------------------------------------------------------------------
# BackendTeamLead
# ---------------------------------------------------------------------------
class TestBackendTeamLead:
    def test_name_and_model_key(self) -> None:
        lead = BackendTeamLead()
        assert lead.name == "BACKEND_LEAD"
        assert lead.model_key == "pro"
        assert lead.prompt_file == "backend_lead_system"

    def test_team_status(self) -> None:
        lead = BackendTeamLead()
        status = lead.get_team_status()
        assert status["team"] == "backend"
        assert status["lead"] == "BACKEND_LEAD"
        assert len(status["members"]) == 3
        assert "API" in status["members"]
        assert "DATABASE" in status["members"]
        assert "INFRASTRUCTURE" in status["members"]

    def test_team_stats(self) -> None:
        lead = BackendTeamLead()
        stats = lead.get_team_stats()
        assert stats["lead"] == "BACKEND_LEAD"
        assert "api" in stats
        assert "database" in stats
        assert "infrastructure" in stats
        assert stats["api"]["agent"] == "API"
        assert stats["database"]["agent"] == "DATABASE"
        assert stats["infrastructure"]["agent"] == "INFRASTRUCTURE"

    def test_injected_agents(self) -> None:
        api = APIAgent()
        db = DatabaseAgent()
        infra = InfrastructureAgent()
        lead = BackendTeamLead(api=api, database=db, infrastructure=infra)
        assert lead._api is api
        assert lead._database is db
        assert lead._infrastructure is infra

    @pytest.mark.asyncio
    async def test_run_routes_to_api(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        lead = BackendTeamLead()
        req = AgentRequest(session_id="s1", query="design REST endpoints", client=ollama_client)
        chunks = [c async for c in lead.run(req)]
        assert any("backend_start" in c for c in chunks)
        assert any("backend_end" in c for c in chunks)
        assert any("API specialist" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_run_routes_to_database(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        lead = BackendTeamLead()
        req = AgentRequest(session_id="s1", query="database schema design", client=ollama_client)
        chunks = [c async for c in lead.run(req)]
        assert any("Database specialist" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_run_routes_to_infrastructure(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        lead = BackendTeamLead()
        req = AgentRequest(session_id="s1", query="kubernetes deployment", client=ollama_client)
        chunks = [c async for c in lead.run(req)]
        assert any("Infrastructure specialist" in c for c in chunks)

    @pytest.mark.asyncio
    async def test_run_fallback_help(self, ollama_client) -> None:
        from backend.agents.base import AgentRequest

        lead = BackendTeamLead()
        req = AgentRequest(session_id="s1", query="hello world", client=ollama_client)
        chunks = [c async for c in lead.run(req)]
        assert any("Backend Team Lead ready" in c for c in chunks)
