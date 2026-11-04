from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from seller_agent.settlement import SellerSettlementClient, SettlementError
from seller_agent.store import SellerStore

logger = logging.getLogger(__name__)
RETRYABLE_STATUS = {408, 429}
MAX_BACKOFF_SECONDS = 60.0


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class EvidenceOutbox:
    def __init__(
        self,
        store: SellerStore,
        client: SellerSettlementClient,
        *,
        retry_seconds: float = 2.0,
        batch_size: int = 20,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.client = client
        self.retry_seconds = retry_seconds
        self.batch_size = batch_size
        self._clock = clock or (lambda: datetime.now(UTC))
        self._stop = asyncio.Event()
        self._task: asyncio.Task | None = None

    async def enqueue(
        self,
        *,
        transaction_id: str,
        seller_id: str,
        kind: str,
        content: bytes,
        media_type: str,
        filename: str,
        note: str = "",
        captured_at: str | None = None,
        created_at: datetime | None = None,
    ) -> bool:
        return await self.store.enqueue_evidence(
            transaction_id=transaction_id,
            seller_id=seller_id,
            kind=kind,
            content=content,
            media_type=media_type,
            filename=filename,
            note=note,
            captured_at=captured_at,
            created_at=created_at,
        )

    async def run_once(
        self, *, now: datetime | None = None
    ) -> dict[str, int]:
        current = now or self._clock()
        rows = await self.store.list_due_evidence(
            now=_iso(current), limit=self.batch_size
        )
        counts = {"sent": 0, "retried": 0, "failed": 0}
        for row in rows:
            token = await self.store.get_settlement_token(
                row["transaction_id"]
            )
            if not token:
                await self.store.reschedule_evidence(
                    row["evidence_key"],
                    next_attempt_at=_iso(
                        current + timedelta(seconds=self.retry_seconds)
                    ),
                    error="seller token unavailable",
                )
                counts["retried"] += 1
                continue
            try:
                await self.client.upload_evidence(
                    token,
                    row["transaction_id"],
                    kind=row["kind"],
                    content=row["content"],
                    media_type=row["media_type"],
                    filename=row["filename"],
                    note=row["note"],
                    captured_at=row["captured_at"],
                )
            except SettlementError as exc:
                if (
                    exc.status_code in RETRYABLE_STATUS
                    or exc.status_code >= 500
                ):
                    await self._retry(row, current, f"{exc.code}: {exc.message}")
                    counts["retried"] += 1
                else:
                    await self.store.fail_evidence(
                        row["evidence_key"],
                        error=f"evidence upload failed: {exc.code}: {exc.message}",
                    )
                    counts["failed"] += 1
                continue
            except httpx.HTTPError as exc:
                await self._retry(row, current, type(exc).__name__)
                counts["retried"] += 1
                continue
            await self.store.mark_evidence_sent(
                row["evidence_key"], sent_at=_iso(current)
            )
            counts["sent"] += 1
        return counts

    async def _retry(
        self, row: dict[str, Any], current: datetime, error: str
    ) -> None:
        attempt = int(row["attempts"]) + 1
        delay = min(
            self.retry_seconds * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS
        )
        await self.store.reschedule_evidence(
            row["evidence_key"],
            next_attempt_at=_iso(current + timedelta(seconds=delay)),
            error=error,
        )

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._loop(), name="seller-evidence-outbox"
        )

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("seller evidence outbox sweep failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.retry_seconds
                )
            except TimeoutError:
                continue

    async def stop(self) -> None:
        self._stop.set()
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None