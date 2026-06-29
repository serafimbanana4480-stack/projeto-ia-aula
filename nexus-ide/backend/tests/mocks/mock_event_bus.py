"""Mock EventBus for testing."""
from __future__ import annotations

from typing import Any, Callable
from dataclasses import dataclass


@dataclass
class MockEvent:
    """Mock event."""
    type: str
    agent: str | None = None
    payload: dict[str, Any] | None = None


class MockEventBus:
    """Mock EventBus for testing."""
    
    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._events: list[MockEvent] = []
    
    async def publish(self, event: MockEvent) -> None:
        """Publish an event to the bus."""
        self._events.append(event)
        # Notify subscribers
        event_type = event.type
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                try:
                    if callable(callback):
                        import asyncio
                        if asyncio.iscoroutinefunction(callback):
                            await callback(event)
                        else:
                            callback(event)
                except Exception:
                    pass  # Ignore errors in callbacks
    
    def subscribe(self, event_type: str, callback: Callable) -> None:
        """Subscribe to events of a specific type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
    
    def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Unsubscribe from events of a specific type."""
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                cb for cb in self._subscribers[event_type] if cb != callback
            ]
    
    def get_events(self) -> list[MockEvent]:
        """Get all published events."""
        return self._events.copy()
    
    def clear_events(self) -> None:
        """Clear all published events."""
        self._events.clear()
    
    async def close(self) -> None:
        """Close the event bus."""
        self._subscribers.clear()
