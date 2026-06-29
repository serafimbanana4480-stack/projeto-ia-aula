"""Agent tools for persistent user profile and memory."""

from __future__ import annotations

import logging
from typing import Any

from backend.persistence.profile_db import (
    add_learned_fact,
    create_memory,
    get_user_profile,
    increment_memory_access,
    search_memories,
    update_preferences,
)
from backend.tools.embeddings import _cosine_sim, embed
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


async def get_user_profile_tool(user_id: str = "") -> dict[str, Any]:
    if not user_id:
        return {"error": "user_id is required"}
    profile = get_user_profile(user_id)
    if not profile:
        return {"error": f"Profile not found for user {user_id}"}
    return {"profile": profile}


async def update_user_preferences_tool(
    user_id: str = "",
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not user_id:
        return {"error": "user_id is required"}
    prefs = preferences or {}
    profile = update_preferences(user_id, prefs)
    if not profile:
        return {"error": "Failed to update preferences"}
    return {"profile": profile}


async def remember_fact_tool(
    user_id: str = "",
    fact: str = "",
    importance: float = 0.5,
) -> dict[str, Any]:
    if not user_id or not fact:
        return {"error": "user_id and fact are required"}
    try:
        add_learned_fact(user_id, fact)
        memory = create_memory(
            user_id=user_id,
            content=fact,
            memory_type="fact",
            importance=importance,
        )
        return {"stored": True, "memory_id": memory.get("id"), "fact": fact}
    except Exception as exc:
        logger.exception("remember_fact failed: %s", exc)
        return {"error": str(exc)}


async def recall_user_memories_tool(
    user_id: str = "",
    query: str = "",
    top_k: int = 5,
) -> dict[str, Any]:
    if not user_id or not query:
        return {"error": "user_id and query are required"}
    try:
        # Keyword search first
        memories = search_memories(user_id, query, limit=top_k * 2)
        if not memories:
            return {
                "query": query,
                "memories": [],
                "message": "No relevant memories found.",
            }

        # Re-rank with embeddings when available
        try:
            query_emb = await embed(query)
            scored: list[tuple[float, dict]] = []
            for mem in memories:
                mem_id = mem.get("id")
                content = mem.get("content", "")
                try:
                    content_emb = await embed(content)
                    sim = _cosine_sim(query_emb, content_emb)
                except Exception:
                    sim = 0.0
                scored.append((sim, mem))
                if mem_id:
                    increment_memory_access(mem_id)
            scored.sort(key=lambda x: x[0], reverse=True)
            top_memories = [m for _, m in scored[:top_k]]
        except Exception:
            top_memories = memories[:top_k]
            for mem in top_memories:
                mid = mem.get("id")
                if mid:
                    increment_memory_access(mid)

        return {
            "query": query,
            "memories": [
                {
                    "id": m.get("id"),
                    "content": (m.get("content", "") or "")[:500],
                    "memory_type": m.get("memory_type"),
                    "importance": m.get("importance"),
                    "created_at": m.get("created_at"),
                }
                for m in top_memories
            ],
            "total_found": len(top_memories),
        }
    except Exception as exc:
        logger.exception("recall_user_memories failed: %s", exc)
        return {"error": str(exc)}


register_tool(
    ToolSpec(
        name="get_user_profile",
        description=(
            "Read the persistent user profile including preferences, routines, "
            "learned facts and evolution summary."
        ),
        schema={
            "type": "object",
            "properties": {
                "user_id": {
                    "type": "string",
                    "description": "The user ID to look up",
                },
            },
            "required": ["user_id"],
        },
        handler=get_user_profile_tool,
    )
)

register_tool(
    ToolSpec(
        name="update_user_preferences",
        description="Update the user's persistent preferences JSON object.",
        schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "preferences": {
                    "type": "object",
                    "description": "Arbitrary preference dictionary",
                },
            },
            "required": ["user_id", "preferences"],
        },
        handler=update_user_preferences_tool,
    )
)

register_tool(
    ToolSpec(
        name="remember_fact",
        description="Store a learned fact about the user into persistent memory.",
        schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "fact": {
                    "type": "string",
                    "description": "The fact to remember",
                },
                "importance": {
                    "type": "number",
                    "default": 0.5,
                    "description": "Importance 0.0-1.0",
                },
            },
            "required": ["user_id", "fact"],
        },
        handler=remember_fact_tool,
    )
)

register_tool(
    ToolSpec(
        name="recall_user_memories",
        description=("Search persistent user memories using keyword and semantic similarity."),
        schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
                "top_k": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum number of results",
                },
            },
            "required": ["user_id", "query"],
        },
        handler=recall_user_memories_tool,
    )
)
