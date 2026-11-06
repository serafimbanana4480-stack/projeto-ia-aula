"""Tool registry - canonical list of executable tools available to agents."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from backend.persistence.db import log_tool_execution
from backend.tools.sanitizer import (
    detect_injection,
    is_external_tool,
    wrap_external_content,
)

# Tool result cache — best-effort; system works without it
try:
    from backend.cache.tool_result_cache import get_tool_cache

    _HAVE_TOOL_CACHE = True
except ImportError:
    _HAVE_TOOL_CACHE = False

logger = logging.getLogger(__name__)


@dataclass
class ToolSpec:
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    risk_level: str = "low"
    # ``risk`` is the concise contract spelling; ``risk_level`` remains for
    # compatibility with existing tool declarations.
    risk: str | None = None
    requires_confirmation: bool = False
    when_to_use: str = ""
    examples: list[dict] = field(default_factory=list)
    schema: dict[str, Any] = field(default_factory=dict)
    handler: Callable[..., Awaitable[Any]] | None = None
    enabled: bool = True
    available: bool = True
    unavailable_reason: str = ""
    missing_dependency: str = ""
    timeout_seconds: float | None = None
    # --- Discovery metadata (used by AI agents and dashboard) ---
    category: str = ""  # file, web, code, git, docker, system, data, etc.
    #: "context" when the tool's schema declares a ``session_id`` its handler
    #: cannot accept. The registry then delivers the TRUSTED session id
    #: through :func:`current_tool_session_id` instead of dropping it.
    session_id_delivery: str = ""
    #: The original handler, kept when the registry installed a session-aware
    #: adapter around it.
    inner_handler: Callable[..., Any] | None = None

    def __post_init__(self) -> None:
        if self.risk:
            self.risk_level = str(self.risk).strip().lower()
        else:
            self.risk = self.risk_level

_registry: dict[str, ToolSpec] = {}
_unavailable_modules: dict[str, dict[str, Any]] = {}

# --- Tool execution guards -------------------------------------------------
# Hard timeout for a single tool handler call. Without it a wedged handler
# (network fetch without timeout, deadlocked subprocess) suspends the whole
# ReAct loop forever — the audit's "agent hangs silently" symptom.
TOOL_TIMEOUT_SECONDS = float(os.environ.get("NEXUS_TOOL_TIMEOUT", "240"))

# Consecutive-failure circuit breaker: after N consecutive failures of the
# same tool within a session the tool is short-circuited and the agent is
# told to stop retrying it (the audit's "blacklist failed tools" rule).
TOOL_MAX_CONSECUTIVE_FAILURES = int(os.environ.get("NEXUS_TOOL_MAX_FAILURES", "3"))
_tool_failures: dict[tuple[str, str], int] = {}


def _failure_key(
    name: str,
    session_id: str | None,
    failure_scope: str | None = None,
) -> tuple[str, str]:
    # Plan tasks share a user session but must not share a circuit breaker:
    # one agent's bad tool calls must not disable the same tool for a sibling.
    return (failure_scope or session_id or "default", name)


def _record_tool_success(
    name: str,
    session_id: str | None,
    failure_scope: str | None = None,
) -> None:
    _tool_failures.pop(_failure_key(name, session_id, failure_scope), None)


def _record_tool_failure(
    name: str,
    session_id: str | None,
    failure_scope: str | None = None,
) -> int:
    key = _failure_key(name, session_id, failure_scope)
    count = _tool_failures.get(key, 0) + 1
    _tool_failures[key] = count
    return count


def tool_failure_count(
    name: str,
    session_id: str | None,
    failure_scope: str | None = None,
) -> int:
    """Current consecutive-failure count for a tool in a session/task scope."""
    return _tool_failures.get(_failure_key(name, session_id, failure_scope), 0)


# --- Trust boundary ---------------------------------------------------------
# A tool result is not automatically trustworthy. ``read_file`` on an
# untrusted checkout, shell stdout, a fetched page or an MCP server reply all
# carry text this process did not author, and that text reaches the model with
# whatever authority the surrounding message has. ``execute_tool`` is the only
# place every tool result passes through, so the quoting happens here: the
# payload is framed as data before the agent ever sees it.

#: Payload keys that carry text from the outside world. Their values are
#: quoted; the control-plane keys (``ok``, ``error``, ``exit_code``,
#: ``written``, ``evidence``, ...) are left alone so the guards, the circuit
#: breaker and the verification gate keep reading the real values.
#:
#: The keys were inventoried from the handlers of the external tools
#: themselves (``web_search_v2``, ``web_fetcher``, ``shell_runner``,
#: ``file_ops``, ``api_tester``, ``db_client``, ``email_tools``,
#: ``embeddings``) rather than guessed: a missing entry means that field
#: reaches the model unframed. Inside a framed field every string leaf is
#: quoted regardless of its own key, so nested payloads (``hits`` ->
#: ``snippet``/``title``/``url``) are covered by the parent.
_EXTERNAL_TEXT_FIELDS: frozenset[str] = frozenset(
    {
        "content",
        "text",
        "output",
        "stdout",
        "stderr",
        "summary",
        "answer",
        "body",
        "snippet",
        "snippets",
        "page_text",
        "markdown",
        "raw",
        "results",
        "hits",
        "links",
        "repositories",
        "rows",
        "columns",
        "emails",
        "memories",
        "sources",
        "response",
        "matches",
        "entries",
        # Fields the external handlers return at the top level: a fetched
        # page's <title>, an inbox listing's subjects/senders, the parsed JSON
        # body of an api_request, response headers, and the diagnostic text a
        # tool writes about itself. All of them are attacker-influenceable.
        "title",
        "message",
        "subjects",
        "senders",
        "parsed",
        "headers",
    }
)

#: Recursion cap for content trees. Web results nest (hits -> snippets), and a
#: hostile payload must not be able to spend the agent's turn walking it.
_EXTERNAL_FRAME_MAX_DEPTH = 4


def _frame_external_text(text: str, source: str) -> str:
    """Quote one text field, and log an injection attempt as a signal.

    Detection never blocks: a search result that says "ignore previous
    instructions" is still legitimate data the user asked about. The log line
    is what makes the attempt visible.
    """
    if not text or not text.strip():
        return text
    framed = wrap_external_content(text, source=source)
    signal = detect_injection(text)
    if signal.detected:
        logger.info(
            "[UNTRUSTED CONTENT] injection pattern %r found in %s output "
            "(%d chars quoted as data, not blocked)",
            signal.pattern,
            source,
            len(text),
        )
    return framed


def _frame_external_tree(value: Any, source: str, depth: int = 0) -> Any:
    """Quote every string leaf under a content field as external data."""
    if isinstance(value, str):
        return _frame_external_text(value, source)
    if depth >= _EXTERNAL_FRAME_MAX_DEPTH:
        return value
    if isinstance(value, dict):
        return {
            key: _frame_external_tree(item, source, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_frame_external_tree(item, source, depth + 1) for item in value]
    return value


def frame_external_result(name: str, payload: Any) -> Any:
    """Quote an external tool's payload as data before it leaves the registry.

    Only the textual content is framed: the success/error schema is untouched,
    so ``ok``, ``error``, ``exit_code``, ``evidence`` and the typed fields keep
    their real values. The call is idempotent — a payload that is already a
    complete data block is returned unchanged, so a cache hit cannot double
    the framing.

    Args:
        name: Tool name, used both to classify the payload and as the source
            recorded in the block.
        payload: The handler's result.

    Returns:
        The same payload with its external text quoted.
    """
    if not is_external_tool(name):
        return payload
    source = f"tool:{name}"
    if isinstance(payload, str):
        return _frame_external_text(payload, source)
    if not isinstance(payload, dict):
        return payload
    # Keep our warning separate from file bytes.  Models editing a file can
    # otherwise mistake the warning for source code and write it back to disk.
    # The nonce-delimited untrusted boundary still surrounds the file itself.
    framed: dict[str, Any] = {}
    for key, value in payload.items():
        framed[key] = (
            _frame_external_tree(value, source) if key in _EXTERNAL_TEXT_FIELDS else value
        )
    if name in {"read_file", "read_file_absolute"} and isinstance(payload.get("content"), str):
        from backend.tools.sanitizer import PREAMBLE

        framed["content"] = wrap_external_content(
            payload["content"], source=source, include_preamble=False
        )
        framed["content_warning"] = PREAMBLE
    return framed


def reset_tool_failures(session_id: str | None = None) -> None:
    """Reset one session/task failure scope, or every scope when omitted.

    Plan execution passes a task-specific scope so parallel tasks in the same
    session do not clear or inherit one another's failure streaks.

    Run 2026-08-03T21:53 session bf1e9435b9ec47c9 is the reference failure:
    ``run_shell`` tripped the breaker during the ANALYZER phase (three blocked
    PowerShell verbs), and when the DEBUGGER's ``Verify`` task started three
    minutes later the tool was still short-circuited on its very first
    iteration. The ``verification`` evidence gate can only be closed by an
    executable check, so the task was unwinnable before it began and ended as
    "Agent execution failed its runtime/tool evidence gate".
    """
    if session_id is None:
        _tool_failures.clear()
        return
    for key in [k for k in _tool_failures if k[0] == (session_id or "default")]:
        del _tool_failures[key]


def reset_tool_failure(name: str, session_id: str | None = None) -> None:
    """Reset the breaker for a single tool, leaving other tools untouched."""
    _tool_failures.pop(_failure_key(name, session_id), None)

_UNAVAILABLE_MODULE_TOOLS: dict[str, tuple[str, ...]] = {
    "browser_automation": (
        "browser_navigate",
        "browser_click",
        "browser_fill",
        "browser_extract_text",
        "browser_screenshot",
        "browser_get_links",
        "browser_close",
    ),
}

# ---------------------------------------------------------------------------
# Optional dependencies behind a tool
# ---------------------------------------------------------------------------
# A tool whose third-party dependency is not installed cannot work: the call
# fails at the first use of the missing package. The catalog used to report
# those tools as ``available=True`` anyway, so the LLM was offered a tool that
# could only ever fail (the audit found 4 ``db_*`` tools needing ``aiosqlite``
# and 7 ``browser_*`` tools needing ``playwright``).
#
# The registry owns the truth: it probes the dependency when the spec is
# registered and marks the spec unavailable, so ``get_tool_catalog()`` reports
# ``missing_dependency`` and ``list_tools()`` stops offering the tool.
#
# The owning module is part of the entry on purpose: the entry describes the
# REAL implementation. A stand-in registered under the same name (a test
# double, an alternative backend) is not the browser tool and must not be
# marked unavailable because Playwright is missing.
_OPTIONAL_DEPENDENCY_TOOLS: dict[str, tuple[str, str, str]] = {
    # tool name -> (owning module, importable module, how to install it)
    "browser_navigate": (
        "backend.tools.browser_automation",
        "playwright",
        "uv sync --extra browser",
    ),
    "browser_click": (
        "backend.tools.browser_automation",
        "playwright",
        "uv sync --extra browser",
    ),
    "browser_fill": (
        "backend.tools.browser_automation",
        "playwright",
        "uv sync --extra browser",
    ),
    "browser_extract_text": (
        "backend.tools.browser_automation",
        "playwright",
        "uv sync --extra browser",
    ),
    "browser_screenshot": (
        "backend.tools.browser_automation",
        "playwright",
        "uv sync --extra browser",
    ),
    "browser_get_links": (
        "backend.tools.browser_automation",
        "playwright",
        "uv sync --extra browser",
    ),
    "browser_close": (
        "backend.tools.browser_automation",
        "playwright",
        "uv sync --extra browser",
    ),
}


def _module_is_importable(module_name: str) -> bool:
    """Whether *module_name* can be imported (without importing it)."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError):
        return False


def _apply_optional_dependency_availability(spec: ToolSpec) -> None:
    """Mark *spec* unavailable when its optional dependency is missing."""
    requirement = _OPTIONAL_DEPENDENCY_TOOLS.get(spec.name)
    if requirement is None:
        return
    owning_module, module_name, install_hint = requirement
    handler_module = str(getattr(spec.handler, "__module__", "") or "")
    if handler_module and handler_module != owning_module:
        # A stand-in, not the real implementation: its availability is its own.
        return
    if _module_is_importable(module_name):
        return
    spec.available = False
    spec.missing_dependency = module_name
    spec.unavailable_reason = (
        f"the optional dependency '{module_name}' is not installed; "
        f"install it with: {install_hint}"
    )


