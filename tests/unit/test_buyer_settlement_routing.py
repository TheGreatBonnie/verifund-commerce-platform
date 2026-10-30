from __future__ import annotations

from buyer_agent.graph import approval_route, buyer_review_route


def state(**fields):
    return {"run_id": "run-1", **fields}


def test_approved_settlement_award_routes_to_agreement_creation():
    assert (
        approval_route(
            state(
                approval={"approved": True, "approved_by": "Demo Buyer"},
                settlement_mode=True,
            )
        )
        == "settlement"
    )


def test_approved_legacy_award_routes_to_the_legacy_order_flow():
    assert (
        approval_route(
            state(
                approval={"approved": True, "approved_by": "Demo Buyer"},
                settlement_mode=False,
            )
        )
        == "off"
    )


def test_rejected_settlement_award_never_starts_agreement_creation():
    assert (
        approval_route(
            state(
                approval={"approved": False, "approved_by": "Demo Buyer"},
                settlement_mode=True,
            )
        )
        == "rejected"
    )


def test_buyer_review_route_requires_an_explicit_acceptance():
    assert buyer_review_route(state(buyer_review={"status": "accepted"})) == "accepted"
    assert buyer_review_route(state(buyer_review={"status": "rejected"})) == "rejected"
    assert buyer_review_route(state()) == "rejected"
