"""Tools exposed to agents via ReAct actions. See ARCHITECTURE.md §5.2."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_TOOLS_REGISTERED = False


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

    # Import order does not matter — each module calls ``register_tool``
    # as a side-effect of being imported.
    from backend.tools import advanced_templates as _advanced_templates  # noqa: F401
    from backend.tools import agent_bus_tools as _agent_bus_tools  # noqa: F401
    from backend.tools import agent_comm as _agent_comm  # noqa: F401
    from backend.tools import browser_automation as _browser_automation  # noqa: F401
    from backend.tools import code_executor as _code_executor  # noqa: F401
    from backend.tools import data_analysis as _data_analysis  # noqa: F401
    from backend.tools import dependency_manager as _dependency_manager  # noqa: F401
    from backend.tools import doc_tools as _doc_tools  # noqa: F401
    from backend.tools import directory_tools as _directory_tools  # noqa: F401
    from backend.tools import email_tools as _email_tools  # noqa: F401
    from backend.tools import embeddings as _embeddings  # noqa: F401
    from backend.tools import file_manager as _file_manager  # noqa: F401
    from backend.tools import file_ops as _file_ops  # noqa: F401
    from backend.tools import git_tools as _git_tools  # noqa: F401
    from backend.tools import git_auto_commit as _git_auto_commit  # noqa: F401
    from backend.tools import cron_scheduler as _cron_scheduler  # noqa: F401
    from backend.tools import tts as _tts  # noqa: F401
    from backend.tools import vision as _vision  # noqa: F401
    from backend.tools import memory_tools as _memory_tools  # noqa: F401
    from backend.tools import profile_tools as _profile_tools  # noqa: F401
    from backend.tools import project_analyzer as _project_analyzer  # noqa: F401
    from backend.tools import report_generator as _report_generator  # noqa: F401
    from backend.tools import scaffold as _scaffold  # noqa: F401
    from backend.tools import shell_runner as _shell_runner  # noqa: F401
    from backend.tools import task_spawner as _task_spawner  # noqa: F401
    from backend.tools import test_generator as _test_generator  # noqa: F401
    from backend.tools import web_fetcher as _web_fetcher  # noqa: F401
    from backend.tools import web_search as _web_search  # noqa: F401
    from backend.tools import web_search_v2 as _web_search_v2  # noqa: F401

    # New features: Auto-commit, TTS, Cron, Vision
    from backend.tools import git_auto_commit as _git_auto_commit  # noqa: F401
    from backend.tools import cron_scheduler as _cron_scheduler  # noqa: F401
    from backend.tools import tts as _tts  # noqa: F401
    from backend.tools import vision as _vision  # noqa: F401

    _TOOLS_REGISTERED = True
    logger.debug("Tool registration completed (%d modules)", 26)


def __getattr__(name: str):
    """Support ``from backend.tools import x`` without forcing eager loads."""
    if name == "_ensure_tools_registered":
        return _ensure_tools_registered
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
