#!/usr/bin/env python3
"""Nexus IDE Self-Test Framework.

Runs comprehensive diagnostics on all system components:
- Model connectivity (Ollama ping)
- Tool registry health
- Filesystem permissions
- Sandbox execution
- Memory/vector store
- WebSocket streaming
- Orchestration engine
- Database connectivity

Usage:
    python scripts/selftest/run_diagnostics.py
    python scripts/selftest/run_diagnostics.py --component ollama
    python scripts/selftest/run_diagnostics.py --verbose
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

logger = logging.getLogger(__name__)


class TestStatus(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    WARN = "warn"


@dataclass
class TestResult:
    name: str
    status: TestStatus
    duration_ms: int
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    suggestion: str = ""


class SelfTestRunner:
    """Runs all self-diagnostics and generates a report."""

    def __init__(self, verbose: bool = False) -> None:
        self.verbose = verbose
        self.results: list[TestResult] = []
        self._start_time = time.time()

    async def run_all(self, components: list[str] | None = None) -> dict[str, Any]:
        """Run all diagnostic tests."""
        tests: list[tuple[str, Callable]] = [
            ("ollama_connectivity", self.test_ollama_connectivity),
            ("tool_registry", self.test_tool_registry),
            ("filesystem_permissions", self.test_filesystem_permissions),
            ("sandbox_execution", self.test_sandbox_execution),
            ("memory_store", self.test_memory_store),
            ("database_connectivity", self.test_database_connectivity),
            ("code_intelligence", self.test_code_intelligence),
            ("orchestration_engine", self.test_orchestration_engine),
            ("websocket_readiness", self.test_websocket_readiness),
            ("config_validity", self.test_config_validity),
        ]

        for name, test_fn in tests:
            if components and name not in components:
                continue
            result = await self._run_test(name, test_fn)
            self.results.append(result)

        return self.generate_report()

    async def _run_test(self, name: str, test_fn: Callable) -> TestResult:
        """Run a single test with timing and error handling."""
        start = time.time()
        try:
            result = await test_fn()
            duration_ms = int((time.time() - start) * 1000)
            result.duration_ms = duration_ms
            return result
        except Exception as exc:
            duration_ms = int((time.time() - start) * 1000)
            return TestResult(
                name=name,
                status=TestStatus.FAIL,
                duration_ms=duration_ms,
                message=str(exc),
                suggestion=f"Check logs for details on {name} failure",
            )

    # ------------------------------------------------------------------
    # Individual Tests
    # ------------------------------------------------------------------

    async def test_ollama_connectivity(self) -> TestResult:
        """Test Ollama server connectivity and model availability."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get("http://localhost:11434/api/tags")
                if resp.status_code == 200:
                    data = resp.json()
                    models = data.get("models", [])
                    model_names = [m.get("name", "unknown") for m in models]
                    return TestResult(
                        name="ollama_connectivity",
                        status=TestStatus.PASS,
                        duration_ms=0,
                        message=f"Ollama reachable with {len(models)} models",
                        details={"models": model_names},
                    )
                else:
                    return TestResult(
                        name="ollama_connectivity",
                        status=TestStatus.FAIL,
                        duration_ms=0,
                        message=f"Ollama returned {resp.status_code}",
                        suggestion="Ensure Ollama is running: ollama serve",
                    )
        except Exception as exc:
            return TestResult(
                name="ollama_connectivity",
                status=TestStatus.FAIL,
                duration_ms=0,
                message=f"Cannot reach Ollama: {exc}",
                suggestion="Start Ollama: ollama serve",
            )

    async def test_tool_registry(self) -> TestResult:
        """Test that all registered tools have handlers."""
        try:
            from backend.tools.registry import list_tools

            tools = list_tools(enabled_only=False)
            enabled = [t.name for t in tools if t.enabled]
            disabled = [t.name for t in tools if not t.enabled]
            no_handler = [t.name for t in tools if t.handler is None]

            if no_handler:
                return TestResult(
                    name="tool_registry",
                    status=TestStatus.WARN,
                    duration_ms=0,
                    message=f"Tools without handlers: {no_handler}",
                    details={"enabled": enabled, "disabled": disabled},
                )

            return TestResult(
                name="tool_registry",
                status=TestStatus.PASS,
                duration_ms=0,
                message=f"{len(enabled)} tools enabled, {len(disabled)} disabled",
                details={"enabled": enabled, "disabled": disabled},
            )
        except Exception as exc:
            return TestResult(
                name="tool_registry",
                status=TestStatus.FAIL,
                duration_ms=0,
                message=str(exc),
            )

    async def test_filesystem_permissions(self) -> TestResult:
        """Test filesystem read/write permissions."""
        import tempfile

        try:
            # Test temp file creation
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write("Nexus self-test")
                tmp_path = f.name

            # Test read
            content = Path(tmp_path).read_text()
            assert content == "Nexus self-test"

            # Test delete
            Path(tmp_path).unlink()

            return TestResult(
                name="filesystem_permissions",
                status=TestStatus.PASS,
                duration_ms=0,
                message="Read, write, and delete permissions OK",
            )
        except Exception as exc:
            return TestResult(
                name="filesystem_permissions",
                status=TestStatus.FAIL,
                duration_ms=0,
                message=str(exc),
                suggestion="Check filesystem permissions in the working directory",
            )

    async def test_sandbox_execution(self) -> TestResult:
        """Test sandboxed code execution."""
        try:
            from backend.sandbox.executor import SandboxExecutor

            executor = SandboxExecutor()
            result = await executor.execute(
                "print('sandbox OK')",
                language="python",
                timeout=5,
            )
            if result.exit_code == 0 and "sandbox OK" in result.stdout:
                return TestResult(
                    name="sandbox_execution",
                    status=TestStatus.PASS,
                    duration_ms=result.duration_ms,
                    message="Sandbox execution working",
                    details={"docker_available": await executor.check_docker()},
                )
            else:
                return TestResult(
                    name="sandbox_execution",
                    status=TestStatus.FAIL,
                    duration_ms=result.duration_ms,
                    message=f"Sandbox failed: {result.stderr}",
                )
        except Exception as exc:
            return TestResult(
                name="sandbox_execution",
                status=TestStatus.FAIL,
                duration_ms=0,
                message=str(exc),
            )

    async def test_memory_store(self) -> TestResult:
        """Test memory store operations."""
        try:
            from backend.knowledge.memory import MemoryStore, EmbeddingService

            svc = EmbeddingService()
            store = MemoryStore(embedding_service=svc, max_memories=10)

            # Store
            mem = await store.store("Test memory for diagnostics")
            assert mem.memory_id

            # Search
            results = await store.search("diagnostics", top_k=1)
            assert len(results) > 0

            # Cleanup
            await store.delete(mem.memory_id)

            return TestResult(
                name="memory_store",
                status=TestStatus.PASS,
                duration_ms=0,
                message="Memory store operations working",
                details=store.stats(),
            )
        except Exception as exc:
            return TestResult(
                name="memory_store",
                status=TestStatus.FAIL,
                duration_ms=0,
                message=str(exc),
            )

    async def test_database_connectivity(self) -> TestResult:
        """Test SQLite database connectivity."""
        try:
            from backend.persistence.db import init_db, create_session, get_session

            init_db()
            session = create_session(title="Self-test session")
            retrieved = get_session(session["id"])
            assert retrieved is not None

            return TestResult(
                name="database_connectivity",
                status=TestStatus.PASS,
                duration_ms=0,
                message="Database operations working",
                details={"session_id": session["id"]},
            )
        except Exception as exc:
            return TestResult(
                name="database_connectivity",
                status=TestStatus.FAIL,
                duration_ms=0,
                message=str(exc),
                suggestion="Check data/nexus.db permissions",
            )

    async def test_code_intelligence(self) -> TestResult:
        """Test code indexing and symbol extraction."""
        try:
            from backend.knowledge.code_intelligence import CodeIndexer

            indexer = CodeIndexer()
            # Index the backend directory
            count = indexer.index_directory(
                str(Path(__file__).resolve().parents[2] / "backend"),
                exclude_dirs=["__pycache__", ".pytest_cache", "tests"],
            )

            stats = indexer.stats()
            return TestResult(
                name="code_intelligence",
                status=TestStatus.PASS if count > 0 else TestStatus.WARN,
                duration_ms=0,
                message=f"Indexed {count} files, {stats['unique_symbols']} symbols",
                details=stats,
            )
        except Exception as exc:
            return TestResult(
                name="code_intelligence",
                status=TestStatus.FAIL,
                duration_ms=0,
                message=str(exc),
            )

    async def test_orchestration_engine(self) -> TestResult:
        """Test orchestration engine initialization."""
        try:
            from backend.orchestrator.events import EventBus
            from backend.orchestrator.engine import OrchestrationEngine

            bus = EventBus()
            engine = OrchestrationEngine(
                ollama=None,  # type: ignore
                registry={},
                event_bus=bus,
            )
            assert engine.get_state("test") == "idle"

            return TestResult(
                name="orchestration_engine",
                status=TestStatus.PASS,
                duration_ms=0,
                message="Orchestration engine initialized",
            )
        except Exception as exc:
            return TestResult(
                name="orchestration_engine",
                status=TestStatus.FAIL,
                duration_ms=0,
                message=str(exc),
            )

    async def test_websocket_readiness(self) -> TestResult:
        """Test that SSE/WebSocket infrastructure is ready."""
        try:
            from backend.orchestrator.events import EventBus

            bus = EventBus()
            # Test that event streaming infrastructure works
            received: list[Any] = []

            async def handler(event: Any) -> None:
                received.append(event)

            await bus.subscribe("test", handler)
            from backend.orchestrator.events import OrchestratorEvent, EventType
            await bus.publish(OrchestratorEvent(event_type=EventType.HEARTBEAT))
            await asyncio.sleep(0.01)

            if received:
                return TestResult(
                    name="websocket_readiness",
                    status=TestStatus.PASS,
                    duration_ms=0,
                    message="Event streaming infrastructure ready",
                )
            else:
                return TestResult(
                    name="websocket_readiness",
                    status=TestStatus.WARN,
                    duration_ms=0,
                    message="Event bus working but no events received",
                )
        except Exception as exc:
            return TestResult(
                name="websocket_readiness",
                status=TestStatus.FAIL,
                duration_ms=0,
                message=str(exc),
            )

    async def test_config_validity(self) -> TestResult:
        """Test that configuration files are valid."""
        try:
            import yaml

            config_dir = Path(__file__).resolve().parents[2] / "config"

            issues = []
            for config_file in ["models.yaml", "modes.yaml"]:
                path = config_dir / config_file
                if not path.exists():
                    issues.append(f"Missing: {config_file}")
                    continue
                try:
                    with open(path) as f:
                        yaml.safe_load(f)
                except yaml.YAMLError as exc:
                    issues.append(f"Invalid YAML in {config_file}: {exc}")

            if issues:
                return TestResult(
                    name="config_validity",
                    status=TestStatus.FAIL,
                    duration_ms=0,
                    message="; ".join(issues),
                )
            return TestResult(
                name="config_validity",
                status=TestStatus.PASS,
                duration_ms=0,
                message="All config files valid",
            )
        except Exception as exc:
            return TestResult(
                name="config_validity",
                status=TestStatus.FAIL,
                duration_ms=0,
                message=str(exc),
            )

    # ------------------------------------------------------------------
    # Report Generation
    # ------------------------------------------------------------------

    def generate_report(self) -> dict[str, Any]:
        """Generate a comprehensive diagnostic report."""
        total = len(self.results)
        passed = sum(1 for r in self.results if r.status == TestStatus.PASS)
        failed = sum(1 for r in self.results if r.status == TestStatus.FAIL)
        warnings = sum(1 for r in self.results if r.status == TestStatus.WARN)
        skipped = sum(1 for r in self.results if r.status == TestStatus.SKIP)
        total_duration = int((time.time() - self._start_time) * 1000)

        return {
            "timestamp": time.time(),
            "total_tests": total,
            "passed": passed,
            "failed": failed,
            "warnings": warnings,
            "skipped": skipped,
            "overall_status": "healthy" if failed == 0 else "degraded",
            "total_duration_ms": total_duration,
            "results": [
                {
                    "name": r.name,
                    "status": r.status.value,
                    "duration_ms": r.duration_ms,
                    "message": r.message,
                    "suggestion": r.suggestion,
                }
                for r in self.results
            ],
        }


async def main() -> None:
    """Run self-diagnostics from CLI."""
    import argparse

    parser = argparse.ArgumentParser(description="Nexus IDE Self-Test Framework")
    parser.add_argument("--component", "-c", help="Run specific component test")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--json", "-j", action="store_true", help="JSON output")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    runner = SelfTestRunner(verbose=args.verbose)
    components = [args.component] if args.component else None
    report = await runner.run_all(components)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("\n" + "=" * 60)
        print("  NEXUS IDE — Self-Diagnostics Report")
        print("=" * 60)
        print(f"  Status: {report['overall_status'].upper()}")
        print(f"  Tests: {report['total_tests']} total | "
              f"{report['passed']} passed | "
              f"{report['failed']} failed | "
              f"{report['warnings']} warnings")
        print(f"  Duration: {report['total_duration_ms']}ms")
        print("-" * 60)

        for r in report["results"]:
            icon = {"pass": "✅", "fail": "❌", "warn": "⚠️", "skip": "⏭️"}.get(r["status"], "?")
            print(f"  {icon} {r['name']}: {r['message']}")
            if r.get("suggestion"):
                print(f"     💡 {r['suggestion']}")

        print("=" * 60 + "\n")

    # Exit with non-zero if failures
    if report["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
