"""Tests for backend.tools.memory_tools."""

from __future__ import annotations

import pytest

from backend.tools.memory_tools import recall_context, store_memory


class TestMemoryTools:
    @pytest.mark.asyncio
    async def test_store_and_recall(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from backend.knowledge.memory import EmbeddingService, MemoryStore

        svc = EmbeddingService()

        async def _fast_embed(text: str) -> list[float]:
            return svc._fallback_embed(text)

        monkeypatch.setattr(svc, "embed", _fast_embed)
        store = MemoryStore(embedding_service=svc, max_memories=100)
        monkeypatch.setattr(
            "backend.tools.memory_tools.get_memory_store",
            lambda: store,
        )

        result = await store_memory(
            content="PostgreSQL is the primary database",
            memory_type="global",
            tags="database,postgres",
            source="TEST",
            user_id="test-user",
        )
        assert result["stored"] is True
        assert "memory_id" in result

        # Search with the same text to guarantee similarity with fallback embeddings
        recall = await recall_context(
            "PostgreSQL primary database", top_k=5, user_id="test-user"
        )
        assert "memories" in recall
        assert any("PostgreSQL" in m["content"] for m in recall["memories"])

    @pytest.mark.asyncio
    async def test_recall_empty_query(self) -> None:
        result = await recall_context("   ")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_store_empty_content(self) -> None:
        result = await store_memory("   ")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_memory_tools_fail_closed_without_authenticated_user(self) -> None:
        assert "trusted authenticated user" in (await recall_context("project"))["error"]
        assert "trusted authenticated user" in (await store_memory("private note"))["error"]

    @pytest.mark.asyncio
    async def test_recall_context_never_returns_another_users_memory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.knowledge.memory import EmbeddingService, MemoryStore

        service = EmbeddingService()

        async def fast_embed(text: str) -> list[float]:
            return service._fallback_embed(text)

        monkeypatch.setattr(service, "embed", fast_embed)
        store = MemoryStore(embedding_service=service, max_memories=100)
        monkeypatch.setattr("backend.tools.memory_tools.get_memory_store", lambda: store)
        await store_memory(
            content="Alice private orchid migration token",
            user_id="alice",
            session_id="alice-session",
        )
        await store_memory(
            content="Bob private orchid migration token",
            user_id="bob",
            session_id="bob-session",
        )

        result = await recall_context("orchid migration token", user_id="alice", top_k=10)

        contents = [memory["content"] for memory in result["memories"]]
        assert any("Alice private" in content for content in contents)
        assert all("Bob private" not in content for content in contents)

    @pytest.mark.asyncio
    async def test_registry_overrides_model_supplied_memory_owner_and_session(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.knowledge.memory import EmbeddingService, MemoryStore
        from backend.tools.registry import execute_tool

        service = EmbeddingService()

        async def fast_embed(text: str) -> list[float]:
            return service._fallback_embed(text)

        monkeypatch.setattr(service, "embed", fast_embed)
        store = MemoryStore(embedding_service=service, max_memories=100)
        monkeypatch.setattr("backend.tools.memory_tools.get_memory_store", lambda: store)

        result = await execute_tool(
            "store_memory",
            "trusted-session",
            {
                "content": "trusted owner record",
                "session_id": "victim-session",
                "user_id": "victim",
                "project_path": "C:/untrusted/model/path",
            },
            user_id="trusted-user",
            project_path="",
        )

        assert result["ok"] is True
        memory = next(iter(store._memories.values()))
        assert memory.user_id == "trusted-user"
        assert memory.session_id == "trusted-session"

    @pytest.mark.asyncio
    async def test_registry_confines_memory_to_selected_project(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.knowledge.memory import EmbeddingService, MemoryStore, MemoryType
        from backend.tools.registry import execute_tool

        service = EmbeddingService()

        async def fast_embed(text: str) -> list[float]:
            return service._fallback_embed(text)

        monkeypatch.setattr(service, "embed", fast_embed)
        store = MemoryStore(embedding_service=service)
        monkeypatch.setattr("backend.tools.memory_tools.get_memory_store", lambda: store)
        await store.store("orchid alpha", user_id="alice", project_id="alpha", memory_type=MemoryType.PROJECT)
        await store.store("orchid beta", user_id="alice", project_id="beta", memory_type=MemoryType.PROJECT)
        await store.store("orchid global", user_id="alice", memory_type=MemoryType.GLOBAL)

        result = await execute_tool(
            "recall_context", "s1", {"query": "orchid", "project_id": "beta"},
            user_id="alice", project_path="alpha",
        )
        assert result["ok"] is True
        content = str(result["result"])
        assert "orchid alpha" in content
        assert "orchid global" in content
        assert "orchid beta" not in content

        result = await execute_tool(
            "store_memory", "s1", {"content": "orchid new", "project_id": "beta"},
            user_id="alice", project_path="alpha",
        )
        assert result["ok"] is True
        assert next(m for m in store._memories.values() if m.content == "orchid new").project_id == "alpha"

        result = await execute_tool(
            "recall_context", "s1", {"query": "orchid"}, user_id="alice", project_path="",
        )
        content = str(result["result"])
        assert "orchid global" in content
        assert "orchid alpha" not in content and "orchid beta" not in content

    @pytest.mark.asyncio
    async def test_registry_confines_bot_memory_even_with_a_selected_project(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from backend.knowledge.memory import EmbeddingService, MemoryStore, MemoryType
        from backend.tools.registry import execute_tool

        service = EmbeddingService()

        async def fast_embed(text: str) -> list[float]:
            return service._fallback_embed(text)

        monkeypatch.setattr(service, "embed", fast_embed)
        store = MemoryStore(embedding_service=service)
        monkeypatch.setattr("backend.tools.memory_tools.get_memory_store", lambda: store)
        await store.store("orchid global", user_id="alice", memory_type=MemoryType.GLOBAL)
        await store.store("orchid other bot", user_id="alice", session_id="other")
        result = await execute_tool(
            "store_memory", "bot-a",
            {"content": "orchid bot note", "memory_type": "global", "project_id": "beta"},
            user_id="alice", project_path="alpha", memory_session_only=True,
        )
        assert result["ok"] is True
        memory = next(m for m in store._memories.values() if m.content == "orchid bot note")
        assert (memory.memory_type, memory.project_id, memory.session_id) == (
            MemoryType.SESSION, "", "bot-a",
        )
        result = await execute_tool(
            "recall_context", "bot-a", {"query": "orchid", "memory_type": "global"},
            user_id="alice", project_path="alpha", memory_session_only=True,
        )
        assert result["ok"] is True
        content = str(result["result"])
        assert "orchid bot note" in content
        assert "orchid global" not in content and "orchid other bot" not in content
