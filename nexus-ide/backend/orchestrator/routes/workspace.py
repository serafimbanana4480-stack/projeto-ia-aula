"""Workspace routes — full filesystem and terminal access.

Endpoints mirror the Workspace Manager tools so the frontend can call them
directly without going through the generic tool-execution layer.
"""

from fastapi import APIRouter, Depends, Request

from backend.core.workspace import (
    copy_file_absolute,
    create_dir_absolute,
    delete_dir_absolute,
    delete_file_absolute,
    discover_projects,
    execute_python,
    execute_script,
    execute_shell,
    get_file_info_absolute,
    get_project_info,
    git_clone,
    git_commit_all,
    git_init,
    git_push,
    git_status,
    list_backups,
    list_dir_absolute,
    move_file_absolute,
    read_file_absolute,
    restore_backup,
    search_files_absolute,
    write_file_absolute,
)
from backend.middleware.auth import require_auth
from backend.middleware.rate_limit import limiter
from backend.models.api import (
    WorkspaceCopyRequest,
    WorkspaceDeleteDirRequest,
    WorkspaceDeleteRequest,
    WorkspaceDiscoverRequest,
    WorkspaceFileInfoRequest,
    WorkspaceGitCloneRequest,
    WorkspaceGitCommitRequest,
    WorkspaceGitInitRequest,
    WorkspaceGitPushRequest,
    WorkspaceGitStatusRequest,
    WorkspaceListBackupsRequest,
    WorkspaceListRequest,
    WorkspaceMoveRequest,
    WorkspaceProjectInfoRequest,
    WorkspacePythonRequest,
    WorkspaceReadRequest,
    WorkspaceRestoreBackupRequest,
    WorkspaceScriptRequest,
    WorkspaceSearchRequest,
    WorkspaceShellRequest,
    WorkspaceWriteRequest,
)

router = APIRouter()


def _extract_token(request: Request) -> str | None:
    """Extract the Bearer token from the Authorization header."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:]
    return None


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


@router.post("/workspace/files/read")
@limiter.limit("60/minute")
async def workspace_read_file(
    req: WorkspaceReadRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await read_file_absolute(req.path)


@router.post("/workspace/files/write")
@limiter.limit("30/minute")
async def workspace_write_file(
    req: WorkspaceWriteRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await write_file_absolute(req.path, req.content, auth_token=_extract_token(request))


@router.post("/workspace/files/list")
@limiter.limit("60/minute")
async def workspace_list_dir(
    req: WorkspaceListRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await list_dir_absolute(req.path, recursive=req.recursive)


@router.post("/workspace/files/create-dir")
@limiter.limit("30/minute")
async def workspace_create_dir(
    req: WorkspaceListRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await create_dir_absolute(req.path)


@router.post("/workspace/files/delete")
@limiter.limit("30/minute")
async def workspace_delete_file(
    req: WorkspaceDeleteRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await delete_file_absolute(
        req.path, move_to_trash=req.move_to_trash, auth_token=_extract_token(request)
    )


@router.post("/workspace/files/delete-dir")
@limiter.limit("10/minute")
async def workspace_delete_dir(
    req: WorkspaceDeleteDirRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await delete_dir_absolute(
        req.path, move_to_trash=req.move_to_trash, auth_token=_extract_token(request)
    )


@router.post("/workspace/files/move")
@limiter.limit("30/minute")
async def workspace_move_file(
    req: WorkspaceMoveRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await move_file_absolute(req.src, req.dest, auth_token=_extract_token(request))


@router.post("/workspace/files/copy")
@limiter.limit("30/minute")
async def workspace_copy_file(
    req: WorkspaceCopyRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await copy_file_absolute(req.src, req.dest, auth_token=_extract_token(request))


@router.post("/workspace/files/info")
@limiter.limit("60/minute")
async def workspace_file_info(
    req: WorkspaceFileInfoRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await get_file_info_absolute(req.path)


@router.post("/workspace/files/search")
@limiter.limit("60/minute")
async def workspace_search_files(
    req: WorkspaceSearchRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await search_files_absolute(req.pattern, req.root_path, max_results=req.max_results)


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------


@router.post("/workspace/terminal/shell")
@limiter.limit("10/minute")
async def workspace_execute_shell(
    req: WorkspaceShellRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await execute_shell(
        command=req.command,
        cwd=req.cwd,
        timeout=req.timeout,
        env=req.env,
        auth_token=_extract_token(request),
    )


@router.post("/workspace/terminal/python")
@limiter.limit("10/minute")
async def workspace_execute_python(
    req: WorkspacePythonRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await execute_python(
        code=req.code,
        cwd=req.cwd,
        timeout=req.timeout,
        auth_token=_extract_token(request),
    )


@router.post("/workspace/terminal/script")
@limiter.limit("10/minute")
async def workspace_execute_script(
    req: WorkspaceScriptRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await execute_script(
        path=req.path,
        args=req.args,
        cwd=req.cwd,
        timeout=req.timeout,
        auth_token=_extract_token(request),
    )


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


@router.post("/workspace/git/init")
@limiter.limit("10/minute")
async def workspace_git_init(
    req: WorkspaceGitInitRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await git_init(req.path)


@router.post("/workspace/git/clone")
@limiter.limit("10/minute")
async def workspace_git_clone(
    req: WorkspaceGitCloneRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await git_clone(req.url, req.path)


@router.post("/workspace/git/commit-all")
@limiter.limit("10/minute")
async def workspace_git_commit(
    req: WorkspaceGitCommitRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await git_commit_all(req.path, req.message)


@router.post("/workspace/git/push")
@limiter.limit("10/minute")
async def workspace_git_push(
    req: WorkspaceGitPushRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await git_push(req.path, req.remote, req.branch)


@router.post("/workspace/git/status")
@limiter.limit("30/minute")
async def workspace_git_status(
    req: WorkspaceGitStatusRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await git_status(req.path)


# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------


@router.post("/workspace/backups/list")
@limiter.limit("30/minute")
async def workspace_list_backups(
    req: WorkspaceListBackupsRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await list_backups(req.path)


@router.post("/workspace/backups/restore")
@limiter.limit("10/minute")
async def workspace_restore_backup(
    req: WorkspaceRestoreBackupRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await restore_backup(req.backup_path, req.target_path)


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------


@router.post("/workspace/projects/discover")
@limiter.limit("30/minute")
async def workspace_discover_projects(
    req: WorkspaceDiscoverRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await discover_projects(req.root_path)


@router.post("/workspace/projects/info")
@limiter.limit("30/minute")
async def workspace_project_info(
    req: WorkspaceProjectInfoRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await get_project_info(req.path)
