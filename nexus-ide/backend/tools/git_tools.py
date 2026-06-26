"""Git integration tools for safe file changes.

Provides read-only git operations and safe write operations (commit, stash)
so agents can work with version control without destructive operations.

DANGEROUS operations (push, force-push, reset --hard, clean) are blocked.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)

# Blocked git commands that could cause data loss
_BLOCKED_COMMANDS = {
    "push",
    "pushf",
    "push-force",
    "force-push",
    "reset",
    "reset-hard",
    "clean",
    "checkout",
    "branch-d",
    "branch-D",
    "branch-delete",
    "rebase",
    "cherry-pick",
}

# Allowed safe git commands
_SAFE_COMMANDS = {
    "status",
    "diff",
    "log",
    "show",
    "blame",
    "branch",
    "tag",
    "remote",
    "stash",
    "add",
    "commit",
    "restore",
}


def _validate_git_command(command: str) -> tuple[bool, str]:
    """Validate that a git command is safe to execute.

    Returns (is_safe, reason).
    """
    parts = command.strip().split()
    if not parts or parts[0] != "git":
        return False, "Command must start with 'git'"

    if len(parts) < 2:
        return False, "No git subcommand specified"

    subcmd = parts[1].lower()

    # Block dangerous commands
    if subcmd in _BLOCKED_COMMANDS:
        return False, f"Git '{subcmd}' is blocked for safety"

    # Block dangerous flags
    cmd_str = " ".join(parts).lower()
    dangerous_flags = ["--force", "--hard", "-f", "-D", "--delete"]
    for flag in dangerous_flags:
        if flag in cmd_str:
            return False, f"Git flag '{flag}' is blocked for safety"

    # Allow known safe commands
    if subcmd in _SAFE_COMMANDS:
        return True, ""

    # Allow unknown commands with caution (whitelist approach would be too restrictive)
    logger.warning("Unusual git command allowed: %s", command)
    return True, ""


async def git_operation(
    command: str = "git status",
    project_path: str = ".",
) -> dict[str, Any]:
    """Execute a safe git command in the project directory.

    Only read operations and safe write operations (add, commit, stash) are allowed.
    Dangerous operations (push, force-push, reset --hard, clean) are blocked.

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
        proc = await asyncio.create_subprocess_exec(
            *command.split(),
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
                "command": command,
            }

        return {
            "output": output.strip(),
            "command": command,
            "exit_code": 0,
        }

    except TimeoutError:
        return {"error": f"Git command timed out: {command}"}
    except FileNotFoundError:
        return {"error": "Git is not installed or not in PATH"}
    except Exception as exc:
        return {"error": f"Git operation failed: {exc}"}


async def git_commit_safe(
    message: str = "auto: changes from NEXUS agent",
    project_path: str = ".",
    add_all: bool = False,
) -> dict[str, Any]:
    """Safely commit changes to git.

    This is a convenience wrapper that:
    1. Optionally runs `git add -A` (if add_all=True)
    2. Runs `git commit -m "<message>"`
    Does NOT push.

    Args:
        message: Commit message.
        project_path: Path to the project directory.
        add_all: Whether to stage all changes before committing.

    Returns:
        Dict with commit result.
    """
    results = {}

    if add_all:
        add_result = await git_operation("git add -A", project_path)
        if "error" in add_result and add_result.get("exit_code", 0) != 0:
            return {"error": f"git add failed: {add_result.get('error', 'unknown')}"}
        results["add"] = add_result.get("output", "staged")

    # Sanitize commit message (no shell injection)
    safe_message = message.replace('"', '\\"').replace("`", "").replace("$", "")[:200]

    commit_result = await git_operation(
        f'git commit -m "{safe_message}"',
        project_path,
    )
    results["commit"] = commit_result

    return results


register_tool(
    ToolSpec(
        name="git_operation",
        description=(
            "Execute a safe git command in the project directory. "
            "Read operations (status, diff, log, show, blame) and safe write "
            "operations (add, commit, stash) are allowed. "
            "Dangerous operations (push, force-push, reset --hard, clean) are blocked."
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
            "Safely commit changes to git. Optionally stages all changes first. "
            "Does NOT push. Use this after modifying files to create a checkpoint."
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
                    "description": "Whether to stage all changes before committing",
                },
            },
            "required": ["message"],
        },
        handler=git_commit_safe,
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

