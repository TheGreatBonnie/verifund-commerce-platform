from __future__ import annotations

import asyncio
from collections import defaultdict


class SettlementCoordinator:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def lock(self, run_id: str) -> asyncio.Lock:
        return self._locks[run_id]

    def is_locked(self, run_id: str) -> bool:
        return self._locks[run_id].locked()