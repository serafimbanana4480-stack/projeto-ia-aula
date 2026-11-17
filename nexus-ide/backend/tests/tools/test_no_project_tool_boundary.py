"""The no-project boundary at the tool layer.

Three rules are pinned here, all of them observed in the live registry before
the fix:

1. a workspace tool (file read/write, shell, code execution) with no selected
   project is refused with an actionable message instead of silently resolving
   relative paths against the backend process' current directory;
2. a project-independent tool (skills, memory, MCP, tasks) keeps working with
   no project, because a missing project must not disable it;
3. a selected project confines the same tools to its root, so the refusal is
   about the *absence* of a folder and never about a folder being present.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.tools.registry import execute_tool, list_tools

SESSION = "sess-no-project"

#: The workspace families whose handlers would otherwise default to "." and
#: operate on the server's working directory.
_WORKSPACE_TOOLS = (
    "read_file",
    "read_multiple_files",
    "write_file",
    "append_file",
    "list_dir",
    "search_in_files",
    "create_directory",
    "run_shell",
    "execute_shell",
    "execute_python",
    "run_tests",
    "run_lint",
    "type_check",
    "format_code",
    "index_codebase",
    "search_codebase",
    "analyze_project",
)

#: Tools that must keep working with no project selected.
_PROJECT_INDEPENDENT_TOOLS = (
    "list_skills",
    "load_skill",
    "discover_skill_candidates",
    "report_skill_outcome",
    "store_memory",
    "recall_context",
    "mcp_list_tools",
    "todo_list",
    "get_session_status",
    "sequential_thinking",
    "web_search",
)

_REFUSAL_MARKERS = ("nenhum projeto", "pasta autorizada", "seleciona o projeto")


def _all_tools() -> frozenset[str]:
    return frozenset(
        spec.name
        for spec in list_tools(enabled_only=True)
        if spec.available and spec.enabled and spec.handler is not None
    )


def _is_refusal(result: dict) -> bool:
    """A refusal must be visible, categorised and must not have run anything."""
    if result.get("ok") is not False:
        return False
    if result.get("error_category") != "project_scope_denied":
        return False
    message = str(result.get("error") or "").casefold()
    return any(marker in message for marker in _REFUSAL_MARKERS)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", _WORKSPACE_TOOLS)
async def test_workspace_tool_without_a_project_is_refused_with_an_actionable_message(
    tool: str,
) -> None:
    args: dict[str, object] = {"path": "README.md", "content": "x", "command": "echo hi"}
    result = await execute_tool(
        tool, SESSION, args, project_path="", allowed_tools=_all_tools()
    )
    assert _is_refusal(result), result


@pytest.mark.asyncio
async def test_relative_write_is_not_silently_redirected_to_the_process_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The original defect: a write landed in the backend's working directory."""
    import os

    monkeypatch.chdir(tmp_path)
    (tmp_path / "orphan.txt").write_text("seed\n", encoding="utf-8")

    result = await execute_tool(
        "append_file",
        SESSION,
        {"path": "orphan.txt", "content": "appended without a project\n"},
        project_path="",
        allowed_tools=_all_tools(),
    )

    assert _is_refusal(result), result
    assert (tmp_path / "orphan.txt").read_text(encoding="utf-8") == "seed\n"
    assert os.getcwd() == str(tmp_path)


@pytest.mark.asyncio
async def test_shell_without_a_project_cannot_pick_a_working_directory() -> None:
    """``cwd`` was popped and the handler defaulted to the process directory."""
    for cwd in (None, ".", "", "./"):
        args: dict[str, object] = {"command": "echo probe"}
        if cwd is not None:
            args["cwd"] = cwd
        result = await execute_tool(
            "run_shell", SESSION, args, project_path="", allowed_tools=_all_tools()
        )
        assert _is_refusal(result), (cwd, result)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", _PROJECT_INDEPENDENT_TOOLS)
async def test_project_independent_tools_still_run_without_a_project(tool: str) -> None:
    """A missing project must not disable browser, MCP, memory or skills."""
    args: dict[str, object] = {"name": "nexus-backend", "query": "nexus"}
    result = await execute_tool(
        tool, SESSION, args, project_path="", allowed_tools=_all_tools(), user_id="probe-user"
    )
    assert result.get("confirmation_required") is not True, result
    assert result.get("error_category") not in {"project_scope_denied", "tool_not_allowed"}, result


@pytest.mark.asyncio
async def test_the_same_tool_runs_inside_a_selected_project(tmp_path: Path) -> None:
    """The refusal is about the missing folder, never about the tool itself."""
    (tmp_path / "inside.md").write_text("conteudo\n", encoding="utf-8")

    blocked = await execute_tool(
        "read_file", SESSION, {"path": "inside.md"}, project_path="", allowed_tools=_all_tools()
    )
    assert _is_refusal(blocked), blocked

    allowed = await execute_tool(
        "read_file",
        SESSION,
        {"path": "inside.md"},
        project_path=str(tmp_path),
        allowed_tools=_all_tools(),
    )
    assert allowed.get("ok") is True, allowed


@pytest.mark.asyncio
async def test_absolute_path_tools_still_ask_for_a_project(tmp_path: Path) -> None:
    """The absolute-path lane keeps its own boundary and its clear message."""
    target = tmp_path / "note.txt"
    target.write_text("hello\n", encoding="utf-8")

    result = await execute_tool(
        "read_file_absolute",
        SESSION,
        {"path": str(target)},
        project_path="",
        allowed_tools=_all_tools(),
    )
    assert result.get("ok") is False
    assert result.get("error_category") == "project_scope_denied"

    # Inside the project root the very same call is served.
    inside = await execute_tool(
        "read_file_absolute",
        SESSION,
        {"path": str(target)},
        project_path=str(tmp_path),
        allowed_tools=_all_tools(),
    )
    assert inside.get("ok") is True, inside


def test_the_projectless_fallback_allowlist_matches_the_real_contract() -> None:
    """``_NO_PROJECT_TOOLS`` is what the chat advertises when the registry
    cannot be listed; it must not promise a tool the registry refuses."""
    from backend.orchestrator.routes.chat_primary import _NO_PROJECT_TOOLS
    from backend.tools.registry import get_tool

    registered = {spec.name for spec in list_tools(enabled_only=False)}
    from backend.tools.registry import _PROJECT_INDEPENDENT_TOOLS

    for name in _NO_PROJECT_TOOLS:
        assert name in registered, f"{name} is advertised but not registered"
        # A workspace tool is one the registry refuses with no project; the
        # projectless fallback must never advertise one.
        assert name in _PROJECT_INDEPENDENT_TOOLS or not (
            {"project_path", "cwd"} & set(get_tool(name).schema.get("properties", {}))
        ), name

    # The capability families that work with no project must still be covered,
    # so a broken registry cannot silently strand a bot's memory or skills.
    for name in ("recall_context", "store_memory", "list_skills", "load_skill", "mcp_list_tools"):
        assert name in set(_NO_PROJECT_TOOLS), name
