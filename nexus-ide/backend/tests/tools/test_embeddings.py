"""Tests for backend.tools.embeddings."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.tools import embeddings as emb


class TestEmbed:
    def test_function_exists(self) -> None:
        assert callable(emb.embed)


class TestChunking:
    def test_chunk_by_lines_basic(self) -> None:
        content = "\n".join(f"line {i}" for i in range(1, 11))
        chunks = emb._chunk_by_lines(content, chunk_size=4, overlap=1)
        assert len(chunks) > 0
        assert chunks[0][0] == 1
        assert chunks[0][2].startswith("line 1")

    def test_chunk_python_extracts_functions(self) -> None:
        content = '''
def hello():
    """Say hello."""
    return "hello"

class Greeter:
    def greet(self, name: str) -> str:
        return f"hi {name}"
'''
        chunks = emb._chunk_python(content)
        names = {c[4] for c in chunks if c[4]}
        assert "hello" in names
        assert "Greeter" in names

    def test_detect_language(self) -> None:
        assert emb._detect_language(Path("foo.py")) == "python"
        assert emb._detect_language(Path("foo.ts")) == "typescript"
        assert emb._detect_language(Path("foo.md")) == "markdown"
        assert emb._detect_language(Path("foo.unknown")) == ""


class TestIndexPersistence:
    @pytest.mark.asyncio
    async def test_index_and_search_codebase(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "math.py").write_text(
            "def add(a, b):\n    return a + b\n\ndef sub(a, b):\n    return a - b\n",
            encoding="utf-8",
        )

        # Force reindex with a clean store
        emb._store.clear()
        count = await emb.index_codebase(str(tmp_path), force_reindex=True)
        assert count >= 1

        results = await emb.search_codebase("add two numbers")
        assert len(results) > 0
        assert any("add" in r.content for r in results)

        stats = await emb.get_index_stats()
        assert stats["total_chunks"] >= count
        assert stats["total_files"] >= 1

    @pytest.mark.asyncio
    async def test_incremental_index_skips_unchanged(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "math.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")

        emb._store.clear()
        await emb.index_codebase(str(tmp_path), force_reindex=True)
        second = await emb.index_codebase(str(tmp_path))
        assert second == 0


class TestKeywordSearch:
    @pytest.mark.asyncio
    async def test_keyword_search_fallback(self, tmp_path: Path) -> None:
        src = tmp_path / "src"
        src.mkdir()
        (src / "math.py").write_text("def multiply(a, b):\n    return a * b\n", encoding="utf-8")
        # Inject a fake chunk without embeddings
        emb._store.clear()
        chunk = emb.CodeChunk(
            file=str(src / "math.py"),
            start_line=1,
            end_line=2,
            content="def multiply(a, b):\n    return a * b\n",
            language="python",
            symbol_name="multiply",
            symbol_type="function",
        )
        emb._store["test::1"] = ([1.0, 0.0], chunk)
        results = emb._keyword_search("multiply", k=5)
        assert len(results) > 0
        assert any("multiply" in r.content for r in results)

    @pytest.mark.asyncio
    async def test_offline_index_keeps_chunks_and_scopes_search(self, tmp_path: Path, monkeypatch) -> None:
        first = tmp_path / "first"
        second = tmp_path / "second"
        first.mkdir()
        second.mkdir()
        (first / "a.txt").write_text("alpha project only", encoding="utf-8")
        (second / "b.txt").write_text("beta project only", encoding="utf-8")

        async def no_embeddings(texts, model):
            return [None for _ in texts]

        monkeypatch.setattr(emb, "_embed_batch_with_fallback", no_embeddings)
        monkeypatch.setattr(emb, "INDEX_SNAPSHOT_PATH", tmp_path / "index.json")
        monkeypatch.setattr(emb, "INDEX_META_PATH", tmp_path / "meta.json")
        emb._store.clear()

        assert await emb.index_codebase(str(first), force_reindex=True) == 1
        assert await emb.index_codebase(str(second)) == 1
        assert len(emb._store) == 2

        results = await emb.search_codebase("alpha", project_path=str(second))
        assert results == []
