"""Diagnostic instrumentation for event-loop stalls in the merged gateway.

All six sub-apps share one uvicorn worker. A single synchronous blocking call
therefore freezes every route. The watcher measures sleep drift and, via
faulthandler, dumps the real thread stacks when the loop stops making
progress, so the blocking call can be identified from Render logs.
"""

from __future__ import annotations

import asyncio
import faulthandler
import logging
from contextlib import asynccontextmanager

log = logging.getLogger(__name__)

# Keyed by task id: a watchdog task has its own contextvars context, so a
# module-level registry is used to report which requests were in flight.
_active_requests: dict[int, str] = {}


def request_started(label: str) -> None:
    task = asyncio.current_task()
    if task is not None:
        _active_requests[id(task)] = label


def request_finished() -> None:
    task = asyncio.current_task()
    if task is not None:
        _active_requests.pop(id(task), None)


def active_requests_snapshot() -> list[str]:
    return list(_active_requests.values())


@asynccontextmanager
async def watch_loop(
    *, threshold: float = 1.0, refresh: float = 0.25, dump_stacks: bool = True
):
    """Watch loop responsiveness; log and dump stacks when it stalls."""
    loop = asyncio.get_running_loop()

    async def monitor() -> None:
        last = loop.time()
        while True:
            await asyncio.sleep(refresh)
            now = loop.time()
            lag = now - last - refresh
            last = now
            if dump_stacks:
                # Re-arm on every tick. If the loop cannot tick for 2s,
                # faulthandler prints all thread stacks, including the exact
                # frame that is blocking the main thread.
                faulthandler.cancel_dump_traceback_later()
                faulthandler.dump_traceback_later(timeout=2, repeat=False)
            if lag >= threshold:
                log.warning(
                    "event loop lag %.3fs; active requests: %s",
                    lag,
                    ", ".join(active_requests_snapshot()) or "-",
                )

    task = asyncio.create_task(monitor())
    # Let the monitor take its first reading before the caller runs anything
    # that could block; otherwise a stall immediately after startup is missed.
    await asyncio.sleep(0)
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        if dump_stacks:
            faulthandler.cancel_dump_traceback_later()
