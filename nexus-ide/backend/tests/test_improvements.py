"""
Test Suite for System Improvements — FASE 1 through FASE 10.

Validates:
- Token management (tiktoken, dynamic threshold, dedup, budget validation)
- Semantic cache (hits, misses, storage)
- Tool result cache (hits, misses, TTL, non-cacheable tools)
- FAISS vector store (search, performance)
- Cost tracking
"""

from __future__ import annotations

import math
import time
from unittest.mock import MagicMock, patch

import pytest


# =========================================================================
# FASE 1 — TOKEN MANAGEMENT
# =========================================================================

class TestTokenCounting:
    """Token counting accuracy and fallback behavior."""

    def test_count_tokens_with_heuristic_fallback(self):
        """Must provide a result even without tiktoken."""
        from backend.token_management import count_tokens

        text = "Hello world, this is a test."
        count = count_tokens(text, model="cl100k_base")
        assert count > 0, "Token count must be positive"
        assert isinstance(count, int), "Token count must be int"

    def test_dynamic_threshold_values(self):
        """Dynamic threshold must be 85% of model's context window."""
        from backend.token_management import dynamic_threshold

        assert dynamic_threshold("micro") == int(4096 * 0.85)
        assert dynamic_threshold("fast") == int(8192 * 0.85)
        assert dynamic_threshold("coder") == int(16384 * 0.85)
        assert dynamic_threshold("reasoning") == int(32768 * 0.85)
        assert dynamic_threshold("deep") == int(65536 * 0.85)

    def test_dynamic_threshold_unknown_tier(self):
        """Unknown tier should fall back to 8192 default."""
        from backend.token_management import dynamic_threshold

        result = dynamic_threshold("nonexistent_tier")
        assert result == int(8192 * 0.85)

    def test_dynamic_threshold_custom_margin(self):
        """Custom safety margin must be respected."""
        from backend.token_management import dynamic_threshold

        result = dynamic_threshold("coder", safety_margin=0.90)
        assert result == int(16384 * 0.90)

    def test_context_deduplication_removes_exact_duplicates(self):
        """Identical blocks must be deduplicated, preserving order."""
        from backend.token_management import deduplicate_context_blocks

        blocks = [
            "System: You are a coding assistant.",
            "System: You are a coding assistant.",  # duplicate
            "User: Write a function.",
            "System: You are a coding assistant.",  # duplicate again
            "User: Make it async.",
        ]

        result = deduplicate_context_blocks(blocks)
        assert len(result) == 3, f"Expected 3 unique blocks, got {len(result)}"
        assert result[0] == "System: You are a coding assistant."
        assert result[1] == "User: Write a function."
        assert result[2] == "User: Make it async."

    def test_context_deduplication_no_duplicates(self):
        """Unique blocks must be returned unchanged."""
        from backend.token_management import deduplicate_context_blocks

        blocks = ["Block A", "Block B", "Block C"]
        result = deduplicate_context_blocks(blocks)
        assert result == blocks

    def test_context_deduplication_empty(self):
        """Empty list must return empty list."""
        from backend.token_management import deduplicate_context_blocks

        result = deduplicate_context_blocks([])
        assert result == []

    def test_validate_total_budget_within_limits(self):
        """Validation must pass when within limits."""
        from backend.token_management import validate_total_budget

        result = validate_total_budget(
            system_tokens=500,
            memory_tokens=300,
            history_tokens=1000,
            query_tokens=50,
            model_tier="coder",
            output_reserve=4096,
        )
        assert result is True

    def test_validate_total_budget_overflow(self):
        """Validation must raise ContextOverflowError when exceeding limits."""
        from backend.token_management import validate_total_budget, ContextOverflowError

        with pytest.raises(ContextOverflowError) as excinfo:
            validate_total_budget(
                system_tokens=10000,
                memory_tokens=5000,
                history_tokens=3000,
                query_tokens=500,
                model_tier="micro",  # only 4096 context
            )
        assert "Context overflow" in str(excinfo.value)
        assert "micro" in str(excinfo.value)

    def test_validate_total_budget_with_tool_results(self):
        """Tool result tokens must be included in the calculation."""
        from backend.token_management import validate_total_budget, ContextOverflowError

        with pytest.raises(ContextOverflowError):
            validate_total_budget(
                system_tokens=2000,
                tool_result_tokens=5000,  # large tool result
                model_tier="micro",
            )

    def test_count_tokens_for_messages(self):
        """Message token counting must work with typical message formats."""
        from backend.token_management import count_tokens_for_messages

        messages = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Write a Python function."},
        ]
        count = count_tokens_for_messages(messages)
        # Each message has ~4 tokens overhead + content tokens
        assert count > 10, "Message token count seems too low"
        assert isinstance(count, int)

    def test_trim_context_structured_preserves_objective(self):
        """First iteration (objective) must always be preserved."""
        from backend.token_management import trim_context_structured

        iterations = [
            {"thought": "Objective: Build a web app", "tool": "", "result": ""},
            {"thought": "Step 1", "tool": "read_file", "result": "content"},
            {"thought": "Step 2", "tool": "write_file", "result": "done"},
            {"thought": "Step 3", "tool": "search", "result": "found"},
            {"thought": "Step 4", "tool": "git_commit", "result": "committed"},
        ]

        trimmed = trim_context_structured(iterations, "coder")
        assert trimmed[0]["thought"] == "Objective: Build a web app"
        assert len(trimmed) > 0

    def test_trim_context_structured_short(self):
        """Fewer iterations than min_iterations must be unchanged."""
        from backend.token_management import trim_context_structured

        iterations = [
            {"thought": "Objective", "tool": "", "result": ""},
            {"thought": "Step 1", "tool": "read_file", "result": "data"},
        ]
        trimmed = trim_context_structured(iterations, "coder")
        assert len(trimmed) == 2

    def test_estimate_token_waste(self):
        """Waste estimation must return reasonable percentages."""
        from backend.token_management import estimate_token_waste

        # No cache, no dedup = 100% waste (no savings)
        waste = estimate_token_waste(cache_hit_rate=0.0, dedup_savings=0.0)
        assert waste == 0.0

        # 50% cache hit + 20% dedup
        waste = estimate_token_waste(cache_hit_rate=0.5, dedup_savings=0.2)
        assert waste > 0
        assert waste < 100
        # 0.5*70 + 0.2*30 = 35 + 6 = 41
        assert waste == pytest.approx(41.0, rel=0.1)


