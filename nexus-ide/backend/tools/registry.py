"""Tool registry - canonical list of executable tools available to agents."""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from backend.persistence.db import log_tool_execution

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


def _failure_key(name: str, session_id: str | None) -> tuple[str, str]:
    return (session_id or "default", name)


def _record_tool_success(name: str, session_id: str | None) -> None:
    _tool_failures.pop(_failure_key(name, session_id), None)


def _record_tool_failure(name: str, session_id: str | None) -> int:
    key = _failure_key(name, session_id)
    count = _tool_failures.get(key, 0) + 1
    _tool_failures[key] = count
    return count


def tool_failure_count(name: str, session_id: str | None) -> int:
    """Current consecutive-failure count for a tool in a session."""
    return _tool_failures.get(_failure_key(name, session_id), 0)


def reset_tool_failures(session_id: str | None = None) -> None:
    """Reset the failure circuit breaker (per session, or everything).

    MUST be called at the start of every plan task. The breaker is keyed by
    ``(session_id, tool)`` and a session spans the whole mission, so without a
    reset a failure streak in one task permanently disables the tool for every
    later task and every other agent.

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


def get_tools_for_agent(agent_name: str) -> list[ToolSpec]:
    """Return tools relevant to a given agent type.

    Mapping is loose: the agent name is matched against tool tags, the category,
    and the tool name. Returns the union of matches.
    """
    if not agent_name:
        return list_tools()
    agent = agent_name.upper()
    matched: set[str] = set()
    for tool in list_tools():
        # Check tags
        for tag in tool.tags:
            if tag.upper() in agent or agent in tag.upper():
                matched.add(tool.name)
        # Check category
        if tool.category and tool.category.upper() in agent:
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
    lines: list[str] = ["# Available Tools", ""]
    current_cat = None
    for tool in tools:
        if tool.category and tool.category != current_cat:
            current_cat = tool.category
            lines.append(f"## {current_cat.title()}")
            lines.append("")
        risk = f" [RISK: {tool.risk_level}]" if include_risk and tool.risk_level != "low" else ""
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
    """Return summary statistics about the registered tools."""
    tools = list_tools()
    by_cat: dict[str, int] = {}
    by_risk: dict[str, int] = {"low": 0, "medium": 0, "high": 0}
    confirmation_count = 0
    for t in tools:
        by_cat[t.category or "uncategorised"] = by_cat.get(t.category or "uncategorised", 0) + 1
        by_risk[t.risk_level] = by_risk.get(t.risk_level, 0) + 1
        if tool_requires_confirmation(t):
            confirmation_count += 1
    return {
        "total": len(tools),
        "by_category": by_cat,
        "by_risk": by_risk,
        "requires_confirmation": confirmation_count,
    }


def set_tool_enabled(name: str, enabled: bool) -> None:
    """Enable or disable a registered tool without changing availability."""
    if name in _registry:
        _registry[name].enabled = bool(enabled)


def _handler_result_failed(result: Any) -> str | None:
    """Return an error when a handler did not produce a successful result.

    ``status == "error"`` is a failure signal in its own right: the fetch tools
    (``web_fetcher``, ``web_search_v2``) return the error text in ``summary``
    and leave every other key absent, so without this check a failed fetch was
    scored as a success — logged ``success=True``, counted as one by the circuit
    breaker, and handed to the model as ``ok: true``.
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
        return str(result.get("error") or "Tool reported failure")
    if result.get("written") is False:
        return str(result.get("error") or "Write operation failed")
    if result.get("deleted") is False:
        return str(result.get("error") or "Delete operation failed")
    if result.get("moved") is False:
        return str(result.get("error") or "Move operation failed")
    if str(result.get("status") or "").strip().lower() == "error":
        return str(
            result.get("summary") or result.get("message") or "Tool reported status=error"
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
    elif name in {
        "read_file_absolute", "list_dir_absolute", "search_files_absolute",
        "read_multiple_files_absolute", "get_file_info_absolute", "list_backups",
        "discover_projects", "get_project_info", "git_status",
    }:
        path_keys = {
            "search_files_absolute": ("root_path",),
            "discover_projects": ("root_path",),
            "get_project_info": ("path",),
            "git_status": ("path",),
            "read_multiple_files_absolute": ("paths",),
        }.get(name, ("path",))
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

    from backend.orchestrator.advanced_modes import get_orchestrator

    return get_orchestrator().check_security_gate(
        action_description=f"{name} {args!r}",
        risk_level=risk_level,
        files_affected=files_affected,
    )


async def execute_tool(
    name: str,
    session_id: str | None,
    args: dict,
    *,
    confirmed: bool = False,
    enforce_confirmation: bool = False,
    retry_confirmation: bool = False,
    confirmation_user_id: str = "",
    autonomous: bool = False,
    project_path: str = "",
    sentinel_enforced: bool = False,
    allowed_tools: Iterable[str] | None = None,
) -> dict:
    spec = get_tool(name)
    if not spec:
        return _typed_tool_response(
            name, ok=False, error=f"Tool '{name}' not found", error_category="unknown_tool"
        )
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
    if sentinel_enforced and project_path and isinstance(args, dict):
        # A tool argument cannot replace the project chosen by the request.
        # Project-relative handlers receive this trusted root before both the
        # Sentinel assessment and the handler call.
        properties = spec.schema.get("properties", {})
        if isinstance(properties, dict):
            trusted_args: dict[str, Any] = {}
            if "project_path" in properties:
                trusted_args["project_path"] = project_path
            if "cwd" in properties:
                trusted_args["cwd"] = project_path
            if trusted_args:
                args = {**args, **trusted_args}
    if name in {
        "todo_write",
        "todo_list",
        "list_skills",
        "load_skill",
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
    arg_errors = validate_tool_args(spec, args)
    if arg_errors:
        return _typed_tool_response(
            name,
            ok=False,
            error="Malformed tool arguments: " + "; ".join(arg_errors),
            error_category="invalid_args",
        )

    # Circuit breaker: a tool that failed N times in a row in this session is
    # short-circuited so the agent stops burning iterations retrying it.
    failures = tool_failure_count(name, session_id)
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

    args, dropped_args = _drop_unsupported_args(spec, args)
    dropped_names = list(dropped_args.get("dropped", []))
    unsupported = [name for name in dropped_names if name != "confirm"]
    if unsupported:
        return _typed_tool_response(
            name,
            ok=False,
            error=(
                "Unsupported tool argument(s): "
                + ", ".join(unsupported)
                + ". Remove them and retry; no action was executed."
            ),
            error_category="invalid_args",
            unsupported_arguments=unsupported,
            valid_arguments=dropped_args.get("valid_arguments", []),
        )

    # Check cache for idempotent tools (only after confirmation is satisfied)
    if _HAVE_TOOL_CACHE:
        try:
            cache = get_tool_cache()
            cached = cache.get(name, args)
            if cached is not None:
                logger.debug("[TOOL CACHE] Hit for %s: %s", name, cached.get("_cached_preview", ""))
                return _typed_tool_response(
                    name,
                    ok=bool(cached.get("ok", True)) and not bool(cached.get("error")),
                    result=cached.get("result"),
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
                tuple(sorted({str(tool).strip() for tool in allowed_tools if str(tool).strip()}))
                if allowed_tools is not None
                else None
            ),
        }
        if project_path:
            handler_args["project_path"] = project_path
    start = time.time()
    try:
        result = await asyncio.wait_for(
            spec.handler(**handler_args), timeout=timeout_seconds
        )
        duration_ms = int((time.time() - start) * 1000)
        handler_error = _handler_result_failed(result)
        if handler_error:
            failure_count = _record_tool_failure(name, session_id)
            response = _typed_tool_response(
                name,
                ok=False,
                result=result,
                error=handler_error,
                error_category="timeout" if result.get("timed_out") else "tool",
                duration_ms=duration_ms,
                timed_out=bool(result.get("timed_out")),
                exit_code=result.get("exit_code"),
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
        _record_tool_success(name, session_id)
        response = _typed_tool_response(
            name, ok=True, result=result, duration_ms=duration_ms
        )
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
        if _HAVE_TOOL_CACHE:
            try:
                cache = get_tool_cache()
                cache.invalidate_after_mutation(name)
                cache.store(name, args, response)
            except Exception:
                pass
        return response
    except TimeoutError:
        duration_ms = int((time.time() - start) * 1000)
        failure_count = _record_tool_failure(name, session_id)
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
        failure_count = _record_tool_failure(name, session_id)
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
