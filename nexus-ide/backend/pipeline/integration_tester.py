"""IntegrationTester — API contract and event bus integration tests.

Generates integration tests from OpenAPI specs and verifies
event bus message flows.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class APIEndpoint:
    """An API endpoint definition."""

    path: str
    method: str
    request_schema: dict[str, Any] = field(default_factory=dict)
    response_schema: dict[str, Any] = field(default_factory=dict)
    status_codes: list[int] = field(default_factory=list)


@dataclass
class IntegrationTest:
    """A generated integration test."""

    name: str
    description: str = ""
    code: str = ""
    target_module: str = ""


class APIContractTester:
    """Generates integration tests from API endpoint definitions."""

    def generate_from_openapi(self, openapi_spec: dict[str, Any]) -> list[IntegrationTest]:
        """Generate tests from an OpenAPI specification.

        Args:
            openapi_spec: Parsed OpenAPI dict.

        Returns:
            List of IntegrationTest objects.
        """
        tests: list[IntegrationTest] = []
        paths = openapi_spec.get("paths", {})

        for path, methods in paths.items():
            for method, spec in methods.items():
                if method == "parameters":
                    continue

                test_name = f"test_{method}_{path.replace('/', '_').strip('_')}"
                status_codes = list(spec.get("responses", {}).keys())

                test_code = self._generate_endpoint_test(
                    path=path,
                    method=method.upper(),
                    status_codes=[int(c) for c in status_codes if c.isdigit()],
                )

                tests.append(IntegrationTest(
                    name=test_name,
                    description=f"Test {method.upper()} {path}",
                    code=test_code,
                    target_module="tests.integration",
                ))

        return tests

    def _generate_endpoint_test(self, path: str, method: str, status_codes: list[int]) -> str:
        """Generate pytest code for an endpoint."""
        lines = [
            f"def {self._test_name(path, method)}():",
            f'    """Test {method} {path}."""',
            "    import httpx",
            f"    response = httpx.{method.lower()}(f'http://localhost:8000{path}')",
        ]

        for code in status_codes:
            lines.append(f"    assert response.status_code in ({', '.join(map(str, status_codes))})")
            break  # Only need one assertion

        # Test error response if 400 or 404 expected
        if 200 in status_codes:
            lines.append("    if response.status_code == 200:")
            lines.append("        assert response.json() is not None")

        return "\n".join(lines) + "\n"

    @staticmethod
    def _test_name(path: str, method: str) -> str:
        safe = path.replace("/", "_").replace("{", "").replace("}", "").replace("-", "_")
        return f"test_{method.lower()}_{safe.strip('_')}"


class EventBusTester:
    """Generates integration tests for event bus flows."""

    def generate_publish_subscribe_test(self, topics: list[str]) -> str:
        """Generate a test verifying publish/subscribe on given topics.

        Args:
            topics: List of topics to test.

        Returns:
            Python test code string.
        """
        lines = [
            "import pytest",
            "from backend.observability.event_bus import EventBus",
            "from backend.observability.events import Event",
            "",
            "@pytest.mark.asyncio",
            "async def test_event_bus_publish_subscribe():",
            '    """Verify events published are received by subscribers."""',
            "    bus = EventBus()",
            "    received = []",
            "",
            "    async def consumer():",
            "        async for event in bus.subscribe('*'):",
            "            received.append(event)",
            "            if len(received) >= len(topics):",
            "                break",
            "",
            "    task = asyncio.create_task(consumer())",
            "    await asyncio.sleep(0.05)",
        ]

        for topic in topics:
            lines.append(f"    await bus.publish(Event(type='{topic}', payload={{'test': True}}))")

        lines.extend([
            "    await asyncio.sleep(0.1)",
            "    task.cancel()",
            "    try:",
            "        await task",
            "    except asyncio.CancelledError:",
            "        pass",
            "",
            f"    assert len(received) == {len(topics)}",
        ])

        return "\n".join(lines) + "\n"


class LoadTestGenerator:
    """Generate load test scripts for APIs."""

    K6_TEMPLATE = """import http from 'k6/http';
import {{ check, sleep }} from 'k6';

export const options = {{
  stages: [
    {{ duration: '30s', target: {ramp_up} }},
    {{ duration: '1m', target: {steady_state} }},
    {{ duration: '30s', target: 0 }},
  ],
  thresholds: {{
    http_req_duration: ['p(95)<{p95_threshold}'],
    http_req_failed: ['rate<{error_rate_threshold}'],
  }},
}};

export default function () {{
  const res = http.get('{base_url}{path}');
  check(res, {{
    'status is 200': (r) => r.status === 200,
    'response time < {p95_threshold}ms': (r) => r.timings.duration < {p95_threshold},
  }});
  sleep(1);
}}
"""

    def generate_k6_script(
        self,
        path: str,
        base_url: str = "http://localhost:8000",
        ramp_up: int = 10,
        steady_state: int = 50,
        p95_threshold: int = 200,
        error_rate_threshold: float = 0.01,
    ) -> str:
        """Generate a k6 load test script."""
        return self.K6_TEMPLATE.format(
            path=path,
            base_url=base_url,
            ramp_up=ramp_up,
            steady_state=steady_state,
            p95_threshold=p95_threshold,
            error_rate_threshold=error_rate_threshold,
        )


class SLAChecker:
    """Validates load test results against SLAs."""

    def check(self, results: dict[str, Any]) -> dict[str, Any]:
        """Check results against SLAs.

        Args:
            results: Load test results dict with metrics.

        Returns:
            Dict with pass/fail status per SLA.
        """
        checks = {
            "p95_latency": {
                "value": results.get("p95_latency_ms", 0),
                "threshold": 200,
                "unit": "ms",
                "passed": results.get("p95_latency_ms", 999) <= 200,
            },
            "error_rate": {
                "value": results.get("error_rate", 1.0),
                "threshold": 0.01,
                "unit": "rate",
                "passed": results.get("error_rate", 1.0) <= 0.01,
            },
            "throughput": {
                "value": results.get("throughput_rps", 0),
                "threshold": 10,
                "unit": "rps",
                "passed": results.get("throughput_rps", 0) >= 10,
            },
        }

        all_passed = all(c["passed"] for c in checks.values())
        return {
            "passed": all_passed,
            "checks": checks,
        }
