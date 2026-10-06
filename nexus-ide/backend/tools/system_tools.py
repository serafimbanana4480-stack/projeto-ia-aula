"""System health tool — aggregate health from all NEXUS subsystems.

Kept as an import-compatibility shim.  Audit P1-7: this module used to hold a
byte-for-byte copy of :mod:`backend.tools.system_health_tool` and register the
same handler a second time under the name ``get_system_health``, while the
other module registered it as ``system_health``.  Two catalog entries for one
behaviour meant the model picked a name at random and the autonomous read-only
allow-list (``registry._AUTONOMOUS_READ_ONLY_TOOLS``) only covered one of them.

There is now exactly **one** registration, owned by
:mod:`backend.tools.system_health_tool`, under the canonical name
``get_system_health``.  This module re-exports the same callable so any
``from backend.tools.system_tools import get_system_health`` keeps working.
"""

from __future__ import annotations

import logging

from backend.tools.system_health_tool import CANONICAL_TOOL_NAME, system_health

logger = logging.getLogger(__name__)

#: Historical name of this module's public callable — same function object as
#: :func:`backend.tools.system_health_tool.system_health`.
get_system_health = system_health

#: The other historical alias of the tool name.
system_health = system_health

__all__ = ["CANONICAL_TOOL_NAME", "get_system_health", "system_health"]
