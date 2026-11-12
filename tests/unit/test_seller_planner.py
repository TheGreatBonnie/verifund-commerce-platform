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
            target_unit_price_cents=39000,
            requested_changes={"warranty_months": 24},
            rationale="Please include 24-month coverage.",
        ),
        current_round=2,
        allowed_prices=[44099],
        allowed_warranty_months=[12, 24, 36],
        previous_offer=None,
        requested_warranty_months=24,
    )
    decision = await ScriptedSellerPlanner().decide(context)
    assert decision.action == "counter"
    assert decision.unit_price_cents == 44099
    assert decision.warranty_months == 24
    assert "floor" in decision.rationale

def test_for_product_carries_catalog_metadata(northwind_policy):
    policy = northwind_policy.for_product("EX-MACBOOK-AIR")
    assert policy.product_description == "Lightweight and powerful notebook featuring Apple's M1 chip for everyday productivity."
    assert policy.image_url.startswith("https://images.unsplash.com/")
    assert policy.product_image_url == policy.image_url
    assert policy.color == "black"


def test_offer_attributes_describe_the_selected_product(northwind_policy):
    policy = northwind_policy.for_product("EX-MACBOOK-AIR")
    quote = Quote(
        base_unit_price_cents=117599,
        warranty_addon_cents=0,
        unit_price_cents=117599,
        subtotal_cents=117599,
        total_cents=117599,
        delivery_days=3,
        stock_confidence=1.0,
        split_shipment=False,
        warranty_months=24,
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
            unit_price_cents=117599,
            warranty_months=24,
            rationale="test",
        ),
    )
    attributes = offer.line_items[0].attributes
    assert attributes["image_url"].startswith("https://images.unsplash.com/")
    assert attributes["color_name"] == "black"
    assert attributes["specs"] == "Lightweight and powerful notebook featuring Apple's M1 chip for everyday productivity."
    assert attributes["category"] == "MacBook"
    assert offer.binding_version == 2
