"""
realtime.py - tiny in-process publish/subscribe used for live updates (Server-Sent Events).

Every endpoint that changes data calls `bus.publish(["doctors", ...])` after committing. All connected browsers
receive {"entities": [...]} and re-fetch just those lists through the normal (permission-checked) API - so no
patient data ever travels over the event stream itself.

NOTE: this is in-memory, so run ONE server process (the Dockerfile does). For several processes/servers swap the
Bus for Redis pub/sub - the rest of the code would not change.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Iterable, Optional

log = logging.getLogger("helix.realtime")


class Bus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def bind(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def publish(self, entities: Iterable[str]) -> None:
        """Thread-safe: may be called from sync endpoint handlers running in the thread pool."""
        msg = json.dumps({"entities": sorted(set(entities))})
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._fanout, msg)
        except RuntimeError:                                  # loop shutting down
            pass

    def _fanout(self, msg: str) -> None:
        for q in list(self._subs):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:                         # slow client: drop; it also polls as a fallback
                pass

    @property
    def listeners(self) -> int:
        return len(self._subs)


bus = Bus()
