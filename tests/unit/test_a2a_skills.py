"""TDD for A2A skills/capabilities upgrade (tradeoff skill + params)."""
from buyer_agent.card import build_buyer_agent_card
from commerce_core.cards import validate_agent_card
from commerce_core.extension import EXTENSION_URI
from google.protobuf import json_format
from seller_agent.card import build_agent_card


def _seller_card(northwind_policy):
    return build_agent_card(northwind_policy, "http://127.0.0.1:9201", tenant="agent_northwind")


def test_seller_advertises_tradeoff_skill(northwind_policy):
    card = _seller_card(northwind_policy)
    ids = {s.id for s in card.skills}
    assert "commerce.negotiate.tradeoff" in ids
    tradeoff = next(s for s in card.skills if s.id == "commerce.negotiate.tradeoff")
    assert "trade-off" in tradeoff.description.lower() or "tradeoff" in tradeoff.description.lower()
    assert "commerce.negotiate" in ids  # backward compat


def test_seller_extension_params_advertise_negotiation(northwind_policy):
    card = _seller_card(northwind_policy)
    ext = next(e for e in card.capabilities.extensions if e.uri == EXTENSION_URI)
    params = json_format.MessageToDict(ext.params)
    assert "negotiation" in params
    n = params["negotiation"]
    assert set(n["strategies"]) == {"collaborative", "competitive", "compromise", "value-based"}
    assert set(n["tradeoff_terms"]) == {"warranty_months", "split_shipment", "shipping_cents", "delivery_days"}
    assert n["max_tradeoffs"] == 2


def test_seller_card_still_validates(northwind_policy):
    assert validate_agent_card(_seller_card(northwind_policy)) == []


def test_buyer_sourcing_advertises_strategy_and_grounding():
    card = build_buyer_agent_card("http://127.0.0.1:9100")
    sourcing = next(s for s in card.skills if s.id == "commerce.sourcing")
    text = (sourcing.description + " " + " ".join(list(sourcing.tags))).lower()
    assert "strategy" in text
    assert "grounded" in text or "catalog" in text