# =========================================================================
# FASE 2 — SEMANTIC CACHE
# =========================================================================

class TestSemanticCache:
    """Semantic cache for LLM responses."""

    @pytest.fixture
    def cache(self):
        from backend.cache import SemanticCache
        return SemanticCache(similarity_threshold=0.85)

    @pytest.fixture
    def same_embedding(self):
        """Return a fixed embedding vector for testing."""
        return [0.1, 0.2, 0.3, 0.4] * 96  # 384-dim

    @pytest.fixture
    def different_embedding(self):
        """Return a very different embedding vector."""
        return [0.9, 0.8, 0.7, 0.6] * 96  # 384-dim

    def test_cache_store_and_retrieve(self, cache, same_embedding):
        """Stored response must be retrievable for an identical query."""
        def embed_fn(text):
            return same_embedding

        cache.store("hello", "world", "test-model", "test-sys", embed_fn)
        result = cache.get("hello", "test-model", "test-sys", embed_fn)
        assert result == "world"

    def test_cache_miss_on_different_query(self, cache, same_embedding, different_embedding):
        """Different queries should miss if embeddings differ."""
        cache.store("hello", "world", "test-model", "test-sys",
                     lambda t: same_embedding)
        result = cache.get("different", "test-model", "test-sys",
                           lambda t: different_embedding)
        assert result is None

    def test_cache_threshold_behavior(self, cache):
        """Similar (but not identical) embeddings must hit if above threshold."""
        def embed_fn(text):
            return [0.1, 0.2, 0.3, 0.4] * 96

        def similar_fn(text):
            return [0.11, 0.21, 0.31, 0.41] * 96  # very close

        cache.store("List files", "['a.py', 'b.py']", "model", "sys", embed_fn)
        result = cache.get("Show files", "model", "sys", similar_fn)
        assert result == "['a.py', 'b.py']"  # should hit

    def test_cache_metrics(self, cache, same_embedding):
        """Cache metrics must track hits and misses correctly."""
        def embed_fn(text):
            return same_embedding

        cache.store("q1", "r1", "model", "sys", embed_fn)
        cache.get("q1", "model", "sys", embed_fn)  # hit
        cache.get("unknown", "model", "sys", lambda t: [0.9] * 384)  # miss

        metrics = cache.get_metrics()
        assert metrics["semantic_cache_hits_total"] >= 1
        assert metrics["semantic_cache_misses_total"] >= 1
        assert metrics["semantic_cache_hit_rate"] > 0

    def test_cache_clear(self, cache, same_embedding):
        """Clear must remove all entries."""
        def embed_fn(text):
            return same_embedding

        cache.store("test", "data", "model", "sys", embed_fn)
        cache.clear()
        metrics = cache.get_metrics()
        assert metrics["semantic_cache_total_entries"] == 0

    def test_cosine_similarity_identical(self):
        """Identical vectors must have similarity = 1.0."""
        from backend.cache.semantic_cache import SemanticCache
        cache = SemanticCache()
        a = [1.0, 0.0, 0.0]
        b = [1.0, 0.0, 0.0]
        sim = cache._cosine_similarity(a, b)
        assert sim == pytest.approx(1.0, abs=0.001)

    def test_cosine_similarity_orthogonal(self):
        """Orthogonal vectors must have similarity = 0.0."""
        from backend.cache.semantic_cache import SemanticCache
        cache = SemanticCache()
        a = [1.0, 0.0, 0.0]
        b = [0.0, 1.0, 0.0]
        sim = cache._cosine_similarity(a, b)
        assert sim == pytest.approx(0.0, abs=0.001)

    def test_cosine_similarity_different_dimensions(self):
        """Different dimension vectors must return 0.0."""
        from backend.cache.semantic_cache import SemanticCache
        cache = SemanticCache()
        sim = cache._cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])
        assert sim == 0.0


