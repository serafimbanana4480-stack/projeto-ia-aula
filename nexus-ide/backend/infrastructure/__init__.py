"""Infrastructure package — Docker sandboxing and git worktree isolation.

Provides low-level runtime and VCS utilities used by agents and the
orchestrator to execute code safely and manage parallel repository branches.
"""
from backend.infrastructure.docker_sandbox import (
    ContainerInfo,
    DockerSandbox,
    DockerSandboxConfig,
)
from backend.infrastructure.worktree_manager import (
    WorktreeError,
    WorktreeInfo,
    WorktreeManager,
    WorktreeManagerConfig,
)

__all__ = [
    "DockerSandbox",
    "DockerSandboxConfig",
    "ContainerInfo",
    "WorktreeManager",
    "WorktreeManagerConfig",
    "WorktreeInfo",
    "WorktreeError",
]
