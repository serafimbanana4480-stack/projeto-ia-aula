"""Git integration tools for safe file changes.

Provides read-only git operations and safe write operations (commit, stash)
so agents can work with version control without destructive operations.

DANGEROUS operations (force-push, reset --hard, clean) are blocked. Normal push
requires the tool registry's explicit high-risk confirmation gate.
"""

from __future__ import annotations

import asyncio
import logging
import shlex
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

# Blocked git commands that could cause data loss
_BLOCKED_COMMANDS = {
    "pushf",
    "push-force",
    "force-push",
    "reset",
    "reset-hard",
    "clean",
    "checkout",
    "branch-delete",
    "rebase",
    "cherry-pick",
}

# Explicitly allowed Git subcommands. Mutating calls remain confirmation-gated.
_SAFE_COMMANDS = {
    "status",
    "diff",
    "log",
    "show",
    "blame",
    "branch",
    "tag",
    "remote",
    "rev-parse",
    "pull",
    "push",
    "stash",
    "add",
    "commit",
    "restore",
}


def _split_git_command(command: str | Sequence[str]) -> list[str]:
    if isinstance(command, str):
        return shlex.split(command, posix=True)
    return [str(part) for part in command]


def _validate_git_command(command: str | Sequence[str]) -> tuple[bool, str]:
    """Validate that a git command is safe to execute.

    Returns (is_safe, reason).
    """
    try:
        parts = _split_git_command(command)
    except ValueError:
        return False, "Command contains malformed quoting"
    if not parts or parts[0] != "git":
        return False, "Command must start with 'git'"

    if len(parts) < 2:
        return False, "No git subcommand specified"

    subcmd = parts[1].lower()

    # Block dangerous commands
    if subcmd in _BLOCKED_COMMANDS:
        return False, f"Git '{subcmd}' is blocked for safety"

    # Block dangerous flags
    dangerous_flags = {"--force", "--hard", "-f", "-d", "--delete", "--mirror"}
    for flag in parts[2:]:
        normalized_flag = flag.lower()
        if (
            normalized_flag in dangerous_flags
            or normalized_flag.startswith("--force-")
            or normalized_flag.startswith("--force=")
        ):
            return False, f"Git flag '{flag}' is blocked for safety"

    # Allow only explicitly reviewed subcommands. Unknown git commands can
    # mutate repository state in ways that are not covered by the safety gate.
    if subcmd in _SAFE_COMMANDS:
        return True, ""

    logger.warning("Unusual git command blocked: %s", command)
    return False, f"Git '{subcmd}' is not in the allowed command list"


def normalize_git_path(path: str, project_path: str) -> str:
    """Return a literal path to an existing project file, rejecting path expansion."""
    if not isinstance(path, str) or not path or "\0" in path:
        raise ValueError("Git path must be a non-empty string without NUL bytes")

    root = Path(project_path).expanduser().resolve()
    target = Path(path).expanduser()
    if not target.is_absolute():
        target = root / target
    target = target.resolve(strict=False)

    try:
        relative = target.relative_to(root)
    except ValueError as exc:
        raise ValueError("Git path must stay inside the project directory") from exc

    if not target.is_file():
        raise ValueError("Git path must identify an existing file")
    return relative.as_posix()


async def git_operation(
    command: str | Sequence[str] = "git status",
    project_path: str = ".",
) -> dict[str, Any]:
    """Execute a safe git command in the project directory.

    Only explicitly reviewed Git subcommands are allowed. Mutating commands are
    subject to the tool registry's confirmation policy; force-push, reset --hard,
    clean, and unknown subcommands are blocked.

    Args:
        command: The git command to execute (e.g. "git status", "git diff", "git add .").
        project_path: Path to the project directory.

    Returns:
        Dict with command output or error.
    """
    # Validate command safety
    is_safe, reason = _validate_git_command(command)
    if not is_safe:
        return {"error": f"Blocked: {reason}"}

    try:
        argv = _split_git_command(command)
    except ValueError:
        return {"error": "Blocked: Command contains malformed quoting"}
    command_text = command if isinstance(command, str) else shlex.join(argv)

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=project_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30.0)

        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            return {
                "exit_code": proc.returncode,
                "error": errors.strip() or output.strip(),
                "command": command_text,
            }

        return {
            "output": output.strip(),
            "command": command_text,
            "exit_code": 0,
        }

    except TimeoutError:
        return {"error": f"Git command timed out: {command_text}"}
    except FileNotFoundError:
        return {"error": "Git is not installed or not in PATH"}
    except Exception as exc:
        return {"error": f"Git operation failed: {exc}"}


