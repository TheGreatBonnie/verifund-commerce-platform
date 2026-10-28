from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Callable, Mapping

from verifund_control_plane.domain import TransactionRecord
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.paypal.port import (
    CaptureResult,
    OrderResult,
    PayoutResult,
)
from verifund_control_plane.repository import Repository


class FakePaymentPort:
    def __init__(
        self,
        repo: Repository,
        *,
        scenario: str = "success",
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.repo = repo
        self.scenario = scenario
        self.clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> str:
        return self.clock().astimezone(UTC).isoformat().replace("+00:00", "Z")

    async def create_order(
        self,
        txn: TransactionRecord,
        *,
        return_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> OrderResult:
        if self.scenario == "order_create_failed":
            raise VerifundError(
                "provider_unavailable",
                "fake payment provider is unavailable",
                status_code=503,
                retryable=True,
            )
        order_id = f"FAKE-ORDER-{uuid.uuid4().hex[:16].upper()}"
        async with self.repo.transaction() as conn:
            await self.repo.save_fake_order(
                conn,
                order_id=order_id,
                transaction_id=txn.transaction_id,
                status="CREATED",
                amount_cents=txn.amount_cents,
                currency=txn.currency,
                payer_action_url=return_url,
                raw={"id": order_id, "status": "CREATED"},
            )
        return OrderResult(
            order_id=order_id,
            status="CREATED",
            payer_action_url=return_url,
            raw={"id": order_id, "status": "CREATED"},
        )

    async def capture_order(
        self, order_id: str, *, idempotency_key: str
    ) -> CaptureResult:
        order = await self.repo.get_fake_order(order_id)
        if order.get("capture_id"):
            return self._capture(order)
        if self.scenario == "capture_pending":
            status = "PENDING"
        elif self.scenario == "capture_declined":
            status = "DECLINED"
        else:
            status = "COMPLETED"
        amount = int(order["amount_cents"])
        if self.scenario == "amount_mismatch":
            amount += 100
        capture_id = f"FAKE-CAP-{uuid.uuid4().hex[:16].upper()}"
        async with self.repo.transaction() as conn:
            await self.repo.update_fake_order(
                conn,
                order_id,
                status="COMPLETED" if status == "COMPLETED" else status,
                capture_id=capture_id,
                capture_status=status,
                capture_amount_cents=amount,
                capture_currency=order["currency"],
                raw={"id": capture_id, "status": status, "amount": amount},
            )
        return CaptureResult(
            order_id=order_id,
            capture_id=capture_id,
            status=status,
            amount_cents=amount,
            currency=str(order["currency"]),
            raw={"id": capture_id, "status": status},
        )

    def _capture(self, order: dict[str, Any]) -> CaptureResult:
        return CaptureResult(
            order_id=str(order["order_id"]),
            capture_id=str(order["capture_id"]),
            status=str(order["capture_status"]),
            amount_cents=int(order["capture_amount_cents"]),
            currency=str(order["capture_currency"]),
            raw={"id": order["capture_id"], "status": order["capture_status"]},
        )

    async def get_order(self, order_id: str) -> OrderResult:
        order = await self.repo.get_fake_order(order_id)
        captures = (self._capture(order),) if order.get("capture_id") else ()
        return OrderResult(
            order_id=str(order["order_id"]),
            status=str(order["status"]),
            payer_action_url=order.get("payer_action_url"),
            captures=captures,
            raw=order.get("raw") or {},
        )

    async def create_payout(
        self,
        txn: TransactionRecord,
        *,
        seller_email: str,
        batch_id: str,
        item_id: str,
    ) -> PayoutResult:
        if self.scenario == "payout_failure":
            status = "FAILED"
        elif self.scenario == "payout_pending":
            status = "PENDING"
        else:
            status = "SUCCESS"
        async with self.repo.transaction() as conn:
            await self.repo.upsert_payout_item(
                conn,
                item_id,
                txn.transaction_id,
                batch_id,
                item_id,
                seller_email,
                txn.amount_cents,
                txn.currency,
                status,
                {"payout_item_id": item_id, "transaction_status": status},
            )
        return PayoutResult(
            batch_id=batch_id,
            item_id=item_id,
            status=status,
            amount_cents=txn.amount_cents,
            currency=txn.currency,
            raw={"payout_item_id": item_id, "transaction_status": status},
        )

    async def get_payout_item(self, item_id: str) -> PayoutResult:
        item = await self.repo.get_payout_item(item_id)
        return PayoutResult(
            batch_id=str(item["batch_id"]),
            item_id=str(item["item_id"]),
            status=str(item["status"]),
            amount_cents=int(item["amount_cents"]),
            currency=str(item["currency"]),
            raw=item.get("raw") or {},
        )

    async def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes
    ) -> bool:
        raise VerifundError(
            "forbidden",
            "fake webhooks use the test header, not PayPal verification",
            status_code=400,
        )