# ---------------------------------------------------------------------------
# Tool categories
# ---------------------------------------------------------------------------
# Every tool belongs to a category. Without one the LLM prompt rendered 111
# tools under the heading of whatever tool happened to come before them, and
# ``get_tools_for_agent("WEB")`` matched only the three tools whose *name*
# contains "web" instead of the whole web category.
#
# The defaults are per module (the natural granularity: a module is one
# capability) with a per-tool override for the tools a module registers that
# belong somewhere else.
_MODULE_CATEGORY_DEFAULTS: dict[str, str] = {
    "backend.core.workspace": "file",
    "backend.tools.advanced_templates": "code",
    "backend.tools.agent_bus_tools": "task",
    "backend.tools.agent_comm": "task",
    "backend.tools.api_tester": "api",
    "backend.tools.append_file": "file",
    "backend.tools.browser_automation": "browser",
    "backend.tools.code_executor": "code",
    "backend.tools.cron_scheduler": "task",
    "backend.tools.data_analysis": "data",
    "backend.tools.db_client": "data",
    "backend.tools.dependency_manager": "code",
    "backend.tools.directory_tools": "file",
    "backend.tools.doc_tools": "code",
    "backend.tools.email_tools": "email",
    "backend.tools.embeddings": "code",
    "backend.tools.file_ops": "file",
    "backend.tools.git_auto_commit": "git",
    "backend.tools.git_tools": "git",
    "backend.tools.memory_tools": "memory",
    "backend.tools.notifications": "notification",
    "backend.tools.profile_tools": "memory",
    "backend.tools.project_analyzer": "project",
    "backend.tools.quality_tools": "code",
    "backend.tools.report_generator": "data",
    "backend.tools.scaffold": "code",
    "backend.tools.shell_runner": "code",
    "backend.tools.task_spawner": "task",
    "backend.tools.test_generator": "code",
    "backend.tools.test_runner": "code",
    "backend.tools.tts": "media",
    "backend.tools.vision": "media",
    "backend.tools.web_fetcher": "web",
    "backend.tools.web_search": "web",
    "backend.tools.web_search_v2": "web",
}

#: Tools whose category differs from their module's default.
_TOOL_CATEGORY_OVERRIDES: dict[str, str] = {
    # backend.core.workspace registers file, git, project and code tools.
    "git_clone": "git",
    "git_commit_all": "git",
    "git_init": "git",
    "git_status": "git",
    "execute_python": "code",
    "execute_script": "code",
    "execute_shell": "code",
    "restore_backup": "file",
    "list_backups": "file",
    "discover_projects": "project",
    "get_project_info": "project",
    # notifications registers a webhook, a desktop toast and an e-mail sender.
    "send_email_notification": "email",
}

#: Capability aliases per category. ``get_tools_for_agent`` matches an agent
#: name against these, so an agent named after a capability ("WEB", "GIT",
#: "DATA") receives the whole category instead of a handful of name matches.
_CATEGORY_CAPABILITIES: dict[str, tuple[str, ...]] = {
    "api": ("api", "http", "rest"),
    "browser": ("browser", "playwright"),
    "code": ("code", "exec", "lint", "test", "quality", "scaffold", "docs"),
    "data": ("data", "database", "db", "sql", "analysis", "report"),
    "docker": ("docker", "container"),
    "email": ("email", "imap", "smtp", "mail"),
    "file": ("file", "fs", "io", "path", "directory"),
    "git": ("git", "vcs", "commit"),
    "knowledge": ("knowledge", "rag"),
    "mcp": ("mcp",),
    "media": ("media", "tts", "voice", "vision", "image", "ocr"),
    "memory": ("memory", "recall", "profile"),
    "notification": ("notification", "notify", "alert", "webhook"),
    "project": ("project", "workspace"),
    "system": ("system", "session", "todo", "skill", "health", "budget"),
    "task": ("task", "schedule", "cron", "agent", "bus", "spawn"),
    "web": ("web", "search", "fetch", "research"),
}

#: Fallback for a tool registered from a module nobody classified.
_DEFAULT_CATEGORY = "system"


def _default_category(tool_name: str, module_name: str) -> str:
    """Return the category a tool gets when it does not declare one."""
    override = _TOOL_CATEGORY_OVERRIDES.get(tool_name)
    if override:
        return override
    return _MODULE_CATEGORY_DEFAULTS.get(module_name, _DEFAULT_CATEGORY)

_CONFIRMATION_TOOLS = {
    "write_file_absolute",
    "delete_file",
    "delete_file_absolute",
    "delete_directory",
    "delete_dir_absolute",
    "move_file",
    "move_file_absolute",
    "copy_file",
    "copy_file_absolute",
    "git_push",
    "git_operation",
    # Commit execution. These write history without a human decision, so they
    # are approval-gated here AND carry an explicit high risk_level: the gate
    # must not depend on a single name list being maintained correctly.
    "git_commit_safe",
    "git_commit_all",
    "approve_pending_commit",
    "git_pull",
    "git_init",
    "git_clone",
    # The auto-commit hook writes history without a human decision, exactly
    # like ``git_commit_safe``. It used to call the commit helper directly in
    # Python, so the gate above was never consulted; registering it here is
    # what makes the whole hook approval-gated.
    "auto_commit_after_write",
    # Writes a SKILL.md into the user's project.
    "build_skill",
    "install_dependency",
    "execute_shell",
    "run_shell",
    "browser_navigate",
    "browser_click",
    "browser_fill",
    "web_search",
    "search_web_v2",
    "fetch_url",
    "deep_research",
}

# Operations that are safe to run unattended when the agent is operating in
# an explicitly autonomous session.  The normal confirmation gate remains in
# place for interactive sessions.  This list is intentionally narrow: an
# autonomous agent must keep moving, but it must not silently turn an
# external side effect (push, delete, browser interaction, email, etc.) into
# an implicit approval.
_AUTONOMOUS_READ_ONLY_TOOLS = frozenset(
    {
        "web_search",
        "search_web_v2",
        "fetch_url",
        "deep_research",
        "search_github",
        "search_docs",
        "read_file",
        "list_files",
        "list_workspace_files",
        "read_workspace_file",
        "get_settings",
        "get_projects",
        "get_metrics",
        "get_health",
        "get_system_health",
    }
)
_SAFE_AUTONOMOUS_COMMANDS = frozenset(
    {
        "pytest",
        "python -m pytest",
        "ruff",
        "python -m ruff",
        "mypy",
        "python -m mypy",
        "pyright",
        "python -m pyright",
        "vitest",
        "jest",
        "npm test",
        "npm run test",
        "npm run build",
        "pnpm test",
        "pnpm build",
        "yarn test",
        "yarn build",
        "git status",
        "git diff",
        "git log",
        "git branch",
        "git rev-parse",
        "git show",
        "pwd",
        "ls",
        "dir",
        "cd",
        "get-childitem",
        "get-location",
        "gci",
        "rg",
        # Interpreter/toolchain probes. A DEBUGGER step that cannot answer
        # "which python am I running?" cannot produce verification evidence.
        "python --version",
        "python -v",
        # ``python -c`` is deliberately absent. The execution gate
        # (``workspace_security._validate_single_command``) refuses inline code
        # unconditionally, so approving it here only produced a misleading
        # "[autonomous_blocked] requires human approval" instead of the real
        # reason. Inline code belongs in ``execute_code``, which is sandboxed.
        "python -m pip list",
        "python -m pip show",
        "python -m pip freeze",
        "pip list",
        "pip show",
        "pip freeze",
        "node --version",
        "node -v",
        "npm --version",
        "npm ls",
        "npm list",
        "pnpm --version",
        "pnpm list",
        "where",
        "which",
        "where.exe",
        "get-command",
        "tsc --noemit",
        "npx tsc --noemit",
        "npm run typecheck",
        "npm run lint",
        "pnpm typecheck",
        "pnpm lint",
        "cat",
        "type",
        "get-content",
        "head",
        "tail",
        "wc",
        "findstr",
        "select-string",
        "sort",
        "uniq",
        "grep",
        "echo",
        "test-path",
        "measure-object",
        "select-object",
        "sort-object",
        "where-object",
        "foreach-object",
        "format-table",
        "format-list",
        "out-string",
        "convertto-json",
    }
)

#: Characters that can redirect output, fork a background job, or hand the
#: rest of the line to a subshell. These stay hard-blocked: unlike ``&&`` and
#: ``|`` they can create or overwrite files, or hide a second command whose
#: text we never inspect.
_UNSAFE_SHELL_CHARS: tuple[str, ...] = (">", "<", "`", "$(")

#: Stderr discards/merges. They cannot create a file with attacker-chosen
#: contents, and models emit them constantly (``pip list 2>nul``), so they are
#: stripped before the redirection check rather than failing the whole command.
_BENIGN_REDIRECTS_RE = re.compile(r"\s*2\s*>\s*(?:&\s*1|nul|/dev/null)")


def _strip_quoted_spans(command: str) -> str:
    """Blank out quoted regions, preserving length and quote positions.

    Separators inside quotes are data, not operators. Without this,
    ``python -c "import sys; print(sys.version)"`` was split at the ``;``
    into ``python -c "import sys`` + ``print(sys.version)"``; the second
    fragment matched nothing and the whole command was refused
    (session 8d7cd19a70934c81, iteration 7).
    """
    out = list(command)
    quote: str | None = None
    for index, char in enumerate(command):
        if quote is None:
            if char in ("'", '"'):
                quote = char
        elif char == quote:
            quote = None
        else:
            out[index] = " "
    return "".join(out)


def _split_shell_segments(normalized: str) -> list[str]:
    """Split a command line on *unquoted* separators we are willing to inspect.

    ``&&``, ``||``, ``|`` and ``;`` chain commands whose text is fully visible
    to us, so each side can be validated independently. A single ``&`` is
    job control (or, on PowerShell, the call operator) and is refused by
    :func:`_is_safe_autonomous_command` before this function runs.

    Splitting is decided on a quote-masked copy so that positions are shared
    with the original, then applied to the original text.
    """
    masked = _strip_quoted_spans(normalized)
    cuts: list[tuple[int, int]] = []
    index = 0
    while index < len(masked):
        for separator in ("&&", "||", "|", ";"):
            if masked.startswith(separator, index):
                cuts.append((index, index + len(separator)))
                index += len(separator)
                break
        else:
            index += 1

    segments: list[str] = []
    previous = 0
    for start, end in cuts:
        segments.append(normalized[previous:start])
        previous = end
    segments.append(normalized[previous:])
    return [segment.strip() for segment in segments if segment.strip()]


def _segment_is_safe(segment: str) -> bool:
    return any(
        segment == prefix or segment.startswith(f"{prefix} ")
        for prefix in _SAFE_AUTONOMOUS_COMMANDS
    )


def _is_safe_autonomous_command(command: object) -> bool:
    """Return True for a bounded, read-only validation/inspection command.

    Every segment of a chained command must independently be a known
    read-only probe. Blanket-refusing ``|`` and ``&&`` — the previous
    behaviour — deadlocked autonomous runs: the DEBUGGER/Verify step is
    *required* to produce runtime evidence, but the shell idioms it reaches
    for on Windows (``cd ... && pytest``, ``Get-ChildItem | Select-Object``)
    were rejected wholesale, so the evidence gate could never be satisfied
    and every Verify task failed (run 2026-08-02T05:22, session
    b9f0dfbd53ad402a: 5 blocked ``run_shell`` calls, all read-only).

    Redirection, backticks and command substitution remain refused because
    their effect is not visible in the text we validate.

    A line break is refused on the RAW command, before normalisation. Bare
    ``str.split()`` folds ``\\n``, ``\\r``, ``\\x0b`` and ``\\x0c`` into spaces, so
    ``"git status\\nwhoami"`` normalised to the single-line string
    ``"git status whoami"`` and satisfied the ``git status`` prefix allowlist
    while the text handed to the shell still contained a line break. The
    payload never reaches the prefix allowlist or the segment splitter now.
    """
    if not isinstance(command, str):
        return False
    if any(char in command for char in ("\n", "\r", "\x0b", "\x0c")):
        return False
    normalized = " ".join(command.strip().lower().split())
    if not normalized:
        return False
    normalized = _BENIGN_REDIRECTS_RE.sub("", normalized)
    # Operator checks run against a quote-masked copy: a ``>`` or ``&`` inside
    # a quoted argument is data the shell never interprets.
    masked = _strip_quoted_spans(normalized)
    if any(token in masked for token in _UNSAFE_SHELL_CHARS):
        return False
    # A lone ``&`` is backgrounding / PowerShell's call operator. ``&&`` is a
    # visible chain and is handled by the segment walk below.
    if re.search(r"(?<!&)&(?!&)", masked):
        return False
    segments = _split_shell_segments(normalized)
    if not segments:
        return False
    return all(_segment_is_safe(segment) for segment in segments)