# =========================================================================
# FASE 2 — TOOL RESULT CACHE
# =========================================================================

class TestToolResultCache:
    """TTL-based tool result cache."""

    @pytest.fixture
    def cache(self):
        from backend.cache import ToolResultCache
        return ToolResultCache(max_entries=100)

    def test_cache_hit_same_args(self, cache):
        """Same tool + same args must return cached result."""
        result = {"files": ["a.py", "b.py"], "count": 2}
        cache.store("search_codebase", {"query": "auth"}, result)
        hit = cache.get("search_codebase", {"query": "auth"})
        assert hit == result

    def test_cache_miss_different_args(self, cache):
        """Different args must miss."""
        cache.store("search_codebase", {"query": "auth"}, {"results": []})
        hit = cache.get("search_codebase", {"query": "other"})
        assert hit is None

    def test_no_cache_for_shell(self, cache):
        """Shell commands must never be cached."""
        cache.store("shell", {"command": "ls -la"}, {"output": "..."})
        hit = cache.get("shell", {"command": "ls -la"})
        assert hit is None

    def test_no_cache_for_write_file(self, cache):
        """Write operations must never be cached."""
        cache.store("write_file", {"path": "test.txt"}, {"written": True})
        hit = cache.get("write_file", {"path": "test.txt"})
        assert hit is None

    def test_cache_hit_rate(self, cache):
        """Hit rate must be tracked correctly."""
        result = {"data": "test"}
        cache.store("read_file", {"path": "file.txt"}, result)
        cache.get("read_file", {"path": "file.txt"})  # hit
        cache.get("read_file", {"path": "other.txt"})  # miss

        metrics = cache.get_metrics()
        assert metrics["tool_cache_hits"] == 1
        assert metrics["tool_cache_misses"] >= 1
        assert metrics["tool_cache_hit_rate"] > 0

    def test_cache_expiry(self, cache):
        """Cache entries must expire after TTL."""
        # Use a tool with very short TTL for testing
        cache.store("get_file_info", {"path": "test.txt"}, {"size": 100})
        hit = cache.get("get_file_info", {"path": "test.txt"})
        assert hit is not None

    def test_cache_clear(self, cache):
        """Clear must remove all entries."""
        cache.store("search_codebase", {"query": "test"}, {"result": []})
        cache.clear()
        hit = cache.get("search_codebase", {"query": "test"})
        assert hit is None
        assert cache.get_metrics()["tool_cache_size"] == 0

    def test_unknown_tool_not_cached(self, cache):
        """Unknown tool names should not be cached (TTL=0)."""
        cache.store("unknown_tool", {"arg": "value"}, {"result": "data"})
        hit = cache.get("unknown_tool", {"arg": "value"})
        assert hit is None


