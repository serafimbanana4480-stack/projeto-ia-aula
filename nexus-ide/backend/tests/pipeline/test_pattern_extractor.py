"""Tests for PatternExtractor and KnowledgeGraphStore."""
from __future__ import annotations

import pytest

from backend.pipeline.pattern_extractor import (
    KnowledgeGraphStore,
    Pattern,
    PatternExtractor,
    PatternQuery,
)


class TestPatternExtractor:
    """Tests for PatternExtractor."""

    def test_extract_from_empty_logs(self):
        extractor = PatternExtractor()
        patterns = extractor.extract([])
        assert len(patterns) == 0

    def test_extract_code_patterns(self):
        extractor = PatternExtractor()
        logs = [
            {
                "success": True,
                "code_summary": "Generated FastAPI project with 5 files",
                "files_created": 5,
                "stack": "python",
                "workflow_id": "wf-001",
            },
        ]
        patterns = extractor.extract(logs)
        code_patterns = [p for p in patterns if p.pattern_type == "code"]
        assert len(code_patterns) >= 1
        assert any("Multi-file" in p.name for p in code_patterns)

    def test_extract_test_patterns(self):
        extractor = PatternExtractor()
        logs = [
            {
                "success": True,
                "test_summary": "Generated pytest suite",
                "coverage_pct": 95,
                "workflow_id": "wf-002",
            },
        ]
        patterns = extractor.extract(logs)
        test_patterns = [p for p in patterns if p.pattern_type == "test"]
        assert len(test_patterns) == 1
        assert test_patterns[0].success_rate == 1.0

    def test_extract_test_patterns_below_threshold(self):
        extractor = PatternExtractor()
        logs = [
            {
                "success": True,
                "test_summary": "Some tests",
                "coverage_pct": 50,
                "workflow_id": "wf-003",
            },
        ]
        patterns = extractor.extract(logs)
        test_patterns = [p for p in patterns if p.pattern_type == "test"]
        assert len(test_patterns) == 0

    def test_extract_repair_patterns(self):
        extractor = PatternExtractor()
        logs = [
            {
                "success": True,
                "repairs": [
                    {
                        "success": True,
                        "error_type": "import_error",
                        "fix_description": "Added missing import",
                        "patch": "import os",
                    },
                ],
                "workflow_id": "wf-004",
            },
        ]
        patterns = extractor.extract(logs)
        repair_patterns = [p for p in patterns if p.pattern_type == "repair"]
        assert len(repair_patterns) == 1
        assert "import_error" in repair_patterns[0].tags

    def test_extract_deploy_patterns(self):
        extractor = PatternExtractor()
        logs = [
            {
                "success": True,
                "deploy": {"strategy": "blue-green", "status": "success"},
                "workflow_id": "wf-005",
            },
        ]
        patterns = extractor.extract(logs)
        deploy_patterns = [p for p in patterns if p.pattern_type == "deploy"]
        assert len(deploy_patterns) == 1
        assert "blue-green" in deploy_patterns[0].tags

    def test_skip_failed_logs(self):
        extractor = PatternExtractor()
        logs = [
            {
                "success": False,
                "code_summary": "Failed code gen",
                "workflow_id": "wf-fail",
            },
        ]
        patterns = extractor.extract(logs)
        assert len(patterns) == 0

    def test_extract_multiple_patterns_from_batch(self):
        extractor = PatternExtractor()
        logs = [
            {
                "success": True,
                "code_summary": "Project A",
                "files_created": 3,
                "stack": "python",
                "test_summary": "Tests for A",
                "coverage_pct": 92,
                "repairs": [{"success": True, "error_type": "syntax_error",
                           "fix_description": "Fixed syntax", "patch": "x = 1"}],
                "deploy": {"strategy": "canary"},
                "workflow_id": "wf-010",
            },
        ]
        patterns = extractor.extract(logs)
        assert len(patterns) >= 4


class TestKnowledgeGraphStore:
    """Tests for KnowledgeGraphStore."""

    @pytest.fixture
    def store_with_data(self):
        store = KnowledgeGraphStore()
        patterns = [
            Pattern(
                pattern_id="p1", pattern_type="code", name="FastAPI CRUD",
                description="Standard CRUD endpoints", context="REST APIs",
                template="from fastapi import FastAPI",
                tags=["python", "fastapi", "api"], stack="python",
            ),
            Pattern(
                pattern_id="p2", pattern_type="code", name="React Component",
                description="Functional component pattern", context="UI components",
                template="const Component = () => {...}",
                tags=["typescript", "react", "ui"], stack="typescript",
            ),
            Pattern(
                pattern_id="p3", pattern_type="repair", name="Import fix",
                description="Fix missing imports", context="Import errors",
                template="import missing_module",
                tags=["repair", "import_error", "python"], stack="python",
            ),
        ]
        store.store_batch(patterns)
        return store

    def test_store_and_retrieve(self):
        store = KnowledgeGraphStore()
        pattern = Pattern(
            pattern_id="test-1", pattern_type="code", name="Test Pattern",
            description="A test", context="testing",
            template="print('hello')", tags=["test"],
        )
        store.store(pattern)
        retrieved = store.get_pattern("test-1")
        assert retrieved is not None
        assert retrieved.name == "Test Pattern"

    def test_query_by_tags(self, store_with_data):
        results = store_with_data.query_by_tags(["python"])
        assert len(results) == 2  # p1 (code) + p3 (repair)

    def test_query_by_tags_with_type_filter(self, store_with_data):
        results = store_with_data.query_by_tags(["python"], pattern_type="code")
        assert len(results) == 1
        assert results[0].pattern_id == "p1"

    def test_query_by_type(self, store_with_data):
        results = store_with_data.query_by_type("repair")
        assert len(results) == 1
        assert results[0].pattern_id == "p3"

    def test_search_similar(self, store_with_data):
        results = store_with_data.search_similar("fastapi python api")
        assert len(results) > 0

    def test_search_similar_no_match(self, store_with_data):
        results = store_with_data.search_similar("rust golang")
        assert isinstance(results, list)

    def test_get_stats(self, store_with_data):
        stats = store_with_data.get_stats()
        assert stats["total"] == 3
        assert stats.get("code", 0) == 2
        assert stats.get("repair", 0) == 1


class TestPatternQuery:
    """Tests for PatternQuery."""

    @pytest.fixture
    def store(self):
        store = KnowledgeGraphStore()
        patterns = [
            Pattern(
                pattern_id="p1", pattern_type="code", name="API Pattern",
                description="FastAPI CRUD", context="APIs",
                template="code here", tags=["code_gen", "python"],
            ),
            Pattern(
                pattern_id="p2", pattern_type="repair", name="Null check",
                description="Fix null pointer", context="errors",
                template="if x is not None", tags=["repair", "null_error"],
            ),
        ]
        store.store_batch(patterns)
        return store

    def test_find_for_task(self, store):
        query = PatternQuery(store)
        results = query.find_for_task("code_gen")
        assert len(results) >= 1

    def test_find_for_task_with_stack(self, store):
        query = PatternQuery(store)
        results = query.find_for_task("code_gen", stack="python")
        assert len(results) >= 1

    def test_find_similar_code(self, store):
        query = PatternQuery(store)
        results = query.find_similar_code("API endpoint creation")
        assert len(results) >= 1
        assert all(p.pattern_type == "code" for p in results)

    def test_find_repairs_for_error(self, store):
        query = PatternQuery(store)
        results = query.find_repairs_for_error("null_error")
        assert len(results) == 1
        assert results[0].pattern_type == "repair"