def _path_is_within_project(
    path: object, project_path: str, *, relative_to_project: bool = False
) -> bool:
    """Return whether a target resolves inside the selected project."""
    if not isinstance(path, str) or not path.strip() or not project_path.strip():
        return False
    try:
        root_path = os.path.realpath(os.path.abspath(project_path))
        target_path = path.strip()
        if not os.path.isabs(target_path):
            drive, _tail = os.path.splitdrive(target_path)
            if not relative_to_project or drive:
                return False
            target_path = os.path.join(root_path, target_path)
        target = os.path.normcase(os.path.realpath(os.path.abspath(target_path)))
        root = os.path.normcase(root_path)
        return os.path.commonpath((target, root)) == root
    except (OSError, ValueError):
        return False


def _apply_trusted_project_scope(
    name: str,
    spec: ToolSpec,
    args: dict[str, Any],
    project_path: str,
) -> str | None:
    """Replace model-selected roots and confine working directories.

    Project identity comes from the request context. A provider argument may
    select a subdirectory within that project, but it cannot switch the tool
    to another checkout or an arbitrary host directory.
    """
    properties = spec.schema.get("properties", {})
    if not isinstance(properties, dict):
        return None

    selected_root = str(project_path or "").strip()
    if selected_root:
        selected_root = os.path.realpath(
            os.path.abspath(os.path.expanduser(selected_root))
        )
        if "project_path" in properties:
            args["project_path"] = selected_root

        if name == "execute_script" and "path" in properties:
            requested_script = args.get("path")
            if isinstance(requested_script, str) and requested_script.strip():
                requested_script = requested_script.strip()
                if not _path_is_within_project(
                    requested_script, selected_root, relative_to_project=True
                ):
                    return "Script path is outside the selected project."
                if not os.path.isabs(requested_script):
                    requested_script = os.path.join(selected_root, requested_script)
                args["path"] = os.path.realpath(os.path.abspath(requested_script))

        if "cwd" in properties:
            requested_cwd = args.get("cwd")
            if not isinstance(requested_cwd, str) or not requested_cwd.strip():
                args["cwd"] = selected_root
            else:
                requested_cwd = requested_cwd.strip()
                if not _path_is_within_project(
                    requested_cwd, selected_root, relative_to_project=True
                ):
                    return (
                        f"Working directory '{requested_cwd}' is outside the selected project."
                    )
                if not os.path.isabs(requested_cwd):
                    requested_cwd = os.path.join(selected_root, requested_cwd)
                args["cwd"] = os.path.realpath(os.path.abspath(requested_cwd))
    else:
        # With no selected project, a provider-supplied path cannot establish
        # project identity. Fail closed instead of letting the handler default
        # to the server's current directory. A few session-scoped tools
        # intentionally carry an empty trusted project_path.
        if "project_path" in properties and name not in {
            "store_memory",
            "consult_agent",
            "spawn_task",
        }:
            if isinstance(args.get("project_path"), str) and args["project_path"].strip():
                return "A trusted project must be selected before using this tool."
            args.pop("project_path", None)

        if (
            name == "execute_script"
            and "path" in properties
            and isinstance(args.get("path"), str)
            and args["path"].strip()
        ):
            return "A trusted project must be selected before executing a script."

        if "cwd" in properties:
            if isinstance(args.get("cwd"), str) and args["cwd"].strip():
                return "A trusted project must be selected before setting a working directory."
            args.pop("cwd", None)

    return None


def _sentinel_paths_within_project(
    args: dict[str, Any], project_path: str, *keys: str
) -> bool:
    """Check every supplied path argument against the selected project root."""
    paths: list[str] = []
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            paths.append(value.strip())
        elif isinstance(value, (list, tuple)):
            paths.extend(
                item.strip()
                for item in value
                if isinstance(item, str) and item.strip()
            )
    return bool(paths and project_path) and all(
        _path_is_within_project(path, project_path, relative_to_project=True)
        for path in paths
    )


def _project_confinement_error(
    name: str, args: dict[str, Any], project_path: str
) -> str | None:
    """Refuse a tool path that is not inside the selected project.

    Absolute-path tools only applied the system-directory blocklist, so a
    path under the user profile but outside the selected project was read or
    written. An empty project is not an implicit root: the caller must select
    one. Paths inside the selected project are unchanged.
    """
    keys = _PROJECT_CONFINED_PATH_KEYS.get(name)
    if not keys or not isinstance(args, dict):
        return None
    supplied: list[str] = []
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            supplied.append(value.strip())
        elif isinstance(value, (list, tuple)):
            supplied.extend(
                item.strip() for item in value if isinstance(item, str) and item.strip()
            )
    if not supplied:
        return None
    root = str(project_path or "").strip()
    if not root:
        return (
            "A trusted project must be selected before this tool can use a path. "
            "Select the project and send the request again."
        )
    for candidate in supplied:
        if not _path_is_within_project(candidate, root, relative_to_project=True):
            return (
                f"Path '{candidate}' is outside the selected project and was not used. "
                "Select that folder as the project if the task should work there."
            )
    return None


_SENTINEL_PROJECT_READ_PATH_KEYS = {
    "read_file": ("path",),
    "read_multiple_files": ("paths",),
    "list_dir": ("path",),
    "search_in_files": ("root_path", "path"),
    "get_file_info": ("path",),
    "search_codebase": ("project_path",),
    "search_symbols": ("project_path",),
    "analyze_project": ("project_path", "path"),
    "get_project_summary": ("project_path", "path"),
    "list_project_files": ("project_path", "path"),
    "mcp_project_context": ("project_path",),
    "mcp_impact_analysis": ("project_path",),
    "mcp_project_status": ("project_path",),
}

_SENTINEL_ABSOLUTE_READ_PATH_KEYS = {
    "read_file_absolute": ("path",),
    "list_dir_absolute": ("path",),
    "search_files_absolute": ("root_path",),
    "read_multiple_files_absolute": ("paths",),
    "get_file_info_absolute": ("path",),
    "list_backups": ("path",),
    "discover_projects": ("root_path",),
    "get_project_info": ("path",),
    "git_status": ("path",),
}

# Tools whose handlers honour an absolute path after only the system-path
# blocklist. The selected project is the trust boundary: a path in the
# arguments must not open another folder, and confirmation of that path is
# not a substitute for selecting the project.
_PROJECT_CONFINED_PATH_KEYS = {
    "read_file_absolute": ("path",),
    "list_dir_absolute": ("path",),
    "search_files_absolute": ("root_path",),
    "read_multiple_files_absolute": ("paths",),
    "get_file_info_absolute": ("path",),
    "list_backups": ("path",),
    "create_dir_absolute": ("path",),
    "delete_file_absolute": ("path",),
    "delete_dir_absolute": ("path",),
    "move_file_absolute": ("src", "dest"),
    "copy_file_absolute": ("src", "dest"),
    "write_file_absolute": ("path",),
    "append_file": ("path",),
    "generate_tests": ("file_path",),
    "restore_backup": ("backup_path", "target_path"),
    "discover_projects": ("root_path",),
    "get_project_info": ("path",),
    "git_status": ("path",),
}

_SENTINEL_EXTERNAL_READ_TOOLS = frozenset(
    {
        "consult_agent",
        "web_search",
        "fetch_url",
        "fetch_and_summarize",
        "search_web_v2",
        "fetch_content_v2",
        "deep_research",
        "search_github",
        "search_docs",
        "search_and_answer",
        "mcp_call_readonly_tool",
    }
)

_SENTINEL_LOCAL_READ_ONLY_TOOLS = frozenset(
    {
        "check_context_size",
        "get_budget_report",
        "list_tasks",
        "scheduler_status",
        "db_schema",
        "db_tables",
        "index_stats",
        "get_commit_history",
        "get_commit_statistics",
        "search_knowledge",
        "get_knowledge_memory",
        "recall_context",
        "mcp_list_tools",
        "mcp_recommend_tools",
        "mcp_sequential_thinking",
        "get_user_profile",
        "recall_user_memories",
        "get_system_health",
        "get_session_status",
        "todo_list",
        "list_skills",
        "discover_skill_candidates",
        "browser_extract_text",
        "browser_get_links",
        "tts_status",
        "vision_status",
        "sequential_thinking",
    }
)


def autonomous_confirmation_required(
    spec: ToolSpec,
    args: dict[str, Any],
    *,
    project_path: str = "",
) -> bool:
    """Decide whether an autonomous call still needs a human decision.

    This is separate from :func:`tool_requires_confirmation` so the default
    interactive safety contract is unchanged.  Autonomous mode may proceed
    through reversible reads, research and verification, while every
    irreversible or externally visible operation remains a real blocker.
    """
    if not tool_requires_confirmation(spec):
        return False
    if spec.name in _AUTONOMOUS_READ_ONLY_TOOLS:
        return False
    if spec.name in {"write_file_absolute", "write_file", "create_file"}:
        # Writing a requested artifact inside the active project is a normal,
        # recoverable implementation step. Paths outside that boundary keep
        # the explicit approval gate.
        path = args.get("path") or args.get("file_path") or args.get("filename")
        return not _path_is_within_project(
            path,
            project_path,
            relative_to_project=spec.name in {"write_file", "create_file"},
        )
    if spec.name in {"delete_file", "delete_file_absolute", "delete_directory", "delete_dir_absolute", "move_file", "move_file_absolute", "copy_file", "copy_file_absolute"}:
        # Project scope does not make destructive operations reversible.
        # Deletion and moves also violate the repository's explicit "nothing
        # is deleted" rule; copies can overwrite a target, so they stay behind
        # the same human confirmation gate.
        return True
    if spec.name in {"execute_shell", "run_shell"}:
        return not _is_safe_autonomous_command(args.get("command"))
    return True


def register_tool(spec: ToolSpec) -> ToolSpec:
    """Register *spec*, filling in the metadata the registry owns.

    Three things are filled in here because they are facts about the tool that
    only the registry can see:

    * the **category** — a spec that does not declare one is classified from
      the module that registered it (see
      :data:`_MODULE_CATEGORY_DEFAULTS`), so every registered tool has a
      category and the LLM prompt groups them correctly;
    * the **availability** — a tool whose optional dependency is not installed
      is marked unavailable (see :data:`_OPTIONAL_DEPENDENCY_TOOLS`), so the
      catalog stops offering a tool that cannot work;
    * the **session id** — a tool whose schema declares ``session_id`` but
      whose handler cannot take it gets a session-aware adapter, so the
      declared value is delivered instead of being dropped.
    """
    if not spec.category:
        caller = inspect.currentframe()
        module_name = ""
        if caller is not None and caller.f_back is not None:
            module_name = str(caller.f_back.f_globals.get("__name__", ""))
        spec.category = _default_category(spec.name, module_name)
    _apply_optional_dependency_availability(spec)
    if (
        spec.handler is not None
        and _schema_declares_session_id(spec)
        and not _handler_accepts_session_id(spec.handler)
    ):
        # The schema promises the caller a trusted session id and the handler
        # cannot take it. Without the adapter the registry would have to drop
        # the value (and, before that, reject the whole call), so the tool
        # would never see the session its own schema advertises.
        spec.inner_handler = spec.handler
        spec.handler = _session_aware_handler(spec, spec.handler)
        spec.session_id_delivery = "context"
    _registry[spec.name] = spec
    logger.info("Registered tool: %s", spec.name)
    return spec


def record_unavailable_module(module_name: str, error: str) -> None:
    """Record an optional module that could not be imported.

    The dashboard uses this information to show a truthful ``missing_dependency``
    state instead of silently omitting the affected tools.
    """
    _unavailable_modules[module_name] = {
        "error": error,
        "tools": _UNAVAILABLE_MODULE_TOOLS.get(module_name, ()),
    }


