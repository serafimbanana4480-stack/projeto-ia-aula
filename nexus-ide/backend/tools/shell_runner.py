"""Shell runner tool — execute safe shell commands via WorkspaceManager.

Delegates all validation and execution to :class:`backend.core.workspace.WorkspaceManager`,
which provides an expanded command whitelist and comprehensive audit logging.
"""

from __future__ import annotations

from backend.tools.registry import ToolSpec, register_tool


async def run_shell(
    command: str,
    project_path: str = ".",
    timeout: int = 30,
) -> dict:
    """Run shell commands in the project directory.

    Args:
        command: Shell command to execute.
        project_path: Project root path (commands run inside this directory).
        timeout: Maximum execution time in seconds.

    Returns:
        Dict with stdout, stderr, return code, and command info.
    """
    from backend.core.workspace import WorkspaceManager
    manager = WorkspaceManager(project_path)
    return await manager.execute_shell(command, cwd=project_path, timeout=timeout)


async def run_python_script(
    code: str,
    project_path: str = ".",
    timeout: int = 30,
) -> dict:
    """Run a Python script string in the project directory."""
    from backend.core.workspace import WorkspaceManager
    manager = WorkspaceManager(project_path)
    return await manager.execute_python(code, cwd=project_path, timeout=timeout)


register_tool(
    ToolSpec(
        name="run_shell",
        description=(
            "Run shell commands in the project directory. "
            "Allowed commands include: python, pip, npm, node, git, cargo, go, docker, make, "
            "gcc, clang, find, grep, awk, sed, tar, ssh, rsync, and many more. "
            "Dangerous commands (rm -rf /, dd, mkfs, format, shutdown, etc.) are blocked."
        ),
        schema={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to execute"},
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
                "timeout": {
                    "type": "integer",
                    "default": 30,
                    "description": "Timeout in seconds",
                },
            },
            "required": ["command"],
        },
        handler=run_shell,
    )
)

register_tool(
    ToolSpec(
        name="run_python_script",
        description="Run a Python script string in the project directory",
        schema={
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Python code to execute"},
                "project_path": {
                    "type": "string",
                    "default": ".",
                    "description": "Project root path",
                },
                "timeout": {
                    "type": "integer",
                    "default": 30,
                    "description": "Timeout in seconds",
                },
            },
            "required": ["code"],
        },
        handler=run_python_script,
    )
)
