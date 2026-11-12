import pytest
import pytest_asyncio
from commerce_core.contracts import Fulfillment, Offer, OfferLineItem, Order
from seller_agent.shared_schema import configure_shared_engine, create_shared_schema
from seller_agent.shared_store import OrgScopedStore
from sqlalchemy.ext.asyncio import create_async_engine


def make_line_item() -> OfferLineItem:
    return OfferLineItem(
        sku="SKU-1", name="Widget", quantity=1,
        unit_price_cents=100, list_unit_price_cents=120,
    )


def make_offer(offer_id: str = "o1") -> Offer:
    return Offer(
        offer_id=offer_id, request_id="req-1", seller_id="seller-a",
        seller_name="Seller A", seller_rating=4.5,
        line_items=[make_line_item()], subtotal_cents=100, total_cents=100,
        delivery_days=1, warranty_months=0, returns_days=0,
        valid_until="2030-01-01T00:00:00Z",
    )


def make_order(order_id: str = "ord-1") -> Order:
    return Order(
        order_id=order_id, offer_id="o1", seller_id="seller-a",
        quantity=1, total_cents=100, line_items=[make_line_item()],
        reserved_at="2026-01-01T00:00:00Z", eta="2026-01-05T00:00:00Z",
        tracking_number="TRK1",
        fulfillment=Fulfillment(carrier="c", status="reserved"),
    )


@pytest_asyncio.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await configure_shared_engine(engine)
    await create_shared_schema(engine)
    yield engine
    await engine.dispose()


async def test_inventory_is_org_scoped(engine):
    a = OrgScopedStore(engine, organization_id="org-a", agent_id="agent-a")
    b = OrgScopedStore(engine, organization_id="org-b", agent_id="agent-b")

    await a.set_stock("SKU-1", 10, 0, None)
    assert (await a.get_stock("SKU-1")).on_hand == 10
    assert (await b.get_stock("SKU-1")).on_hand == 0

    assert await a.reserve("SKU-1", 2, allow_split=False) == {
        "split_shipment": False,
        "on_hand": 8,
    }
    assert (await a.get_stock("SKU-1")).on_hand == 8
    assert (await b.get_stock("SKU-1")).on_hand == 0


async def test_reserve_splits_when_allowed(engine):
    a = OrgScopedStore(engine, organization_id="org-a")
    await a.set_stock("SKU-1", 2, 5, 3)
    assert await a.reserve("SKU-1", 4, allow_split=True) == {
        "split_shipment": True,
        "on_hand": 0,
    }


async def test_reserve_rejects_unknown_sku(engine):
    a = OrgScopedStore(engine, organization_id="org-a")
    with pytest.raises(ValueError):
        await a.reserve("missing", 1, allow_split=False)


async def test_offers_are_org_scoped(engine):
    a = OrgScopedStore(engine, organization_id="org-a")
    b = OrgScopedStore(engine, organization_id="org-b")
    await a.save_offer(make_offer(), task_id="t1", context_id="c1")
    assert (await a.get_offer("o1")).offer_id == "o1"
    assert await b.get_offer("o1") is None
    assert [row["offer"]["offer_id"] for row in await a.list_offers()] == ["o1"]
    assert await b.list_offers() == []


async def test_settlement_tokens_are_org_scoped(engine):
    a = OrgScopedStore(engine, organization_id="org-a")
    b = OrgScopedStore(engine, organization_id="org-b")
    await a.save_settlement_token("tx-1", "seller-a", "token-a")
    assert await a.get_settlement_token("tx-1") == "token-a"
    assert await b.get_settlement_token("tx-1") is None
    assert len(await a.list_settlement_tokens()) == 1
    assert await b.list_settlement_tokens() == []


