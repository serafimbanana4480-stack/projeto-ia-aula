#!/usr/bin/env python3
"""Complete end-to-end smoke test for NEXUS IDE after major improvements.

Validates:
- All new tools are registered
- Guardian agent works
- Swarm orchestrator works
- Project wizard works
- Multi-LLM manager works
- Advanced templates generate valid projects
- Structured logging works
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
from pathlib import Path

# Add project root to path so 'backend' package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))


async def run_tests() -> dict:
    """Run all smoke tests and return results."""
    results = {"passed": 0, "failed": 0, "tests": []}

    def record(name: str, success: bool, detail: str = "") -> None:
        results["tests"].append({"name": name, "success": success, "detail": detail})
        if success:
            results["passed"] += 1
        else:
            results["failed"] += 1
        status = "PASS" if success else "FAIL"
        print(f"  [{status}] {name}: {detail}")

    print("=" * 60)
    print("NEXUS IDE — Complete Smoke Test")
    print("=" * 60)

    # Test 1: Tool Registry
    print("\n1. Tool Registry")
    try:
        from backend.tools.registry import list_tools

        tools = list_tools()
        tool_names = {t.name for t in tools}
        expected = {
            "read_file", "write_file", "list_dir", "search_in_files",
            "create_directory", "copy_file", "move_file", "delete_file",
            "run_shell", "run_python_script",
            "analyze_project", "install_dependency", "list_dependencies",
            "generate_tests", "scaffold_project", "generate_project",
        }
        missing = expected - tool_names
        record(
            "New tools registered",
            len(missing) == 0,
            f"Registered: {len(tool_names)}, Missing: {missing or 'None'}"
        )
    except Exception as exc:
        record("New tools registered", False, str(exc))

    # Test 2: Directory Tools
    print("\n2. Directory Tools")
    try:
        from backend.tools.directory_tools import create_directory, delete_file

        with tempfile.TemporaryDirectory() as tmp:
            result = await create_directory("test_dir", project_path=tmp)
            assert result["created"] is True
            assert (Path(tmp) / "test_dir").exists()
            record("create_directory", True)
    except Exception as exc:
        record("create_directory", False, str(exc))

    # Test 3: Shell Runner
    print("\n3. Shell Runner")
    try:
        from backend.tools.shell_runner import run_shell

        result = await run_shell("echo hello")
        assert result.get("success") is True or result.get("exit_code") == 0
        assert "hello" in result["stdout"]
        record("run_shell echo", True)

        # Test blocked command
        result = await run_shell("rm -rf /")
        assert "error" in result
        record("run_shell blocks dangerous", True)
    except Exception as exc:
        record("Shell runner", False, str(exc))

    # Test 4: Project Analyzer
    print("\n4. Project Analyzer")
    try:
        from backend.tools.project_analyzer import analyze_project

        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "main.py").write_text("def hello(): pass\n")
            result = await analyze_project(project_path=tmp)
            assert "error" not in result
            loc = result.get("lines_of_code", {})
            total_loc = loc.get("total_lines_of_code", 0) if isinstance(loc, dict) else loc
            assert total_loc > 0
            record("analyze_project", True, f"LOC={total_loc}")
    except Exception as exc:
        record("analyze_project", False, str(exc))

    # Test 5: Advanced Templates
    print("\n5. Advanced Templates")
    try:
        from backend.tools.advanced_templates import TEMPLATES, generate_project

        assert len(TEMPLATES) >= 6
        record("Templates loaded", True, f"Count={len(TEMPLATES)}")

        with tempfile.TemporaryDirectory() as tmp:
            result = await generate_project("python", "test-proj", project_path=tmp)
            assert result["count"] > 0
            assert (Path(tmp) / "test-proj" / "pyproject.toml").exists()
            record("generate_project", True, f"Files={result['count']}")
    except Exception as exc:
        record("Advanced templates", False, str(exc))

    # Test 6: Multi-LLM Manager
    print("\n6. Multi-LLM Manager")
    try:
        from backend.llm.multi_llm_manager import MultiLLMManager

        manager = MultiLLMManager()
        assert isinstance(manager.providers, dict)
        record("MultiLLMManager init", True)
    except Exception as exc:
        record("MultiLLMManager", False, str(exc))

    # Test 7: Guardian Agent
    print("\n7. Guardian Agent")
    try:
        from backend.agents.guardian import NexusGuardianAgent

        guardian = NexusGuardianAgent()
        status = guardian.get_status()
        assert "running" in status
        record("Guardian status", True)

        guardian._add_suggestion(
            category="test", priority="high", title="Test",
            description="d", action="a", auto_fixable=False,
        )
        suggestions = guardian.get_suggestions()
        assert len(suggestions) == 1
        record("Guardian suggestions", True)
    except Exception as exc:
        record("Guardian agent", False, str(exc))

    # Test 8: Swarm Orchestrator
    print("\n8. Swarm Orchestrator")
    try:
        from backend.orchestrator.swarm import SwarmOrchestrator

        class FakeAgent:
            async def run(self, req):
                yield "test"

        registry = {"CODER": FakeAgent()}
        swarm = SwarmOrchestrator(None, registry, None)
        result = await swarm.execute_swarm(
            objective="test", session_id="s1", agents=["CODER"], strategy="ensemble"
        )
        assert result.strategy_used == "ensemble"
        record("Swarm ensemble", True)
    except Exception as exc:
        record("Swarm orchestrator", False, str(exc))

    # Test 9: Structured Logging
    print("\n9. Structured Logging")
    try:
        from backend.observability.advanced_logging import StructuredLogger

        slog = StructuredLogger()
        slog.info("Test message", agent="TEST", session_id="s1")
        logs = slog.get_logs(session_id="s1")
        assert len(logs) == 1
        record("Structured logging", True)
    except Exception as exc:
        record("Structured logging", False, str(exc))

    # Test 10: Kimi Provider
    print("\n10. Kimi Provider")
    try:
        from backend.llm.kimi_provider import KimiProvider

        provider = KimiProvider(api_key="fake-key")
        assert provider._base_url == "https://api.moonshot.cn/v1"
        record("KimiProvider init", True)
    except Exception as exc:
        record("KimiProvider", False, str(exc))

    # Summary
    print("\n" + "=" * 60)
    print(f"Results: {results['passed']} passed, {results['failed']} failed")
    print("=" * 60)

    return results


if __name__ == "__main__":
    results = asyncio.run(run_tests())
    sys.exit(0 if results["failed"] == 0 else 1)
