"""Workspace routes — full filesystem and terminal access.

Endpoints mirror the Workspace Manager tools so the frontend can call them
directly without going through the generic tool-execution layer.
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.core.workspace import (
    create_dir_absolute,
    delete_file_absolute,
    discover_projects,
    execute_python,
    execute_script,
    execute_shell,
    get_project_info,
    git_clone,
    git_commit_all,
    git_init,
    git_push,
    git_status,
    list_dir_absolute,
    read_file_absolute,
    search_files_absolute,
    write_file_absolute,
)
from backend.models.api import (
    WorkspaceDeleteRequest,
    WorkspaceDiscoverRequest,
    WorkspaceGitCloneRequest,
    WorkspaceGitCommitRequest,
    WorkspaceGitInitRequest,
    WorkspaceGitPushRequest,
    WorkspaceGitStatusRequest,
    WorkspaceListRequest,
    WorkspaceProjectInfoRequest,
    WorkspacePythonRequest,
    WorkspaceReadRequest,
    WorkspaceScriptRequest,
    WorkspaceSearchRequest,
    WorkspaceShellRequest,
    WorkspaceWriteRequest,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Filesystem
# ---------------------------------------------------------------------------


@router.post("/workspace/files/read")
async def workspace_read_file(req: WorkspaceReadRequest) -> dict:
    return await read_file_absolute(req.path)


@router.post("/workspace/files/write")
async def workspace_write_file(req: WorkspaceWriteRequest) -> dict:
    return await write_file_absolute(req.path, req.content)


@router.post("/workspace/files/list")
async def workspace_list_dir(req: WorkspaceListRequest) -> dict:
    return await list_dir_absolute(req.path, recursive=req.recursive)


@router.post("/workspace/files/create-dir")
async def workspace_create_dir(req: WorkspaceListRequest) -> dict:
    return await create_dir_absolute(req.path)


@router.post("/workspace/files/delete")
async def workspace_delete_file(req: WorkspaceDeleteRequest) -> dict:
    return await delete_file_absolute(req.path, move_to_trash=req.move_to_trash)


@router.post("/workspace/files/search")
async def workspace_search_files(req: WorkspaceSearchRequest) -> dict:
    return await search_files_absolute(req.pattern, req.root_path, max_results=req.max_results)


# ---------------------------------------------------------------------------
# Terminal
# ---------------------------------------------------------------------------


@router.post("/workspace/terminal/shell")
async def workspace_execute_shell(req: WorkspaceShellRequest) -> dict:
    return await execute_shell(
        command=req.command,
        cwd=req.cwd,
        timeout=req.timeout,
        env=req.env,
    )


@router.post("/workspace/terminal/python")
async def workspace_execute_python(req: WorkspacePythonRequest) -> dict:
    return await execute_python(
        code=req.code,
        cwd=req.cwd,
        timeout=req.timeout,
    )


@router.post("/workspace/terminal/script")
async def workspace_execute_script(req: WorkspaceScriptRequest) -> dict:
    return await execute_script(
        path=req.path,
        args=req.args,
        cwd=req.cwd,
        timeout=req.timeout,
    )


# ---------------------------------------------------------------------------
# Git
# ---------------------------------------------------------------------------


@router.post("/workspace/git/init")
async def workspace_git_init(req: WorkspaceGitInitRequest) -> dict:
    return await git_init(req.path)


@router.post("/workspace/git/clone")
async def workspace_git_clone(req: WorkspaceGitCloneRequest) -> dict:
    return await git_clone(req.url, req.path)


@router.post("/workspace/git/commit-all")
async def workspace_git_commit(req: WorkspaceGitCommitRequest) -> dict:
    return await git_commit_all(req.path, req.message)


@router.post("/workspace/git/push")
async def workspace_git_push(req: WorkspaceGitPushRequest) -> dict:
    return await git_push(req.path, req.remote, req.branch)


@router.post("/workspace/git/status")
async def workspace_git_status(req: WorkspaceGitStatusRequest) -> dict:
    return await git_status(req.path)


# ---------------------------------------------------------------------------
# Project discovery
# ---------------------------------------------------------------------------


@router.post("/workspace/projects/discover")
async def workspace_discover_projects(req: WorkspaceDiscoverRequest) -> dict:
    return await discover_projects(req.root_path)


@router.post("/workspace/projects/info")
async def workspace_project_info(req: WorkspaceProjectInfoRequest) -> dict:
    return await get_project_info(req.path)