async def test_evidence_outbox_is_org_scoped(engine):
    a = OrgScopedStore(engine, organization_id="org-a")
    b = OrgScopedStore(engine, organization_id="org-b")
    inserted = await a.enqueue_evidence(
        transaction_id="tx-1",
        seller_id="seller-a",
        kind="receipt",
        content=b"hello",
        media_type="text/plain",
        filename="receipt.txt",
    )
    assert inserted is True
    duplicate = await a.enqueue_evidence(
        transaction_id="tx-1",
        seller_id="seller-a",
        kind="receipt",
        content=b"hello",
        media_type="text/plain",
        filename="receipt.txt",
    )
    assert duplicate is False

    row = await a.get_evidence_outbox("tx-1", "receipt")
    assert row is not None and row["evidence_key"] == row["outbox_id"]
    assert await b.get_evidence_outbox("tx-1", "receipt") is None

    due = await a.list_due_evidence(now="2999-01-01T00:00:00Z")
    assert len(due) == 1
    assert await b.list_due_evidence(now="2999-01-01T00:00:00Z") == []

    await a.mark_evidence_sent(row["evidence_key"], sent_at="2026-01-01T00:00:00Z")
    assert await a.list_due_evidence(now="2999-01-01T00:00:00Z") == []


async def test_evidence_reschedule_and_fail_are_org_scoped(engine):
    a = OrgScopedStore(engine, organization_id="org-a")
    b = OrgScopedStore(engine, organization_id="org-b")
    await a.enqueue_evidence(
        transaction_id="tx-1",
        seller_id="seller-a",
        kind="receipt",
        content=b"hello",
        media_type="text/plain",
        filename="receipt.txt",
    )
    row = await a.get_evidence_outbox("tx-1", "receipt")
    assert row is not None
    key = row["evidence_key"]
    await a.reschedule_evidence(key, next_attempt_at="2026-01-01T00:00:00Z",
                                error="boom")
    rescheduled = await a.get_evidence_outbox("tx-1", "receipt")
    assert rescheduled is not None
    assert rescheduled["attempts"] == 1
    await a.fail_evidence(key, error="fatal")
    failed = await a.get_evidence_outbox("tx-1", "receipt")
    assert failed is not None
    assert failed["status"] == "failed"
    # other org cannot mutate the row
    await b.fail_evidence(key, error="other")
    final = await a.get_evidence_outbox("tx-1", "receipt")
    assert final is not None
    assert final["last_error"] == "fatal"


async def test_orders_are_org_scoped(engine):
    a = OrgScopedStore(engine, organization_id="org-a", agent_id="agent-a")
    b = OrgScopedStore(engine, organization_id="org-b", agent_id="agent-b")
    await a.save_order(make_order(), idempotency_key="idem-1")
    order = await a.get_order_by_idempotency("idem-1")
    assert order is not None
    assert order.order_id == "ord-1"
    assert await b.get_order_by_idempotency("idem-1") is None
    assert len(await a.list_orders()) == 1
    assert await b.list_orders() == []


async def test_transaction_is_org_scoped(engine):
    a = OrgScopedStore(engine, organization_id="org-a")
    b = OrgScopedStore(engine, organization_id="org-b")
    await a.save_offer(make_offer(), task_id="t1", context_id="c1")
    await a.set_stock("SKU-1", 5, 0, None)
    async with a.transaction() as tx:
        assert (await tx.get_offer("o1")).offer_id == "o1"
        assert await tx.get_order_by_idempotency("missing") is None
        reservation = await tx.reserve("SKU-1", 2, allow_split=False)
        assert reservation.split_shipment is False
    assert (await a.get_stock("SKU-1")).on_hand == 3
    async with b.transaction() as tx:
        assert await tx.get_offer("o1") is None
        with pytest.raises(ValueError):
            await tx.reserve("SKU-1", 1, allow_split=False)


async def test_create_schema_and_seed_catalog_are_noops(engine, northwind_policy):
    store = OrgScopedStore(engine, organization_id="org-a", agent_id="agent-a")
    assert await store.create_schema() is None
    assert await store.seed_catalog(northwind_policy) is None