async def git_commit_safe(
    message: str = "auto: changes from NEXUS agent",
    project_path: str = ".",
    add_all: bool = False,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    """Commit Git changes, isolating path-scoped commits from unrelated staged work.

    When ``add_all`` is false, explicit paths are required. Those literal paths
    are staged and passed to ``git commit --only`` so other staged changes stay
    out of the resulting commit. Does NOT push.

    This tool is declared ``risk_level="high"`` and is listed in
    ``registry._CONFIRMATION_TOOLS``, so every call is held for human approval
    by the registry — not only ``add_all``.

    Args:
        message: Commit message.
        project_path: Path to the project directory.
        add_all: Whether to stage all changes before committing.
        paths: Exact project-relative or absolute paths when ``add_all`` is false.

    Returns:
        Dict with commit result.
    """
    results: dict[str, Any] = {}

    if add_all and paths:
        return {"error": "Specify either add_all or paths, not both."}

    normalized_paths: list[str] = []
    if not add_all:
        if not paths:
            return {"error": "Explicit paths are required when add_all is false."}
        try:
            normalized_paths = [normalize_git_path(path, project_path) for path in paths]
        except (TypeError, ValueError) as exc:
            return {"error": f"Invalid commit path: {exc}"}

    if add_all:
        add_result = await git_operation(["git", "add", "-A"], project_path)
        if "error" in add_result:
            return {
                "error": f"git add failed: {add_result.get('error', 'unknown')}",
                "commit": {"exit_code": 1, "error": add_result.get("error", "unknown")},
            }
        results["add"] = add_result.get("output", "staged")
    else:
        pathspecs = [f":(literal){path}" for path in normalized_paths]
        add_result = await git_operation(["git", "add", "--", *pathspecs], project_path)
        if "error" in add_result:
            return {
                "error": f"git add failed: {add_result.get('error', 'unknown')}",
                "commit": {"exit_code": 1, "error": add_result.get("error", "unknown")},
            }
        results["add"] = add_result.get("output", "staged")

    # argv passing prevents shell injection; keep normal commit-message characters intact.
    safe_message = message[:200]

    commit_args = ["git", "commit"]
    if not add_all:
        commit_args.append("--only")
    commit_args.extend(["-m", safe_message])
    if normalized_paths:
        commit_args.extend(["--", *[f":(literal){path}" for path in normalized_paths]])

    commit_result = await git_operation(commit_args, project_path)
    results["commit"] = commit_result
    if "error" in commit_result:
        results["error"] = f"git commit failed: {commit_result['error']}"

    return results


register_tool(
    ToolSpec(
        name="git_operation",
        description=(
            "Execute a safe git command in the project directory. "
            "Only explicitly allowed subcommands are accepted. Mutating operations "
            "require tool confirmation; force-push, reset --hard, clean, and "
            "unknown subcommands are blocked."
        ),
        schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The git command to execute (e.g. 'git status', 'git diff')",
                },
                "project_path": {
                    "type": "string",
                    "description": "Path to the project directory",
                },
            },
            "required": ["command"],
        },
        handler=git_operation,
    )
)

