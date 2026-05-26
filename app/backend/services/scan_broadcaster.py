"""Thread-safe pub/sub for scanner progress events.

The scanner runner pushes events from worker threads via ``publish()``.
FastAPI SSE routes consume via the ``subscribe()`` async generator. The
broadcaster bridges the two using ``loop.call_soon_threadsafe`` so that
``asyncio.Queue.put_nowait`` is always invoked on the loop that owns each
subscriber.

Multiple subscribers per run_id are supported (e.g. user reloads the page).
``close(run_id)`` signals end-of-stream to all subscribers for that run.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import AsyncIterator

logger = logging.getLogger(__name__)


class ScanBroadcaster:
    """Process-local fan-out of scanner progress events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # run_id -> list of (event_loop, queue) pairs, one per active subscriber
        self._subs: dict[int, list[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}

    def publish(self, run_id: int, event: dict) -> None:
        """Send *event* to every subscriber on *run_id*. Thread-safe.

        Safe to call from any thread. Subscribers whose event loop has been
        closed are silently skipped.
        """
        with self._lock:
            subscribers = list(self._subs.get(run_id, []))
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, event)
            except RuntimeError as e:
                logger.debug("Dropping event for closed loop on run %s: %s", run_id, e)

    def close(self, run_id: int) -> None:
        """Signal end-of-stream to all subscribers on *run_id*."""
        with self._lock:
            subscribers = list(self._subs.get(run_id, []))
        for loop, queue in subscribers:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, None)
            except RuntimeError:
                pass

    async def subscribe(self, run_id: int) -> AsyncIterator[dict]:
        """Async generator yielding events for *run_id* until end-of-stream."""
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        with self._lock:
            self._subs.setdefault(run_id, []).append((loop, q))
        try:
            while True:
                event = await q.get()
                if event is None:
                    return
                yield event
        finally:
            with self._lock:
                remaining = [
                    (l, qq) for (l, qq) in self._subs.get(run_id, []) if qq is not q
                ]
                if remaining:
                    self._subs[run_id] = remaining
                else:
                    self._subs.pop(run_id, None)


# Process-wide singleton — services / routes share it.
_broadcaster = ScanBroadcaster()


def get_broadcaster() -> ScanBroadcaster:
    return _broadcaster
