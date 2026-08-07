"""Safe hand-over of the process-wide LLM client after runtime settings change.

The Settings endpoint can replace a client without restarting the backend.  A
chat stream captures its client at the beginning of the request, therefore an
old client must remain open until that stream finishes.  These small helpers
track that reference count and close retired clients deterministically.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _active_clients(app: Any) -> dict[int, tuple[Any, int]]:
    active = getattr(app.state, "llm_active_clients", None)
    if active is None:
        active = {}
        app.state.llm_active_clients = active
    return active


def _retired_clients(app: Any) -> dict[int, Any]:
    retired = getattr(app.state, "retired_llm_clients", None)
    if retired is None:
        retired = {}
        app.state.retired_llm_clients = retired
    return retired


def acquire_llm_client(app: Any, client: Any) -> None:
    """Record that an SSE chat stream is using *client*."""
    if client is None:
        return
    active = _active_clients(app)
    client_id = id(client)
    existing = active.get(client_id)
    active[client_id] = (client, (existing[1] if existing else 0) + 1)


async def _close_client(client: Any) -> None:
    close = getattr(client, "aclose", None)
    if not callable(close):
        return
    try:
        await close()
    except Exception as exc:  # noqa: BLE001 - cleanup must not break a response
        logger.warning("Failed to close retired LLM client: %s", exc)


async def retire_llm_client(app: Any, client: Any) -> None:
    """Close *client* now, or after the final stream using it completes."""
    if client is None:
        return
    active = _active_clients(app)
    client_id = id(client)
    if active.get(client_id, (None, 0))[1] > 0:
        _retired_clients(app)[client_id] = client
        return
    await _close_client(client)


async def release_llm_client(app: Any, client: Any) -> None:
    """Release a chat stream's reference and clean up a retired client."""
    if client is None:
        return
    active = _active_clients(app)
    client_id = id(client)
    existing = active.get(client_id)
    if existing is None:
        return
    if existing[1] > 1:
        active[client_id] = (client, existing[1] - 1)
        return
    active.pop(client_id, None)
    retired = _retired_clients(app)
    retired_client = retired.pop(client_id, None)
    if retired_client is not None:
        await _close_client(retired_client)


async def close_all_llm_clients(app: Any) -> None:
    """Close current, active, and retired clients during application shutdown."""
    clients: dict[int, Any] = {}
    current = getattr(app.state, "llm_client", None)
    if current is not None:
        clients[id(current)] = current
    clients.update({client_id: client for client_id, (client, _) in _active_clients(app).items()})
    clients.update(_retired_clients(app))
    _active_clients(app).clear()
    _retired_clients(app).clear()
    for client in clients.values():
        await _close_client(client)
