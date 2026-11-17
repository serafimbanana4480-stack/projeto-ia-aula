"""Real bot-session memory cycle: ``store_memory`` then ``recall_context``.

These tests exercise the production wiring end to end — the tool registry
(trusted session/user injection, ``memory_session_only`` scoping), the real
``PersistentMemoryStore`` and its SQLite backing table. Only the embedding
provider is substituted for the deterministic lexical fallback, because loading
a transformer model is an external ML dependency unrelated to the memory cycle
under test.
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.knowledge import memory as memory_module
from backend.knowledge.memory import EmbeddingService, MemoryType
from backend.knowledge.persistent_memory import PersistentMemoryStore, _db_path
from backend.tools.registry import execute_tool


async def _fallback_embed(service: EmbeddingService, text: str) -> list[float]:
    return service._fallback_embed(text)


@pytest.mark.asyncio
async def test_bot_session_memory_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    service = EmbeddingService()
    monkeypatch.setattr(service, "embed", lambda text: _fallback_embed(service, text))
    store = PersistentMemoryStore(embedding_service=service)
    monkeypatch.setattr(memory_module, "_memory_store", store)

    session_id = "bot-session-round-trip"
    stored = await execute_tool(
        "store_memory",
        session_id,
        {"content": "O bot Pixel usa Conventional Commits nos commits."},
        user_id="alice",
        memory_session_only=True,
    )
    assert stored["ok"] is True, stored
    assert stored["result"]["stored"] is True

    recalled = await execute_tool(
        "recall_context",
        session_id,
        {"query": "padrão de commits do Pixel"},
        user_id="alice",
        memory_session_only=True,
    )
    assert recalled["ok"] is True, recalled
    memories = recalled["result"]["memories"]
    assert any("Conventional Commits" in item["content"] for item in memories), memories

    # The memory really reached the SQLite table, not just the in-process dict.
    with sqlite3.connect(str(_db_path())) as conn:
        rows = conn.execute(
            "SELECT content, session_id, memory_type FROM persistent_memories "
            "WHERE session_id = ?",
            (session_id,),
        ).fetchall()
    assert any("Conventional Commits" in row[0] for row in rows), rows
    assert all(row[1] == session_id for row in rows), rows
    assert all(row[2] == MemoryType.SESSION.value for row in rows), rows


@pytest.mark.asyncio
async def test_bot_memory_is_private_to_its_session(monkeypatch: pytest.MonkeyPatch) -> None:
    service = EmbeddingService()
    monkeypatch.setattr(service, "embed", lambda text: _fallback_embed(service, text))
    store = PersistentMemoryStore(embedding_service=service)
    monkeypatch.setattr(memory_module, "_memory_store", store)

    await execute_tool(
        "store_memory",
        "bot-session-a",
        {"content": "Orquídea privada do bot Alfa."},
        user_id="alice",
        memory_session_only=True,
    )

    # Another bot session of the same owner must not see it.
    recalled = await execute_tool(
        "recall_context",
        "bot-session-b",
        {"query": "Orquídea privada do bot Alfa"},
        user_id="alice",
        memory_session_only=True,
    )
    assert recalled["ok"] is True, recalled
    assert recalled["result"]["memories"] == [], recalled["result"]["memories"]