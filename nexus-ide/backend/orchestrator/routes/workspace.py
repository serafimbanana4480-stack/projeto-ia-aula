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
from backend.middleware.auth import require_admin, require_auth
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


def _confined(tool: str, project_path: str, **paths: str) -> dict[str, str] | None:
    """Apply the tool-registry project boundary before an absolute filesystem call.

    These routes used to forward the request path straight to the absolute
    helpers. Those helpers only reject system directories, so an authenticated
    request could read or write another folder. The selected project is the
    same boundary ``execute_tool`` enforces.
    """
    from backend.tools.registry import _project_confinement_error

    message = _project_confinement_error(tool, paths, project_path or "")
    if message is None:
        return None
    return {"error": message, "error_category": "project_scope_denied"}


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


@router.post("/workspace/files/read")
async def workspace_read_file(
    req: WorkspaceReadRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined("read_file_absolute", req.project_path, path=req.path)
    if denied:
        return denied
    return await read_file_absolute(req.path)


@router.post("/workspace/files/write")
async def workspace_write_file(
    req: WorkspaceWriteRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined("write_file_absolute", req.project_path, path=req.path)
    if denied:
        return denied
    return await write_file_absolute(req.path, req.content, auth_token=_extract_token(request))


@router.post("/workspace/files/list")
async def workspace_list_dir(
    req: WorkspaceListRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined("list_dir_absolute", req.project_path, path=req.path)
    if denied:
        return denied
    return await list_dir_absolute(req.path, recursive=req.recursive)


@router.post("/workspace/files/create-dir")
async def workspace_create_dir(
    req: WorkspaceListRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined("create_dir_absolute", req.project_path, path=req.path)
    if denied:
        return denied
    return await create_dir_absolute(req.path)


@router.post("/workspace/files/delete")
async def workspace_delete_file(
    req: WorkspaceDeleteRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined("delete_file_absolute", req.project_path, path=req.path)
    if denied:
        return denied
    return await delete_file_absolute(
        req.path, move_to_trash=req.move_to_trash, auth_token=_extract_token(request)
    )


@router.post("/workspace/files/delete-dir")
async def workspace_delete_dir(
    req: WorkspaceDeleteDirRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined("delete_dir_absolute", req.project_path, path=req.path)
    if denied:
        return denied
    return await delete_dir_absolute(
        req.path, move_to_trash=req.move_to_trash, auth_token=_extract_token(request)
    )


@router.post("/workspace/files/move")
async def workspace_move_file(
    req: WorkspaceMoveRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined(
        "move_file_absolute", req.project_path, src=req.src, dest=req.dest
    )
    if denied:
        return denied
    return await move_file_absolute(req.src, req.dest, auth_token=_extract_token(request))


@router.post("/workspace/files/copy")
async def workspace_copy_file(
    req: WorkspaceCopyRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined(
        "copy_file_absolute", req.project_path, src=req.src, dest=req.dest
    )
    if denied:
        return denied
    return await copy_file_absolute(req.src, req.dest, auth_token=_extract_token(request))


@router.post("/workspace/files/info")
async def workspace_file_info(
    req: WorkspaceFileInfoRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined("get_file_info_absolute", req.project_path, path=req.path)
    if denied:
        return denied
    return await get_file_info_absolute(req.path)


@router.post("/workspace/files/search")
async def workspace_search_files(
    req: WorkspaceSearchRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined(
        "search_files_absolute", req.project_path, root_path=req.root_path
    )
    if denied:
        return denied
    return await search_files_absolute(req.pattern, req.root_path, max_results=req.max_results)


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------


@router.post("/workspace/terminal/shell")
async def workspace_execute_shell(
    req: WorkspaceShellRequest, request: Request, _user: dict = Depends(require_admin)
) -> dict:
    return await execute_shell(
        command=req.command,
        cwd=req.project_path or req.cwd,
        timeout=req.timeout,
        env=req.env,
        auth_token=_extract_token(request),
    )


@router.post("/workspace/terminal/python")
async def workspace_execute_python(
    req: WorkspacePythonRequest, request: Request, _user: dict = Depends(require_admin)
) -> dict:
    return await execute_python(
        code=req.code,
        cwd=req.project_path or req.cwd,
        timeout=req.timeout,
        auth_token=_extract_token(request),
    )


@router.post("/workspace/terminal/script")
async def workspace_execute_script(
    req: WorkspaceScriptRequest, request: Request, _user: dict = Depends(require_admin)
) -> dict:
    return await execute_script(
        path=req.path,
        args=req.args,
        cwd=req.project_path or req.cwd,
        timeout=req.timeout,
        auth_token=_extract_token(request),
    )


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


@router.post("/workspace/git/init")
async def workspace_git_init(
    req: WorkspaceGitInitRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await git_init(req.path)


@router.post("/workspace/git/clone")
async def workspace_git_clone(
    req: WorkspaceGitCloneRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await git_clone(req.url, req.path)


@router.post("/workspace/git/commit-all")
async def workspace_git_commit(
    req: WorkspaceGitCommitRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await git_commit_all(req.path, req.message)


@router.post("/workspace/git/push")
async def workspace_git_push(
    req: WorkspaceGitPushRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    return await git_push(req.path, req.remote, req.branch)


@router.post("/workspace/git/status")
async def workspace_git_status(
    req: WorkspaceGitStatusRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined("git_status", req.project_path, path=req.path)
    if denied:
        return denied
    return await git_status(req.path)


# ---------------------------------------------------------------------------
# Backup / restore
# ---------------------------------------------------------------------------


@router.post("/workspace/backups/list")
async def workspace_list_backups(
    req: WorkspaceListBackupsRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined("list_backups", req.project_path, path=req.path)
    if denied:
        return denied
    return await list_backups(req.path)


@router.post("/workspace/backups/restore")
async def workspace_restore_backup(
    req: WorkspaceRestoreBackupRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined(
        "restore_backup",
        req.project_path,
        backup_path=req.backup_path,
        target_path=req.target_path,
    )
    if denied:
        return denied
    return await restore_backup(req.backup_path, req.target_path)


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------


@router.post("/workspace/projects/discover")
async def workspace_discover_projects(
    req: WorkspaceDiscoverRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined(
        "discover_projects", req.project_path, root_path=req.root_path
    )
    if denied:
        return denied
    return await discover_projects(req.root_path)


@router.post("/workspace/projects/info")
async def workspace_project_info(
    req: WorkspaceProjectInfoRequest, request: Request, _user: dict = Depends(require_auth)
) -> dict:
    denied = _confined("get_project_info", req.project_path, path=req.path)
    if denied:
        return denied
    return await get_project_info(req.path)