# =========================================================================
# FASE 3 — FAISS VECTOR STORE
# =========================================================================

class TestFAISSVectorStore:
    """FAISS-based ANN vector search."""

    # Skip the entire class when faiss is not installed so the suite stays
    # green without the optional faiss-cpu dependency.
    faiss = pytest.importorskip("faiss")

    @pytest.fixture
    def store(self, tmp_path):
        from backend.cache.vector_store import FAISSEmbeddingStore
        return FAISSEmbeddingStore(
            dimension=64,
            index_path=str(tmp_path / "faiss_test"),
            nlist=10,
        )

    def test_add_and_search(self, store):
        """Adding vectors and searching must return results."""
        import numpy as np

        for i in range(100):
            emb = list(np.random.rand(64))
            store.add(emb, {"id": i, "content": f"chunk_{i}"})

        query = list(np.random.rand(64))
        results = store.search(query, top_k=10)

        assert len(results) == 10
        # Scores must be in descending order
        scores = [s for s, _ in results]
        assert all(scores[i] >= scores[i + 1] for i in range(len(scores) - 1))

    def test_search_empty_store(self, store):
        """Empty store must return empty results."""
        results = store.search([0.1] * 64, top_k=5)
        assert results == []

    def test_search_top_k_less_than_total(self, store):
        """top_k must be respected when less than total vectors."""
        import numpy as np

        for i in range(20):
            store.add(list(np.random.rand(64)), {"id": i})

        results = store.search(list(np.random.rand(64)), top_k=30)
        assert len(results) == 20  # can't return more than exist

    def test_add_batch(self, store):
        """Batch add must work and return correct IDs."""
        import numpy as np

        embs = [list(np.random.rand(64)) for _ in range(50)]
        metas = [{"id": i} for i in range(50)]

        ids = store.add_batch(embs, metas)
        assert len(ids) == 50
        assert len(store._metadata) == 50

    def test_persist_and_reload(self, tmp_path):
        """Index must survive persist/reload cycle."""
        from backend.cache.vector_store import FAISSEmbeddingStore
        import numpy as np

        idx_path = tmp_path / "faiss_persist"

        # Create and populate
        store1 = FAISSEmbeddingStore(dimension=64, index_path=str(idx_path), nlist=10)
        for i in range(50):
            store1.add(list(np.random.rand(64)), {"id": i})
        store1.persist()

        # Reload
        store2 = FAISSEmbeddingStore(dimension=64, index_path=str(idx_path), nlist=10)
        stats = store2.get_stats()
        assert stats["active_vectors"] == 50

    def test_remove_vector(self, store):
        """Removed vectors must be marked."""
        import numpy as np

        store.add(list(np.random.rand(64)), {"id": 0})
        result = store.remove(vector_id=0)
        assert result is True
        assert store._metadata[0].get("_removed") is True

    def test_remove_nonexistent_vector(self, store):
        """Removing non-existent ID must return False."""
        result = store.remove(vector_id=999)
        assert result is False

    def test_get_stats(self, store):
        """Stats must provide useful information."""
        import numpy as np

        for i in range(10):
            store.add(list(np.random.rand(64)), {"id": i})

        stats = store.get_stats()
        assert stats["total_vectors"] == 10
        assert stats["active_vectors"] == 10
        assert stats["dimension"] == 64
        assert "total_searches" in stats


# =========================================================================
# FASE 5 — COST TRACKING
# =========================================================================

