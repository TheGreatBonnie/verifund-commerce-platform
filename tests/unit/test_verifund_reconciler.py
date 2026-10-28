from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from verifund_control_plane.reconciler import Reconciler

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def record(
    transaction_id: str,
    state: str,
    *,
    funding: dict | None = None,
    payout: dict | None = None,
    updated_at: datetime | None = None,
    receipt: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        transaction_id=transaction_id,
        state=state,
        funding=funding,
        payout=payout,
        updated_at=updated_at or NOW,
        receipt=receipt,
        amount_cents=123400,
        deadlines={},
    )


class Repo:
    def __init__(self) -> None:
        self.transactions = {
            "FUNDING_PENDING": [
                record(
                    "vf_funding",
                    "FUNDING_PENDING",
                    funding={"provider_order_id": "ORDER-1"},
                ),
                record("vf_funding_new", "FUNDING_PENDING", funding={"status": "creating"}),
            ],
            "PAYOUT_PENDING": [
                record("vf_payout", "PAYOUT_PENDING", payout={"item_id": "ITEM-1"})
            ],
            "RELEASE_PERMITTED": [
                record("vf_stale", "RELEASE_PERMITTED", updated_at=NOW - timedelta(hours=3))
            ],
            "VERIFICATION_PENDING": [record("vf_verify", "VERIFICATION_PENDING")],
            "RELEASED": [
                record(
                    "vf_released",
                    "RELEASED",
                    payout={"item_id": "ITEM-1"},
                    receipt=None,
                )
            ],
        }
        self.webhooks = [
            {"event_id": "WH-1", "status": "failed", "payload": {"id": "WH-1"}},
            {"event_id": "WH-2", "status": "unmatched", "payload": {"id": "WH-2"}},
        ]
        self.operations = [
            {
                "operation_id": "op_1",
                "transaction_id": "vf_funding_new",
                "kind": "create_order",
                "status": "started",
                "created_at": (NOW - timedelta(minutes=5)).isoformat(),
            }
        ]
        self.runs: list[dict] = []

    async def list_transactions(self, *, state=None, limit=100):
        return list(self.transactions.get(state, []))

    async def list_webhook_events(self, *, status=None, limit=100):
        return [item for item in self.webhooks if item["status"] == status]

    async def list_started_operations(self, limit=100):
        return list(self.operations)

    async def find_started_operation(self, transaction_id, kind):
        for operation in self.operations:
            if (
                operation["transaction_id"] == transaction_id
                and operation["kind"] == kind
            ):
                return operation
        return None

    async def ledger_balances(self, transaction_id):
        return {"held_funds": 0, "platform_cash": 123400, "seller_paid": 123400}

    async def save_reconciler_run(
        self, run_id, started_at, finished_at, stats, error=None
    ):
        self.runs.append(
            {
                "run_id": run_id,
                "started_at": started_at,
                "finished_at": finished_at,
                "stats": stats,
                "error": error,
            }
        )

    async def mark_webhook_event(self, event_id, status, *, last_error=None):
        for item in self.webhooks:
            if item["event_id"] == event_id:
                item["status"] = status

    async def update_provider_operation(self, operation_id, **kwargs):
        for operation in self.operations:
            if operation["operation_id"] == operation_id:
                operation.update(kwargs)


class Service:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.verify_state = "RELEASE_PERMITTED"

    async def refresh_funding(self, transaction_id, *, actor):
        self.calls.append(("refresh_funding", transaction_id))

    async def refresh_payout(self, transaction_id, *, actor):
        self.calls.append(("refresh_payout", transaction_id))

    async def recover_operation(self, operation, *, actor):
        self.calls.append(("recover_operation", operation["operation_id"]))
        return True

    async def verify(self, transaction_id, *, actor):
        self.calls.append(("verify", transaction_id))
        return {"state": self.verify_state}

    async def backfill_receipt(self, transaction_id, *, actor):
        self.calls.append(("backfill_receipt", transaction_id))
        return True


class Settings:
    reconciler_pending_seconds = 30
    payout_alert_hours = 1


async def test_run_once_sweeps_every_domain_and_records_a_run():
    repo = Repo()
    service = Service()
    dispatches: list[dict] = []

    async def dispatch(_service, event):
        dispatches.append(event)
        return "processed"

    reconciler = Reconciler(
        repo=repo,
        service=service,
        settings=Settings(),
        clock=lambda: NOW,
        webhook_dispatch=dispatch,
    )
    stats = await reconciler.run_once()

    assert ("refresh_funding", "vf_funding") in service.calls
    assert ("refresh_payout", "vf_payout") in service.calls
    assert ("verify", "vf_verify") in service.calls
    assert ("backfill_receipt", "vf_released") in service.calls
    assert ("recover_operation", "op_1") in service.calls
    assert [item["id"] for item in dispatches] == ["WH-1", "WH-2"]
    assert stats["stale_release_permitted"] == 1
    assert stats["receipts_backfilled"] == 1
    assert stats["webhooks_retried"] == 2
    assert stats["provider_intents_recovered"] == 1
    assert len(repo.runs) == 1
    assert repo.runs[0]["error"] is None


async def test_one_failing_sweep_does_not_stop_the_others():
    repo = Repo()
    service = Service()

    async def broken_funding(transaction_id, *, actor):
        raise RuntimeError("paypal down")

    service.refresh_funding = broken_funding  # type: ignore[method-assign]

    async def dispatch(_service, event):
        return "processed"

    reconciler = Reconciler(
        repo=repo,
        service=service,
        settings=Settings(),
        clock=lambda: NOW,
        webhook_dispatch=dispatch,
    )
    stats = await reconciler.run_once()

    assert stats["errors"] == 1
    assert stats["webhooks_retried"] == 2
    assert ("refresh_payout", "vf_payout") in service.calls
