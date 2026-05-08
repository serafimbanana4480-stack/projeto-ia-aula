"""Semantic search over the codebase using qwen3-embedding:4b + ChromaDB."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CodeChunk:
    file: str
    start_line: int
    end_line: int
    content: str
    score: float = 0.0


async def embed(text: str) -> list[float]:
    """Generate an embedding via Ollama `qwen3-embedding:4b`."""
    raise NotImplementedError


async def index_codebase(root: str) -> int:
    """Walk `root`, chunk files, embed and store in Chroma. Returns chunk count."""
    raise NotImplementedError


async def search_codebase(query: str, k: int = 8) -> list[CodeChunk]:
    """Semantic search returning top-k code chunks."""
    raise NotImplementedError