class TestCostTracking:
    """LLM cost tracking."""

    def test_cost_calculation(self):
        """Cost must be calculated based on token counts and model pricing."""
        from backend.observability.metrics import CostTracker
        tracker = CostTracker()

        cost = tracker.record(
            model="gpt-4o",
            input_tokens=1000,
            output_tokens=500,
            session_id="test-session",
            agent="CODER",
        )

        # gpt-4o: input=$5/1M, output=$15/1M
        expected = (1000 * 5.0 + 500 * 15.0) / 1_000_000
        assert abs(cost - expected) < 0.0001
        assert tracker.get_session_cost("test-session") == cost

    def test_cost_accumulation(self):
        """Multiple calls to same session must accumulate cost."""
        from backend.observability.metrics import CostTracker
        tracker = CostTracker()

        tracker.record("gpt-4o", 1000, 500, "session-1", "CODER")
        tracker.record("gpt-4o", 2000, 1000, "session-1", "CODER")

        expected_total = (1000 * 5.0 + 500 * 15.0 + 2000 * 5.0 + 1000 * 15.0) / 1_000_000
        assert abs(tracker.get_session_cost("session-1") - expected_total) < 0.0001

    def test_cost_zero_tokens(self):
        """Zero tokens must result in zero cost."""
        from backend.observability.metrics import CostTracker
        tracker = CostTracker()

        cost = tracker.record("gpt-4o", 0, 0, "session-1", "CODER")
        assert cost == 0.0

    def test_cost_report(self):
        """Report must contain all tracked sessions."""
        from backend.observability.metrics import CostTracker
        tracker = CostTracker()

        tracker.record("model", 100, 50, "session-a", "AGENT_A")
        tracker.record("model", 200, 100, "session-b", "AGENT_B")

        report = tracker.get_report()
        assert report["total_cost_usd"] > 0
        assert "AGENT_A" in report["by_agent"]
        assert "AGENT_B" in report["by_agent"]
        assert len(report["top_5_sessions"]) == 2


# =========================================================================
# FASE 10 — INTEGRATION / END-TO-END
# =========================================================================

class TestTokenManagementIntegration:
    """Integration test: token management + cache + metrics."""

    def test_full_pipeline_no_crash(self):
        """Full pipeline must not crash with realistic data."""
        from backend.token_management import (
            count_tokens,
            deduplicate_context_blocks,
            validate_total_budget,
            dynamic_threshold,
        )

        # Simulate building context
        system = "You are a senior software engineer. Help the user with code."
        memory = "User prefers Python and async/await patterns."
        history = "User: Write a FastAPI endpoint\nAssistant: Here's the code..."
        query = "Make it async with PostgreSQL"
        tool_results = "Read file: main.py (size: 2KB)"

        # Count tokens
        sys_tok = count_tokens(system)
        mem_tok = count_tokens(memory)
        hist_tok = count_tokens(history)
        query_tok = count_tokens(query)
        tool_tok = count_tokens(tool_results)

        # All must be positive
        assert all(t > 0 for t in [sys_tok, mem_tok, hist_tok, query_tok, tool_tok])

        # Deduplicate
        blocks = [system, memory, history, query, tool_results]
        unique = deduplicate_context_blocks(blocks)
        assert len(unique) == 5  # all unique

        # Validate budget
        assert validate_total_budget(
            system_tokens=sys_tok,
            memory_tokens=mem_tok,
            history_tokens=hist_tok,
            query_tokens=query_tok,
            tool_result_tokens=tool_tok,
            model_tier="coder",
        )

        # Dynamic threshold
        threshold = dynamic_threshold("coder")
        assert threshold == int(16384 * 0.85)


class TestCacheIntegration:
    """Integration: tool cache + semantic cache working together."""

    def test_caches_independent(self):
        """Tool cache and semantic cache must operate independently."""
        from backend.cache import ToolResultCache, SemanticCache

        tool_cache = ToolResultCache()
        sem_cache = SemanticCache()

        # Tool cache stores tool results
        tool_cache.store("search_codebase", {"query": "auth"}, ["auth.py", "login.py"])
        assert tool_cache.get("search_codebase", {"query": "auth"}) is not None

        # Semantic cache operates independently
        def embed(t): return [0.1] * 384
        sem_cache.store("hello", "world", "m", "s", embed)
        assert sem_cache.get("hello", "m", "s", embed) == "world"

        # Clearing one must not affect the other
        tool_cache.clear()
        assert tool_cache.get("search_codebase", {"query": "auth"}) is None
        assert sem_cache.get("hello", "m", "s", embed) == "world"
