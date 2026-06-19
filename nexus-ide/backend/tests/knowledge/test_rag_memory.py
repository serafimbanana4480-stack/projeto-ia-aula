"""RAG / memory integration tests.

Covers:
- MemoryStore context assembly with keyword boost
- Conversation memory helpers
- memory_tools recall_context / store_memory
- Second Brain API routes (ingest, search, list, delete)
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.knowledge.memory import EmbeddingService, MemoryStore, MemoryType
from backend.middleware.auth import create_access_token
from backend.orchestrator.main import app
from backend.tools.memory_tools import recall_context, store_memory


@pytest.fixture
def rag_store(monkeypatch: pytest.MonkeyPatch) -> MemoryStore:
    """In-memory store with deterministic fallback embeddings for fast tests."""
    svc = EmbeddingService()

    async def _fast_embed(text: str) -> list[float]:
        return svc._fallback_embed(text)

    monkeypatch.setattr(svc, "embed", _fast_embed)
    return MemoryStore(embedding_service=svc, max_memories=100)


@pytest.fixture
def client() -> TestClient:
    token = create_access_token({"sub": "test-user", "email": "test@test.com"})
    return TestClient(app, headers={"Authorization": f"Bearer {token}"})


class TestMemoryContext:
    @pytest.mark.asyncio
    async def test_get_context_includes_relevant_memories(self, rag_store: MemoryStore) -> None:
        await rag_store.store(
            "Authentication uses JWT tokens for security",
            memory_type=MemoryType.GLOBAL,
        )
        await rag_store.store(
            "Database uses PostgreSQL with SQLAlchemy ORM",
            memory_type=MemoryType.GLOBAL,
        )
        await rag_store.store(
            "The sky is blue on sunny days",
            memory_type=MemoryType.GLOBAL,
        )

        context = await rag_store.get_context("JWT authentication", top_k=2)
        assert "JWT" in context or "authentication" in context.lower()
        assert "PostgreSQL" in context or "ORM" in context

    @pytest.mark.asyncio
    async def test_get_context_respects_token_budget(self, rag_store: MemoryStore) -> None:
        long_content = "word " * 2000
        await rag_store.store(long_content, memory_type=MemoryType.GLOBAL)
        await rag_store.store("short note", memory_type=MemoryType.GLOBAL)

        context = await rag_store.get_context("word", max_tokens=10, top_k=5)
        # Budget is tiny; only short note should fit
        assert "short note" in context or context == ""

    @pytest.mark.asyncio
    async def test_remember_conversation_links_memories(self, rag_store: MemoryStore) -> None:
        user_mem, assistant_mem = await rag_store.remember_conversation(
            user_message="What is the database?",
            assistant_message="PostgreSQL.",
            session_id="s1",
            source="MICRO",
        )
        assert user_mem.memory_type == MemoryType.CONVERSATION
        assert assistant_mem.memory_type == MemoryType.CONVERSATION
        assert assistant_mem.related_memory_ids == [user_mem.memory_id]
        assert user_mem.related_memory_ids == [assistant_mem.memory_id]


class TestMemoryTools:
    @pytest.mark.asyncio
    async def test_store_and_recall_tool(self, monkeypatch: pytest.MonkeyPatch) -> None:
        svc = EmbeddingService()

        async def _fast_embed(text: str) -> list[float]:
            return svc._fallback_embed(text)

        monkeypatch.setattr(svc, "embed", _fast_embed)
        store = MemoryStore(embedding_service=svc, max_memories=100)
        monkeypatch.setattr("backend.knowledge.memory._memory_store", store)

        stored = await store_memory(
            content="The project uses FastAPI and SQLAlchemy",
            memory_type="project",
            project_id="proj_1",
            tags="tech,stack",
            source="TEST",
        )
        assert stored["stored"] is True
        assert "memory_id" in stored

        recall = await recall_context(
            "The project uses FastAPI and SQLAlchemy", project_id="proj_1", top_k=5
        )
        assert "memories" in recall
        assert any("FastAPI" in m["content"] for m in recall["memories"])

    @pytest.mark.asyncio
    async def test_recall_filters_by_memory_type(self, monkeypatch: pytest.MonkeyPatch) -> None:
        svc = EmbeddingService()

        async def _fast_embed(text: str) -> list[float]:
            return svc._fallback_embed(text)

        monkeypatch.setattr(svc, "embed", _fast_embed)
        store = MemoryStore(embedding_service=svc, max_memories=100)
        monkeypatch.setattr("backend.knowledge.memory._memory_store", store)

        await store_memory("Global note", memory_type="global")
        await store_memory("Session note", memory_type="session", session_id="s1")

        recall = await recall_context("note", memory_type="session", session_id="s1")
        assert all(m["type"] == "session" for m in recall["memories"])


class TestSecondBrainRoutes:
    def test_ingest_note_and_search(self, client: TestClient) -> None:
        response = client.post(
            "/api/brain/ingest",
            json={
                "type": "note",
                "title": "Testing notes",
                "content": "Pytest is great for Python tests.",
                "tags": ["testing", "python"],
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["stored"] is True
        assert "memory_id" in body

        search = client.get("/api/brain/search", params={"q": "Pytest"})
        assert search.status_code == 200
        results = search.json()
        assert results["count"] >= 1
        assert any("Pytest" in m["content_preview"] for m in results["memories"])

    def test_list_memories(self, client: TestClient) -> None:
        client.post(
            "/api/brain/ingest",
            json={"type": "note", "title": "List test", "content": "content"},
        )
        response = client.get("/api/brain/memories")
        assert response.status_code == 200
        body = response.json()
        assert body["count"] >= 1
        assert "memories" in body

    def test_delete_memory(self, client: TestClient) -> None:
        response = client.post(
            "/api/brain/ingest",
            json={"type": "note", "title": "Delete me", "content": "temp"},
        )
        memory_id = response.json()["memory_id"]

        delete = client.delete(f"/api/brain/memories/{memory_id}")
        assert delete.status_code == 200
        assert delete.json()["deleted"] is True

        search = client.get("/api/brain/search", params={"q": "Delete me"})
        assert search.json()["count"] == 0
