"""Tests for integration_tester.py components."""
from __future__ import annotations

import pytest

from backend.pipeline.integration_tester import (
    APIContractTester,
    EventBusTester,
    LoadTestGenerator,
    SLAChecker,
)


class TestAPIContractTester:
    """Tests for APIContractTester."""

    @pytest.fixture
    def sample_openapi(self) -> dict:
        return {
            "openapi": "3.0.0",
            "paths": {
                "/users": {
                    "get": {
                        "responses": {
                            "200": {"description": "OK"},
                            "404": {"description": "Not found"},
                        }
                    },
                    "post": {
                        "responses": {
                            "201": {"description": "Created"},
                            "400": {"description": "Bad request"},
                        }
                    },
                },
                "/users/{id}": {
                    "get": {
                        "responses": {
                            "200": {"description": "OK"},
                        }
                    },
                },
            },
        }

    def test_generate_from_openapi(self, sample_openapi: dict) -> None:
        tester = APIContractTester()
        tests = tester.generate_from_openapi(sample_openapi)

        assert len(tests) == 3
        names = {t.name for t in tests}
        assert "test_get_users" in names
        assert "test_post_users" in names
        assert "test_get_users_{id}" in names

    def test_generated_test_contains_assertions(self, sample_openapi: dict) -> None:
        tester = APIContractTester()
        tests = tester.generate_from_openapi(sample_openapi)

        get_test = next(t for t in tests if t.name == "test_get_users")
        assert "assert" in get_test.code
        assert "httpx" in get_test.code

    def test_empty_openapi_returns_empty(self) -> None:
        tester = APIContractTester()
        tests = tester.generate_from_openapi({"paths": {}})
        assert tests == []


class TestEventBusTester:
    """Tests for EventBusTester."""

    def test_generate_publish_subscribe_test(self) -> None:
        tester = EventBusTester()
        code = tester.generate_publish_subscribe_test(["user.created", "user.updated"])

        assert "pytest" in code
        assert "EventBus" in code
        assert "user.created" in code
        assert "user.updated" in code
        assert "assert len(received) == 2" in code

    def test_generate_single_topic(self) -> None:
        tester = EventBusTester()
        code = tester.generate_publish_subscribe_test(["order.placed"])
        assert "order.placed" in code
        assert "== 1" in code


class TestLoadTestGenerator:
    """Tests for LoadTestGenerator."""

    def test_generate_k6_script(self) -> None:
        gen = LoadTestGenerator()
        script = gen.generate_k6_script("/api/users")

        assert "http.get" in script
        assert "/api/users" in script
        assert "http://localhost:8000" in script
        assert "status is 200" in script

    def test_generate_k6_custom_params(self) -> None:
        gen = LoadTestGenerator()
        script = gen.generate_k6_script(
            "/api/orders",
            base_url="https://api.prod.com",
            ramp_up=5,
            steady_state=100,
            p95_threshold=500,
        )

        assert "https://api.prod.com" in script
        assert "5" in script  # ramp_up
        assert "100" in script  # steady_state
        assert "500" in script  # p95 threshold


class TestSLAChecker:
    """Tests for SLAChecker."""

    def test_all_pass(self) -> None:
        checker = SLAChecker()
        results = {
            "p95_latency_ms": 150,
            "error_rate": 0.005,
            "throughput_rps": 20,
        }
        report = checker.check(results)

        assert report["passed"] is True
        assert report["checks"]["p95_latency"]["passed"] is True
        assert report["checks"]["error_rate"]["passed"] is True
        assert report["checks"]["throughput"]["passed"] is True

    def test_p95_fails(self) -> None:
        checker = SLAChecker()
        results = {
            "p95_latency_ms": 300,
            "error_rate": 0.005,
            "throughput_rps": 20,
        }
        report = checker.check(results)

        assert report["passed"] is False
        assert report["checks"]["p95_latency"]["passed"] is False

    def test_error_rate_fails(self) -> None:
        checker = SLAChecker()
        results = {
            "p95_latency_ms": 100,
            "error_rate": 0.02,
            "throughput_rps": 20,
        }
        report = checker.check(results)

        assert report["passed"] is False
        assert report["checks"]["error_rate"]["passed"] is False

    def test_throughput_fails(self) -> None:
        checker = SLAChecker()
        results = {
            "p95_latency_ms": 100,
            "error_rate": 0.005,
            "throughput_rps": 5,
        }
        report = checker.check(results)

        assert report["passed"] is False
        assert report["checks"]["throughput"]["passed"] is False
