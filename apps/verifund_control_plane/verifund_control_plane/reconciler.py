from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from verifund_control_plane.paypal.webhooks import dispatch as default_dispatch
from verifund_control_plane.tenancy.identity import SYSTEM_IDENTITY


class ReconcilerService(Protocol):
    async def refresh_funding(
        self, transaction_id: str, *, actor: str
    ) -> Any: ...

    async def refresh_payout(
        self, transaction_id: str, *, actor: str
    ) -> Any: ...

    async def recover_operation(
        self, operation: dict[str, Any], *, actor: str
    ) -> bool: ...

    async def verify(
        self, transaction_id: str, *, actor: str
    ) -> dict[str, Any]: ...

    async def backfill_receipt(
        self, transaction_id: str, *, actor: str
    ) -> bool: ...

    async def cancel(
        self,
        transaction_id: str,
        request: Any,
        *,
        actor: str,
        idempotency_key: str | None,
    ) -> dict[str, Any]: ...

    async def refresh_tracker(self, transaction_id: str) -> Any: ...


class ReconcilerSettings(Protocol):
    @property
    def reconciler_pending_seconds(self) -> int: ...

    @property
    def payout_alert_hours(self) -> int: ...

    @property
    def reconciler_interval_seconds(self) -> int: ...


class Reconciler:
    def __init__(
        self,
        *,
        repo: Any,
        service: ReconcilerService,
        settings: ReconcilerSettings,
        clock: Callable[[], datetime],
        webhook_dispatch: Callable[[Any, dict[str, Any]], Awaitable[str]] | None = None,
        scanner: Any = None,
        tenancy: Any = None,
    ) -> None:
        self.repo = repo
        self.tenancy = tenancy
        self.service = service
        self.settings = settings
        self.clock = clock
        self.webhook_dispatch = webhook_dispatch or default_dispatch
        self.scanner = scanner if scanner is not None else FakeScanner()
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
            "deemed_released": 0,
            "webhooks_retried": 0,
            "receipts_backfilled": 0,
            "ledger_mismatches": 0,
            "provider_intents_started": 0,
            "provider_intents_recovered": 0,
            "trackers_refreshed": 0,
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
            await self._safe(stats, self._sweep_trackers(stats))
            await self._safe(stats, self._sweep_deadlines(stats))
            await self._safe(stats, self._sweep_scans(stats))
            await self._safe(stats, self._sweep_remediation(stats))
            await self._safe(stats, self._sweep_release_permitted(stats))
            await self._safe(stats, self._sweep_deemed_acceptance(stats))
            await self._safe(stats, self._sweep_webhooks(stats))
            await self._safe(stats, self._sweep_receipts(stats))
            await self._safe(stats, self._sweep_ledger(stats))
            await self._safe(stats, self._sweep_provider_intents(stats))
            await self._safe(stats, self._sweep_agreements(stats))
        except Exception as exc:
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
            if self.tenancy is not None:
                profile = await self.tenancy.get_seller_profile(record.seller_id)
                seller_org_id = record.seller_organization_id or (
                    profile["organization_id"] if profile else None
                )
                seller_active = (
                    profile is not None
                    and profile["verification_status"] == "verified"
                    and seller_org_id is not None
                    and (await self.tenancy.get_organization(seller_org_id) or {}).get(
                        "status"
                    )
                    == "active"
                )
                release = (
                    await self.tenancy.get_payout_release(
                        record.transaction_id, seller_org_id
                    )
                    if seller_org_id
                    else None
                )
                if not seller_active and release is None:
                    stats["payouts_held"] = stats.get("payouts_held", 0) + 1
                    try:
                        await self.tenancy.record_audit(
                            scope="system",
                            organization_id=seller_org_id,
                            transaction_id=record.transaction_id,
                            actor_user_id=SYSTEM_IDENTITY.user_id,
                            actor_type="system",
                            action="payout_hold_seller_suspended",
                            resource_id=record.transaction_id,
                            payload={},
                        )
                    except Exception:  # noqa: BLE001,S110 - per-record tolerance is deliberate
                        pass
                    continue
                    continue
            await self.service.refresh_payout(
                record.transaction_id, actor="reconciler"
            )
            stats["payouts_checked"] += 1

    async def _sweep_trackers(self, stats: dict[str, int]) -> None:
        if not hasattr(self.service, "refresh_tracker"):
            return
        for record in await self.repo.list_transactions():
            if not (record.tracker or {}).get("tracker_id"):
                continue
            try:
                await self.service.refresh_tracker(record.transaction_id)
            except Exception:  # noqa: BLE001 - tracker refresh is best-effort
                stats["errors"] += 1
                continue
            stats["trackers_refreshed"] += 1

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

    async def _sweep_remediation(self, stats: dict[str, int]) -> None:
        from verifund_contracts import TransactionState

        from verifund_control_plane.repository import AuditInput

        now = self._now()
        for record in await self.repo.list_transactions(state="REMEDIATION_REQUIRED"):
            deadlines = record.deadlines or {}
            raw = deadlines.get("remediation") or deadlines.get("inspection")
            if raw is None:
                continue
            try:
                deadline = datetime.fromisoformat(str(raw))
            except (TypeError, ValueError):
                continue
            if now < deadline:
                continue
            async with self.repo.transaction() as conn:
                current = await self.repo.get_transaction(record.transaction_id, conn)
                if current.state != TransactionState.REMEDIATION_REQUIRED:
                    continue
                await self.repo.transition(
                    conn,
                    record.transaction_id,
                    expected_version=current.version,
                    expected_state=current.state,
                    new_state=TransactionState.REVIEW_REQUIRED,
                    changes={},
                    audit=AuditInput("reconciler", "remediation_deadline_missed"),
                )
            stats["deadline_reviews"] += 1

    async def _sweep_scans(self, stats: dict[str, int]) -> None:
        if not hasattr(self.service, "verify") or not hasattr(
            self.repo, "update_evidence_scan_status"
        ):
            return
        from verifund_contracts import TransactionState

        from verifund_control_plane.repository import AuditInput

        now = self._now()
        timeout = timedelta(
            minutes=getattr(self.settings, "scan_pending_timeout_minutes", 60)
        )
        for record in await self.repo.list_transactions(state="VERIFICATION_PENDING"):
            items = await self.repo.list_evidence(record.transaction_id)
            pending = [i for i in items if getattr(i, "scan_status", None) == "pending"]
            if not pending:
                continue
            changed = False
            for item in pending:
                created = getattr(item, "created_at", None)
                try:
                    created_dt = (
                        created if isinstance(created, datetime) else datetime.fromisoformat(str(created))
                    )
                except (TypeError, ValueError):
                    created_dt = now
                if now - created_dt.astimezone(UTC) > timeout:
                    async with self.repo.transaction() as conn:
                        current = await self.repo.get_transaction(record.transaction_id, conn)
                        if current.state == TransactionState.VERIFICATION_PENDING:
                            await self.repo.transition(
                                conn,
                                record.transaction_id,
                                expected_version=current.version,
                                expected_state=current.state,
                                new_state=TransactionState.REVIEW_REQUIRED,
                                changes={},
                                audit=AuditInput("reconciler", "pending_scan_timeout"),
                            )
                    stats["deadline_reviews"] += 1
                    changed = False
                    break
                try:
                    result = await self.scanner.scan(item)
                except Exception:  # noqa: BLE001, S112
                    continue
                if result in {"clean", "rejected"}:
                    async with self.repo.transaction() as conn:
                        await self.repo.update_evidence_scan_status(
                            conn, item.evidence_id, result
                        )
                    changed = True
            if changed:
                try:
                    await self.service.verify(record.transaction_id, actor="reconciler")
                except Exception:  # noqa: BLE001
                    stats["errors"] += 1

    async def _sweep_release_permitted(self, stats: dict[str, int]) -> None:
        cutoff = self._now() - timedelta(
            hours=self.settings.payout_alert_hours
        )
        for record in await self.repo.list_transactions(
            state="RELEASE_PERMITTED"
        ):
            if record.updated_at.astimezone(UTC) < cutoff:
                stats["stale_release_permitted"] += 1

    async def _sweep_deemed_acceptance(self, stats: dict[str, int]) -> None:
        if not hasattr(self.service, "release") or not hasattr(
            self.service, "_agreement_terms"
        ):
            return
        from verifund_contracts import ReleaseRequest

        now = self._now()
        for record in await self.repo.list_transactions(state="RELEASE_PERMITTED"):
            verification = record.verification or {}
            requirements = verification.get("requirements") or []
            if requirements and not all(
                (req.get("status") == "pass") for req in requirements
            ):
                continue
            deadlines = record.deadlines or {}
            inspection_raw = deadlines.get("inspection")
            if inspection_raw is None:
                inspection_raw = verification.get("inspection_deadline")
            try:
                inspection = (
                    datetime.fromisoformat(str(inspection_raw))
                    if inspection_raw is not None
                    else now
                )
            except (TypeError, ValueError):
                inspection = now
            dispute_hours = 0
            try:
                terms = await self.service._agreement_terms(record.transaction_id)
                if isinstance(terms, dict):
                    dispute_hours = int(
                        terms.get("dispute_window_hours") or 0
                    )
            except Exception:  # noqa: BLE001
                dispute_hours = 0
            deadline = inspection + timedelta(hours=dispute_hours)
            if now < deadline:
                continue
            try:
                await self.service.release(
                    record.transaction_id,
                    ReleaseRequest(
                        released_by="reconciler", note="deemed acceptance", override=False
                    ),
                    actor="reconciler",
                )
                stats["deemed_released"] += 1
            except Exception:  # noqa: BLE001
                stats["errors"] += 1

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

    async def _sweep_agreements(self, stats: dict[str, int]) -> None:
        from verifund_contracts import CancelReason, CancelRequest, TransactionState
        svc = self.service
        agreement_service = getattr(svc, "agreement_service", None)
        if agreement_service is None:
            return
        now = self._now()
        expired = await agreement_service.expire_due(now)
        for aid in expired:
            agr = await agreement_service.get(aid)
            if agr is None:
                continue
            txn_id = getattr(agr, "transaction_id", None)
            if not txn_id:
                continue
            try:
                record = await self.repo.get_transaction(txn_id)
            except Exception:  # noqa: BLE001, S112
                continue
            if record.state in {
                TransactionState.FUNDED, TransactionState.REVIEW_REQUIRED,
                TransactionState.CANCELED,
            }:
                continue
            try:
                await svc.cancel(
                    txn_id,
                    CancelRequest(reason_code=CancelReason.AGREEMENT_EXPIRED),
                    actor="reconciler",
                    idempotency_key=f"expire:{aid}",
                )
            except Exception:  # noqa: BLE001
                stats["errors"] = stats.get("errors", 0) + 1
                continue
            stats["deadlines_checked"] = stats.get("deadlines_checked", 0) + 1
        # Funding-expiry termination: agreements AGREED whose funding deadline passed.
        for record in await self.repo.list_transactions(state="AGREED"):
            deadline_raw = (record.deadlines or {}).get("funding")
            if not deadline_raw:
                continue
            try:
                deadline = datetime.fromisoformat(str(deadline_raw))
            except ValueError:
                continue
            if now <= deadline:
                continue
            agreement = await agreement_service.get_by_transaction(record.transaction_id)
            if agreement is None or agreement.status.value != "AGREED":
                continue
            try:
                async with self.repo.transaction() as conn:
                    await agreement_service.terminate(
                        conn, agreement.agreement_id, reason="funding_expired", now=now
                    )
            except Exception:  # noqa: BLE001, S110
                pass

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
                        str(started_at)
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

class FakeScanner:
    """Default scan provider: marks every pending item clean."""

    async def scan(self, item: Any) -> str:
        return "clean"
