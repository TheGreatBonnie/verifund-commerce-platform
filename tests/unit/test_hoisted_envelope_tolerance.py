"""A hoisted commerce envelope must be readable, not rejected."""
from __future__ import annotations

from commerce_core.contracts import CounterOffer
from commerce_core.extension import expected_schema, parse_payload


def test_parse_payload_accepts_a_hoisted_counter_envelope() -> None:
    envelope = {
        "schema": expected_schema("counter_offer"),
        "schema_version": "1.0",
        "negotiation_round": 2,
        "target_unit_price_cents": 123577,
        "requested_changes": {"warranty_months": 24},
        "rationale": "x",
    }

    counter = parse_payload("counter_offer", envelope, CounterOffer)

    assert counter.negotiation_round == 2
    assert counter.target_unit_price_cents == 123577
