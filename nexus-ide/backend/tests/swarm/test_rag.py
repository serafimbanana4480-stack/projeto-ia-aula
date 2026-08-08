"""Unit tests for SWARM RAG retriever & chunker.

Embeddings are disabled by default in tests so the suite runs offline.
"""

from __future__ import annotations

from backend.swarm.rag.chunker import (
    chunk_text,
    detect_language,
    extract_keywords,
)
from backend.swarm.rag.retriever import InMemoryIndex, SwarmRetriever


def test_detect_language() -> None:
    assert detect_language("foo.py") == "python"
    assert detect_language("foo.tsx") == "tsx"
    assert detect_language("foo.md") == "markdown"
    assert detect_language("foo") == ""


def test_chunk_text_splits_paragraphs() -> None:
    text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
    chunks = chunk_text(text, source_path="x.md", target_chars=20, overlap_chars=5)
    assert len(chunks) >= 1
    assert all(c.source_path == "x.md" for c in chunks)


def test_chunk_text_includes_line_ranges() -> None:
    text = "line 1\nline 2\n\nline 4\nline 5"
    chunks = chunk_text(text, source_path="x.py", target_chars=500, overlap_chars=0)
    assert chunks
    assert all(c.end_line >= c.start_line for c in chunks)


def test_extract_keywords_strips_stopwords() -> None:
    kws = extract_keywords("the quick brown fox jumps over the lazy dog and the cat")
    assert "the" not in kws
    assert "quick" in kws or "brown" in kws


def test_in_memory_index_bm25_ranks_relevant_higher() -> None:
    from backend.swarm.rag.chunker import chunk_text

    # Small target_chars so each paragraph becomes its own chunk
    chunks = chunk_text(
        "authentication flow uses JWT tokens\n"
        "\n"
        "database connection pooling\n"
        "\n"
        "JWT token validation in middleware",
        source_path="a.py",
        target_chars=50,
        overlap_chars=0,
    )
    assert len(chunks) >= 2, f"expected multiple chunks, got {len(chunks)}"
    idx = InMemoryIndex()
    idx.add(chunks)
    # Chunk 0 is the JWT one, chunk 1 is the DB one
    s_jwt = idx.bm25_score("JWT authentication", chunks[0].chunk_id)
    s_db = idx.bm25_score("JWT authentication", chunks[1].chunk_id)
    assert s_jwt > s_db


def test_retriever_hybrid_search() -> None:
    from backend.swarm.rag.chunker import chunk_text

    chunks = chunk_text(
        "Use bcrypt for password hashing\n"
        "\n"
        "Tokens must be rotated weekly\n"
        "\n"
        "bcrypt with cost factor 12 is recommended",
        source_path="auth.md",
        target_chars=500,
    )
    # Embeddings disabled — keep the test offline-friendly
    r = SwarmRetriever(enable_embeddings=False)
    r.add_chunks(chunks)
    hits = r.retrieve("password hashing bcrypt", top_k=3)
    assert hits
    # Best hit must mention bcrypt (the keyword leg is what we exercise)
    assert "bcrypt" in hits[0].text.lower()


def test_retriever_no_chunks_returns_empty() -> None:
    r = SwarmRetriever(enable_embeddings=False)
    assert r.retrieve("anything", top_k=5) == []


def test_retriever_stats_track_chunks() -> None:
    r = SwarmRetriever(enable_embeddings=False)
    from backend.swarm.rag.chunker import chunk_text

    r.add_chunks(chunk_text("alpha beta gamma", source_path="a.py"))
    s = r.stats()
    assert s["chunks"] >= 1
    assert s["embeddings"] == 0  # we disabled them


def test_retriever_scopes_hits_to_project() -> None:
    r = SwarmRetriever(enable_embeddings=False)
    from pathlib import Path
    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        first = root / "first"
        second = root / "second"
        first.mkdir()
        second.mkdir()
        r.add_chunks(chunk_text("alpha only", source_path=str(first / "a.py")))
        r.add_chunks(chunk_text("beta only", source_path=str(second / "b.py")))

        hits = r.retrieve("alpha", project_path=str(second))
        assert hits == []
