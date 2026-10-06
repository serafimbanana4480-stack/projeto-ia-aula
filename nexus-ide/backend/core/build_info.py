"""Build/version identity for a running NEXUS IDE instance.

Audit P1: there was no way to tell *which* build a deployed instance is
serving, so "the fix isn't in production yet" was impossible to verify from the
outside.  ``/version`` (and ``/api/version``) report the version, the git sha
and a couple of cheap environment facts, all unauthenticated and free of
secrets.

Nothing here may raise: this is a diagnostic endpoint and it must keep working
on a half-broken machine (no git, unreadable package metadata...).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

#: Bumped by hand; the API title used to hard-code "0.1.0" and drifted.
NEXUS_VERSION = "0.1.0"

#: Repository root (…/nexus-ide).
_REPO_ROOT = Path(__file__).resolve().parents[2]

_GIT_TIMEOUT_SECONDS = 5


@lru_cache(maxsize=1)
def _git_sha() -> str:
    """Return the short git sha of the working tree, or ``""``.

    ``git`` is optional: containers and exported tarballs frequently ship
    without it, and a missing sha must not break startup.
    """
    env = dict(os.environ)
    # Never let a user's global git config stall or prompt the process.
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        completed = subprocess.run(  # noqa: S603 — fixed argv, no shell
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=str(_REPO_ROOT),
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
            timeout=_GIT_TIMEOUT_SECONDS,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.debug("git sha unavailable: %s", exc)
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def get_build_info() -> dict[str, Any]:
    """Version + build identity. Never raises."""
    info: dict[str, Any] = {
        "name": "NEXUS IDE",
        "version": NEXUS_VERSION,
        "git_sha": _git_sha() or "unknown",
        "python": ".".join(str(part) for part in sys.version_info[:3]),
    }
    try:
        from backend.config.settings import get_settings

        current = get_settings()
        info["environment"] = str(getattr(current, "environment", "unknown"))
        info["llm_provider"] = str(getattr(current, "llm_provider", "unknown"))
    except Exception:  # pragma: no cover - diagnostics must not raise
        logger.debug("Could not read settings for build info", exc_info=True)
        info["environment"] = "unknown"
        info["llm_provider"] = "unknown"

    # Configuration *presence* only — never values.
    info["redis_url_configured"] = bool(os.environ.get("REDIS_URL", "").strip())
    try:
        from backend.middleware.rate_limit import is_enabled, requests_per_minute

        info["rate_limit_enabled"] = is_enabled()
        info["rate_limit_requests_per_minute"] = requests_per_minute()
    except Exception:  # pragma: no cover
        logger.debug("Could not read rate limit config for build info", exc_info=True)
    return info
