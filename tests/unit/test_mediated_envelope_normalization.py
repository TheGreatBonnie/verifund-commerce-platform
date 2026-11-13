"""The orchestrator must not forward an envelope the LLM mangled."""
from __future__ import annotations

import pytest
from orchestrator_agent.mediation import normalize_seller_request

COUNTER_SCHEMA = "https://marketmesh.example/extensions/commerce/v1/schemas/counter-offer.json"


def test_rewraps_a_hoisted_counter_payload() -> None:
    mangled = {
        "negotiation_round": "2",
        "target_unit_price_cents": "123577",
        "requested_changes": {
            "warranty_months": "24",
            "split_shipment": "false",
            "shipping_cents": "0",
            "delivery_days": "3",
        },
        "rationale": "competitive",
        "in_response_to_offer_id": "e1cc4593-8052-4f94-9488-bfb975e98d01",
        "idempotency_key": "",
        "schema": COUNTER_SCHEMA,
        "schema_version": "1.0",
    }

    normalized = normalize_seller_request(mangled)

    assert normalized["schema"] == COUNTER_SCHEMA
    assert normalized["schema_version"] == "1.0"
    assert "payload" in normalized
    payload = normalized["payload"]
    assert payload["negotiation_round"] == 2
    assert payload["target_unit_price_cents"] == 123577
    assert payload["requested_changes"]["warranty_months"] == 24
    assert payload["requested_changes"]["split_shipment"] is False
    assert payload["requested_changes"]["shipping_cents"] == 0
    assert payload["requested_changes"]["delivery_days"] == 3


def test_normalizes_an_empty_requested_changes_string() -> None:
    envelope = {
        "schema": COUNTER_SCHEMA,
        "schema_version": "1.0",
        "payload": {
            "negotiation_round": "2",
            "target_unit_price_cents": "117398",
            "requested_changes": "",
            "rationale": "x",
        },
    }

    normalized = normalize_seller_request(envelope)

    assert normalized["payload"]["requested_changes"] == {}
    assert normalized["payload"]["target_unit_price_cents"] == 117398


def test_leaves_a_well_formed_envelope_intact() -> None:
    envelope = {
        "schema": COUNTER_SCHEMA,
        "schema_version": "1.0",
        "payload": {
            "negotiation_round": 2,
            "target_unit_price_cents": 115000,
            "requested_changes": {"warranty_months": 24},
            "rationale": "x",
        },
    }

    normalized = normalize_seller_request(envelope)

    assert normalized["schema"] == envelope["schema"]
    assert normalized["schema_version"] == envelope["schema_version"]
    assert normalized["payload"]["negotiation_round"] == 2
    assert normalized["payload"]["target_unit_price_cents"] == 115000
    assert normalized["payload"]["requested_changes"] == {"warranty_months": 24}
    assert normalized["payload"]["rationale"] == "x"


def test_rejects_an_envelope_that_cannot_be_made_valid() -> None:
    with pytest.raises(ValueError):
        normalize_seller_request({"schema": COUNTER_SCHEMA, "schema_version": "1.0"})
