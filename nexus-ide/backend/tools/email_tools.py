"""Email tool wrappers for agent use."""

from __future__ import annotations

import json
import logging
from typing import Any

from backend.tools.email_client import fetch_emails as _fetch_emails
from backend.tools.email_client import search_emails as _search_emails
from backend.tools.registry import ToolSpec, register_tool

logger = logging.getLogger(__name__)


def _parse_config(config_json: str | dict) -> dict[str, Any]:
    """Parse email configuration from JSON string or dict."""
    if isinstance(config_json, str):
        return json.loads(config_json)
    return dict(config_json)


async def check_inbox(
    config_json: str | dict,
    limit: int = 10,
    unread_only: bool = False,
) -> dict[str, Any]:
    """Check inbox using stored email configuration.

    Args:
        config_json: JSON string or dict with keys:
            host, port, username, password, use_ssl (optional), folder (optional).
        limit: Maximum emails to retrieve.
        unread_only: Only fetch unread emails.

    Returns:
        Dict with count and emails list.
    """
    config = _parse_config(config_json)
    emails = _fetch_emails(
        folder=config.get("folder", "INBOX"),
        limit=limit,
        unread_only=unread_only,
        host=config["host"],
        port=config["port"],
        username=config["username"],
        password=config["password"],
        use_ssl=config.get("use_ssl", True),
    )
    return {
        "count": len(emails),
        "emails": emails,
    }


async def search_emails_tool(
    query: str,
    config_json: str | dict,
    limit: int = 10,
) -> dict[str, Any]:
    """Search emails by query using stored configuration.

    Args:
        query: Search query string.
        config_json: JSON string or dict with email credentials.
        limit: Maximum results.

    Returns:
        Dict with count and matching emails list.
    """
    config = _parse_config(config_json)
    results = _search_emails(
        query=query,
        folder=config.get("folder", "INBOX"),
        limit=limit,
        host=config["host"],
        port=config["port"],
        username=config["username"],
        password=config["password"],
        use_ssl=config.get("use_ssl", True),
    )
    return {
        "count": len(results),
        "emails": results,
    }


async def summarize_inbox(
    limit: int = 10,
    config_json: str | None = None,
) -> dict[str, Any]:
    """Return a summary of recent emails.

    Args:
        limit: Maximum emails to summarize.
        config_json: Optional JSON string or dict with email credentials.
            If omitted, a note is returned.

    Returns:
        Dict with summary fields.
    """
    if not config_json:
        return {
            "note": "Provide config_json to retrieve and summarize emails.",
            "limit": limit,
        }

    config = _parse_config(config_json)
    emails = _fetch_emails(
        folder=config.get("folder", "INBOX"),
        limit=limit,
        unread_only=False,
        host=config["host"],
        port=config["port"],
        username=config["username"],
        password=config["password"],
        use_ssl=config.get("use_ssl", True),
    )

    unread_count = sum(1 for e in emails if e.get("unread"))
    return {
        "count": len(emails),
        "unread_count": unread_count,
        "subjects": [e["subject"] for e in emails],
        "senders": list({e["from"] for e in emails}),
        "emails": emails,
    }


register_tool(
    ToolSpec(
        name="check_inbox",
        description="Check email inbox and return recent emails using IMAP configuration.",
        schema={
            "type": "object",
            "properties": {
                "config_json": {
                    "type": "string",
                    "description": "JSON string with host, port, username, password, use_ssl, folder",
                },
                "limit": {"type": "integer", "default": 10},
                "unread_only": {"type": "boolean", "default": False},
            },
            "required": ["config_json"],
        },
        handler=check_inbox,
    )
)

register_tool(
    ToolSpec(
        name="search_emails",
        description="Search emails by subject or body using IMAP configuration.",
        schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query string"},
                "config_json": {
                    "type": "string",
                    "description": "JSON string with host, port, username, password, use_ssl, folder",
                },
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["query", "config_json"],
        },
        handler=search_emails_tool,
    )
)

register_tool(
    ToolSpec(
        name="summarize_inbox",
        description="Return a summary of recent emails (subjects, senders, unread count).",
        schema={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "default": 10},
                "config_json": {
                    "type": "string",
                    "description": "Optional JSON string with host, port, username, password, use_ssl, folder",
                },
            },
        },
        handler=summarize_inbox,
    )
)