def tool_requires_confirmation(spec: ToolSpec) -> bool:
    """Return whether a tool must be approved before execution."""
    return (
        spec.requires_confirmation
        or spec.risk_level in {"high", "critical"}
        or spec.name in _CONFIRMATION_TOOLS
    )


def get_tool_catalog() -> list[dict[str, Any]]:
    """Return truthful availability and safety metadata for the UI."""
    _maybe_register()
    catalog: list[dict[str, Any]] = []
    for spec in sorted(_registry.values(), key=lambda item: item.name):
        requires_confirmation = tool_requires_confirmation(spec)
        status = (
            "missing_dependency"
            if not spec.available and spec.missing_dependency
            else "unavailable"
            if not spec.available
            else "blocked"
            if not spec.enabled
            else "requires_confirmation"
            if requires_confirmation
            else "available"
        )
        catalog.append(
            {
                "name": spec.name,
                "description": spec.description,
                "enabled": spec.enabled,
                "available": spec.available,
                "status": status,
                "schema": spec.schema,
                "category": spec.category or "uncategorised",
                "risk": spec.risk or spec.risk_level,
                "risk_level": spec.risk_level,
                "requires_confirmation": requires_confirmation,
                "when_to_use": spec.when_to_use,
                "tags": spec.tags,
                "unavailable_reason": spec.unavailable_reason,
                "missing_dependency": spec.missing_dependency,
                "timeout_seconds": spec.timeout_seconds,
            }
        )
    known_names = {item["name"] for item in catalog}
    for module_name, info in sorted(_unavailable_modules.items()):
        for tool_name in info["tools"]:
            if tool_name in known_names:
                continue
            catalog.append(
                {
                    "name": tool_name,
                    "description": f"Tool disponibilizada pelo módulo {module_name}.",
                    "enabled": False,
                    "available": False,
                    "status": "missing_dependency",
                    "schema": {},
                    "category": "browser" if module_name == "browser_automation" else "system",
                    "risk": "medium",
                    "risk_level": "medium",
                    "requires_confirmation": True,
                    "missing_dependency": module_name,
                    "unavailable_reason": info["error"],
                    "error": info["error"],
                }
            )
    return catalog


def _maybe_register() -> None:
    """Trigger lazy tool registration if it hasn't happened yet."""
    try:
        from backend.tools import _ensure_tools_registered

        _ensure_tools_registered()
    except ImportError:
        pass


def get_tool(name: str) -> ToolSpec | None:
    if name not in _registry:
        from backend.tools import _ensure_tool_registered

        _ensure_tool_registered(name)
    if name not in _registry:
        _maybe_register()
    return _registry.get(name)


def list_tools(enabled_only: bool = True) -> list[ToolSpec]:
    _maybe_register()
    tools = list(_registry.values())
    if enabled_only:
        tools = [t for t in tools if t.enabled and t.available]
    return tools
# ---------------------------------------------------------------------------
# Discovery helpers (used by AI agents, dashboard, and the orchestrator)
# ---------------------------------------------------------------------------
def list_tools_by_category(enabled_only: bool = True) -> dict[str, list[ToolSpec]]:
    """Group enabled tools by category. Categories with no tools are omitted."""
    out: dict[str, list[ToolSpec]] = {}
    for tool in list_tools(enabled_only=enabled_only):
        cat = tool.category or "uncategorised"
        out.setdefault(cat, []).append(tool)
    return out


def list_tools_by_tag(tag: str, enabled_only: bool = True) -> list[ToolSpec]:
    """Return tools that have the given tag."""
    return [t for t in list_tools(enabled_only=enabled_only) if tag in t.tags]


def search_tools(query: str, enabled_only: bool = True) -> list[ToolSpec]:
    """Fuzzy search tools by name, description, tag, or category.

    Args:
        query: Free-text search string. Case-insensitive.

    Returns:
        Tools whose name, description, tags, or category contain the query.
        Sorted by relevance (name match > description > tag > category).
    """
    if not query:
        return []
    q = query.lower().strip()
    scored: list[tuple[int, ToolSpec]] = []
    for tool in list_tools(enabled_only=enabled_only):
        score = 0
        if q in tool.name.lower():
            score += 10
        if q in tool.description.lower():
            score += 5
        for tag in tool.tags:
            if q in tag.lower():
                score += 3
        if tool.category and q in tool.category.lower():
            score += 2
        if score > 0:
            scored.append((score, tool))
    scored.sort(key=lambda x: -x[0])
    return [t for _, t in scored]


def _agent_tokens(agent_name: str) -> set[str]:
    """Split an agent name into comparable upper-case tokens."""
    return {part.upper() for part in re.split(r"[^A-Za-z0-9]+", agent_name) if part}


def get_tools_for_agent(agent_name: str) -> list[ToolSpec]:
    """Return tools relevant to a given agent type.

    The agent name is matched against the tool's *capability* first: its
    category and the capability aliases of that category (see
    :data:`_CATEGORY_CAPABILITIES`). Matching is token based, so an agent
    named "WEB" (or "WEB_RESEARCHER") gets the whole web category instead of
    the three tools whose name happens to contain "web", and an agent named
    "CODER" is not silently narrowed to the code category by a substring
    coincidence.

    Tags and tool names are still matched (loosely, as before) and the union
    of all matches is returned. An agent name that matches nothing at all
    still receives the full catalog: refusing to give an agent any tool is a
    worse failure than a slightly wide selection.
    """
    if not agent_name:
        return list_tools()
    agent = agent_name.upper()
    tokens = _agent_tokens(agent_name)
    matched: set[str] = set()
    for tool in list_tools():
        # Check tags
        for tag in tool.tags:
            if tag.upper() in agent or agent in tag.upper():
                matched.add(tool.name)
        # Check the category and the capabilities it stands for
        category = (tool.category or "").lower()
        if category and category.upper() in tokens:
            matched.add(tool.name)
        for capability in _CATEGORY_CAPABILITIES.get(category, ()):
            if capability.upper() in tokens:
                matched.add(tool.name)
        # Check name
        if agent in tool.name.upper():
            matched.add(tool.name)
    return [t for t in list_tools() if t.name in matched] or list_tools()


def get_tool_descriptions_for_llm(
    agent_name: str | None = None,
    include_examples: bool = True,
    include_risk: bool = True,
    max_tools: int | None = None,
) -> str:
    """Return a formatted text block describing tools, suitable for system prompts.

    The tools are grouped by category before rendering, so every category
    heading appears exactly once. Rendering them in registration order instead
    produced the same heading several times and left most tools under a
    heading that had nothing to do with them.

    Args:
        agent_name: If provided, filter to tools relevant to that agent.
        include_examples: Include 1 example per tool.
        include_risk: Include risk level annotation.
        max_tools: Limit the number of tools (useful for small-context models).

    Returns:
        A multi-line text block ready to be appended to a system prompt.
    """
    tools = get_tools_for_agent(agent_name) if agent_name else list_tools()
    if max_tools is not None:
        tools = tools[:max_tools]
    grouped: dict[str, list[ToolSpec]] = {}
    for tool in tools:
        grouped.setdefault(tool.category or _DEFAULT_CATEGORY, []).append(tool)
    lines: list[str] = ["# Available Tools", ""]
    for category, category_tools in grouped.items():
        lines.append(f"## {category.title()}")
        lines.append("")
        for tool in category_tools:
            risk = (
                f" [RISK: {tool.risk_level}]" if include_risk and tool.risk_level != "low" else ""
            )
            conf = " [requires confirmation]" if tool_requires_confirmation(tool) else ""
            lines.append(f"- `{tool.name}`{risk}{conf} — {tool.description}")
            if tool.when_to_use:
                lines.append(f"  - When: {tool.when_to_use}")
            if include_examples and tool.examples:
                ex = tool.examples[0]
                ex_args = ", ".join(f"{k}={v!r}" for k, v in ex.items())
                lines.append(f"  - Example: `{tool.name}({ex_args})`")
    return "\n".join(lines)


def get_tool_stats() -> dict[str, Any]:
    """Return summary statistics about the registered tools.

    The counts cover EVERY registered tool, not only the ones on offer: the
    catalog reports the unavailable ones too (with their missing dependency),
    so the statistics and the catalog must describe the same population. The
    ``available`` count says how many of them can actually be called.
    """
    tools = list_tools(enabled_only=False)
    by_cat: dict[str, int] = {}
    by_risk: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    confirmation_count = 0
    available_count = 0
    for t in tools:
        by_cat[t.category or "uncategorised"] = by_cat.get(t.category or "uncategorised", 0) + 1
        by_risk[t.risk_level] = by_risk.get(t.risk_level, 0) + 1
        if tool_requires_confirmation(t):
            confirmation_count += 1
        if t.enabled and t.available:
            available_count += 1
    return {
        "total": len(tools),
        "available": available_count,
        "by_category": by_cat,
        "by_risk": by_risk,
        "requires_confirmation": confirmation_count,
    }


def set_tool_enabled(name: str, enabled: bool) -> None:
    """Enable or disable a registered tool without changing availability."""
    if name in _registry:
        _registry[name].enabled = bool(enabled)


#: Handler statuses that mean "the action did NOT happen".
#:
#: A preview is not a result: ``git_push`` and ``db_execute`` answer a call
#: that was not confirmed with ``{"status": "preview", "message": "Push not
#: executed. Pass confirm=True ..."}``. Scoring that as a success closed the
#: runtime's verification gate with a call that did nothing, so the agent
#: could claim the push or the write happened. These statuses are failures.
_NOT_EXECUTED_STATUSES: frozenset[str] = frozenset(
    {"preview", "not_executed", "pending_review", "dry_run"}
)


def _handler_result_failed(result: Any) -> str | None:
    """Return an error when a handler did not produce a successful result.

    ``status == "error"`` is a failure signal in its own right: the fetch tools
    (``web_fetcher``, ``web_search_v2``) return the error text in ``summary``
    and leave every other key absent, so without this check a failed fetch was
    scored as a success — logged ``success=True``, counted as one by the circuit
    breaker, and handed to the model as ``ok: true``.

    A handler that says the action was not executed (``status`` in
    :data:`_NOT_EXECUTED_STATUSES`) is a failure for the same reason: the
    evidence gate must not be closed by a call that did nothing.

    The handler's own explanation (``reason``/``message``/``error``) is kept:
    replacing it with a generic "Tool reported failure" threw away the only
    actionable text the handler produced.
    """
    if not isinstance(result, dict):
        return None
    if result.get("error"):
        return str(result["error"])
    if result.get("timed_out"):
        return str(result.get("error") or "Tool process timed out")
    if result.get("exit_code") not in (None, 0):
        return str(result.get("stderr") or f"Command exited with code {result['exit_code']}")
    if result.get("ok") is False or result.get("success") is False:
        return str(
            result.get("reason")
            or result.get("error")
            or result.get("message")
            or "Tool reported failure"
        )
    if result.get("written") is False:
        return str(result.get("error") or "Write operation failed")
    if result.get("deleted") is False:
        return str(result.get("error") or "Delete operation failed")
    if result.get("moved") is False:
        return str(result.get("error") or "Move operation failed")
    status = str(result.get("status") or "").strip().lower()
    if status == "error":
        return str(
            result.get("summary") or result.get("message") or "Tool reported status=error"
        )
    if status in _NOT_EXECUTED_STATUSES:
        return str(
            result.get("reason")
            or result.get("message")
            or result.get("summary")
            or f"Tool reported status={status} (the action was not executed)"
        )
    return None


def _drop_unsupported_args(spec: ToolSpec, args: dict) -> tuple[dict, dict]:
    """Split args into handler-supported and ignored arguments."""
    handler = getattr(spec, "handler", None)
    if handler is None or not isinstance(args, dict):
        return args, {}
    try:
        params = inspect.signature(handler).parameters
    except (TypeError, ValueError):
        return args, {}
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return args, {}
    accepted = {key: value for key, value in args.items() if key in params}
    dropped = {key: value for key, value in args.items() if key not in params}
    if not dropped:
        return accepted, {}
    return accepted, {
        "dropped": sorted(dropped),
        "valid_arguments": sorted(params),
        "note": "Unsupported arguments were ignored.",
    }


