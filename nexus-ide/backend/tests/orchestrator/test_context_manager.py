"""Tests for backend.orchestrator.context_manager."""

from __future__ import annotations

from backend.history_sanitizer import sanitize_history_content
from backend.orchestrator.context_manager import AgentScratchpad, ContextStore
from backend.persistence.db import add_message, create_session, get_messages
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

    def test_tool_transport_is_removed_from_legacy_assistant_history(self) -> None:
        content = (
            "A executar.\n"
            '```tool\n{"name":"list_dir","arguments":{"path":"."}}\n```\n'
            "Resultado final."
        )
        assert sanitize_history_content("assistant", content) == (
            "A executar.\n\nResultado final."
        )

    def test_repeated_tool_payloads_are_quarantined(self) -> None:
        content = "\n".join(
            [
                '{"name":"list_dir","arguments":{"path":"."}}',
                '{"name":"list_dir","arguments":{"path":"src"}}',
                '{"name":"list_dir","arguments":{"path":"tests"}}',
                "⚠ O modelo repetiu chamadas de ferramenta.",
            ]
        )
        cleaned = sanitize_history_content("assistant", content)
        assert "list_dir" not in cleaned
        assert "nenhuma dessas chamadas" in cleaned
        assert "⚠ O modelo repetiu" in cleaned

    def test_user_content_is_never_sanitized(self) -> None:
        content = 'Mostra este exemplo: {"name":"tool","arguments":{}}'
        assert sanitize_history_content("user", content) == content

    def test_legacy_duplicate_turns_are_collapsed_without_deleting_history(self) -> None:
        session_id = "legacy-duplicate-session"
        create_session(title="Legacy", session_id=session_id)
        add_message(session_id, "user", "verifica o projeto")
        add_message(session_id, "user", "verifica o projeto", tier_used="CODER")
        add_message(session_id, "assistant", "Concluído.", tier_used="CODER")

        messages = get_messages(session_id)

        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert messages[0]["content"] == "verifica o projeto"


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
