"""SSE fan-out for reload notifications."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any


class EventHub:
    def __init__(self, limit: int = 200):
        self._subscribers: list[asyncio.Queue] = []
        self.limit = limit
        self.recent: list[dict[str, Any]] = []

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        self._subscribers.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

    def count(self) -> int:
        return len(self._subscribers)

    def publish(self, name: str, data: dict[str, Any] | None = None) -> None:
        event = {"name": name, "data": data or {}, "at": time.time()}
        self.recent.append(event)
        self.recent = self.recent[-self.limit:]
        for queue in list(self._subscribers):
            try:
                queue.put_nowait(event)
            except (asyncio.QueueFull, RuntimeError):
                pass

    async def publish_async(self, name: str, data: dict[str, Any] | None = None) -> None:
        self.publish(name, data)

    def dump(self) -> str:
        return json.dumps(self.recent, ensure_ascii=False)
