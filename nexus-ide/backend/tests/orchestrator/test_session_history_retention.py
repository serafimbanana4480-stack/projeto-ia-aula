"""Background maintenance must not delete durable execution history."""

from __future__ import annotations

import asyncio
from unittest.mock import Mock

import pytest

from backend.orchestrator.session_lifecycle import SessionLifecycleManager


@pytest.mark.asyncio
async def test_background_session_maintenance_never_prunes_run_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = SessionLifecycleManager()
    completed = asyncio.Event()

    async def inventory(*, allow_destructive: bool = False) -> dict:
        assert not allow_destructive
        completed.set()
        return {}

    prune = Mock()
    monkeypatch.setattr(manager, "run_gc", inventory)
    monkeypatch.setattr(manager, "_maybe_prune_run_state", prune)
    manager.start()
    try:
        await asyncio.wait_for(completed.wait(), timeout=3)
    finally:
        await manager.stop()
    prune.assert_not_called()
