"""P1-7 — ten registered-looking tools that never reached the LLM.

``_ensure_tools_registered`` listed 43 modules and omitted five, so ten tools
(``check_context_size``, ``get_budget_report``, ``trim_context``,
``search_knowledge``, ``add_knowledge``, ``get_knowledge_memory``,
``get_project_summary``, ``list_project_files``, ``system_health`` and
``get_system_health``) were invisible to ``get_tool_catalog()`` and therefore to
the model.  ``system_health`` and ``get_system_health`` were additionally the
same code registered twice.

The coverage test below is the anti-regression: every module in
``backend/tools/`` must either be registered or be on an explicit, justified
do-not-register list.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core import disk_guard
from backend.tools import DO_NOT_REGISTER_MODULES, TOOL_MODULES
from backend.tools.registry import get_tool, get_tool_catalog

TOOLS_DIR = Path(__file__).resolve().parents[2] / "backend" / "tools"

#: The ten tools the audit found invisible.  Each must now be in the catalog.
PREVIOUSLY_INVISIBLE = (
    "check_context_size",
    "get_budget_report",
    "trim_context",
    "search_knowledge",
    "add_knowledge",
    "get_knowledge_memory",
    "get_project_summary",
    "list_project_files",
    "get_system_health",
)


@pytest.fixture(autouse=True)
def _no_disk_guard(monkeypatch):
    monkeypatch.setattr(disk_guard, "require_disk_headroom", lambda *_a, **_k: None)
    yield


@pytest.fixture(scope="module")
def catalog() -> list[dict]:
    from backend.tools import _ensure_tools_registered

    _ensure_tools_registered()
    return get_tool_catalog()


def _names(catalog: list[dict]) -> set[str]:
    return {str(entry.get("name")) for entry in catalog}


# ---------------------------------------------------------------------------
# 1. The previously invisible tools are visible
# ---------------------------------------------------------------------------
class TestPreviouslyInvisibleTools:
    @pytest.mark.parametrize("tool_name", PREVIOUSLY_INVISIBLE)
    def test_tool_is_in_the_catalog(self, tool_name: str, catalog: list[dict]) -> None:
        assert tool_name in _names(catalog), (
            f"{tool_name} is registered-looking but invisible to the LLM"
        )

    @pytest.mark.parametrize("tool_name", PREVIOUSLY_INVISIBLE)
    def test_tool_is_executable(self, tool_name: str) -> None:
        spec = get_tool(tool_name)
        assert spec is not None, tool_name
        assert callable(spec.handler)
        assert spec.description, f"{tool_name} has no description for the model"
        assert spec.when_to_use, f"{tool_name} has no when_to_use for the model"

    def test_duplicate_health_tool_is_collapsed(self, catalog: list[dict]) -> None:
        """``system_health`` and ``get_system_health`` were the same tool."""
        from backend.tools.system_health_tool import CANONICAL_TOOL_NAME, get_system_health

        names = [str(entry.get("name")) for entry in catalog]
        assert CANONICAL_TOOL_NAME in names
        assert names.count("get_system_health") == 1
        # The historical alias is no longer a second catalog entry...
        assert "system_health" not in names
        # ...but it is still importable, so nothing that referenced it breaks.
        import backend.tools.system_tools as system_tools

        assert system_tools.system_health is get_system_health
        assert system_tools.get_system_health is get_system_health

    def test_canonical_name_is_in_the_autonomous_read_only_allow_list(self) -> None:
        """The canonical name is the one the allow-list already knew about.

        Keeping ``get_system_health`` (not ``system_health``) means the tool
        stays eligible for autonomous read-only execution.
        """
        from backend.tools.registry import _AUTONOMOUS_READ_ONLY_TOOLS

        assert "get_system_health" in _AUTONOMOUS_READ_ONLY_TOOLS

    def test_health_tool_actually_runs(self) -> None:
        import asyncio

        from backend.tools.system_health_tool import system_health

        payload = asyncio.run(system_health())
        assert payload["ok"] is True
        assert "services" in payload
        assert payload["status"] in {"healthy", "degraded", "unhealthy"}


# ---------------------------------------------------------------------------
# 2. Full module coverage (the anti-regression)
# ---------------------------------------------------------------------------
class TestModuleCoverage:
    def test_every_module_is_registered_or_justified(self) -> None:
        on_disk = {
            path.stem
            for path in TOOLS_DIR.glob("*.py")
            if path.stem != "__init__"
        }
        registered = set(TOOL_MODULES)
        do_not = set(DO_NOT_REGISTER_MODULES)
        overlap = registered & do_not
        assert not overlap, f"module in both lists: {sorted(overlap)}"

        unaccounted = on_disk - registered - do_not
        assert not unaccounted, (
            "tool modules that are neither registered nor on the documented "
            f"do-not-register list: {sorted(unaccounted)}.\n"
            "Add them to backend.tools.TOOL_MODULES, or to "
            "DO_NOT_REGISTER_MODULES with a reason."
        )

    def test_registered_modules_all_exist(self) -> None:
        missing = [name for name in TOOL_MODULES if not (TOOLS_DIR / f"{name}.py").exists()]
        assert not missing, f"TOOL_MODULES lists non-existent modules: {missing}"

    def test_do_not_register_entries_have_a_reason(self) -> None:
        for name, reason in DO_NOT_REGISTER_MODULES.items():
            assert reason and len(reason) > 10, f"{name} has no documented reason"
            assert (TOOLS_DIR / f"{name}.py").exists(), f"{name} does not exist"

    def test_do_not_register_modules_really_register_nothing(self) -> None:
        """A module on the do-not-register list must not self-register a tool.

        Checked on the *module-level* call (tools self-register with a bare
        ``register_tool(ToolSpec(...))`` at import time), so importing
        ``register_tool`` itself, or defining it, is fine.
        """
        import ast

        for name in DO_NOT_REGISTER_MODULES:
            tree = ast.parse((TOOLS_DIR / f"{name}.py").read_text(encoding="utf-8"))
            for node in tree.body:  # module level only
                if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
                    continue
                func = node.value.func
                called = getattr(func, "id", None) or getattr(func, "attr", None)
                assert called != "register_tool", (
                    f"{name} self-registers a tool at module level but is listed "
                    "in DO_NOT_REGISTER_MODULES"
                )

    def test_module_hints_resolve_to_registered_modules(self) -> None:
        from backend.tools import _TOOL_MODULE_HINTS

        unknown = {
            module
            for module in _TOOL_MODULE_HINTS.values()
            if module not in TOOL_MODULES
        }
        assert not unknown, (
            f"_TOOL_MODULE_HINTS points at unregistered modules: {sorted(unknown)}"
        )

    def test_health_tool_hints_point_at_the_canonical_module(self) -> None:
        from backend.tools import _TOOL_MODULE_HINTS

        assert _TOOL_MODULE_HINTS["get_system_health"] == "system_health_tool"
        assert _TOOL_MODULE_HINTS["system_health"] == "system_health_tool"

    def test_catalog_is_not_empty_and_has_no_duplicates(self, catalog: list[dict]) -> None:
        names = [str(entry.get("name")) for entry in catalog]
        assert len(names) > 100, "tool catalog shrank unexpectedly"
        duplicates = {name for name in names if names.count(name) > 1}
        assert not duplicates, f"duplicate tools in the catalog: {sorted(duplicates)}"

    def test_every_catalog_entry_is_dispatchable(self, catalog: list[dict]) -> None:
        """Every catalog entry is either a real spec or an honest placeholder.

        ``get_tool_catalog`` emits ``status="missing_dependency"`` entries for
        tools whose optional dependency is absent (Playwright here).  Those are
        not dispatchable *by design* — the point is that the catalog says so
        rather than pretending the tool exists.
        """
        placeholders = 0
        for entry in catalog:
            name = str(entry.get("name"))
            if get_tool(name) is None:
                assert entry.get("status") == "missing_dependency", (
                    f"{name} is listed but neither resolvable nor declared missing"
                )
                assert entry.get("available") is False
                placeholders += 1
        assert placeholders < len(catalog) / 4, "most of the catalog is a placeholder"

    def test_newly_registered_tools_have_schemas(self) -> None:
        for name in PREVIOUSLY_INVISIBLE:
            spec = get_tool(name)
            assert spec is not None
            assert isinstance(spec.schema, dict), name
            assert spec.schema.get("type") == "object", name
