from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from commerce_core.contracts import (
    ApprovalReceipt,
    Fulfillment,
    OfferLineItem,
    Order,
    OrderStatus,
    PurchaseOrderRequest,
    ShippingAddress,
)
from seller_agent.planner import ScriptedSellerPlanner
from seller_agent.service import SellerService
from seller_agent.settlement import SettlementError
from seller_agent.store import SellerStore
from sqlalchemy.ext.asyncio import create_async_engine

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64
TOKEN = "v1.secret"


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'seller.db'}"
    )
    value = SellerStore(engine)
    await value.create_schema()
    yield value
    await engine.dispose()


class FakeSettlement:
    def __init__(
        self, projection: dict | None = None, error: Exception | None = None
    ) -> None:
        self.projection = projection
        self.error = error

    async def get_transaction(self, token, transaction_id):
        if self.error is not None:
            raise self.error
        assert self.projection is not None
        return dict(self.projection)


def order() -> Order:
    return Order(
        order_id="MM-DEMO",
        offer_id="offer-1",
        seller_id="northwind-audio",
        status=OrderStatus.CONFIRMED,
        quantity=2,
        total_cents=20000,
        line_items=[
            OfferLineItem(
                sku="NC-700",
                name="Nimbus NC-700",
                quantity=2,
                unit_price_cents=10000,
                list_unit_price_cents=12000,
            )
        ],
        reserved_at=NOW,
        eta=NOW + timedelta(days=5),
        tracking_number="TRK-1",
        fulfillment=Fulfillment(
            carrier="Northwind Logistics", status="reserved"
        ),
    )


def purchase_order() -> PurchaseOrderRequest:
    return PurchaseOrderRequest(
        request_id="po-1",
        run_id="run-1",
        offer_id="offer-1",
        seller_id="northwind-audio",
        quantity=2,
        shipping_address=ShippingAddress(
            name="Demo Buyer",
            line1="1 Market Street",
            city="San Francisco",
            region="CA",
            postal_code="94105",
            country="US",
        ),
        approval=ApprovalReceipt(
            approval_id="apr-1",
            approved_by="Demo Buyer",
            approved_at=NOW,
        ),
        idempotency_key="run-1:offer-1",
        expected_total_cents=20000,
        settlement_transaction_id="vf_1",
        agreement_hash=HASH,
        settlement_token=TOKEN,
    )


def projection(**overrides):
    value = {
        "transaction_id": "vf_1",
        "state": "FUNDED",
        "seller_id": "northwind-audio",
        "amount_cents": 20000,
        "currency": "USD",
        "agreement_hash": HASH,
        "deadlines": {"evidence": None, "inspection": None},
        "evidence": None,
        "purchase_order": None,
        "updated_at": NOW.isoformat(),
    }
    value.update(overrides)
    return value


def build(store, policy, *, settlement=None):
    return SellerService(
        store=store,
        policy=policy,
        planner=ScriptedSellerPlanner(),
        settlement=settlement,
        settlement_enabled=True,
    )


async def test_settlement_status_omits_tokens_and_reports_state(
    store, northwind_policy
):
    await store.save_settlement_token("vf_1", "northwind-audio", TOKEN)
    settlement = FakeSettlement(projection())
    service = build(store, northwind_policy, settlement=settlement)

    rows = await service.settlement_status()

    assert rows[0]["transaction_id"] == "vf_1"
    assert rows[0]["state"] == "FUNDED"
    assert rows[0]["unavailable"] is False
    assert TOKEN not in json.dumps(rows)


async def test_settlement_status_degrades_when_the_control_plane_is_down(
    store, northwind_policy
):
    await store.save_settlement_token("vf_1", "northwind-audio", TOKEN)
    settlement = FakeSettlement(
        error=SettlementError("provider_unavailable", "down", status_code=503)
    )
    service = build(store, northwind_policy, settlement=settlement)

    rows = await service.settlement_status()

    assert rows[0]["transaction_id"] == "vf_1"
    assert rows[0]["state"] == "unavailable"
    assert rows[0]["unavailable"] is True
    assert TOKEN not in json.dumps(rows)


async def test_list_settlement_tokens_never_returns_the_token(
    store, northwind_policy
):
    await store.save_settlement_token("vf_1", "northwind-audio", TOKEN)

    rows = await store.list_settlement_tokens()

    assert rows == [
        {
            "transaction_id": "vf_1",
            "seller_id": "northwind-audio",
            "updated_at": rows[0]["updated_at"],
        }
    ]
    assert "token" not in rows[0]
