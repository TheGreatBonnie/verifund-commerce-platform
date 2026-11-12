from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from commerce_core.contracts import (
    CommerceErrorCode,
    Fulfillment,
    Offer,
    OfferStatus,
    Order,
    OrderStatus,
    PurchaseOrderRequest,
)

from seller_agent.store import SellerStore

SettlementValidator = Callable[[PurchaseOrderRequest], Awaitable[None]]


class OrderError(Exception):
    def __init__(
        self,
        code: CommerceErrorCode,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def _is_expired(valid_until: datetime, now: datetime) -> bool:
    if valid_until.tzinfo is None:
        valid_until = valid_until.replace(tzinfo=UTC)
    return valid_until <= now


class OrderService:
    def __init__(self, store: SellerStore) -> None:
        self.store = store

    def _validate(self, po: PurchaseOrderRequest, offer: Offer) -> None:
        if offer.seller_id != po.seller_id:
            raise OrderError(
                CommerceErrorCode.INVALID_REQUEST,
                "Offer seller does not match purchase order.",
            )
        if offer.status not in {OfferStatus.FINAL, OfferStatus.ACCEPTED}:
            raise OrderError(
                CommerceErrorCode.INVALID_REQUEST,
                "Offer is not final or accepted.",
            )
        if po.expected_total_cents != offer.total_cents:
            raise OrderError(
                CommerceErrorCode.INVALID_REQUEST,
                "Expected total does not match the offer.",
            )
        if po.quantity != sum(item.quantity for item in offer.line_items):
            raise OrderError(
                CommerceErrorCode.INVALID_REQUEST,
                "Purchase quantity does not match the offer.",
            )
        if not po.approval.approved_by.strip():
            raise OrderError(
                CommerceErrorCode.INVALID_REQUEST,
                "Human approval is required.",
            )
        if _is_expired(offer.valid_until, datetime.now(UTC)):
            raise OrderError(
                CommerceErrorCode.OFFER_EXPIRED,
                "Offer has expired.",
            )

    async def create_order(
        self,
        po: PurchaseOrderRequest,
        *,
        settlement_validator: SettlementValidator | None = None,
    ) -> Order:
        now = datetime.now(UTC)
        async with self.store.transaction() as tx:
            existing = await tx.get_order_by_idempotency(po.idempotency_key)
            if existing is not None:
                return existing
            offer = await tx.get_offer(po.offer_id)
            if offer is None:
                raise OrderError(
                    CommerceErrorCode.INVALID_REQUEST, "Offer not found."
                )
            self._validate(po, offer)
            if settlement_validator is not None:
                try:
                    await settlement_validator(po)
                except OrderError:
                    raise
                except Exception as exc:
                    raise OrderError(
                        CommerceErrorCode.CONFLICT,
                        str(exc) or "Settlement validation failed.",
                    ) from exc
            try:
                reservation = await tx.reserve(
                    offer.line_items[0].sku,
                    po.quantity,
                    allow_split=offer.terms.split_shipment,
                )
            except ValueError as exc:
                raise OrderError(
                    CommerceErrorCode.OUT_OF_STOCK,
                    "Insufficient stock for this offer.",
                    retryable=True,
                ) from exc
            eta = now + timedelta(days=offer.delivery_days)
            order = Order(
                order_id=f"MM-{uuid.uuid4().hex[:10].upper()}",
                offer_id=offer.offer_id,
                seller_id=offer.seller_id,
                status=OrderStatus.CONFIRMED,
                currency=offer.currency,
                quantity=po.quantity,
                total_cents=offer.total_cents,
                line_items=offer.line_items,
                reserved_at=now,
                eta=eta,
                tracking_number=f"MMTRK{uuid.uuid4().hex[:12].upper()}",
                fulfillment=Fulfillment(
                    carrier="MarketMesh Logistics",
                    status="reserved"
                    if not reservation.split_shipment
                    else "partially_reserved",
                ),
            )
            await tx.save_order(order, idempotency_key=po.idempotency_key)
            return order