register_tool(
    ToolSpec(
        name="git_commit_safe",
        description=(
            "Commit Git changes. By default, provide exact paths; only those paths are "
            "staged and committed, leaving other staged work untouched. Set add_all=true "
            "only for an explicitly approved whole-project commit. Does NOT push. "
            "Every call requires confirmation (risk_level high) via the registry's "
            "approval gate."
        ),
        schema={
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "Commit message",
                },
                "project_path": {
                    "type": "string",
                    "description": "Path to the project directory",
                },
                "add_all": {
                    "type": "boolean",
                    "description": (
                        "Whether to stage and commit all changes. This tool always "
                        "requires confirmation, with or without add_all."
                    ),
                },
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Exact project paths to stage and commit when add_all is false",
                },
            },
            "required": ["message"],
        },
        handler=git_commit_safe,
        # A commit writes history with no undo. The registry's high-risk gate is
        # the real control; the explicit level keeps that true even if the
        # name-based list in _CONFIRMATION_TOOLS is ever pruned.
        risk_level="high",
    )
)


async def git_pull(command: str, project_path: str | None = None) -> dict:
    """Pull changes from remote (safe operation, read-only effect on remote).

    Args:
        command: git pull arguments (e.g. 'origin main' or 'origin feature-branch')
        project_path: Path to the project directory

    Returns:
        dict with stdout/stderr from git pull
    """
    cmd_lower = command.strip().lower()
    # Block force-pull with rebase/reset
    for blocked in ("-f ", " --force", "--rebase", "reset --hard"):
        if blocked in cmd_lower:
            return {"error": f"Blocked unsafe pull flag: {blocked.strip()}"}
    return await git_operation(f"git pull {command}", project_path)


async def git_push(
    command: str, project_path: str | None = None, confirm: bool = False
) -> dict:
    """Push commits to remote.

    **Requires explicit confirmation** via the ``confirm`` parameter to prevent
    accidental pushes. If ``confirm`` is False, returns a dry-run preview.
    Set the env var ``NEXUS_ALLOW_GIT_PUSH=true`` to enable without confirm
    (only do this in trusted environments).

    Args:
        command: git push arguments (e.g. 'origin main' or 'origin feature-branch')
        project_path: Path to the project directory
        confirm: Must be True to actually push

    Returns:
        dict with status (preview/pushed) and stdout/stderr
    """
    import os

    allow_without_confirm = os.environ.get("NEXUS_ALLOW_GIT_PUSH", "").lower() == "true"

    if not confirm and not allow_without_confirm:
        # Dry-run preview
        preview = await git_operation(
            f"git push --dry-run {command}", project_path
        )
        return {
            "status": "preview",
            "message": (
                "Push not executed. Pass confirm=True to actually push, "
                "or set NEXUS_ALLOW_GIT_PUSH=true env var."
            ),
            "dry_run_output": preview,
        }

    cmd_lower = command.strip().lower()
    # Block force-push (catastrophic)
    for blocked in ("-f", "--force", "--force-with-lease", "mirror"):
        if blocked in cmd_lower:
            return {"error": f"Blocked unsafe push flag: {blocked}"}

    # Also block deleting remote branches
    if ":delete" in command or "--delete" in command:
        return {"error": "Blocked push --delete (use 'git branch -d' locally instead)"}

    result = await git_operation(f"git push {command}", project_path)
    result["status"] = "pushed"
    return result


register_tool(
    ToolSpec(
        name="git_pull",
        description=(
            "Pull changes from a remote repository. Safe read-only operation. "
            "Force-pull and rebase flags are blocked."
        ),
        schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Pull arguments e.g. 'origin main' or 'origin feature-branch'"
                    ),
                },
                "project_path": {
                    "type": "string",
                    "description": "Path to the project directory",
                },
            },
            "required": ["command"],
        },
        handler=git_pull,
    )
)

register_tool(
    ToolSpec(
        name="git_push",
        description=(
            "Push commits to a remote repository. **Requires confirmation** via "
            "the confirm=true parameter (or set NEXUS_ALLOW_GIT_PUSH=true env). "
            "Without confirmation, returns a dry-run preview. Force-push, "
            "mirror-push, and --delete are blocked."
        ),
        schema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "Push arguments e.g. 'origin main' or 'origin feature-branch'"
                    ),
                },
                "project_path": {
                    "type": "string",
                    "description": "Path to the project directory",
                },
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true to actually push (safety check)",
                    "default": False,
                },
            },
            "required": ["command"],
        },
        handler=git_push,
    )
)