def validate_tool_args(spec: ToolSpec, args: dict[str, Any]) -> list[str]:
    """Validate tool arguments against the supported JSON-schema subset."""
    schema = spec.schema or {}
    if not isinstance(args, dict):
        return ["arguments must be an object"]
    errors: list[str] = []
    # p34: free models often send scalars as strings ("timeout": "30"). Coerce
    # unambiguous top-level numeric/boolean strings in place before validating
    # (BUG_HUNTER_RUNTIME run_shell failed on this, 2026-10-29).
    for _name, _rule in (schema.get("properties") or {}).items():
        _val = args.get(_name)
        if not isinstance(_val, str) or not isinstance(_rule, dict):
            continue
        _t = _rule.get("type")
        _types = _t if isinstance(_t, list) else [_t]
        if "string" in _types:
            continue
        _s = _val.strip()
        try:
            if "integer" in _types and re.fullmatch(r"-?\d+", _s):
                args[_name] = int(_s)
            elif "number" in _types and re.fullmatch(r"-?\d+(?:\.\d+)?", _s):
                args[_name] = float(_s) if "." in _s else int(_s)
            elif "boolean" in _types and _s.lower() in ("true", "false"):
                args[_name] = _s.lower() == "true"
        except ValueError:
            pass

    def check(value: Any, rule: dict[str, Any], path: str) -> None:
        alternatives = rule.get("anyOf") or rule.get("oneOf")
        if alternatives:
            for alternative in alternatives:
                candidate: list[str] = []
                before = len(errors)
                check(value, alternative, path)
                candidate = errors[before:]
                del errors[before:]
                if not candidate:
                    break
            else:
                errors.append(f"{path} does not match any allowed schema")
            return
        expected = rule.get("type")
        expected_types = expected if isinstance(expected, list) else [expected]
        valid_type = not expected or any(
            (kind == "object" and isinstance(value, dict))
            or (kind == "array" and isinstance(value, list))
            or (kind == "string" and isinstance(value, str))
            or (kind == "integer" and isinstance(value, int) and not isinstance(value, bool))
            or (kind == "number" and isinstance(value, (int, float)) and not isinstance(value, bool))
            or (kind == "boolean" and isinstance(value, bool))
            or (kind == "null" and value is None)
            for kind in expected_types
        )
        if not valid_type:
            errors.append(f"{path} has invalid type")
            return
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            if "minimum" in rule and value < rule["minimum"]:
                errors.append(f"{path} is below minimum")
            if "maximum" in rule and value > rule["maximum"]:
                errors.append(f"{path} is above maximum")
        if isinstance(value, str):
            if "minLength" in rule and len(value) < int(rule["minLength"]):
                errors.append(f"{path} is shorter than minLength")
            if "maxLength" in rule and len(value) > int(rule["maxLength"]):
                errors.append(f"{path} is longer than maxLength")
        if isinstance(value, list):
            if "minItems" in rule and len(value) < int(rule["minItems"]):
                errors.append(f"{path} has fewer than minItems")
            if "maxItems" in rule and len(value) > int(rule["maxItems"]):
                errors.append(f"{path} has more than maxItems")
            if isinstance(rule.get("items"), dict):
                for index, item in enumerate(value):
                    check(item, rule["items"], f"{path}[{index}]")
        if isinstance(value, dict):
            properties = rule.get("properties", {})
            for required in rule.get("required", []):
                if required not in value:
                    errors.append(f"{path}.{required} is required")
            additional = rule.get("additionalProperties", True)
            for key, item in value.items():
                child = f"{path}.{key}"
                if key in properties and isinstance(properties[key], dict):
                    check(item, properties[key], child)
                elif additional is False:
                    errors.append(f"{child} is not allowed")
                elif isinstance(additional, dict):
                    check(item, additional, child)
        if "enum" in rule and value not in rule["enum"]:
            errors.append(f"{path} must be one of {rule['enum']!r}")

    check(args, schema, "arguments")
    return errors


def _validate_against_handler(spec: ToolSpec, args: dict[str, Any]) -> list[str]:
    """Validate the arguments against the handler's own signature.

    The JSON schema is the tool's *published* contract, but the handler
    signature is the ground truth for everything the schema does not say: a
    tool whose schema is missing (or wrong) must still reject a call that
    omits a required argument, otherwise the handler raises a ``TypeError``
    deep inside the call instead of the registry reporting ``invalid_args``.

    An argument the schema already describes is left to the schema: the
    schema is the contract the model was shown, so it wins.

    Unknown arguments are NOT reported here: the registry drops them (a key
    the handler cannot accept must not sink an otherwise valid call).
    """
    handler = getattr(spec, "handler", None)
    if handler is None or not isinstance(args, dict):
        return []
    try:
        params = inspect.signature(handler).parameters
    except (TypeError, ValueError):
        return []

    schema = spec.schema if isinstance(spec.schema, dict) else {}
    properties = schema.get("properties")
    described = set(properties) if isinstance(properties, dict) else set()

    hints = _resolved_type_hints(handler)

    errors: list[str] = []
    for name, param in params.items():
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        if name in described:
            # The schema already constrains this argument.
            continue
        if name not in args:
            if param.default is inspect.Parameter.empty:
                errors.append(f"arguments.{name} is required")
            continue
        expected = _annotation_type(hints.get(name, param.annotation))
        if expected is None:
            continue
        value = args[name]
        if value is None:
            # ``None`` is accepted for an optional argument.
            continue
        if not isinstance(value, expected):
            errors.append(
                f"arguments.{name} has invalid type (expected {expected.__name__})"
            )
    return errors


def _resolved_type_hints(handler: Callable[..., Any]) -> dict[str, Any]:
    """Return the handler's resolved type hints (empty when unresolvable).

    ``from __future__ import annotations`` turns every annotation into a
    string, so the raw signature cannot be used to check a type.
    """
    import typing

    try:
        return typing.get_type_hints(handler)
    except Exception:  # noqa: BLE001 - a broken hint must not break the call
        return {}


def _annotation_type(annotation: Any) -> type | None:
    """Return the concrete type an annotation demands, or ``None``.

    Only unambiguous annotations are checked: a union, a generic or a bare
    ``Any`` says nothing the registry can enforce.
    """
    if annotation is inspect.Parameter.empty or annotation is Any:
        return None
    if isinstance(annotation, type):
        return annotation
    if isinstance(annotation, str):
        # ``from __future__ import annotations`` turns the annotation into a
        # string; only the plain builtin names can be resolved without the
        # module namespace.
        resolved = _BUILTIN_ANNOTATIONS.get(annotation.strip())
        return resolved
    return None


#: The plain builtin annotations the registry can enforce from a string.
_BUILTIN_ANNOTATIONS: dict[str, type] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": bool,
    "list": list,
    "dict": dict,
    "bytes": bytes,
    "set": set,
    "tuple": tuple,
}


def _typed_tool_response(
    name: str,
    *,
    ok: bool,
    result: Any = None,
    error: str | None = None,
    error_category: str = "none",
    command: str | None = None,
    exit_code: int | None = None,
    duration_ms: int = 0,
    timed_out: bool = False,
    **extra: Any,
) -> dict[str, Any]:
    raw = result if isinstance(result, dict) else {}
    command = command or raw.get("command")
    if exit_code is None and raw.get("exit_code") is not None:
        try:
            exit_code = int(raw["exit_code"])
        except (TypeError, ValueError):
            exit_code = None
    timed_out = bool(timed_out or raw.get("timed_out", False))
    evidence = raw.get("evidence")
    if not isinstance(evidence, dict):
        evidence = {
            "kind": "tool_execution",
            "tool": name,
            "verified": bool(ok and not timed_out and (exit_code is None or exit_code == 0)),
            "command": command,
            "exit_code": exit_code,
            "duration_ms": duration_ms,
            "timed_out": timed_out,
        }
    payload: dict[str, Any] = {
        "tool": name,
        "ok": bool(ok),
        "result": result,
        "error_category": error_category,
        "command": command,
        "exit_code": exit_code,
        "duration_ms": int(duration_ms),
        "evidence": evidence,
        "timed_out": timed_out,
    }
    if error:
        payload["error"] = error
    payload.update(extra)
    return payload


def _sentinel_assessment(
    name: str,
    args: dict[str, Any],
    spec: ToolSpec,
    *,
    project_path: str,
) -> dict[str, Any]:
    """Apply the Infinity Sentinel risk taxonomy to one concrete tool call."""
    # Unknown tools must not inherit ToolSpec's low-risk default. Every tool
    # needs an explicit classification before Sentinel can auto-approve it.
    risk_by_label = {"low": 3, "medium": 2, "high": 3, "critical": 4}
    risk_level = risk_by_label.get(str(spec.risk_level or "low").lower(), 3)

    if name in {"write_file", "create_file", "append_file", "create_directory"}:
        target = args.get("path") or args.get("file_path") or args.get("filename")
        risk_level = (
            1
            if _path_is_within_project(
                target, project_path, relative_to_project=True
            )
            else 3
        )
    elif name == "write_file_absolute":
        target = args.get("path") or args.get("file_path")
        risk_level = 1 if _path_is_within_project(target, project_path) else 3
    elif name == "create_dir_absolute":
        risk_level = (
            1
            if _path_is_within_project(args.get("path"), project_path)
            else 3
        )
    elif name == "install_dependency":
        risk_level = 2
    elif name in {
        "delete_file", "delete_file_absolute", "delete_directory", "delete_dir_absolute",
        "move_file", "move_file_absolute", "copy_file", "copy_file_absolute",
    }:
        risk_level = 3
    elif name == "git_push":
        risk_level = 4
    elif name == "git_operation":
        command = str(args.get("command") or "").strip().lower()
        if command.startswith("git "):
            command = command[4:].lstrip()
        parts = command.split(maxsplit=1)
        operation = parts[0] if parts else ""
        operation_args = parts[1].split() if len(parts) > 1 else []
        read_only = operation in {
            "status", "diff", "log", "show", "blame", "rev-parse"
        }
        if operation == "branch":
            read_only = not operation_args or set(operation_args).issubset(
                {"--list", "-l", "-a", "--all", "-r", "--remotes", "--show-current"}
            )
        elif operation == "tag":
            read_only = not operation_args or set(operation_args).issubset(
                {"--list", "-l"}
            )
        risk_level = 0 if read_only else 4 if operation == "push" else 3
    elif name in {
        "git_commit_all", "git_commit_safe", "git_pull", "git_clone",
        "auto_commit_after_write", "approve_pending_commit", "reject_pending_commit",
    }:
        risk_level = 3
    elif name == "git_init":
        risk_level = 2
    elif name == "api_request":
        method = str(args.get("method") or "GET").strip().upper()
        risk_level = 2 if method in {"GET", "HEAD", "OPTIONS"} else 3
    elif name == "browser_navigate":
        risk_level = 2
    elif name in {"docker_run", "docker_compose_up"}:
        risk_level = 3
    elif name == "docker_compose_down":
        risk_level = 4 if args.get("volumes") else 3
    elif name in {"execute_shell", "run_shell"}:
        cwd = args.get("cwd")
        safe_cwd = bool(project_path) and (
            not cwd
            or _path_is_within_project(
                cwd, project_path, relative_to_project=True
            )
        )
        risk_level = (
            1
            if _is_safe_autonomous_command(args.get("command")) and safe_cwd
            else 3
        )
    elif name in {
        "execute_code",
        "execute_python",
        "execute_script",
        "run_python_script",
        "db_execute",
        "send_webhook",
        "send_email_notification",
    }:
        risk_level = 3
    elif name in {"generate_project", "scaffold_project"}:
        risk_level = 2
    elif name in _SENTINEL_ABSOLUTE_READ_PATH_KEYS:
        path_keys = _SENTINEL_ABSOLUTE_READ_PATH_KEYS[name]
        risk_level = (
            0 if _sentinel_paths_within_project(args, project_path, *path_keys) else 3
        )
    elif name == "restore_backup":
        risk_level = 3
    elif name == "data_analysis":
        risk_level = (
            3
            if args.get("code")
            or (
                args.get("data_path")
                and not _path_is_within_project(
                    args.get("data_path"), project_path, relative_to_project=True
                )
            )
            else 0
        )
    elif name == "browser_click":
        risk_level = 3
    elif name == "browser_fill":
        risk_level = 2
    elif name in {"schedule_task", "spawn_task", "publish_bus_message"}:
        risk_level = 3 if name != "publish_bus_message" else 2
    elif name in {
        "update_user_preferences", "remember_fact", "store_memory", "add_knowledge",
        "resume_session",
    }:
        risk_level = 2
    elif name == "todo_write":
        risk_level = 1
    elif name == "run_lint":
        risk_level = (
            1
            if args.get("fix") and project_path
            and _path_is_within_project(
                args.get("path") or ".", project_path, relative_to_project=True
            )
            else 3 if args.get("fix") else 0
        )
    elif name == "format_code":
        risk_level = (
            0
            if args.get("check")
            else 1
            if project_path
            and _path_is_within_project(
                args.get("path") or ".", project_path, relative_to_project=True
            )
            else 3
        )
    elif name == "generate_tests":
        risk_level = (
            1
            if project_path
            and _path_is_within_project(
                args.get("file_path"), project_path, relative_to_project=True
            )
            else 3
        )
    elif name == "generate_module_doc":
        source_in_project = _path_is_within_project(
            args.get("file_path"), project_path, relative_to_project=True
        )
        output_path = args.get("output_path")
        if output_path:
            risk_level = (
                1
                if source_in_project
                and _path_is_within_project(
                    output_path, project_path, relative_to_project=True
                )
                else 3
            )
        else:
            risk_level = 0 if source_in_project else 3
    elif name == "report_generation":
        output_path = args.get("output_path")
        risk_level = (
            1
            if output_path
            and project_path
            and _path_is_within_project(
                output_path, project_path, relative_to_project=True
            )
            else 3
            if output_path
            else 0
        )
    elif name == "cancel_task":
        risk_level = 2
    elif name == "run_tests":
        test_path = args.get("test_path") or "."
        risk_level = (
            1
            if project_path
            and _path_is_within_project(
                test_path, project_path, relative_to_project=True
            )
            else 3
        )
    elif name == "type_check":
        risk_level = (
            2
            if project_path
            and _path_is_within_project(
                args.get("path") or ".", project_path, relative_to_project=True
            )
            else 3
        )
    elif name in {"index_codebase", "index_symbols"}:
        index_path = args.get("project_path") or project_path
        risk_level = (
            1
            if project_path
            and _path_is_within_project(
                index_path, project_path, relative_to_project=True
            )
            else 3
        )
    elif name in {"check_inbox", "search_emails", "summarize_inbox", "speak"}:
        risk_level = 2
    elif name in {
        "show_desktop_notification",
        "subscribe_bus_topic",
        "browser_screenshot",
        "browser_close",
        "trim_context",
    }:
        risk_level = 1
    elif name in _SENTINEL_PROJECT_READ_PATH_KEYS:
        path_keys = _SENTINEL_PROJECT_READ_PATH_KEYS[name]
        risk_level = (
            0
            if _sentinel_paths_within_project(args, project_path, *path_keys)
            else 3
        )
    elif name in _SENTINEL_EXTERNAL_READ_TOOLS:
        risk_level = 2
    elif name in {"db_query", "db_execute"}:
        risk_level = 2 if name == "db_query" else 3
    elif name in {"mcp_call_tool", "mcp_builder", "build_skill"}:
        risk_level = 3
    elif name in {
        "pause_session",
        "resume_session",
        "cancel_run",
        "analyze_image",
        "analyze_screenshot",
        "compare_images",
    }:
        risk_level = 2
    elif name in _SENTINEL_LOCAL_READ_ONLY_TOOLS:
        risk_level = 0

    if spec.requires_confirmation:
        risk_level = max(risk_level, 2)

    files_affected: list[str] = []
    for key in ("path", "file_path", "filename", "src", "destination", "target"):
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            files_affected.append(value.strip())
    for key in ("files", "paths"):
        values = args.get(key)
        if isinstance(values, (list, tuple)):
            files_affected.extend(
                value.strip()
                for value in values
                if isinstance(value, str) and value.strip()
            )

    if name in _SENTINEL_PROJECT_READ_PATH_KEYS or name in _SENTINEL_ABSOLUTE_READ_PATH_KEYS:
        # A read does not affect the target file. Treating read paths as
        # affected files made any path containing a word such as "live" look
        # like a production write and strand the agent behind an approval
        # prompt, even when the file was inside the selected project.
        files_affected = []

    from backend.orchestrator.advanced_modes import get_orchestrator

    return get_orchestrator().check_security_gate(
        action_description=f"{name} {args!r}",
        risk_level=risk_level,
        files_affected=files_affected,
    )


