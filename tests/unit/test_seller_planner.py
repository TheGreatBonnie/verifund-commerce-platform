from commerce_core.contracts import CounterOffer
from seller_agent.planner import ScriptedSellerPlanner, SellerDecisionContext


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
