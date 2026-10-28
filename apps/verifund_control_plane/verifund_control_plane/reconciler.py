from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Awaitable, Callable

from verifund_control_plane.paypal.webhooks import dispatch as default_dispatch
from verifund_control_plane.service import VerifundService
from verifund_control_plane.settings import Settings


class Reconciler:
    def __init__(
        self,
        *,
        repo: Any,
        service: VerifundService,
        settings: Settings,
        clock: Callable[[], datetime],
        webhook_dispatch: Callable[[Any, dict[str, Any]], Awaitable[str]] | None = None,
    ) -> None:
        self.repo = repo
        self.service = service
        self.settings = settings
        self.clock = clock
        self.webhook_dispatch = webhook_dispatch or default_dispatch
        self._task: asyncio.Task | None = None

    def _now(self) -> datetime:
        return self.clock().astimezone(UTC)

    async def _safe(self, stats: dict[str, int], operation: Awaitable[None]) -> None:
        try:
            await operation
        except Exception:  # noqa: BLE001
            stats["errors"] += 1

    def _new_stats(self) -> dict[str, int]:
        return {
            "errors": 0,
            "funding_checked": 0,
            "payouts_checked": 0,
            "deadlines_checked": 0,
            "deadline_reviews": 0,
            "stale_release_permitted": 0,
            "webhooks_retried": 0,
            "receipts_backfilled": 0,
            "ledger_mismatches": 0,
            "provider_intents_started": 0,
            "provider_intents_recovered": 0,
        }

    async def run_once(self) -> dict[str, int]:
        run_id = f"rec_{uuid.uuid4().hex}"
        started_at = self._now()
        stats = self._new_stats()
        self._recovered_this_run: set[str] = set()
        error: str | None = None
        try:
            await self._safe(stats, self._sweep_funding(stats))
            await self._safe(stats, self._sweep_payouts(stats))
            await self._safe(stats, self._sweep_deadlines(stats))
            await self._safe(stats, self._sweep_release_permitted(stats))
            await self._safe(stats, self._sweep_webhooks(stats))
            await self._safe(stats, self._sweep_receipts(stats))
            await self._safe(stats, self._sweep_ledger(stats))
            await self._safe(stats, self._sweep_provider_intents(stats))
        except Exception as exc:  # noqa: BLE001
            error = type(exc).__name__
            raise
        finally:
            await self.repo.save_reconciler_run(
                run_id, started_at, self._now(), stats, error
            )
        return stats

    async def _sweep_funding(self, stats: dict[str, int]) -> None:
        for record in await self.repo.list_transactions(state="FUNDING_PENDING"):
            funding = record.funding or {}
            if funding.get("provider_order_id"):
                await self.service.refresh_funding(
                    record.transaction_id, actor="reconciler"
                )
                stats["funding_checked"] += 1
                continue
            operation = await self.repo.find_started_operation(
                record.transaction_id, "create_order"
            )
            if operation is not None and await self.service.recover_operation(
                operation, actor="reconciler"
            ):
                stats["provider_intents_recovered"] += 1
                self._recovered_this_run.add(
                    str(operation.get("operation_id"))
                )

    async def _sweep_payouts(self, stats: dict[str, int]) -> None:
        for record in await self.repo.list_transactions(state="PAYOUT_PENDING"):
            await self.service.refresh_payout(
                record.transaction_id, actor="reconciler"
            )
            stats["payouts_checked"] += 1

    async def _sweep_deadlines(self, stats: dict[str, int]) -> None:
        for record in await self.repo.list_transactions(
            state="VERIFICATION_PENDING"
        ):
            projection = await self.service.verify(
                record.transaction_id, actor="reconciler"
            )
            stats["deadlines_checked"] += 1
            if projection.get("state") == "REVIEW_REQUIRED":
                stats["deadline_reviews"] += 1

    async def _sweep_release_permitted(self, stats: dict[str, int]) -> None:
        cutoff = self._now() - timedelta(
            hours=self.settings.payout_alert_hours
        )
        for record in await self.repo.list_transactions(
            state="RELEASE_PERMITTED"
        ):
            if record.updated_at.astimezone(UTC) < cutoff:
                stats["stale_release_permitted"] += 1

    async def _sweep_webhooks(self, stats: dict[str, int]) -> None:
        seen: set[str] = set()
        for status in ("failed", "unmatched", "pending"):
            for event in await self.repo.list_webhook_events(status=status):
                if event["event_id"] in seen:
                    continue
                seen.add(event["event_id"])
                try:
                    outcome = await self.webhook_dispatch(
                        self.service, event["payload"]
                    )
                except Exception:  # noqa: BLE001
                    stats["errors"] += 1
                    continue
                await self.repo.mark_webhook_event(
                    event["event_id"], outcome
                )
                stats["webhooks_retried"] += 1

    async def _sweep_receipts(self, stats: dict[str, int]) -> None:
        for record in await self.repo.list_transactions(state="RELEASED"):
            if await self.service.backfill_receipt(
                record.transaction_id, actor="reconciler"
            ):
                stats["receipts_backfilled"] += 1

    async def _sweep_ledger(self, stats: dict[str, int]) -> None:
        for record in await self.repo.list_transactions(state="RELEASED"):
            balances = await self.repo.ledger_balances(record.transaction_id)
            if (
                balances.get("held_funds", 0) != 0
                or balances.get("seller_paid", 0) != record.amount_cents
            ):
                stats["ledger_mismatches"] += 1

    async def _sweep_provider_intents(self, stats: dict[str, int]) -> None:
        cutoff = self._now() - timedelta(
            seconds=self.settings.reconciler_pending_seconds
        )
        for operation in await self.repo.list_started_operations():
            if str(operation.get("operation_id")) in getattr(
                self, "_recovered_this_run", set()
            ):
                continue
            started_at = operation.get("created_at")
            if started_at is not None:
                try:
                    parsed = datetime.fromisoformat(
                        str(started_at).replace("Z", "+00:00")
                    )
                except ValueError:
                    parsed = None
                if parsed is not None and parsed.astimezone(UTC) >= cutoff:
                    continue
            stats["provider_intents_started"] += 1
            if await self.service.recover_operation(
                operation, actor="reconciler"
            ):
                stats["provider_intents_recovered"] += 1
                continue
            await self.repo.update_provider_operation(
                str(operation["operation_id"]),
                status="failed",
                last_error="abandoned after crash",
                increment_attempts=True,
            )

    async def _loop(self) -> None:
        while True:
            await self.run_once()
            await asyncio.sleep(self.settings.reconciler_interval_seconds)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None