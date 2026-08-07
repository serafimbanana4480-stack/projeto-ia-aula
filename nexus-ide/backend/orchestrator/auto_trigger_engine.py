"""Auto Trigger Engine — event-driven automatic cycle triggering.

Listens to Agent Bus events and triggers improvement cycles automatically
when critical conditions are detected:
- errors.found with severity=critical
- test.results with pass_rate < threshold
- agent.status with failed state
- quality_gate.failed
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from backend.core.agent_bus import BusMessage, get_agent_bus

logger = logging.getLogger(__name__)


class AutoTriggerEngine:
    """Event-driven trigger for autonomous improvement cycles."""

    TRIGGER_RULES = [
        {
            "topic": "errors.found",
            "condition": lambda payload: payload.get("severity") == "critical",
            "cooldown_seconds": 300,
            "priority": "critical",
        },
        {
            "topic": "test.results",
            "condition": lambda payload: payload.get("pass_rate", 1.0) < 0.9,
            "cooldown_seconds": 600,
            "priority": "high",
        },
        {
            "topic": "agent.status",
            "condition": lambda payload: payload.get("status") == "failed",
            "cooldown_seconds": 120,
            "priority": "high",
        },
        {
            "topic": "quality_gate.failed",
            "condition": lambda payload: True,
            "cooldown_seconds": 180,
            "priority": "critical",
        },
    ]

    def __init__(self, orchestrator: Any) -> None:
        self.orchestrator = orchestrator
        self._running = False
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._last_triggered: dict[str, datetime] = {}

    async def start(self) -> None:
        if self._running:
            logger.warning("AutoTriggerEngine already running")
            return
        self._running = True
        self._stop_event.clear()
        self._task = asyncio.create_task(self._listen(), name="auto-trigger-engine")
        logger.info("AutoTriggerEngine started (listening to %d rules)", len(self.TRIGGER_RULES))

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._stop_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            with asyncio.suppress(asyncio.CancelledError):
                await self._task
        logger.info("AutoTriggerEngine stopped")

    async def _listen(self) -> None:
        bus = get_agent_bus()
        try:
            for rule in self.TRIGGER_RULES:
                await bus.subscribe(rule["topic"], self._on_event)
        except Exception:
            logger.exception("AutoTriggerEngine subscription failed")

    async def _on_event(self, message: BusMessage) -> None:
        topic = message.topic
        payload = message.payload or {}
        for rule in self.TRIGGER_RULES:
            if rule["topic"] != topic:
                continue
            if not rule["condition"](payload):
                continue
            if not self._cooldown_elapsed(topic, rule["cooldown_seconds"]):
                logger.debug("Trigger %s skipped (cooldown active)", topic)
                return
            self._last_triggered[topic] = datetime.now(UTC)
            logger.info(
                "Auto-trigger fired | topic=%s priority=%s payload=%s",
                topic,
                rule["priority"],
                payload,
            )
            try:
                await self.orchestrator.run_cycle()
            except Exception:
                logger.exception("Auto-triggered cycle failed")

    def _cooldown_elapsed(self, topic: str, cooldown_seconds: int) -> bool:
        last = self._last_triggered.get(topic)
        if last is None:
            return True
        elapsed = (datetime.now(UTC) - last).total_seconds()
        return elapsed >= cooldown_seconds
