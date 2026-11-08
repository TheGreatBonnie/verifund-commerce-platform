"""TDD for #3 trade-off generation (top-2, all-4 keys, price-stuck only)."""
import pytest
from buyer_agent.planner import CounterChoice
from pydantic import ValidationError
from seller_agent.planner import SellerDecision


def test_counter_choice_allows_all_four_keys():
    c = CounterChoice(target_unit_price_cents=18500, requested_changes={"warranty_months": 24, "shipping_cents": 0, "delivery_days": 2, "split_shipment": True}, rationale="x")
    assert c.requested_changes["shipping_cents"] == 0
    assert c.requested_changes["delivery_days"] == 2
    assert len(c.requested_changes) == 4


def test_counter_choice_proposed_tradeoffs_top2():
    c = CounterChoice(target_unit_price_cents=18500, requested_changes={"warranty_months": 24}, rationale="x", proposed_tradeoffs=[{"key": "warranty_months", "value": 24}, {"key": "shipping_cents", "value": 0}])
    assert len(c.proposed_tradeoffs) == 2
    assert c.proposed_tradeoffs[0]["key"] == "warranty_months"


def test_counter_choice_rejects_more_than_two_tradeoffs():
    with pytest.raises(ValidationError):
        CounterChoice(target_unit_price_cents=18500, requested_changes={}, rationale="x", proposed_tradeoffs=[{"key": "warranty_months", "value": 24}, {"key": "shipping_cents", "value": 0}, {"key": "delivery_days", "value": 2}])


def test_seller_decision_accepts_requested_changes():
    d = SellerDecision(action="counter", unit_price_cents=18500, warranty_months=12, rationale="x", requested_changes={"shipping_cents": 0, "delivery_days": 2})
    assert d.requested_changes["shipping_cents"] == 0


def test_seller_decision_rejects_bad_shipment_type():
    with pytest.raises(ValidationError):
        SellerDecision(action="counter", unit_price_cents=18500, warranty_months=12, rationale="x", requested_changes={"shipping_cents": -1})


def test_concessions_accepts_tradeoff_keys():
    from commerce_core.negotiation.concessions import constrain_buyer_counter
    dec, rej = constrain_buyer_counter(target_unit_price_cents=18300, allowed_targets=[18300], requested_changes={"shipping_cents": 0, "delivery_days": 2}, allowed_warranty_months=[12, 24], allow_split=True, strategy="value-based")
    assert rej is None and dec is not None
    assert dec.requested_changes == {"shipping_cents": 0, "delivery_days": 2}
