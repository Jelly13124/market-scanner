"""Tests for ScanBroadcaster pub/sub.

Each test wraps its async coroutine in ``asyncio.run`` so we don't depend on
pytest-asyncio. The broadcaster bridges sync worker threads (publish) to
async generators (subscribe); these tests exercise both sides.
"""

from __future__ import annotations

import asyncio
import threading

from app.backend.services.scan_broadcaster import ScanBroadcaster


async def _drain(gen, target_count: int, timeout: float = 2.0):
    """Read up to *target_count* events with a short timeout. Returns list of events."""
    events: list = []

    async def _collect():
        async for event in gen:
            events.append(event)
            if len(events) >= target_count:
                return

    try:
        await asyncio.wait_for(_collect(), timeout=timeout)
    except asyncio.TimeoutError:
        pass
    return events


def test_publish_from_main_thread_delivers_to_subscriber():
    async def scenario():
        b = ScanBroadcaster()
        gen = b.subscribe(1)

        async def producer():
            await asyncio.sleep(0.01)
            b.publish(1, {"event": "progress", "processed": 1})
            b.publish(1, {"event": "complete"})
            b.close(1)

        task = asyncio.create_task(producer())
        events = await _drain(gen, target_count=2)
        await task
        assert [e["event"] for e in events] == ["progress", "complete"]

    asyncio.run(scenario())


def test_publish_from_worker_thread():
    async def scenario():
        b = ScanBroadcaster()
        gen = b.subscribe(7)

        started = threading.Event()

        def worker():
            started.set()
            b.publish(7, {"event": "progress", "processed": 1})
            b.publish(7, {"event": "progress", "processed": 2})
            b.close(7)

        t = threading.Thread(target=worker, daemon=True)
        # Tiny delay so subscribe registers before publish fires.
        async def kickoff():
            await asyncio.sleep(0.01)
            t.start()

        asyncio.create_task(kickoff())
        events = await _drain(gen, target_count=2)
        started.wait(timeout=1.0)
        t.join(timeout=1.0)
        assert len(events) == 2
        assert events[0]["processed"] == 1
        assert events[1]["processed"] == 2

    asyncio.run(scenario())


def test_multiple_subscribers_each_get_events():
    async def scenario():
        b = ScanBroadcaster()
        g1 = b.subscribe(42)
        g2 = b.subscribe(42)

        async def producer():
            # Subscribers register lazily on first __anext__, so wait long
            # enough that both drainers in gather() below have entered their
            # await q.get() before we publish.
            await asyncio.sleep(0.05)
            b.publish(42, {"n": 1})
            b.close(42)

        # gather() runs both drainers concurrently so both subscribers register
        # before the producer fires.
        producer_task = asyncio.create_task(producer())
        e1, e2 = await asyncio.gather(
            _drain(g1, target_count=1),
            _drain(g2, target_count=1),
        )
        await producer_task
        assert e1 == [{"n": 1}]
        assert e2 == [{"n": 1}]

    asyncio.run(scenario())


def test_publish_to_unsubscribed_run_is_noop():
    async def scenario():
        b = ScanBroadcaster()
        # No subscriber on run_id=99 — must not raise.
        b.publish(99, {"event": "noop"})
        b.close(99)

    asyncio.run(scenario())


def test_subscriber_cleanup_after_close():
    async def scenario():
        b = ScanBroadcaster()
        gen = b.subscribe(5)

        async def stop():
            await asyncio.sleep(0.01)
            b.close(5)

        asyncio.create_task(stop())
        events = await _drain(gen, target_count=10)
        assert events == []
        # Internal subscriber map should have removed run_id=5.
        assert 5 not in b._subs

    asyncio.run(scenario())
