"""In-process publish/subscribe."""

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any


class EventBus:
    """Delivers JSON-serializable payloads to every current subscriber of a topic.

    Delivery is fire-and-forget: publishing never blocks, and a payload published
    while nobody is subscribed is dropped.
    """

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Enqueue ``payload`` on every queue subscribed to ``topic``."""
        for queue in tuple(self._subscribers.get(topic, ())):
            queue.put_nowait(payload)

    @asynccontextmanager
    async def subscription(self, topic: str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        """Yield a queue that receives payloads published to ``topic`` until exit."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers[topic].add(queue)
        try:
            yield queue
        finally:
            self._subscribers[topic].discard(queue)
            if not self._subscribers[topic]:
                del self._subscribers[topic]
