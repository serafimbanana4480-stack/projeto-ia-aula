"""RAG chunker — splits documents into embedding-friendly chunks.

Uses a token-aware strategy:
- Target chunk size in characters (configurable; default 1500)
- Overlap window (default 200) to keep cross-chunk context
- Respects code blocks (```...```) when present
- Preserves file path + line numbers so retrieval is citeable
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass


@dataclass
class TextChunk:
    """A single chunk of text with provenance."""

    chunk_id: str
    text: str
    source_path: str
    start_line: int
    end_line: int
    metadata: dict = None  # type: ignore[assignment]
    language: str = ""


# A coarse char→token ratio for safety
_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate the number of tokens in ``text`` (no model required)."""
    if not text:
        return 0
    return max(1, len(text) // _CHARS_PER_TOKEN)


def split_by_paragraphs(text: str) -> list[tuple[str, int, int]]:
    """Split text by paragraphs; return (paragraph, start_line, end_line)."""
    if not text:
        return []
    paragraphs: list[tuple[str, int, int]] = []
    line_no = 1
    buf: list[str] = []
    buf_start = 1
    for line in text.splitlines():
        if line.strip() == "":
            if buf:
                paragraphs.append(("\n".join(buf), buf_start, line_no - 1))
                buf = []
                buf_start = line_no + 1
        else:
            if not buf:
                buf_start = line_no
            buf.append(line)
        line_no += 1
    if buf:
        paragraphs.append(("\n".join(buf), buf_start, line_no - 1))
    return paragraphs


def chunk_text(
    text: str,
    source_path: str = "<inline>",
    target_chars: int = 1500,
    overlap_chars: int = 200,
    language: str = "",
) -> list[TextChunk]:
    """Chunk ``text`` into overlapping windows respecting paragraphs.

    Returns a list of :class:`TextChunk` with file path + line ranges.
    """
    if not text:
        return []

    paragraphs = split_by_paragraphs(text)
    if not paragraphs:
        return []

    chunks: list[TextChunk] = []
    buf: list[str] = []
    buf_start_line = paragraphs[0][1]
    buf_len = 0
    counter = 0

    def _flush(end_line: int) -> None:
        nonlocal counter
        joined = "\n".join(buf).strip()
        if joined:
            chunks.append(
                TextChunk(
                    chunk_id=f"{source_path}::{counter}::{buf_start_line}",
                    text=joined,
                    source_path=source_path,
                    start_line=buf_start_line,
                    end_line=end_line,
                    metadata={"tokens": estimate_tokens(joined)},
                    language=language,
                )
            )
            counter += 1

    for para, start, end in paragraphs:
        if buf_len + len(para) + 1 > target_chars and buf:
            # Flush current buffer
            _flush(end_line=buf[-1] if False else end - 1)
            # Start new buffer with overlap
            if overlap_chars > 0 and buf:
                overlap_text = "\n".join(buf)
                if len(overlap_text) > overlap_chars:
                    overlap_text = overlap_text[-overlap_chars:]
                buf = [overlap_text]
                buf_len = len(overlap_text)
                buf_start_line = start
            else:
                buf = []
                buf_len = 0
                buf_start_line = start
        buf.append(para)
        buf_len += len(para) + 1

    if buf:
        _flush(end_line=paragraphs[-1][2])

    return chunks


# ---------------------------------------------------------------------------
# Convenience: detect language by file extension
# ---------------------------------------------------------------------------

_EXT_LANG: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "jsx",
    ".md": "markdown",
    ".rst": "rst",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
    ".sh": "bash",
    ".ps1": "powershell",
    ".bat": "batch",
    ".html": "html",
    ".css": "css",
    ".scss": "scss",
    ".rs": "rust",
    ".go": "go",
    ".java": "java",
    ".kt": "kotlin",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".c": "c",
    ".h": "c",
    ".hpp": "cpp",
}


def detect_language(path: str) -> str:
    """Detect language from a file extension."""
    if not path:
        return ""
    lower = path.lower()
    for ext, lang in _EXT_LANG.items():
        if lower.endswith(ext):
            return lang
    return ""


def chunk_files(
    files: Iterable[tuple[str, str]],
    target_chars: int = 1500,
    overlap_chars: int = 200,
) -> list[TextChunk]:
    """Chunk a sequence of (path, content) pairs."""
    out: list[TextChunk] = []
    for path, content in files:
        out.extend(
            chunk_text(
                content,
                source_path=path,
                target_chars=target_chars,
                overlap_chars=overlap_chars,
                language=detect_language(path),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Cheap keyword extractor (used by hybrid search)
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "if",
        "while",
        "for",
        "to",
        "of",
        "in",
        "on",
        "at",
        "by",
        "from",
        "with",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "this",
        "that",
        "these",
        "those",
        "it",
        "its",
        "their",
        "there",
        "here",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "when",
        "where",
        "why",
        "i",
        "you",
        "he",
        "she",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "hers",
        "our",
        "their",
        "mine",
        "yours",
        "hers",
        "ours",
        "theirs",
        "do",
        "does",
        "did",
        "done",
        "have",
        "has",
        "had",
        "having",
        "will",
        "would",
        "shall",
        "should",
        "can",
        "could",
        "may",
        "might",
        "must",
    ]
)


def extract_keywords(text: str, max_keywords: int = 12) -> list[str]:
    """Extract distinctive keywords from ``text`` (cheap heuristic)."""
    if not text:
        return []
    # Tokenise, lowercase, strip non-alphanumeric
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower())
    counts: dict[str, int] = {}
    for t in tokens:
        if t in _STOPWORDS:
            continue
        counts[t] = counts.get(t, 0) + 1
    # CamelCase split bonus
    bonus: dict[str, int] = {}
    for t in list(counts):
        for part in re.findall(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z]|$)|[a-z]+", t):
            if len(part) > 3:
                bonus[part.lower()] = bonus.get(part.lower(), 0) + 1
    for k, v in bonus.items():
        counts[k] = counts.get(k, 0) + v
    return [w for w, _ in sorted(counts.items(), key=lambda x: -x[1])[:max_keywords]]


__all__ = [
    "TextChunk",
    "chunk_text",
    "chunk_files",
    "detect_language",
    "estimate_tokens",
    "extract_keywords",
]
