"""Terminal routes for local command execution in the editor workspace."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from backend.middleware.auth import require_auth
from backend.models.api import TerminalExecuteRequest, TerminalExecuteResponse
from backend.sandbox.executor import get_sandbox_executor

router = APIRouter()


@router.post("/terminal/execute", response_model=TerminalExecuteResponse)
async def execute_terminal_command(
    req: TerminalExecuteRequest, request: Request, _user: dict = Depends(require_auth)
) -> TerminalExecuteResponse:
    executor = get_sandbox_executor()

    # Resolve working directory from project_path
    cwd = None
    if req.project_path and req.project_path != ".":
        from pathlib import Path

        project = Path(req.project_path).resolve()
        if project.is_dir():
            cwd = str(project)

    result = await executor.execute(
        req.command,
        language="bash",
        timeout=req.timeout_seconds,
        session_id=req.session_id or request.headers.get("x-session-id", ""),
        cwd=cwd,
    )
    return TerminalExecuteResponse(
        execution_id=result.execution_id,
        command=req.command,
        stdout=result.stdout,
        stderr=result.stderr,
        exit_code=result.exit_code,
        timed_out=result.timed_out,
        duration_ms=result.duration_ms,
        risk_level=result.risk_level.value,
    )
