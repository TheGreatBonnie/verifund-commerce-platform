from __future__ import annotations

import asyncio

import pytest
from buyer_agent.server import run_registry_poller


class Registry:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    async def refresh_registry(self) -> bool:
        self.calls += 1
        return self.calls > self.failures


async def test_poller_retries_until_the_registry_answers():
    registry = Registry(failures=2)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        if registry.calls >= 3:
            raise asyncio.CancelledError
        slept.append(seconds)

    with pytest.raises(asyncio.CancelledError):
        await run_registry_poller(registry, poll_interval=30.0, sleep=sleep)
    assert registry.calls == 3
    assert slept == [1.0, 2.0]


async def test_poller_settles_into_the_poll_interval_once_answered():
    registry = Registry(failures=0)
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        if len(slept) >= 2:
            raise asyncio.CancelledError
        slept.append(seconds)

    with pytest.raises(asyncio.CancelledError):
        await run_registry_poller(registry, poll_interval=30.0, sleep=sleep)
    assert slept == [30.0, 30.0]
