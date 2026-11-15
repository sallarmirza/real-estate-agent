"""SSE stream that pushes live dashboard data to the browser.

Flow: Redis event → mark dirty → throttle loop recomputes → push to all tabs.
"""
from __future__ import annotations
import asyncio
import json
import os
import redis.asyncio as aioredis
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from .dashboard_router import fetch_stats, fetch_leads, fetch_engagement
from .dashboard_events import CHANNEL, REDIS_URL

router = APIRouter(prefix="/estate")

THROTTLE_SECONDS = 2
KEEPALIVE_SECONDS = 15


class DashboardHub:
    def __init__(self) -> None:
        self.clients: set[asyncio.Queue] = set()
        self.dirty: bool = False

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1)
        self.clients.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.clients.discard(q)

    def mark_dirty(self) -> None:
        self.dirty = True

    def push(self, payload: str) -> None:
        for q in self.clients:
            if q.full():
                q.get_nowait()
            q.put_nowait(payload)


hub = DashboardHub()
_tasks: list[asyncio.Task] = []


def _build_payload() -> str:
    data = {
        "stats": fetch_stats(),
        "engagement": fetch_engagement(),
        "leads": fetch_leads(limit=20),
    }
    return json.dumps(jsonable_encoder(data))


async def _listen_redis() -> None:
    while True:
        r = aioredis.from_url(REDIS_URL, protocol=2)
        try:
            pubsub = r.pubsub()
            await pubsub.subscribe(CHANNEL)
            async for msg in pubsub.listen():
                if msg["type"] == "message":
                    hub.mark_dirty()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("dashboard listener error, retrying - error=%s", e)
            await asyncio.sleep(3)
        finally:
            await r.aclose()


async def _broadcast_loop() -> None:
    while True:
        await asyncio.sleep(THROTTLE_SECONDS)
        if not hub.dirty or not hub.clients:
            continue
        hub.dirty = False
        try:
            payload = await run_in_threadpool(_build_payload)
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning("dashboard recompute failed - error=%s", e)
            continue
        hub.push(payload)


async def start_dashboard_stream() -> None:
    _tasks.append(asyncio.create_task(_listen_redis()))
    _tasks.append(asyncio.create_task(_broadcast_loop()))


async def stop_dashboard_stream() -> None:
    for t in _tasks:
        t.cancel()
    await asyncio.gather(*_tasks, return_exceptions=True)
    _tasks.clear()


@router.get("/dashboard/stream")
async def dashboard_stream(request: Request):
    """SSE: pushes the full dashboard payload whenever any lead data changes."""
    queue = hub.subscribe()

    async def event_gen():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=KEEPALIVE_SECONDS)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            hub.unsubscribe(queue)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
