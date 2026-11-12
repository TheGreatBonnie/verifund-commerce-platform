from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from a2a.types.a2a_pb2 import Role
from commerce_core.a2a_parts import first_envelope, make_message
from commerce_core.contracts import (
    AcceptOffer,
    ApprovalReceipt,
    Offer,
    OfferLineItem,
    OfferStatus,
    PurchaseOrderRequest,
    ShippingAddress,
)
from commerce_core.extension import wrap_payload
from seller_agent.graph import CommerceProtocolError, accept_offer
from seller_agent.order_service import OrderError, OrderService
from seller_agent.planner import ScriptedSellerPlanner
from seller_agent.service import (
    SellerService,
    settlement_token_from,
    strip_settlement_token,
)
from seller_agent.settlement import SellerSettlementClient
from seller_agent.store import SellerStore
from sqlalchemy.ext.asyncio import create_async_engine

NOW = datetime(2030, 1, 1, 12, 0, tzinfo=UTC)
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
    def __init__(self, projection: dict) -> None:
        self.projection = projection
        self.calls: list[dict] = []

    async def get_transaction(
        self, transaction_id, *, organization_id, seller_id
    ):
        self.calls.append(
            {
                "transaction_id": transaction_id,
                "organization_id": organization_id,
                "seller_id": seller_id,
            }
        )
        return dict(self.projection)


def projection(**overrides):
    value = {
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "state": "AWARDED",
        "seller_id": "northwind-audio",
        "amount_cents": 120000,
        "currency": "USD",
        "agreement_hash": HASH,
        "agreement_version": 1,
        "quantity": 12,
        "line_items": [],
        "delivery_days": 5,
        "warranty_months": 24,
        "returns_days": 30,
        "purchase_order": None,
        "evidence": None,
        "deadlines": {"evidence": None, "inspection": None},
        "allowed_actions": [],
        "updated_at": NOW.isoformat(),
    }
    value.update(overrides)
    return value


def accept() -> AcceptOffer:
    return AcceptOffer(
        offer_id="offer-1",
        round=1,
        accepted_total_cents=120000,
        settlement_transaction_id="vf_1",
        agreement_hash=HASH,
        settlement_token=TOKEN,
    )


def offer() -> Offer:
    return Offer(
        offer_id="offer-1",
        request_id="rfq-1",
        seller_id="northwind-audio",
        seller_name="Northwind Audio",
        seller_rating=4.8,
        line_items=[
            OfferLineItem(
                sku="NC-700",
                name="Nimbus NC-700",
                quantity=12,
                unit_price_cents=10000,
                list_unit_price_cents=12000,
            )
        ],
        subtotal_cents=120000,
        total_cents=120000,
        delivery_days=5,
        warranty_months=24,
        returns_days=30,
        valid_until=NOW + timedelta(days=7),
        status=OfferStatus.FINAL,
    )


def purchase_order() -> PurchaseOrderRequest:
    return PurchaseOrderRequest(
        request_id="po-1",
        run_id="run-1",
        offer_id="offer-1",
        seller_id="northwind-audio",
        quantity=12,
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
        expected_total_cents=120000,
        settlement_transaction_id="vf_1",
        agreement_hash=HASH,
        settlement_token=TOKEN,
    )


def build(store, policy, projection_value=None):
    client = FakeSettlement(projection_value or projection())
    service = SellerService(
        store=store,
        policy=policy,
        planner=ScriptedSellerPlanner(),
        settlement=cast(SellerSettlementClient, client),
        settlement_enabled=True,
        organization_id="org_test",
    )
    return service, client


async def test_handle_turn_keeps_the_token_out_of_graph_state(
    store, northwind_policy
):
    service, _ = build(store, northwind_policy)
    captured: dict = {}

    class Graph:
        async def ainvoke(self, state, config):
            captured["state"] = state
            captured["config"] = config
            return {
                "error": {
                    "code": "invalid_request",
                    "message": "stop",
                    "retryable": False,
                    "details": {},
                }
            }

    service.graph = Graph()
    message = make_message(
        role=Role.ROLE_USER,
        text="Accept the award.",
        context_id="ctx-1",
        envelope=wrap_payload("accept_offer", accept()),
    )

    await service.handle_turn("task-1", "ctx-1", message)

    assert "settlement_token" not in captured["state"]["incoming"]["payload"]
    assert captured["state"]["incoming"]["payload"]["agreement_hash"] == HASH
    assert (
        captured["config"]["configurable"]["settlement_token"] == TOKEN
    )


