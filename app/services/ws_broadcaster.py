"""WebSocket event broadcaster — singleton event bus.

Maintains a set of asyncio Queue subscribers. Any async component (e.g. the
scheduler) can call ``publish()`` to fan-out an event to all connected
WebSocket clients without knowing anything about FastAPI or the WS layer.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.core.logging import get_logger

log = get_logger(__name__)


class EventBroadcaster:
    """Fan-out event bus backed by per-client asyncio Queues.

    All methods are designed to be called from the FastAPI event loop.
    Do *not* call ``publish`` from a plain thread — use
    ``asyncio.get_event_loop().call_soon_threadsafe`` if needed.
    """

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    @property
    def subscriber_count(self) -> int:
        """Return the number of currently connected WebSocket clients."""
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """Register a new subscriber and return its event queue.

        Returns:
            An asyncio Queue that will receive all future published events.
        """
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=200)
        self._subscribers.add(q)
        log.debug("ws_subscriber_added", total=len(self._subscribers))
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        """Remove a subscriber queue (call on WebSocket disconnect).

        Args:
            q: The queue previously returned by :meth:`subscribe`.
        """
        self._subscribers.discard(q)
        log.debug("ws_subscriber_removed", total=len(self._subscribers))

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        """Broadcast an event to every connected subscriber.

        Slow consumers whose queue is full are silently dropped to prevent
        back-pressure from one laggy client from stalling the scheduler.

        Args:
            event_type: Short identifier (e.g. ``"trade_opened"``).
            payload: Arbitrary JSON-serialisable dict attached to the event.
        """
        if not self._subscribers:
            return
        event: dict[str, Any] = {"type": event_type, "data": payload}
        dead: list[asyncio.Queue[dict[str, Any]]] = []
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)
        if dead:
            log.warning("ws_slow_consumers_dropped", dropped=len(dead))


# ---- module-level singleton ----------------------------------------------
_broadcaster: EventBroadcaster = EventBroadcaster()


def get_broadcaster() -> EventBroadcaster:
    """Return the module-level :class:`EventBroadcaster` singleton.

    Returns:
        The shared broadcaster instance.
    """
    return _broadcaster
