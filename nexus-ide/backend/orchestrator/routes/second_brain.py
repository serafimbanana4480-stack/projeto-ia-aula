"""Second Brain Knowledge Base routes."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request

from backend.middleware.auth import require_auth
from backend.tools.web_fetcher import fetch_and_summarize

logger = logging.getLogger(__name__)
router = APIRouter()


def _get_db(request: Request):
    from backend.persistence.db import get_db
    return get_db()


@router.post("/brain/ingest")
async def ingest(
    request: Request,
    data: dict[str, Any],
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Ingest a link, note, or book into the Second Brain."""
    item_type = data.get("type", "note")
    title = data.get("title", "")
    content = data.get("content", "")
    url = data.get("url", "")
    tags = data.get("tags", [])
    user_id = _user.get("user_id", "")

    if item_type == "link" and url:
        fetched = await fetch_and_summarize(url)
        if fetched.get("status") != "error":
            content = fetched.get("summary", "")
            title = title or fetched.get("title", url)

    memory_id = str(uuid.uuid4()).replace("-", "")[:16]
    conn = _get_db(request)
    conn.execute(
        """INSERT INTO persistent_memories
           (id, user_id, content, summary, memory_type, tags, source, importance)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (memory_id, user_id, content, title, item_type, json.dumps(tags), url or "manual", 0.7),
    )
    conn.commit()
    conn.close()
    return {"memory_id": memory_id, "type": item_type, "title": title, "stored": True}


@router.get("/brain/search")
async def search_brain(
    request: Request,
    q: str = "",
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Search the Second Brain."""
    user_id = _user.get("user_id", "")
    conn = _get_db(request)
    cursor = conn.execute(
        """SELECT id, content, summary, memory_type, tags, source, importance, created_at
           FROM persistent_memories
           WHERE user_id = ? AND (content LIKE ? OR summary LIKE ? OR tags LIKE ?)
           ORDER BY importance DESC, created_at DESC
           LIMIT 20""",
        (user_id, f"%{q}%", f"%{q}%", f"%{q}%"),
    )
    rows = cursor.fetchall()
    conn.close()
    memories = []
    for r in rows:
        memories.append({
            "id": r[0],
            "content_preview": (r[1] or "")[:200],
            "summary": r[2],
            "type": r[3],
            "tags": json.loads(r[4]) if r[4] else [],
            "source": r[5],
            "importance": r[6],
            "created_at": r[7],
        })
    return {"query": q, "memories": memories, "count": len(memories)}


@router.get("/brain/memories")
async def list_memories(
    request: Request,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """List all memories."""
    user_id = _user.get("user_id", "")
    conn = _get_db(request)
    cursor = conn.execute(
        """SELECT id, content, summary, memory_type, tags, source, importance, created_at
           FROM persistent_memories
           WHERE user_id = ?
           ORDER BY created_at DESC
           LIMIT 100""",
        (user_id,),
    )
    rows = cursor.fetchall()
    conn.close()
    memories = []
    for r in rows:
        memories.append({
            "id": r[0],
            "content_preview": (r[1] or "")[:200],
            "summary": r[2],
            "type": r[3],
            "tags": json.loads(r[4]) if r[4] else [],
            "source": r[5],
            "importance": r[6],
            "created_at": r[7],
        })
    return {"memories": memories, "count": len(memories)}


@router.delete("/brain/memories/{memory_id}")
async def delete_memory(
    request: Request,
    memory_id: str,
    _user: dict = Depends(require_auth),
) -> dict[str, Any]:
    """Delete a memory."""
    user_id = _user.get("user_id", "")
    conn = _get_db(request)
    conn.execute(
        "DELETE FROM persistent_memories WHERE id = ? AND user_id = ?",
        (memory_id, user_id),
    )
    conn.commit()
    conn.close()
    return {"deleted": True, "memory_id": memory_id}
