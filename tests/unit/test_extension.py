import pytest

from commerce_core.contracts import RFQ, RFQConstraints, RFQPreferences
from commerce_core.extension import EXTENSION_URI, parse_payload, wrap_payload


def test_round_trip_rfq():
    rfq = RFQ(
        request_id="rfq-1",
        run_id="run-1",
        category="consumer-electronics",
        product_hint="Nimbus NC-700",
        quantity=12,
        required_by="2026-11-04T00:00:00Z",
        constraints=RFQConstraints(
            min_warranty_months=24, min_returns_days=30, color="black"
        ),
        preferences=RFQPreferences(sustainability=True),
    )
    envelope = wrap_payload("rfq", rfq)
    assert envelope["schema"].startswith(EXTENSION_URI)
    assert parse_payload("rfq", envelope, RFQ) == rfq


def test_wrong_schema_is_rejected():
    with pytest.raises(ValueError, match="schema"):
        parse_payload(
            "offer",
            {
                "schema": "https://example.com/wrong.json",
                "schema_version": "1.0",
                "payload": {},
            },
            RFQ,
        )
