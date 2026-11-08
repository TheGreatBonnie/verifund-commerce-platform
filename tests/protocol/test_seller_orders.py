from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from commerce_core.contracts import (
    ApprovalReceipt,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
    PurchaseOrderRequest,
    ShippingAddress,
)
from commerce_core.pricing import load_policy

from tests.support.a2a import send_purchase_order

POLICY_PATH = Path(
    "docs/templates/northwind.yaml"
)
PRODUCT_SKU = "MM-WIRELESS-HEADPHONES"
QUANTITY = 12


def product_policy():
    return load_policy(POLICY_PATH).for_product(PRODUCT_SKU)


def build_offer(*, valid_until: datetime, suffix: str) -> Offer:
    policy = product_policy()
    quote = policy.quote(
        QUANTITY,
        policy.initial_unit_price_cents,
        policy.base_warranty_months,
    )
    line_item = OfferLineItem(
        sku=policy.sku,
        name=policy.product_name,
        quantity=QUANTITY,
        unit_price_cents=quote.base_unit_price_cents,
        list_unit_price_cents=policy.list_unit_price_cents,
        warranty_addon_cents=quote.warranty_addon_cents,
        attributes={"color": policy.color},
    )
    return Offer(
        offer_id=f"offer-{suffix}",
        request_id="rfq-order",
        seller_id=policy.seller_id,
        seller_name=policy.name,
        seller_rating=policy.rating,
        task_id="negotiation-task",
        context_id="run-1",
        line_items=[line_item],
        subtotal_cents=quote.subtotal_cents,
        shipping_cents=0,
        total_cents=quote.total_cents,
        delivery_days=quote.delivery_days,
        warranty_months=quote.warranty_months,
        returns_days=policy.returns_days,
        valid_until=valid_until,
        terms=OfferTerms(
            sustainability_certified=policy.sustainability_certified,
            stock_confidence=quote.stock_confidence,
            split_shipment=quote.split_shipment,
        ),
        status=OfferStatus.FINAL,
        round=3,
        rationale="Order test offer.",
    )


@pytest.fixture
async def accepted_offer(seller_session) -> dict:
    offer = build_offer(
        valid_until=datetime.now(UTC) + timedelta(minutes=30),
        suffix="accepted",
    )
    await seller_session.store.save_offer(
        offer, task_id="negotiation-task", context_id="run-1"
    )
    return offer.model_dump(mode="json")


@pytest.fixture
async def expired_offer(seller_session) -> dict:
    offer = build_offer(
        valid_until=datetime.now(UTC) - timedelta(minutes=1),
        suffix="expired",
    )
    await seller_session.store.save_offer(
        offer, task_id="negotiation-task", context_id="run-1"
    )
    return offer.model_dump(mode="json")


def make_purchase_order(offer: dict, idempotency_key: str) -> PurchaseOrderRequest:
    return PurchaseOrderRequest(
        request_id=f"po-{idempotency_key}",
        run_id="run-1",
        offer_id=offer["offer_id"],
        seller_id=offer["seller_id"],
        quantity=QUANTITY,
        shipping_address=ShippingAddress(
            name="Demo Buyer",
            line1="1 Market Street",
            city="San Francisco",
            region="CA",
            postal_code="94105",
            country="US",
        ),
        approval=ApprovalReceipt(
            approval_id="approval-1",
            approved_by="demo-human",
            approved_at=datetime.now(UTC),
            note="Approved for the hackathon demo.",
        ),
        idempotency_key=idempotency_key,
        expected_total_cents=offer["total_cents"],
    )


async def test_order_is_created_once(seller_session, accepted_offer):
    po = make_purchase_order(accepted_offer, idempotency_key="idem-1")
    first = await send_purchase_order(seller_session, po)
    second = await send_purchase_order(seller_session, po)
    assert first["order_id"] == second["order_id"]
    assert first["status"] == "confirmed"
    assert first["total_cents"] == accepted_offer["total_cents"]


async def test_duplicate_does_not_double_reserve(
    seller_session, accepted_offer
):
    po = make_purchase_order(accepted_offer, idempotency_key="idem-2")
    await send_purchase_order(seller_session, po)
    await send_purchase_order(seller_session, po)
    stock = await seller_session.store.get_stock(PRODUCT_SKU)
    assert stock.on_hand == product_policy().stock_on_hand - QUANTITY


async def test_expired_offer_is_rejected(seller_session, expired_offer):
    response = await send_purchase_order(
        seller_session,
        make_purchase_order(expired_offer, idempotency_key="idem-3"),
    )
    assert response["code"] == "offer_expired"
    assert response["retryable"] is False


async def test_out_of_stock_returns_retryable_error(
    seller_session, accepted_offer
):
    await seller_session.store.set_stock(PRODUCT_SKU, 0, 0)
    response = await send_purchase_order(
        seller_session,
        make_purchase_order(accepted_offer, idempotency_key="idem-4"),
    )
    assert response["code"] == "out_of_stock"
    assert response["retryable"] is True
