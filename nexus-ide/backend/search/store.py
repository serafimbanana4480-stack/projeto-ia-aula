"""Thin wrapper around sqlite-vec for semantic code search."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Any

try:
    import sqlite_vec

    SQLITE_VEC_AVAILABLE = True
except ImportError:
    sqlite_vec = None  # type: ignore[assignment]
    SQLITE_VEC_AVAILABLE = False

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 768
CHUNKS_TABLE = "code_chunks"
VEC_TABLE = "vec_chunks"


def _load_extension(conn: sqlite3.Connection) -> None:
    if not SQLITE_VEC_AVAILABLE or sqlite_vec is None:
        raise RuntimeError("sqlite-vec is not installed")
    conn.enable_load_extension(True)
    conn.load_extension(sqlite_vec.loadable_path())


def init_search_db(db_path: str) -> None:
    """Create the sqlite-vec virtual table and metadata table."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        _load_extension(conn)
        conn.execute(
            f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS {VEC_TABLE} USING vec0(
                embedding float[{EMBEDDING_DIM}]
            )
            """
        )
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {CHUNKS_TABLE} (
                id INTEGER PRIMARY KEY,
                file TEXT NOT NULL,
                start_line INTEGER NOT NULL,
                end_line INTEGER NOT NULL,
                content TEXT NOT NULL
            )
            """
        )
        conn.commit()
        logger.info("Search DB initialized at %s", db_path)
    finally:
        conn.close()


def insert_chunks(db_path: str, chunks: list[dict[str, Any]]) -> None:
    """Batch insert chunks and their embeddings."""
    if not chunks:
        return
    conn = sqlite3.connect(db_path)
    try:
        _load_extension(conn)
        for chunk in chunks:
            cursor = conn.execute(
                f"""
                INSERT INTO {CHUNKS_TABLE} (file, start_line, end_line, content)
                VALUES (?, ?, ?, ?)
                """,
                (
                    chunk["file"],
                    chunk["start_line"],
                    chunk["end_line"],
                    chunk["content"],
                ),
            )
            rowid = cursor.lastrowid
            embedding_json = json.dumps(chunk["embedding"])
            conn.execute(
                f"INSERT INTO {VEC_TABLE} (rowid, embedding) VALUES (?, ?)",
                (rowid, embedding_json),
            )
        conn.commit()
        logger.debug("Inserted %d chunks into search DB", len(chunks))
    finally:
        conn.close()


def search_chunks(
    db_path: str, embedding: list[float], k: int = 8
) -> list[dict[str, Any]]:
    """Vector search returning top-k matches with metadata and distance."""
    conn = sqlite3.connect(db_path)
    try:
        _load_extension(conn)
        embedding_json = json.dumps(embedding)
        rows = conn.execute(
            f"""
            SELECT c.file, c.start_line, c.end_line, c.content, v.distance
            FROM {VEC_TABLE} v
            JOIN {CHUNKS_TABLE} c ON v.rowid = c.id
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            LIMIT ?
            """,
            (embedding_json, k, k),
        ).fetchall()
        return [
            {
                "file": r[0],
                "start_line": r[1],
                "end_line": r[2],
                "content": r[3],
                "distance": r[4],
            }
            for r in rows
        ]
    finally:
        conn.close()