# --- Run budget accounting (Fase 1c) ---------------------------------------
# Every tool call an agent makes inside a run is charged to that run, and a run
# that has exhausted a hard limit is stopped *here*, at the single place every
# tool call passes through, instead of being discovered after it has spent more.
#
# The channel is a context variable (``backend.runtime.run_context``) rather
# than a new ``execute_tool`` parameter: the run id is ambient context owned by
# whoever opened the run, and adding a parameter would touch every caller (the
# agents, the MCP server, the e2e scenarios) for a value most of them do not
# have. With no run in context the guard is a no-op, so no existing caller
# changes behaviour.
#
# There is deliberately no read-only exemption. A budget is the operator's
# statement of how much work a run may do, and a run that may spend nothing is
# a run that has to stop: letting "free" reads through keeps an over-budget
# run looping (and keep spending tokens and wall-clock) on evidence it is no
# longer allowed to act on. The block is observable — the response names the
# exceeded limits and the accumulated usage — so the agent reports the stop
# instead of retrying into it.

#: Kill switch for the accounting hook (``0``/``false`` disables it). Present
#: because a mis-configured budget must be able to stop blocking a run by an
#: environment change during an incident, rather than by a code rollback.
TOOL_BUDGET_HOOK_ENV = "NEXUS_TOOL_BUDGET_HOOK"

_budget_coordinator: Any | None = None
_budget_coordinator_path: str | None = None


