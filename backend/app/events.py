"""Ereignis-Bus für Live-Updates in der Oberfläche (Server-Sent Events).

Worker laufen in eigenen Threads, die Oberfläche hängt am Event-Loop.
publish() ist deshalb bewusst thread-sicher.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

log = logging.getLogger(__name__)

MAX_QUEUE = 200


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def publish(self, event_type: str, **data: Any) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        payload = {"type": event_type, **data}
        try:
            loop.call_soon_threadsafe(self._dispatch, payload)
        except RuntimeError:  # Loop gerade beendet
            pass

    def _dispatch(self, payload: dict[str, Any]) -> None:
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Langsamer Client: ältestes Ereignis verwerfen
                try:
                    queue.get_nowait()
                    queue.put_nowait(payload)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


bus = EventBus()
