"""Tools exposed to agents via ReAct actions. See ARCHITECTURE.md §5.2."""

from __future__ import annotations

import logging
from importlib import import_module

logger = logging.getLogger(__name__)

_TOOLS_REGISTERED = False

_TOOL_MODULE_HINTS = {
    "api_request": "api_tester",
    "consult_agent": "agent_comm",
    "data_analysis": "data_analysis",
    "deep_research": "web_search_v2",
    "execute_code": "code_executor",
    "execute_shell": "code_executor",
    "fetch_content_v2": "web_search_v2",
    "fetch_url": "web_search",
    "format_code": "quality_tools",
    "generate_tests": "test_generator",
    "index_codebase": "embeddings",
    "index_stats": "embeddings",
    "index_symbols": "embeddings",
    "list_dir": "file_ops",
    "list_dir_absolute": "file_ops",
    "read_file": "file_ops",
    "read_file_absolute": "file_ops",
    "read_multiple_files": "file_ops",
    "read_multiple_files_absolute": "file_ops",
    "recall_context": "memory_tools",
    "report_generation": "report_generator",
    "run_lint": "quality_tools",
    "run_shell": "shell_runner",
    "run_tests": "test_runner",
    "scaffold_project": "scaffold",
    "search_codebase": "embeddings",
    "search_docs": "web_search_v2",
    "search_github": "web_search_v2",
    "search_in_files": "file_ops",
    "search_symbols": "embeddings",
    "search_web_v2": "web_search_v2",
    "spawn_task": "task_spawner",
    "store_memory": "memory_tools",
    "type_check": "quality_tools",
    "web_search": "web_search",
    "write_file": "file_ops",
    "write_file_absolute": "file_ops",
}


def _ensure_tool_registered(tool_name: str) -> None:
    """Import only the module likely to own *tool_name* on execution paths."""
    module_name = _TOOL_MODULE_HINTS.get(tool_name)
    if not module_name:
        return
    try:
        import_module(f"backend.tools.{module_name}")
    except (ImportError, ModuleNotFoundError) as exc:
        from backend.tools.registry import record_unavailable_module

        record_unavailable_module(module_name, str(exc))
        logger.warning("Tool module %s unavailable for %s: %s", module_name, tool_name, exc)


def _ensure_tools_registered() -> None:
    """Lazy-load all tool modules so they self-register on first use.

    Importing the full tool graph eagerly adds ~300-800 ms to cold-start
    because modules like ``advanced_templates`` and ``embeddings`` pull
    heavy dependencies.  By deferring until the first ``execute_tool`` or
    ``list_tools`` call we keep startup fast while still guaranteeing that
    every tool is available at request time.
    """
    global _TOOLS_REGISTERED
    if _TOOLS_REGISTERED:
        return

    # Import order does not matter — each module calls ``register_tool`` as a
    # side-effect of being imported.  A missing optional dependency must not
    # prevent unrelated tools from registering (for example, Playwright must
    # not disable memory, code execution, or search tools).
    modules = (
        "advanced_templates",
        "agent_bus_tools",
        "agent_comm",
        "api_tester",
        "append_file",
        "browser_automation",
        "code_executor",
        "cron_scheduler",
        "data_analysis",
        "db_client",
        "dependency_manager",
        "directory_tools",
        "doc_tools",
        "docker_tools",
        "email_tools",
        "embeddings",
        "file_manager",
        "file_ops",
        "git_auto_commit",
        "git_tools",
        "memory_tools",
        "mcp_tools",
        "notifications",
        "profile_tools",
        "project_analyzer",
        "quality_tools",
        "report_generator",
        "scaffold",
        "shell_runner",
        "task_spawner",
        "test_generator",
        "test_runner",
        "tts",
        "vision",
        "web_fetcher",
        "web_search",
        "web_search_v2",
    )
    for module_name in modules:
        try:
            import_module(f"backend.tools.{module_name}")
        except (ImportError, ModuleNotFoundError) as exc:
            from backend.tools.registry import record_unavailable_module

            record_unavailable_module(module_name, str(exc))
            logger.warning("Skipping unavailable optional tool module %s: %s", module_name, exc)

    # New features: Auto-commit, TTS, Cron, Vision

    _TOOLS_REGISTERED = True
    logger.debug("Tool registration completed (%d modules)", len(modules))


def __getattr__(name: str):
    """Support ``from backend.tools import x`` without forcing eager loads."""
    if name == "_ensure_tools_registered":
        return _ensure_tools_registered
    if name == "_ensure_tool_registered":
        return _ensure_tool_registered
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