def _tool_budget_hook_enabled() -> bool:
    return os.environ.get(TOOL_BUDGET_HOOK_ENV, "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _run_budget_coordinator() -> Any | None:
    """Return a cached :class:`RunCoordinator`, rebuilt when the database moves.

    ``RunCoordinator()`` resolves the database path at call time and re-runs
    the (idempotent) schema check, so caching one instance per path keeps the
    per-call cost at a single ``UPDATE`` while a test that repoints
    ``DB_PATH`` still gets a coordinator pointed at the right file.
    """
    global _budget_coordinator, _budget_coordinator_path
    from backend.persistence import db

    path = str(db.DB_PATH)
    if _budget_coordinator is None or _budget_coordinator_path != path:
        from backend.runtime.run_coordinator import RunCoordinator

        try:
            _budget_coordinator = RunCoordinator()
        except Exception:
            logger.debug("[TOOL BUDGET] run coordinator unavailable", exc_info=True)
            return None
        _budget_coordinator_path = path
    return _budget_coordinator


def record_run_tool_call(name: str) -> dict[str, Any] | None:
    """Charge one tool call to the active run and report an exhausted budget.

    Returns ``None`` when the call may proceed: no active run in context, the
    hook is disabled, no coordinator is reachable, the run does not exist, or
    the run is still inside its limits. Returns a dict carrying ``error``,
    ``exceeded``, ``usage`` and ``run_id`` when a hard limit was exceeded and
    the tool must not run.

    Accounting must never break a tool call: a storage failure is logged and
    the call proceeds. The only thing that stops a tool is a *verdict*, because
    that is the operator's explicit limit rather than an infrastructure error.
    """
    from backend.runtime.run_context import get_current_run_id

    run_id = get_current_run_id()
    if not run_id or not _tool_budget_hook_enabled():
        return None
    coordinator = _run_budget_coordinator()
    if coordinator is None:
        return None
    try:
        verdict = coordinator.record_usage(run_id, tool_calls=1)
    except Exception as exc:
        logger.warning("[TOOL BUDGET] could not charge %s to run %s: %s", name, run_id, exc)
        return None
    if verdict.ok:
        return None
    logger.warning(
        "[TOOL BUDGET] %s blocked for run %s: budget exceeded %s (usage=%s)",
        name,
        run_id,
        verdict.exceeded,
        verdict.usage,
    )
    return {
        "run_id": run_id,
        "exceeded": dict(verdict.exceeded),
        "usage": dict(verdict.usage),
        "error": f"budget exceeded: {dict(verdict.exceeded)}",
    }


# --- Side-effect idempotency (Fase 1c) --------------------------------------
# The budget hook above answers "may this run still spend a call?". The ledger
# below answers a different question: "was this exact action already applied by
# this run?". It is lane-agnostic by construction — primary, engine and swarm
# all funnel through ``execute_tool`` — so a retried or resumed run cannot write
# the same file or re-run the same command a second time through a lane the
# primary tracker never sees.


def _side_effect_task_id() -> str:
    """The task the active run is executing, or ``""`` when none is published.

    ``backend/runtime/run_context.py`` publishes only the run id today, so the
    key is run-wide instead of per-task. The lookup is dynamic on purpose: the
    day the context starts publishing ``get_current_task_id``, the key tightens
    by itself with no change here.
    """
    from backend.runtime import run_context

    getter = getattr(run_context, "get_current_task_id", None)
    if not callable(getter):
        return ""
    try:
        return str(getter() or "").strip()
    except Exception:
        logger.debug("[SIDE EFFECT] could not read the current task id", exc_info=True)
        return ""


def _side_effect_key(name: str, run_id: str, args: Any) -> str:
    """Identity of one side effect, or ``""`` when it cannot be derived."""
    from backend.runtime.primary import side_effect_idempotency_key

    return side_effect_idempotency_key(run_id, _side_effect_task_id(), name, args)


def side_effect_replay(name: str, args: Any) -> dict[str, Any] | None:
    """Replay guard for side-effecting tools; ``None`` means "execute it".

    Returns the tool's response when this exact action was already confirmed
    for the active run, so the handler is not called a second time.

    Every coordinator failure is fail-open **for the ledger only**: a tool whose
    ledger cannot be read still runs, because refusing to work is worse than a
    possible duplicate. Nothing here can weaken the budget block above, which
    returns before this point.
    """
    from backend.runtime.primary import is_side_effecting_tool
    from backend.runtime.run_context import get_current_run_id

    run_id = get_current_run_id()
    if not run_id or not is_side_effecting_tool(name):
        return None
    try:
        key = _side_effect_key(name, run_id, args)
    except Exception:
        logger.debug("[SIDE EFFECT] could not derive the key for %s", name, exc_info=True)
        return None
    coordinator = _run_budget_coordinator()
    if coordinator is None:
        return None
    try:
        already = bool(coordinator.is_side_effect_confirmed(run_id, key))
    except Exception as exc:
        logger.warning(
            "[SIDE EFFECT] could not check the ledger for %s in run %s: %s",
            name,
            run_id,
            exc,
        )
        return None
    if not already:
        return None
    logger.info(
        "[SIDE EFFECT] %s already confirmed in run %s (%s); execution skipped",
        name,
        run_id,
        key,
    )
    return _typed_tool_response(
        name,
        ok=True,
        result={
            "idempotent_replay": True,
            "idempotency_key": key,
            "message": "side effect already confirmed in this run; execution skipped",
        },
        idempotent_replay=True,
        idempotency_key=key,
        message="side effect already confirmed in this run; execution skipped",
    )


def record_side_effect(name: str, args: Any, result: Any) -> None:
    """Record a completed side effect so a replay is recognised as done.

    Called only after the handler reported success. The outcome is digested —
    never stored — so the ledger row says *that* the action happened without
    turning the database into a second copy of the tool's output.
    """
    from backend.runtime.primary import (
        is_side_effecting_tool,
        side_effect_result_digest,
    )
    from backend.runtime.run_context import get_current_run_id

    run_id = get_current_run_id()
    if not run_id or not is_side_effecting_tool(name):
        return
    try:
        key = _side_effect_key(name, run_id, args)
        payload = result.get("result") if isinstance(result, dict) else None
        digest = side_effect_result_digest(payload if payload is not None else result)
    except Exception:
        logger.debug("[SIDE EFFECT] could not digest the result of %s", name, exc_info=True)
        return
    coordinator = _run_budget_coordinator()
    if coordinator is None:
        return
    try:
        coordinator.record_side_effect(run_id, key, kind=name, result_digest=digest)
    except Exception as exc:
        logger.warning(
            "[SIDE EFFECT] could not record %s for run %s: %s", key, run_id, exc
        )


# ---------------------------------------------------------------------------
# Handler invocation
# ---------------------------------------------------------------------------
# The registry accepts handlers of two shapes: a coroutine function and a
# plain function. Both used to be awaited (``await spec.handler(...)``), which
# raised ``TypeError: object dict can't be used in 'await' expression`` for
# every synchronous handler — seven tools could therefore never succeed.
#
# A synchronous handler is run in a worker thread. Calling it directly on the
# event loop blocked the loop for the handler's whole duration, so
# ``asyncio.wait_for`` could never interrupt it: a handler that slept 60 s
# blew through a 2 s timeout every time.


def _is_async_handler(handler: Any) -> bool:
    """Whether *handler* is a coroutine function (or a callable returning one)."""
    if inspect.iscoroutinefunction(handler):
        return True
    call = getattr(handler, "__call__", None)  # noqa: B004 - bound __call__ probe
    return call is not None and inspect.iscoroutinefunction(call)


def _call_handler_sync(handler: Callable[..., Any], handler_args: dict[str, Any]) -> Any:
    """Call a synchronous handler (used as the worker-thread body)."""
    return handler(**handler_args)


async def _invoke_handler(
    handler: Callable[..., Any],
    handler_args: dict[str, Any],
    timeout_seconds: float,
) -> Any:
    """Run *handler* under a hard timeout and return its result.

    * A coroutine handler is awaited directly.
    * A synchronous handler runs in a worker thread, so the timeout can
      actually interrupt the wait: the caller is released and the tool is
      reported as timed out instead of blocking the whole agent loop.
    * A handler that returns something that is not awaitable is taken at face
      value — that value IS the result.
    """
    if _is_async_handler(handler):
        outcome = handler(**handler_args)
        if not inspect.isawaitable(outcome):
            # Not a coroutine function after all: the plain value is the result.
            return outcome
        return await asyncio.wait_for(outcome, timeout=timeout_seconds)

    result = await asyncio.wait_for(
        asyncio.to_thread(_call_handler_sync, handler, handler_args),
        timeout=timeout_seconds,
    )
    if inspect.isawaitable(result):
        # A synchronous handler that returned an awaitable: await it here so
        # the caller receives a real result instead of a coroutine object.
        result = await result
    return result


# ---------------------------------------------------------------------------
# Trusted session id
# ---------------------------------------------------------------------------
# The trusted session id is the caller's session, never the model's argument.
# It is injected into the tools that scope their state by session, and it is
# published in a context variable so a handler that does not take the
# ``session_id`` keyword can still read it.
_SESSION_ID_REQUIRED_TOOLS: frozenset[str] = frozenset(
    {"todo_write", "todo_list", "list_skills", "load_skill"}
)

#: Tools whose schema declares ``session_id`` and whose contract says the
#: session is injected by NEXUS (so the model must not choose it), but whose
#: handler cannot take the parameter directly. The registry replaces the
#: model-supplied value with the trusted one and delivers it through the
#: session-aware adapter installed at registration time.
_SESSION_ID_OVERRIDDEN_TOOLS: frozenset[str] = frozenset({"build_skill", "consult_agent"})

_current_tool_session: ContextVar[str] = ContextVar("nexus_tool_session_id", default="")


def current_tool_session_id() -> str:
    """The trusted session id of the tool call in flight ("" outside a call)."""
    return _current_tool_session.get()


def _schema_declares_session_id(spec: ToolSpec) -> bool:
    """Whether the tool's schema declares a ``session_id`` property."""
    schema = spec.schema if isinstance(spec.schema, dict) else {}
    properties = schema.get("properties")
    return isinstance(properties, dict) and "session_id" in properties


def _handler_accepts_session_id(handler: Any) -> bool:
    """Whether *handler* takes a ``session_id`` keyword argument."""
    if handler is None:
        return False
    try:
        params = inspect.signature(handler).parameters
    except (TypeError, ValueError):
        return False
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return True
    return "session_id" in params


def _inner_handler_parameters(handler: Any) -> tuple[set[str], bool]:
    """Return (accepted parameter names, accepts-any-keyword) for *handler*."""
    try:
        params = inspect.signature(handler).parameters
    except (TypeError, ValueError):
        return set(), True
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return set(), True
    return {name for name in params}, False


def _session_aware_handler(
    spec: ToolSpec,
    handler: Callable[..., Any],
) -> Callable[..., Any]:
    """Wrap *handler* so it can receive a trusted ``session_id``.

    A tool whose schema declares ``session_id`` promises the caller that the
    session is injected. When the handler has no such parameter the promise
    cannot be kept by calling it directly, so the registry would have to drop
    the value (and, before that, reject the whole call). The wrapper accepts
    the keyword, publishes it in :func:`current_tool_session_id` for the
    duration of the call and forwards it to the inner handler when the inner
    handler can take it.

    The inner handler is resolved from ``spec`` at CALL time, so replacing it
    (a test double, or a future implementation that really takes the
    parameter) is picked up without re-registering the tool.
    """
    import functools

    def _inner() -> Callable[..., Any]:
        return getattr(spec, "inner_handler", None) or handler

    def _clean(kwargs: dict[str, Any], inner: Callable[..., Any]) -> dict[str, Any]:
        accepted, accepts_any = _inner_handler_parameters(inner)
        if accepts_any:
            return dict(kwargs)
        return {key: value for key, value in kwargs.items() if key in accepted}

    def _forward(
        kwargs: dict[str, Any], inner: Callable[..., Any], session_id: str
    ) -> dict[str, Any]:
        """Build the keyword arguments the inner handler actually accepts."""
        accepted, accepts_any = _inner_handler_parameters(inner)
        forwarded = _clean(kwargs, inner)
        if accepts_any or "session_id" in accepted:
            forwarded["session_id"] = session_id
        return forwarded

    if _is_async_handler(handler):

        @functools.wraps(handler)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            inner = _inner()
            session_id = str(kwargs.pop("session_id", "") or "")
            token = _current_tool_session.set(session_id)
            try:
                return await inner(*args, **_forward(kwargs, inner, session_id))
            finally:
                _current_tool_session.reset(token)

        # ``functools.wraps`` copies ``__wrapped__``, which makes
        # ``inspect.signature`` report the INNER signature. The wrapper must
        # advertise the keyword it actually accepts.
        _set_wrapper_signature(async_wrapper, handler, accepts_session_id=True)
        return async_wrapper

    @functools.wraps(handler)
    def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        inner = _inner()
        session_id = str(kwargs.pop("session_id", "") or "")
        token = _current_tool_session.set(session_id)
        try:
            return inner(*args, **_forward(kwargs, inner, session_id))
        finally:
            _current_tool_session.reset(token)

    _set_wrapper_signature(sync_wrapper, handler, accepts_session_id=True)
    return sync_wrapper


def _set_wrapper_signature(
    wrapper: Callable[..., Any],
    inner: Callable[..., Any],
    *,
    accepts_session_id: bool,
) -> None:
    """Give *wrapper* the signature it really has (including ``session_id``)."""
    try:
        inner_signature = inspect.signature(inner)
    except (TypeError, ValueError):
        return
    parameters = list(inner_signature.parameters.values())
    if accepts_session_id and "session_id" not in inner_signature.parameters:
        parameters.append(
            inspect.Parameter(
                "session_id",
                inspect.Parameter.KEYWORD_ONLY,
                default="",
                annotation=str,
            )
        )
    import contextlib

    with contextlib.suppress(TypeError, ValueError):  # pragma: no cover - defensive
        wrapper.__signature__ = inner_signature.replace(  # type: ignore[attr-defined]
            parameters=parameters
        )


def _cache_scope_kwargs(cache: Any, method_name: str, **scope: Any) -> dict[str, Any]:
    """Return the scoping keyword arguments *cache* actually accepts.

    The result cache is best-effort: a stand-in (a test double, or a cache
    implementation that predates the scoping parameters) must keep working, so
    the registry asks the cache before it passes the scope.
    """
    method = getattr(cache, method_name, None)
    if method is None:
        return {}
    try:
        params = inspect.signature(method).parameters
    except (TypeError, ValueError):
        return {}
    if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return dict(scope)
    if "session_id" in params and "project_root" in params:
        return dict(scope)
    return {}


async def execute_tool(
    name: str,
    session_id: str | None,
    args: dict,
    *,
    confirmed: bool = False,
    enforce_confirmation: bool = False,
    retry_confirmation: bool = False,
    confirmation_user_id: str = "",
    user_id: str = "",
    autonomous: bool = False,
    project_path: str = "",
    sentinel_enforced: bool = False,
    allowed_tools: Iterable[str] | None = None,
    failure_scope: str | None = None,
) -> dict:
    trusted_allowed_tools = (
        frozenset(str(tool).strip() for tool in allowed_tools if str(tool).strip())
        if allowed_tools is not None
        else None
    )
    # The allowlist is the caller's boundary, enforced here.
    #
    # When the sentinel is enforced it plays a different role: it is the
    # boundary FORWARDED to the delegate (the sentinel's trusted server
    # context), and the sentinel's own risk assessment is the authority for
    # the current call. Blocking the call here made the sentinel's own
    # delegation path unreachable — the delegate could never be invoked with
    # the very boundary it is meant to inherit.
    if (
        trusted_allowed_tools is not None
        and name not in trusted_allowed_tools
    ):
        return _typed_tool_response(
            name,
            ok=False,
            error=f"Tool '{name}' is not permitted by the caller's allowlist.",
            error_category="tool_not_allowed",
        )

    spec = get_tool(name)
    if not spec:
        return _typed_tool_response(
            name, ok=False, error=f"Tool '{name}' not found", error_category="unknown_tool"
        )
    args = dict(args) if isinstance(args, dict) else {}
    trusted_user_id = str(user_id or confirmation_user_id or "").strip()
    if name == "mcp_builder":
        if not trusted_user_id:
            return _typed_tool_response(
                name,
                ok=False,
                error=(
                    "A trusted authenticated user context is required to create shared MCP "
                    "connectors."
                ),
                error_category="auth_context_missing",
            )
        try:
            from backend.middleware.auth import get_auth_service

            is_admin = get_auth_service().is_admin(trusted_user_id)
        except Exception:
            is_admin = False
        if not is_admin:
            return _typed_tool_response(
                name,
                ok=False,
                error=(
                    "Creating shared MCP connectors requires administrator privileges."
                ),
                error_category="forbidden",
            )
    user_scoped_tool = (
        name in {"recall_context", "store_memory", "consult_agent", "spawn_task"}
        or name.startswith("browser_")
    )
    if user_scoped_tool:
        # Never accept a tenant identity from provider-produced arguments. Drop
        # it before the public JSON schema is checked, then inject the trusted
        # principal after schema filtering below.
        args = dict(args) if isinstance(args, dict) else {}
        args.pop("user_id", None)
        if not trusted_user_id:
            return _typed_tool_response(
                name,
                ok=False,
                error="A trusted authenticated user context is required for this tool.",
                error_category="auth_context_missing",
            )
    if name in {"store_memory", "consult_agent", "spawn_task"} and isinstance(args, dict):
        # Project continuity writes and delegated agents may only target the
        # project root selected by the authenticated chat request. A
        # model-provided project_path must never choose a host path.
        args = {**args, "project_path": project_path or ""}
    if name.startswith("browser_") and isinstance(args, dict):
        # Browser contexts are session-scoped; a model-supplied session id
        # must not select another caller's context.
        #
        # The trusted id is only injected when the tool's own schema accepts
        # it. A schema that forbids additional properties and does not declare
        # `session_id` would otherwise reject the very call the injection is
        # meant to protect.
        schema = spec.schema if isinstance(spec.schema, dict) else {}
        properties = schema.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        allows_extra = schema.get("additionalProperties") is not False
        if "session_id" in properties or allows_extra:
            args = {**args, "session_id": str(session_id or "")}

    if not spec.available:
        reason = spec.unavailable_reason or spec.missing_dependency or "unavailable"
        return _typed_tool_response(
            name, ok=False, error=f"Tool '{name}' is unavailable: {reason}",
            error_category="unavailable",
        )
    if not spec.enabled:
        return _typed_tool_response(
            name, ok=False, error=f"Tool '{name}' is disabled", error_category="disabled"
        )
    if not spec.handler:
        return _typed_tool_response(
            name, ok=False, error=f"Tool '{name}' has no handler", error_category="tool"
        )
    scope_error = _apply_trusted_project_scope(name, spec, args, project_path)
    if scope_error:
        return _typed_tool_response(
            name,
            ok=False,
            error=scope_error,
            error_category="project_scope_denied",
        )
    if name in {
        "todo_write",
        "todo_list",
        "list_skills",
        "load_skill",
        "recall_context",
        "store_memory",
        "consult_agent",
        "spawn_task",
    } and isinstance(args, dict):
        # Defense in depth: execute_tool's session_id comes from the caller's
        # trusted request context; the model-controlled argument is never a
        # storage selector. Fail closed when that context is missing.
        trusted_session_id = str(session_id or "").strip()
        if not trusted_session_id:
            return _typed_tool_response(
                name,
                ok=False,
                error="A trusted session context is required for this tool.",
                error_category="invalid_session",
            )
        args = {**args, "session_id": trusted_session_id}
    elif name in _SESSION_ID_OVERRIDDEN_TOOLS and isinstance(args, dict):
        # ``build_skill`` declares ``session_id`` in its schema ("Trusted
        # session is injected by NEXUS; omit this field") but its handler had
        # no such parameter, so the registry dropped the value and the tool
        # never saw the session its own contract advertises. The trusted id
        # replaces the model-supplied one; the model must not be able to
        # select another session.
        trusted_session_id = str(session_id or "").strip()
        args = {**args, "session_id": trusted_session_id}

    # Validate against the schema the tool PUBLISHED, before the unknown
    # arguments are dropped. A schema that says ``additionalProperties: False``
    # is making an explicit statement about extra keys and must keep it; a
    # schema that leaves it unset (138 of the 148, which means "extra keys
    # allowed") must not reject a call over one.
    arg_errors = validate_tool_args(spec, args)

    # Drop the arguments the handler cannot accept. A key the handler cannot
    # accept must not sink an otherwise valid call: the model was told the
    # extra keys are allowed, and the handler simply ignores the ones it does
    # not know. A missing REQUIRED property or a wrong type is still a hard
    # failure (checked above and below).
    args, dropped_args = _drop_unsupported_args(spec, args)
    dropped_names = list(dropped_args.get("dropped", []))
    if dropped_names:
        logger.info(
            "[TOOL ARGS] %s: dropped unsupported argument(s): %s",
            name,
            ", ".join(dropped_names),
        )

    if user_scoped_tool:
        args["user_id"] = trusted_user_id

    # The handler's own signature is the ground truth for what it requires.
    arg_errors.extend(_validate_against_handler(spec, args))
    if arg_errors:
        return _typed_tool_response(
            name,
            ok=False,
            error="Malformed tool arguments: " + "; ".join(arg_errors),
            error_category="invalid_args",
        )

    # Circuit breaker: a tool that failed N times in a row in this session is
    # short-circuited so the agent stops burning iterations retrying it.
    failures = tool_failure_count(name, session_id, failure_scope)
    if failures >= TOOL_MAX_CONSECUTIVE_FAILURES:
        logger.warning(
            "[TOOL CIRCUIT] %s short-circuited after %d consecutive failures (session=%s)",
            name,
            failures,
            session_id,
        )
        return _typed_tool_response(
            name,
            ok=False,
            error=(
                f"Tool '{name}' failed {failures} times in a row and is temporarily "
                "disabled for this session. Do NOT call it again — use a different "
                "tool or answer with the information you already have."
            ),
            error_category="tool",
            circuit_open=True,
        )

    sentinel_gate: dict[str, Any] | None = None
    if sentinel_enforced:
        try:
            sentinel_gate = _sentinel_assessment(
                name, args, spec, project_path=project_path
            )
        except Exception:
            logger.exception("Sentinel could not assess tool call %s", name)
            return _typed_tool_response(
                name,
                ok=False,
                error="Sentinel could not verify this action; no tool was executed.",
                error_category="sentinel_unavailable",
            )
    sentinel_requires_approval = bool(
        sentinel_gate and sentinel_gate.get("requires_approval")
    )

    # Confirmation gate BEFORE cache: a cached hit must never bypass the
    # user's explicit approval for confirmation-listed tools (e.g. fetch_url).
    needs_confirmation = (
        autonomous_confirmation_required(spec, args, project_path=project_path)
        if autonomous
        else tool_requires_confirmation(spec)
    )
    needs_confirmation = needs_confirmation or sentinel_requires_approval
    # ``args`` came from the model and is never proof of user approval. Only
    # the trusted ``confirmed`` flag set by the approval flow may open this
    # gate; accepting ``{"confirm": true}`` here lets a model approve itself.
    if (
        (enforce_confirmation and needs_confirmation) or sentinel_requires_approval
    ) and not confirmed:
        from backend.tools.confirmations import create_confirmation

        confirmation_id = await create_confirmation(
            session_id=session_id or "default",
            tool_name=name,
            args=args,
            retry_enabled=retry_confirmation,
            user_id=confirmation_user_id,
        )
        response = _typed_tool_response(
            name,
            ok=False,
            error=f"Confirmation required before executing '{name}'.",
            error_category="confirmation_required",
            confirmation_required=True,
            confirmation_id=confirmation_id,
            tool_args=args,
            risk_level=(
                sentinel_gate.get("risk_level", spec.risk_level)
                if sentinel_gate
                else spec.risk_level
            ),
            suggestion="Review the arguments and approve the operation to continue.",
        )
        if sentinel_gate:
            response["sentinel_gate"] = sentinel_gate
        return response

    # A confirmed or unguarded call still cannot leave the selected project.
    # Sentinel may ask for approval first; approval of a foreign path is not
    # permission to open that folder.
    if isinstance(args, dict):
        confinement_error = _project_confinement_error(name, args, project_path)
        if confinement_error:
            return _typed_tool_response(
                name,
                ok=False,
                error=confinement_error,
                error_category="project_scope_denied",
            )

    # Run budget accounting, before the cache: a cache hit is still a tool call
    # the agent spent a turn on, and a run past its limits must be told to stop
    # rather than be served quietly.
    budget_block = record_run_tool_call(name)
    if budget_block is not None:
        return _typed_tool_response(
            name,
            ok=False,
            error=budget_block["error"],
            error_category="budget_exceeded",
            run_id=budget_block.get("run_id", ""),
            budget_exceeded=budget_block.get("exceeded", {}),
            budget_usage=budget_block.get("usage", {}),
        )

    # Side-effect idempotency, immediately before the handler runs and before
    # the cache: a cached hit would hide the replay, and the whole point is that
    # a second identical write inside one run is *reported* as a replay instead
    # of being served from a previous execution. Every lane reaches this line,
    # which is what makes the guarantee lane-agnostic.
    replay = side_effect_replay(name, args)
    if replay is not None:
        return replay

    # Check cache for idempotent tools (only after confirmation is satisfied).
    # The cache is scoped by session (and by project root for the path
    # tools): the result of a read depends on who asked and on which project
    # was selected, so two sessions must never share an entry.
    if _HAVE_TOOL_CACHE:
        try:
            cache = get_tool_cache()
            scope = {
                "session_id": str(session_id or ""),
                "project_root": str(project_path or ""),
            }
            cached = cache.get(name, args, **_cache_scope_kwargs(cache, "get", **scope))
            if cached is not None:
                logger.debug("[TOOL CACHE] Hit for %s: %s", name, cached.get("_cached_preview", ""))
                return _typed_tool_response(
                    name,
                    ok=bool(cached.get("ok", True)) and not bool(cached.get("error")),
                    result=frame_external_result(name, cached.get("result")),
                    error=cached.get("error"),
                    error_category=cached.get("error_category", "none"),
                    duration_ms=int(cached.get("duration_ms", 0)),
                    _from_cache=True,
                    _cache_hit=True,
                )
        except Exception:
            pass  # Cache is best-effort

    timeout_seconds = (
        float(spec.timeout_seconds)
        if spec.timeout_seconds is not None
        else TOOL_TIMEOUT_SECONDS
    )
    handler_args = args
    if name in {"consult_agent", "spawn_task"}:
        # These values are trusted server context, not model-controlled tool
        # arguments. Delegated workers inherit the same boundaries as the caller.
        handler_args = {
            **args,
            "sentinel_enforced": sentinel_enforced,
            "allowed_tools": (
                tuple(sorted(trusted_allowed_tools))
                if trusted_allowed_tools is not None
                else None
            ),
        }
        handler_args["project_path"] = project_path or ""
    start = time.time()
    session_token = _current_tool_session.set(str(session_id or ""))
    try:
        # The handler may be synchronous or asynchronous; both are run under
        # the tool timeout (a synchronous handler in a worker thread, so the
        # timeout can interrupt it).
        result = await _invoke_handler(spec.handler, handler_args, timeout_seconds)
        duration_ms = int((time.time() - start) * 1000)
        raw_result = result if isinstance(result, dict) else {}
        # The failure verdict is read from the RAW handler payload. Framing
        # first would turn ``{"status": "error", "summary": "Error fetching
        # URL: ..."}`` into a quoted blob and the error text handed to the model
        # would carry wrapper fences — a broken, unquotable diagnostic.
        handler_error = _handler_result_failed(result)
        # Quote the external content, then build the response. The control
        # plane (``ok``, ``error``, ``exit_code``, ``evidence``) keeps the
        # handler's own values; only text the model reads as evidence is
        # framed, so the success/error schema is unchanged.
        framed_result = frame_external_result(name, result)
        if handler_error:
            failure_count = _record_tool_failure(name, session_id, failure_scope)
            response = _typed_tool_response(
                name,
                ok=False,
                result=framed_result,
                error=handler_error,
                error_category="timeout" if raw_result.get("timed_out") else "tool",
                duration_ms=duration_ms,
                timed_out=bool(raw_result.get("timed_out")),
                exit_code=raw_result.get("exit_code"),
                consecutive_failures=failure_count,
            )
            log_tool_execution(
                session_id=session_id,
                tool_name=name,
                args=args,
                result=response,
                success=False,
                error=handler_error,
                duration_ms=duration_ms,
            )
            return response
        _record_tool_success(name, session_id, failure_scope)
        response = _typed_tool_response(
            name, ok=True, result=framed_result, duration_ms=duration_ms
        )
        if dropped_names:
            # Transparency: the model gets told which of its arguments were
            # ignored, so it can correct the call instead of wondering.
            response["dropped_arguments"] = dropped_names
        if sentinel_gate:
            response["sentinel_gate"] = sentinel_gate
        log_tool_execution(
            session_id=session_id,
            tool_name=name,
            args=args,
            result=response,
            success=True,
            duration_ms=duration_ms,
        )
        # Record the confirmed side effect only now that the handler really
        # succeeded: a failed, timed-out or rejected call must not close the
        # ledger entry a replay would be measured against.
        record_side_effect(name, args, result)
        if _HAVE_TOOL_CACHE:
            try:
                cache = get_tool_cache()
                cache.invalidate_after_mutation(name)
                cache.store(
                    name,
                    args,
                    response,
                    **_cache_scope_kwargs(
                        cache,
                        "store",
                        session_id=str(session_id or ""),
                        project_root=str(project_path or ""),
                    ),
                )
            except Exception:
                pass
        return response
    except TimeoutError:
        duration_ms = int((time.time() - start) * 1000)
        failure_count = _record_tool_failure(name, session_id, failure_scope)
        error_msg = f"Tool '{name}' timed out after {timeout_seconds:.0f}s"
        logger.warning("[TOOL TIMEOUT] %s (session=%s)", error_msg, session_id)
        response = _typed_tool_response(
            name,
            ok=False,
            error=error_msg,
            error_category="timeout",
            duration_ms=duration_ms,
            timed_out=True,
            exit_code=124,
            consecutive_failures=failure_count,
        )
        log_tool_execution(
            session_id=session_id,
            tool_name=name,
            args=args,
            result=response,
            success=False,
            error=error_msg,
            duration_ms=duration_ms,
        )
        return response
    except Exception as exc:
        duration_ms = int((time.time() - start) * 1000)
        failure_count = _record_tool_failure(name, session_id, failure_scope)
        error_msg = str(exc)
        response = _typed_tool_response(
            name,
            ok=False,
            error=error_msg,
            error_category="tool",
            duration_ms=duration_ms,
            consecutive_failures=failure_count,
        )
        log_tool_execution(
            session_id=session_id,
            tool_name=name,
            args=args,
            result=response,
            success=False,
            error=error_msg,
            duration_ms=duration_ms,
        )
        return response
    finally:
        # The trusted session id is published for the duration of the call
        # only: a handler that does not take ``session_id`` as a keyword can
        # still read it, and no later call inherits it.
        _current_tool_session.reset(session_token)
