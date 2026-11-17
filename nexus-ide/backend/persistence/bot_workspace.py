"""Default folder for a bot when the user has not selected a project.

The folder is created on demand under the NEXUS data directory, or under
``NEXUS_BOT_WORKSPACE_ROOT`` when that setting is present. A registered
project always wins over this folder. The path is sandboxed by the tool
registry the same way as any other project root.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_SAFE_ID = re.compile(r"[^A-Za-z0-9_-]+")


def _data_dir() -> Path:
    configured = os.environ.get("NEXUS_DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "data"


def bot_workspace_base() -> Path:
    """Parent directory that holds one folder per bot."""
    configured = os.environ.get("NEXUS_BOT_WORKSPACE_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (_data_dir() / "bot-workspaces").resolve()


def bot_workspace_root(bot_id: str) -> str:
    """Create and return the sandbox root for one bot.

    The id is reduced to a single path segment so a crafted identifier cannot
    escape the workspace parent.
    """
    safe = _SAFE_ID.sub("_", str(bot_id or "").strip()).strip("._")[:80]
    if not safe:
        safe = "bot"
    base = bot_workspace_base()
    target = (base / safe).resolve()
    if os.path.commonpath((str(base), str(target))) != str(base):
        raise ValueError("A pasta do bot saiu da raiz configurada.")
    target.mkdir(parents=True, exist_ok=True)
    return str(target)


def is_default_bot_workspace(path: str) -> bool:
    """True when ``path`` lives inside the default bot-workspace parent."""
    text = str(path or "").strip()
    if not text:
        return False
    try:
        resolved = Path(text).expanduser().resolve()
        base = bot_workspace_base()
    except OSError:
        return False
    try:
        return os.path.commonpath((str(base), str(resolved))) == str(base)
    except ValueError:
        return False
