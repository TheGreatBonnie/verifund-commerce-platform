from __future__ import annotations

import asyncio
import logging
import time

import pytest
from gateway.loop_watch import (
    active_requests_snapshot,
    request_finished,
    request_started,
    watch_loop,
)


@pytest.mark.asyncio
async def test_watch_loop_logs_a_stall_with_the_active_request(caplog):
    request_started("POST /verifund-agent/a2a")
    try:
        with caplog.at_level(logging.WARNING, logger="gateway.loop_watch"):
            async with watch_loop(threshold=0.1, refresh=0.02, dump_stacks=False):
                # Simulate a synchronous blocking call on the event loop,
                # then yield so the watchdog task can record the drift.
                time.sleep(0.25)  # noqa: ASYNC251 - intentionally blocks the loop
                await asyncio.sleep(0.1)
    finally:
        request_finished()

    lag_records = [r for r in caplog.records if "event loop lag" in r.getMessage()]
    assert lag_records, "no lag warning was logged"
    assert "POST /verifund-agent/a2a" in lag_records[0].getMessage()
    assert active_requests_snapshot() == []


@pytest.mark.asyncio
async def test_watch_loop_stays_quiet_when_the_loop_is_responsive(caplog):
    with caplog.at_level(logging.WARNING, logger="gateway.loop_watch"):
        async with watch_loop(threshold=0.5, refresh=0.02, dump_stacks=False):
            await asyncio.sleep(0.1)

    assert [r for r in caplog.records if "event loop lag" in r.getMessage()] == []
