"""Sandbox package — isolated code execution and security policies.

See ARCHITECTURE.md §11.
"""
from backend.sandbox.executor import (
    SandboxExecutor,
    SandboxConfig,
    SandboxResult,
    SecurityPolicy,
    DangerousCommandDetector,
    RiskLevel,
    get_sandbox_executor,
    get_security_policy,
)

__all__ = [
    "SandboxExecutor",
    "SandboxConfig",
    "SandboxResult",
    "SecurityPolicy",
    "DangerousCommandDetector",
    "RiskLevel",
    "get_sandbox_executor",
    "get_security_policy",
]
