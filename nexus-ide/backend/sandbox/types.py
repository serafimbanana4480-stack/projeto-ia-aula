"""Sandbox Types — common data structures for sandbox system.

Shared types used across sandbox modules to avoid circular imports.
"""
from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(str, Enum):
    """Risk level classification for sandbox operations."""
    SAFE = "safe"  # read-only, no side effects
    LOW = "low"  # file writes within project
    MEDIUM = "medium"  # network access, package install
    HIGH = "high"  # system modification, git operations
    CRITICAL = "critical"  # destructive operations, requires explicit approval


@dataclass
class SandboxConfig:
    """Configuration for sandbox execution environment."""

    image: str = "python:3.12-slim"  # Docker image
    timeout_seconds: int = 30
    max_memory_mb: int = 512
    max_cpu_cores: float = 0.5
    max_disk_mb: int = 100
    network_enabled: bool = False
    read_only_root: bool = True
    allow_write_paths: list[str] = field(default_factory=lambda: ["/tmp", "/workspace"])
    environment: dict[str, str] = field(default_factory=dict)
    working_dir: str = "/workspace"


@dataclass
class SandboxResult:
    """Result of a sandboxed execution."""

    execution_id: str
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_ms: int
    memory_used_mb: float = 0.0
    risk_level: RiskLevel = RiskLevel.SAFE
    sandbox_healthy: bool = True
    snapshot_hash: str | None = None
    dependencies_installed: list[str] = field(default_factory=list)
    policy_violations: list[str] = field(default_factory=list)
