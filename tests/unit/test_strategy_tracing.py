"""TDD for graph-level strategy tracing (buyer)."""
from commerce_core.contracts import (
    Mandate,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
    Preferences,
)


async def test_record_decision_traces_strategy():
    from buyer_agent.graph import _record_decision

    captured = {}

    class FakeTrace:
        async def record(self, run_id, *, direction, method, payload, seller_id):
            captured.update(payload)

    class FakeServices:
        trace = FakeTrace()

    entry = await _record_decision(
        FakeServices(),
        "run-1",
        source="scripted.decision",
        action="counter",
        rationale="test",
        fallback_used=False,
        seller_id="s1",
        strategy="competitive",
    )
    assert entry["strategy"] == "competitive"
    assert captured["strategy"] == "competitive"


async def test_choose_counter_traces_choice_strategy():
    from buyer_agent.graph import _choose_counter
    from buyer_agent.planner import CounterChoice

    class FakePlanner:
        async def choose_counter(self, offer, mandate, allowed, round_number):
            return CounterChoice(target_unit_price_cents=allowed[0], requested_changes={}, rationale="x", strategy="value-based")

    mandate = Mandate(run_id="r", category="consumer-electronics", product_hint="H", quantity=12, max_total_cents=340000, deadline_days=14, min_warranty_months=12, min_returns_days=30, preferences=Preferences())
    offer = Offer(offer_id="o1", request_id="r1", seller_id="s1", seller_name="S1", seller_rating=4.0, line_items=[OfferLineItem(sku="SKU", name="I", quantity=12, unit_price_cents=200, list_unit_price_cents=220)], subtotal_cents=2400, shipping_cents=0, total_cents=2400, delivery_days=7, warranty_months=12, returns_days=30, valid_until="2030-01-01T00:00:00Z", terms=OfferTerms(), status=OfferStatus.PROPOSED, round=1)

    class EmptyServices:
        trace = None

    choice, used_fallback, trace = await _choose_counter(EmptyServices(), "run-1", FakePlanner(), offer, mandate, [18300], 2, "s1")
    assert used_fallback is False
    assert choice.strategy == "value-based"
    planner_events = [t for t in trace if t.get("type") == "planner_decision"]
    assert planner_events and planner_events[0]["strategy"] == "value-based"


async def test_choose_counter_fallback_traces_collaborative():
    from buyer_agent.graph import _choose_counter

    class BadPlanner:
        async def choose_counter(self, offer, mandate, allowed, round_number):
            raise RuntimeError("boom")

    mandate = Mandate(run_id="r", category="consumer-electronics", product_hint="H", quantity=12, max_total_cents=340000, deadline_days=14, min_warranty_months=12, min_returns_days=30, preferences=Preferences())
    offer = Offer(offer_id="o1", request_id="r1", seller_id="s1", seller_name="S1", seller_rating=4.0, line_items=[OfferLineItem(sku="SKU", name="I", quantity=12, unit_price_cents=200, list_unit_price_cents=220)], subtotal_cents=2400, shipping_cents=0, total_cents=2400, delivery_days=7, warranty_months=12, returns_days=30, valid_until="2030-01-01T00:00:00Z", terms=OfferTerms(), status=OfferStatus.PROPOSED, round=1)

    class EmptyServices:
        trace = None

    _choice, used_fallback, trace = await _choose_counter(EmptyServices(), "run-1", BadPlanner(), offer, mandate, [18300], 2, "s1")
    assert used_fallback is True
    planner_events = [t for t in trace if t.get("type") == "planner_decision"]
    assert planner_events and planner_events[0]["fallback_used"] is True
    assert planner_events[0].get("strategy") == "collaborative"