async def test_redact_message_removes_the_token_from_a2a_history(
    store, northwind_policy
):
    service, _ = build(store, northwind_policy)
    message = make_message(
        role=Role.ROLE_USER,
        text="Accept the award.",
        context_id="ctx-1",
        envelope=wrap_payload("accept_offer", accept()),
    )

    redacted = service.redact_message(message)

    original = first_envelope(message)
    assert original is not None
    assert settlement_token_from(original) == TOKEN
    cleaned = first_envelope(redacted)
    assert cleaned is not None
    assert settlement_token_from(cleaned) is None
    assert cleaned["payload"]["agreement_hash"] == HASH


def test_strip_settlement_token_does_not_mutate_the_source():
    envelope = wrap_payload("accept_offer", accept())
    cleaned = strip_settlement_token(envelope)
    assert "settlement_token" not in cleaned["payload"]
    assert envelope["payload"]["settlement_token"] == TOKEN


async def test_validate_acceptance_binds_the_agreement_and_records_context(
    store, northwind_policy
):
    service, client = build(store, northwind_policy)

    result = await service.validate_acceptance(accept(), token=TOKEN)

    assert result["agreement_hash"] == HASH
    assert client.calls == [
        {
            "transaction_id": "vf_1",
            "organization_id": "org_test",
            "seller_id": "northwind-audio",
        }
    ]
    assert await store.list_settlement_tokens() == [
        {
            "transaction_id": "vf_1",
            "seller_id": "northwind-audio",
            "updated_at": (await store.list_settlement_tokens())[0][
                "updated_at"
            ],
        }
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("state", "FUNDED"),
        ("state", "CANCELED"),
        ("seller_id", "circuitforge"),
        ("agreement_hash", "b" * 64),
        ("amount_cents", 1),
        ("currency", "EUR"),
    ],
)
async def test_validate_acceptance_rejects_bad_bindings(
    store, northwind_policy, field, value
):
    service, _ = build(
        store, northwind_policy, projection(**{field: value})
    )

    with pytest.raises(CommerceProtocolError):
        await service.validate_acceptance(accept(), token=TOKEN)


async def test_validate_acceptance_requires_fields(
    store, northwind_policy
):
    service, _ = build(store, northwind_policy)

    missing = accept().model_copy(update={"agreement_hash": None})
    with pytest.raises(CommerceProtocolError):
        await service.validate_acceptance(missing, token=TOKEN)


async def test_validate_purchase_order_requires_funded_and_records_context(
    store, northwind_policy
):
    service, client = build(
        store, northwind_policy, projection(state="FUNDED")
    )

    result = await service.validate_purchase_order(
        purchase_order(), token=TOKEN
    )

    assert result["state"] == "FUNDED"
    assert client.calls == [
        {
            "transaction_id": "vf_1",
            "organization_id": "org_test",
            "seller_id": "northwind-audio",
        }
    ]
    assert [row["transaction_id"] for row in await store.list_settlement_tokens()] == [
        "vf_1"
    ]


async def test_validate_purchase_order_rejects_an_unfunded_transaction(
    store, northwind_policy
):
    service, _ = build(store, northwind_policy, projection(state="AWARDED"))

    with pytest.raises(CommerceProtocolError):
        await service.validate_purchase_order(
            purchase_order(), token=TOKEN
        )


async def test_accept_offer_node_passes_the_token_from_config(
    store, northwind_policy
):
    service, _ = build(store, northwind_policy)
    await store.save_offer(offer(), task_id="task-1", context_id="ctx-1")

    result = await accept_offer(
        {
            "task_id": "task-1",
            "context_id": "ctx-1",
            "kind": "accept_offer",
            "incoming": strip_settlement_token(
                wrap_payload("accept_offer", accept())
            ),
        },
        {"configurable": {"service": service, "settlement_token": TOKEN}},
    )

    assert result["offer"]["status"] == "accepted"


async def test_order_service_validates_before_reserving_stock(
    store, northwind_policy
):
    await store.set_stock("NC-700", 20, 0)
    await store.save_offer(offer(), task_id="task-1", context_id="ctx-1")
    called: list[str] = []

    async def validator(po):
        called.append(po.idempotency_key)
        raise RuntimeError("transaction is not funded")

    with pytest.raises(OrderError):
        await OrderService(store).create_order(
            purchase_order(), settlement_validator=validator
        )

    assert called == ["run-1:offer-1"]
    assert (await store.get_stock("NC-700")).on_hand == 20


async def test_order_service_skips_validation_for_an_idempotent_retry(
    store, northwind_policy
):
    await store.set_stock("NC-700", 20, 0)
    await store.save_offer(offer(), task_id="task-1", context_id="ctx-1")
    service = OrderService(store)
    first = await service.create_order(purchase_order())

    async def validator(po):
        raise RuntimeError("late validation must not run")

    second = await service.create_order(
        purchase_order(), settlement_validator=validator
    )

    assert second.order_id == first.order_id
    assert (await store.get_stock("NC-700")).on_hand == 8
