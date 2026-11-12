from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from seller_agent.evidence_outbox import EvidenceOutbox
from seller_agent.settlement import SellerSettlementClient
from seller_agent.shared_store import OrgScopedStore

logger = logging.getLogger(__name__)


class SharedEvidenceSweeper:
    """Run the evidence outbox once per active organization/seller.

    The store is rebuilt for each seller on each pass so an evidence query can
    never cross organization boundaries.
    """

    def __init__(
        self,
        engine: AsyncEngine,
        settlement: SellerSettlementClient,
        *,
        interval_seconds: float = 2.0,
        retry_seconds: float = 2.0,
        batch_size: int = 20,
    ) -> None:
        self.engine = engine
        self.settlement = settlement
        self.interval_seconds = interval_seconds
        self.retry_seconds = retry_seconds
        self.batch_size = batch_size
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    async def _active_sellers(self) -> list[dict]:
        async with self.engine.connect() as conn:
            rows = (await conn.execute(text(
                "SELECT agent_id, organization_id FROM seller_configs "
                "WHERE status = 'active'"
            ))).all()
        return [dict(row._mapping) for row in rows]

    async def run_once(self) -> dict[str, int]:
        total = {"sent": 0, "retried": 0, "failed": 0}
        for row in await self._active_sellers():
            store = OrgScopedStore(
                self.engine,
                organization_id=row["organization_id"],
                agent_id=row["agent_id"],
            )
            outbox = EvidenceOutbox(
                store,
                self.settlement,
                retry_seconds=self.retry_seconds,
                batch_size=self.batch_size,
            )
            try:
                counts = await outbox.run_once()
            except Exception:
                logger.exception(
                    "evidence sweep failed for %s/%s",
                    row["organization_id"], row["agent_id"])
                continue
            for key, value in counts.items():
                total[key] += value
        return total

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("shared evidence sweep pass failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.interval_seconds)
            except TimeoutError:
                continue
