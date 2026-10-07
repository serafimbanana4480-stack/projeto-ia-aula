"""Tools exposed to agents via ReAct actions. See ARCHITECTURE.md §5.2."""

from __future__ import annotations

import logging
from importlib import import_module

logger = logging.getLogger(__name__)

_TOOLS_REGISTERED = False

#: Every tool module that is expected to self-register on import.  This tuple is
#: the contract asserted by ``backend/tests/security_hardening_tools.py``: any
#: module in ``backend/tools/`` that is neither listed here nor in
#: :data:`DO_NOT_REGISTER_MODULES` is a regression.
TOOL_MODULES: tuple[str, ...] = (
    "advanced_templates",
    "agent_bus_tools",
    "agent_comm",
    "api_tester",
    "append_file",
    "browser_automation",
    "code_executor",
    "context_budget_tool",
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
    "knowledge_tools",
    "mcp_tools",
    "memory_tools",
    "notifications",
    "profile_tools",
    "project_analyzer",
    "project_tools",
    "quality_tools",
    "report_generator",
    "scaffold",
    "sequential_thinking_tool",
    "session_tools",
    "shell_runner",
    "skills_tools",
    "system_health_tool",
    "system_tools",
    "task_spawner",
    "test_generator",
    "test_runner",
    "todo_tools",
    "tts",
    "vision",
    "web_fetcher",
    "web_search",
    "web_search_v2",
)

#: Tool modules deliberately *not* imported by ``_ensure_tools_registered``,
#: with the reason.  Keep this list short and justified: it is the escape hatch
#: that stops the coverage test from becoming a to-do list.  ``__init__`` is
#: excluded implicitly (it is this module).
DO_NOT_REGISTER_MODULES: dict[str, str] = {
    # Infrastructure, not tools: no ``register_tool`` call anywhere in them.
    "registry": "tool registry plumbing — defines register_tool, registers nothing",
    "ollama_client": "HTTP client shim over AirLLM, not a tool",
    "opencode_client": "async provider client, not a tool",
    "email_client": "IMAP client, reachable through email_tools",
    "file_api": "unified file API facade, used by the file routes",
    "interpreters": "interpreter resolution shared by shelling-out tools",
    "model_validator": "startup model availability check, not a tool",
    "sanitizer": "prompt-injection defences applied by the tool layer",
    "confirmations": "in-process confirmation gates used by risky tools",
    "discovery": "tool-catalog rendering for the system prompt",
    "ai_suggestions": "post-processing helpers, no tool surface",
    # NOTE: ``file_manager`` and ``web_fetcher`` import no tools of their own
    # but were already in the registration tuple before this audit, so they stay
    # there (loading them is harmless and removing them would be a behaviour
    # change for no security benefit). They are helpers for file_ops and the
    # web-search tools respectively.
}

_TOOL_MODULE_HINTS = {
    "api_request": "api_tester",
    "consult_agent": "agent_comm",
    "get_budget_report": "context_budget_tool",
    "get_knowledge_memory": "knowledge_tools",
    "get_project_summary": "project_tools",
    "get_system_health": "system_health_tool",
    "check_context_size": "context_budget_tool",
    "trim_context": "context_budget_tool",
    "search_knowledge": "knowledge_tools",
    "add_knowledge": "knowledge_tools",
    "list_project_files": "project_tools",
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
    "sequential_thinking": "sequential_thinking_tool",
    "system_health": "system_health_tool",
    "cancel_run": "session_tools",
    "get_session_status": "session_tools",
    "list_skills": "skills_tools",
    "load_skill": "skills_tools",
    "discover_skill_candidates": "skills_tools",
    "build_skill": "skills_tools",
    "mcp_builder": "mcp_tools",
    "mcp_call_readonly_tool": "mcp_tools",
    "mcp_call_tool": "mcp_tools",
    "mcp_list_tools": "mcp_tools",
    "mcp_recommend_tools": "mcp_tools",
    "mcp_project_context": "mcp_tools",
    "mcp_impact_analysis": "mcp_tools",
    "mcp_project_status": "mcp_tools",
    "mcp_sequential_thinking": "mcp_tools",
    "pause_session": "session_tools",
    "resume_session": "session_tools",
    "todo_list": "todo_tools",
    "todo_write": "todo_tools",
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
    #
    # Audit P1-7: this tuple is the *complete* list of tool modules.  Five of
    # them were missing, which made ten registered-looking tools invisible to
    # ``get_tool_catalog()`` and therefore to the LLM:
    # context_budget_tool (3), knowledge_tools (3), project_tools (2),
    # system_health_tool (1) and system_tools (1).
    modules = TOOL_MODULES
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
