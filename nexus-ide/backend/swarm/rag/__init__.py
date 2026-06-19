"""SWARM RAG package — indexer, chunker, hybrid retriever."""

from backend.swarm.rag.chunker import (
    TextChunk,
    chunk_files,
    chunk_text,
    detect_language,
    estimate_tokens,
    extract_keywords,
)
from backend.swarm.rag.retriever import (
    InMemoryIndex,
    RetrievalHit,
    SwarmRetriever,
    get_retriever,
    index_directory,
    reset_retriever,
)

__all__ = [
    "TextChunk",
    "chunk_files",
    "chunk_text",
    "detect_language",
    "estimate_tokens",
    "extract_keywords",
    "InMemoryIndex",
    "RetrievalHit",
    "SwarmRetriever",
    "get_retriever",
    "index_directory",
    "reset_retriever",
]
