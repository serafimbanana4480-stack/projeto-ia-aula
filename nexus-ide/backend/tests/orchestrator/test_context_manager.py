"""Tests for backend.orchestrator.context_manager."""
from __future__ import annotations

from backend.orchestrator.context_manager import AgentScratchpad, ContextStore
from backend.tools.ollama_client import ChatMessage


class TestContextStoreHistory:
    async def test_empty_session_returns_empty_list(self) -> None:
        store = ContextStore()
        assert await store.get_history("new-session") == []

    async def test_append_and_read(self) -> None:
        store = ContextStore()
        await store.append_message("s1", ChatMessage(role="user", content="hi"))
        await store.append_message("s1", ChatMessage(role="assistant", content="hello"))
        history = await store.get_history("s1")
        assert [m.role for m in history] == ["user", "assistant"]
        assert history[1].content == "hello"

    async def test_sessions_are_isolated(self) -> None:
        store = ContextStore()
        await store.append_message("s1", ChatMessage(role="user", content="only-s1"))
        assert await store.get_history("s2") == []

    async def test_history_sliding_window(self) -> None:
        store = ContextStore(max_history=3)
        for i in range(5):
            await store.append_message("s1", ChatMessage(role="user", content=str(i)))
        history = await store.get_history("s1")
        assert [m.content for m in history] == ["2", "3", "4"]


class TestContextStoreScratchpad:
    async def test_lazy_creation(self) -> None:
        store = ContextStore()
        pad = await store.get_scratchpad("s1", "CODER")
        assert isinstance(pad, AgentScratchpad)
        assert pad.session_id == "s1"
        assert pad.agent_id == "CODER"
        # Default state.
        assert pad.iteration == 0
        assert pad.observations == []

    async def test_same_key_returns_same_instance(self) -> None:
        store = ContextStore()
        a = await store.get_scratchpad("s1", "CODER")
        b = await store.get_scratchpad("s1", "CODER")
        assert a is b


class TestClearSession:
    async def test_clears_both_history_and_scratchpads(self) -> None:
        store = ContextStore()
        await store.append_message("s1", ChatMessage(role="user", content="x"))
        await store.get_scratchpad("s1", "CODER")
        await store.clear_session("s1")
        assert await store.get_history("s1") == []
        # Fresh scratchpad on next access.
        pad = await store.get_scratchpad("s1", "CODER")
        assert pad.iteration == 0
