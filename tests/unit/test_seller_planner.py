from datetime import UTC, datetime, timedelta

from commerce_core.contracts import RFQ, CounterOffer
from commerce_core.pricing import Quote
from seller_agent.graph import SellerState, _offer_from_quote
from seller_agent.planner import (
    ScriptedSellerPlanner,
    SellerDecision,
    SellerDecisionContext,
)


async def test_below_floor_target_holds_current_policy_price(
    circuitforge_policy,
):
    context = SellerDecisionContext(
        policy=circuitforge_policy,
        catalog_item={},
        counter_offer=CounterOffer(
            negotiation_round=2,
            target_unit_price_cents=25522,
            requested_changes={"warranty_months": 24},
            rationale="Please include 24-month coverage.",
        ),
        current_round=2,
        allowed_prices=[26312],
        allowed_warranty_months=[12, 24, 36],
        previous_offer=None,
        requested_warranty_months=24,
    )
    decision = await ScriptedSellerPlanner().decide(context)
    assert decision.action == "counter"
    assert decision.unit_price_cents == 26312
    assert decision.warranty_months == 24
    assert "floor" in decision.rationale

def test_for_product_carries_catalog_metadata(northwind_policy):
    policy = northwind_policy.for_product("MM-MACBOOK-AIR-M4-13")
    assert policy.product_description == "Apple M4 · 16GB memory · 256GB SSD · Space Gray"
    assert policy.image_emoji == "💻"
    assert policy.product_color == "#eaf0fb"
    assert policy.color == "gray"


def test_offer_attributes_describe_the_selected_product(northwind_policy):
    policy = northwind_policy.for_product("MM-MACBOOK-AIR-M4-13")
    quote = Quote(
        base_unit_price_cents=97900,
        warranty_addon_cents=0,
        unit_price_cents=97900,
        subtotal_cents=97900,
        total_cents=97900,
        delivery_days=5,
        stock_confidence=0.9,
        split_shipment=False,
        warranty_months=12,
        valid_until=datetime.now(UTC) + timedelta(hours=1),
    )
    state: SellerState = {
        "task_id": "task-1",
        "context_id": "context-1",
        "rfq": RFQ(
            request_id="rfq-1",
            run_id="task-1",
            category="general",
            product_hint="MacBook Air",
            quantity=1,
            required_by=datetime.now(UTC) + timedelta(days=7),
        ),
        "previous_offer": None,
        "current_round": 1,
    }
    offer = _offer_from_quote(
        policy=policy,
        state=state,
        quote=quote,
        decision=SellerDecision(
            action="propose",
            unit_price_cents=97900,
            warranty_months=12,
            rationale="test",
        ),
    )
    attributes = offer.line_items[0].attributes
    assert attributes["image_emoji"] == "💻"
    assert attributes["color"] == "#eaf0fb"
    assert attributes["color_name"] == "gray"
    assert attributes["specs"] == "Apple M4 · 16GB memory · 256GB SSD · Space Gray"
    assert attributes["category"] == "Electronics"
    assert offer.binding_version == 2
