"""Regression coverage for memory isolation and concurrent persistence."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from backend.knowledge.memory import EmbeddingService, MemoryType
from backend.knowledge.persistent_memory import PersistentMemoryStore


@pytest.mark.asyncio
async def test_failed_concurrent_write_does_not_erase_successful_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    from backend.knowledge import persistent_memory as pm

    monkeypatch.setattr(pm, "DB_PATH", tmp_path / "memories.sqlite")
    embeddings = EmbeddingService()
    first_started = asyncio.Event()
    release_first = asyncio.Event()

    async def embed(text: str) -> list[float]:
        if text == "failing write":
            first_started.set()
            await release_first.wait()
        return embeddings._fallback_embed(text)

    monkeypatch.setattr(embeddings, "embed", embed)
    store = PersistentMemoryStore(embedding_service=embeddings)
    save_memory = store._save_memory

    def save_or_fail(memory, **kwargs):
        if memory.content == "failing write":
            raise sqlite3.OperationalError("simulated failure")
        return save_memory(memory, **kwargs)

    monkeypatch.setattr(store, "_save_memory", save_or_fail)
    first = asyncio.create_task(store.store("failing write"))
    await first_started.wait()
    second = asyncio.create_task(store.store("successful write"))
    await asyncio.sleep(0)
    release_first.set()
    failed, succeeded = await asyncio.gather(first, second, return_exceptions=True)

    assert isinstance(failed, sqlite3.OperationalError)
    assert not isinstance(succeeded, BaseException)
    assert store.get(succeeded.memory_id) is not None
    restarted = PersistentMemoryStore(embedding_service=embeddings)
    assert restarted.get(succeeded.memory_id) is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [True, False])
async def test_automatic_answer_stays_in_its_session_after_restart(
    monkeypatch: pytest.MonkeyPatch, tmp_path, legacy: bool
) -> None:
    from backend.knowledge import persistent_memory as pm

    monkeypatch.setattr(pm, "DB_PATH", tmp_path / "memories.sqlite")
    embeddings = EmbeddingService()

    async def embed(text: str) -> list[float]:
        return embeddings._fallback_embed(text)

    monkeypatch.setattr(embeddings, "embed", embed)
    store = PersistentMemoryStore(embedding_service=embeddings)
    tags = ["agent.run", "nexus", "auto_memory"]
    if not legacy:
        tags.append("assistant_response")
    await store.store(
        "unique private outcome",
        user_id="alice",
        session_id="one",
        project_id="project",
        memory_type=MemoryType.CONVERSATION,
        tags=tags,
    )
    restarted = PersistentMemoryStore(embedding_service=embeddings)
    own = await restarted.get_context(
        "unique private outcome", user_id="alice", session_id="one", project_id="project"
    )
    other = await restarted.get_context(
        "unique private outcome", user_id="alice", session_id="two", project_id="project"
    )
    assert "unique private outcome" in own
    assert "unique private outcome" not in other
