"""Terminal routes for local command execution in the editor workspace."""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends

from backend.core.workspace_security import _validate_shell_command
from backend.core.workspace_shell import execute_shell
from backend.middleware.auth import require_admin
from backend.models.api import TerminalExecuteRequest, TerminalExecuteResponse
from backend.sandbox.executor import DangerousCommandDetector

router = APIRouter()


@router.post("/terminal/execute", response_model=TerminalExecuteResponse)
async def execute_terminal_command(
    req: TerminalExecuteRequest, _user: dict = Depends(require_admin)
) -> TerminalExecuteResponse:
    # Use the same server-side project boundary as the file API. A client may
    # select a registered project, but cannot point terminal execution at an
    # arbitrary directory on the host.
    from backend.orchestrator.routes.files import _resolve_project_root

    project_root = _resolve_project_root(
        req.project_path,
        req.session_id,
        str(_user.get("user_id") or ""),
    )
    cwd = str(project_root)

    started = time.perf_counter()
    execution_id = uuid.uuid4().hex[:12]
    risk, reasons = DangerousCommandDetector.assess_risk(req.command)
    is_safe, validation_reason = _validate_shell_command(req.command)
    if risk.value == "critical" or not is_safe:
        reason = "; ".join(reasons) if reasons else validation_reason
        return TerminalExecuteResponse(
            execution_id=execution_id,
            command=req.command,
            stdout="",
            stderr=f"Command blocked: {reason}",
            exit_code=1,
            timed_out=False,
            duration_ms=int((time.perf_counter() - started) * 1000),
            risk_level="critical",
        )

    result = await execute_shell(req.command, cwd=cwd, timeout=req.timeout_seconds)
    error = str(result.get("error") or "")
    return TerminalExecuteResponse(
        execution_id=execution_id,
        command=req.command,
        stdout=str(result.get("stdout") or ""),
        stderr=str(result.get("stderr") or error),
        exit_code=int(result.get("exit_code", 1 if error else 0)),
        timed_out=bool(result.get("timed_out") or "timed out" in error.lower()),
        duration_ms=int((time.perf_counter() - started) * 1000),
        risk_level=risk.value,
    )
