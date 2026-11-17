"""The provider and model of the agent that is currently calling a tool.

``consult_agent`` used to build a fresh client from the process default,
which on this project is a local endpoint that is often not running. The
consultation has to use the same provider the calling bot already reached.
"""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any

_client: ContextVar[Any] = ContextVar("nexus_caller_llm_client", default=None)
_model: ContextVar[str] = ContextVar("nexus_caller_llm_model", default="")


def bind_caller_llm(client: Any, model: str = "") -> None:
    """Remember the client and model for tools invoked on this task."""
    _client.set(client)
    _model.set(str(model or "").strip())


def current_caller_llm() -> tuple[Any, str]:
    """Return ``(client, model)``. The client is None when nothing bound one."""
    return _client.get(), _model.get()
