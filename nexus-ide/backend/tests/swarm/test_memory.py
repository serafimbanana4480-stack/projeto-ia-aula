"""Unit tests for SWARM memory layers."""

from __future__ import annotations

from backend.swarm.memory.memory_layers import (
    LAYER_NAMES,
    MemoryStore,
    get_memory_store,
    reset_memory_store,
)


def test_layers_present() -> None:
    reset_memory_store()
    store = get_memory_store()
    for name in LAYER_NAMES:
        assert hasattr(store, name)
        assert len(store.layer(name)) == 0


def test_add_and_query() -> None:
    reset_memory_store()
    store = MemoryStore()
    store.add("short_term", "hello world", tags=["greeting"], importance=0.5)
    store.add("long_term", "remember this", tags=["fact"], importance=0.9)
    assert len(store.short_term) == 1
    assert len(store.long_term) == 1

    hits = store.query("hello", layers=["short_term"])
    assert any("hello" in h.content for h in hits)


def test_query_filters_by_layer() -> None:
    reset_memory_store()
    store = MemoryStore()
    store.add("decision", "Use Postgres", tags=["db"], importance=0.8)
    store.add("project", "Postgres at localhost", tags=["db"], importance=0.5)
    hits = store.query("Postgres", layers=["decision"])
    assert all(h.layer == "decision" for h in hits)


def test_capacity_eviction_keeps_important() -> None:
    reset_memory_store()
    store = MemoryStore(capacity_per_layer=3)
    for i in range(5):
        store.add("short_term", f"item {i}", importance=0.1 * i)
    # Highest importance (item 4, 3) survive
    contents = {e.content for e in store.short_term.recent(limit=10)}
    assert "item 4" in contents
    assert "item 0" not in contents


def test_stats() -> None:
    reset_memory_store()
    store = MemoryStore()
    store.add("short_term", "a")
    store.add("long_term", "b")
    s = store.stats()
    assert s == {"short_term": 1, "long_term": 1, "project": 0, "decision": 0, "architecture": 0}
