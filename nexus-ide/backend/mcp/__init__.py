"""NEXUS IDE — MCP (Model Context Protocol) connector subsystem.

Gives the IDE a first-class way to register, test, and export MCP server
connections (filesystem, GitHub, Postgres, Slack, etc.) without hand-editing
JSON config files. See ``backend/mcp/templates.py`` for the built-in catalog
and ``backend/mcp/store.py`` for the persistent connector store.
"""

from backend.mcp.store import MCPConnectorStore, mcp_store
from backend.mcp.templates import MCP_TEMPLATES

__all__ = ["MCPConnectorStore", "mcp_store", "MCP_TEMPLATES"]
