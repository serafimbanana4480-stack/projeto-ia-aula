"""Tests for backend.orchestrator.routes.embeddings — endpoint schema validation."""

from __future__ import annotations

from backend.orchestrator.routes.embeddings import (
    IndexRequest,
    IndexResponse,
    SearchRequest,
    SearchResponse,
    SearchResultItem,
)


class TestIndexRequest:
    def test_valid(self) -> None:
        req = IndexRequest(project_path="/home/user/project")
        assert req.project_path == "/home/user/project"

    def test_default_k_in_search(self) -> None:
        req = SearchRequest(query="find auth logic")
        assert req.k == 8


class TestSearchResponse:
    def test_empty_results(self) -> None:
        resp = SearchResponse(query="test", results=[], total_found=0)
        assert resp.total_found == 0

    def test_with_results(self) -> None:
        item = SearchResultItem(
            file="src/auth.py",
            start_line=10,
            end_line=20,
            score=0.95,
            content="def authenticate():",
        )
        resp = SearchResponse(query="auth", results=[item], total_found=1)
        assert resp.results[0].file == "src/auth.py"
        assert resp.results[0].score == 0.95


class TestIndexResponse:
    def test_response(self) -> None:
        resp = IndexResponse(chunks_indexed=42, project_path="/tmp/proj")
        assert resp.chunks_indexed == 42
