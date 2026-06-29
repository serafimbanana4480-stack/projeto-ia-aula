"""Infrastructure package — Docker sandboxing and git worktree isolation.

Provides low-level runtime and VCS utilities used by agents and the
orchestrator to execute code safely and manage parallel repository branches.
"""
from backend.infrastructure.docker_sandbox import (
    DockerSandbox,
    DockerSandboxConfig,
    ContainerInfo,
)
from backend.infrastructure.worktree_manager import (
    WorktreeManager,
    WorktreeManagerConfig,
    WorktreeInfo,
    WorktreeError,
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
