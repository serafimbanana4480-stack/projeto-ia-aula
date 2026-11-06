"""NEXUS IDE — MCP (Model Context Protocol) connector subsystem.

Gives the IDE a first-class way to register, test, and export MCP server
connections (filesystem, GitHub, Postgres, Slack, etc.) without hand-editing
JSON config files. See ``backend/mcp/templates.py`` for the built-in catalog
and ``backend/mcp/store.py`` for the persistent connector store.

Why this module has import machinery in it
-----------------------------------------
This package lives in ``backend/mcp/`` and the NEXUS backend puts the
``backend/`` directory on ``sys.path`` (see ``backend/migrations/env.py``,
which runs inside ``init_db()`` at every process start). That makes the
*top-level* name ``mcp`` resolve to THIS package instead of the installed
``mcp`` SDK: ``from mcp import ClientSession`` then raises ``ImportError``
and the whole MCP subsystem is dead in a running process, even though the
SDK is installed.

Both names have to keep working:

* ``import mcp`` must return the installed SDK (``mcp.server``,
  ``mcp.types``, ``mcp.client.stdio`` ...), and
* ``import backend.mcp`` must return this connector subsystem.

A package directory can only be a regular package (which shadows the SDK)
or a namespace portion (which cannot re-export anything). So the shadow is
resolved here instead: when this file is executed as the top-level ``mcp``
package — i.e. it won the name away from the SDK — it loads the installed
SDK and installs it in ``sys.modules["mcp"]``. The import machinery then
hands the SDK (not this package) to every ``import mcp`` in the process.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

#: Distribution/import name of the third-party Model Context Protocol SDK.
_SDK_NAME = "mcp"


def _installed_sdk_init() -> Path | None:
    """Return the ``__init__.py`` of the installed ``mcp`` SDK, if any.

    This very file is skipped on purpose: it is the shadow, not the SDK.
    """
    own = Path(__file__).resolve()
    for entry in sys.path:
        if not entry:
            continue
        try:
            candidate = (Path(entry) / _SDK_NAME / "__init__.py").resolve()
        except OSError:  # pragma: no cover - unreadable sys.path entry
            continue
        if candidate == own:
            continue
        if candidate.is_file():
            return candidate
    return None


def _redirect_to_installed_sdk() -> ModuleType:
    """Replace this shadowing package with the installed ``mcp`` SDK."""
    init_file = _installed_sdk_init()
    if init_file is None:
        raise ImportError(
            "O SDK 'mcp' (Model Context Protocol) não está instalado neste runtime; "
            "a pasta backend/mcp do NEXUS não o pode substituir."
        )
    spec = importlib.util.spec_from_file_location(
        _SDK_NAME,
        init_file,
        submodule_search_locations=[str(init_file.parent)],
    )
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"Não foi possível carregar o SDK MCP a partir de {init_file}")
    module = importlib.util.module_from_spec(spec)
    # Publish the SDK before executing it: its own relative imports
    # (``from .client.session import ...``) resolve through sys.modules.
    sys.modules[_SDK_NAME] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(_SDK_NAME, None)
        raise
    return module


if __name__ == _SDK_NAME:
    # Executed as the top-level ``mcp`` package: this directory shadowed the
    # installed SDK. Hand the SDK back to the import machinery.
    _redirect_to_installed_sdk()
else:
    from backend.mcp.store import MCPConnectorStore, mcp_store
    from backend.mcp.templates import MCP_TEMPLATES

    __all__ = ["MCPConnectorStore", "mcp_store", "MCP_TEMPLATES"]
