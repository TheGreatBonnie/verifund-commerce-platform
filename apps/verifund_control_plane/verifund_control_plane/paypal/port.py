from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from verifund_control_plane.domain import TransactionRecord


@dataclass(frozen=True)
class CaptureResult:
    order_id: str
    capture_id: str
    status: str
    amount_cents: int
    currency: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrderResult:
    order_id: str
    status: str
    payer_action_url: str | None = None
    captures: tuple[CaptureResult, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PayoutResult:
    batch_id: str
    item_id: str
    status: str
    amount_cents: int
    currency: str
    raw: dict[str, Any] = field(default_factory=dict)


class PaymentPort(Protocol):
    async def create_order(
        self,
        txn: TransactionRecord,
        *,
        return_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> OrderResult: ...

    async def capture_order(
        self, order_id: str, *, idempotency_key: str
    ) -> CaptureResult: ...

    async def get_order(self, order_id: str) -> OrderResult: ...

    async def create_payout(
        self,
        txn: TransactionRecord,
        *,
        seller_email: str,
        batch_id: str,
        item_id: str,
    ) -> PayoutResult: ...

    async def get_payout_item(self, item_id: str) -> PayoutResult: ...

    async def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes
    ) -> bool: ...