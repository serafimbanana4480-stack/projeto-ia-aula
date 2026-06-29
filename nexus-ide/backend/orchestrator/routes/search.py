
"""Semantic code search API routes."""

import logging
import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from backend.orchestrator.limiter import limiter

logger = logging.getLogger(__name__)
router = APIRouter()


class SearchRequest(BaseModel):
    query: str
    project_path: str | None = None
    k: int = 8


class CodeChunk(BaseModel):
    file: str
    start_line: int
    end_line: int
    content: str
    score: float = 0.0


class SearchResponse(BaseModel):
    results: list[CodeChunk]
    total_files: int
    query: str


def _simple_code_search(query: str, root: str, k: int = 8) -> list[dict[str, Any]]:
    """Simple regex-based code search fallback when embeddings unavailable."""
    results = []
    query_terms = [t.lower() for t in query.split() if len(t) > 2]
    if not query_terms:
        query_terms = [query.lower()]

    for dirpath, _dirnames, filenames in os.walk(root):
        # Skip common non-source directories
        if any(
            skip in dirpath
            for skip in [
                "node_modules",
                ".git",
                "__pycache__",
                "venv",
                ".venv",
                "dist",
                "build",
            ]
        ):
            continue
        for filename in filenames:
            if not filename.endswith(
                (
                    ".py",
                    ".ts",
                    ".tsx",
                    ".js",
                    ".jsx",
                    ".go",
                    ".rs",
                    ".java",
                    ".cpp",
                    ".c",
                    ".h",
                )
            ):
                continue
            filepath = os.path.join(dirpath, filename)
            rel_path = os.path.relpath(filepath, root)
            try:
                with open(
                    filepath, "r", encoding="utf-8", errors="ignore"
                ) as f:
                    lines = f.readlines()
            except Exception:
                continue

            for i, line in enumerate(lines):
                line_lower = line.lower()
                score = sum(1 for term in query_terms if term in line_lower)
                if score > 0:
                    start = max(0, i - 2)
                    end = min(len(lines), i + 3)
                    context = "".join(lines[start:end])
                    results.append({
                        "file": rel_path,
                        "start_line": start + 1,
                        "end_line": end,
                        "content": context,
                        "score": score,
                    })

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:k]


@router.post("/search/code", response_model=SearchResponse)
@limiter.limit("60/minute")
async def search_code(
    req: SearchRequest,
    mode: str = Query("semantic", description="Search mode: semantic, regex, or hybrid"),
    request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Search codebase for relevant code snippets."""
    project_path = req.project_path or os.getcwd()
    if not os.path.isdir(project_path):
        raise HTTPException(
            status_code=400, detail=f"Invalid project path: {project_path}"
        )

    allowed_modes = {"semantic", "regex", "hybrid"}
    if mode not in allowed_modes:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {mode}. Choose from {allowed_modes}",
        )

    semantic_results: list[dict[str, Any]] = []
    regex_results: list[dict[str, Any]] = []

    # Semantic search
    if mode in ("semantic", "hybrid"):
        try:
            from backend.tools.embeddings import search_codebase

            client = request.app.state.ollama
            db_path = getattr(request.app.state, "search_db_path", "")
            if client and db_path:
                chunks = await search_codebase(
                    req.query, client, db_path, k=req.k
                )
                semantic_results = [
                    {
                        "file": c.file,
                        "start_line": c.start_line,
                        "end_line": c.end_line,
                        "content": c.content,
                        "score": c.score,
                    }
                    for c in chunks
                ]
            else:
                logger.debug(
                    "Semantic search unavailable: missing client or db_path"
                )
        except Exception as exc:
            logger.debug("Semantic search failed: %s", exc)

    # Regex search
    if mode in ("regex", "hybrid"):
        regex_results = _simple_code_search(req.query, project_path, req.k)
        # Normalize regex scores to 0-1 range for fair comparison
        if regex_results:
            max_score = max(r["score"] for r in regex_results)
            if max_score > 0:
                for r in regex_results:
                    r["score"] = r["score"] / max_score

    # Merge results
    if mode == "hybrid":
        # Deduplicate by (file, start_line, end_line), keep highest score
        seen: dict[tuple[str, int, int], dict[str, Any]] = {}
        for r in semantic_results:
            key = (r["file"], r["start_line"], r["end_line"])
            if key not in seen or seen[key]["score"] < r["score"]:
                seen[key] = r
        for r in regex_results:
            key = (r["file"], r["start_line"], r["end_line"])
            if key not in seen or seen[key]["score"] < r["score"]:
                seen[key] = r
        merged = sorted(seen.values(), key=lambda x: x["score"], reverse=True)
        results = merged[: req.k]
    elif mode == "semantic":
        results = (
            semantic_results
            if semantic_results
            else _simple_code_search(req.query, project_path, req.k)
        )
        if not semantic_results:
            logger.info("Semantic search unavailable, fell back to regex")
    else:
        results = regex_results

    return {
        "results": results,
        "total_files": len(set(r["file"] for r in results)),
        "query": req.query,
    }
