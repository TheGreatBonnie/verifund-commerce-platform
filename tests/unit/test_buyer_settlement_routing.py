from __future__ import annotations

from types import SimpleNamespace

from buyer_agent.graph import (
    settlement_award_route,
    settlement_approval_route,
    settlement_funding_route,
    settlement_release_route,
)


def state(**fields):
    return {"run_id": "run-1", **fields}


def test_settlement_award_route_uses_off_mode_when_no_settlement():
    assert settlement_award_route(state(settlement=None)) == "off"
    assert settlement_award_route(state(settlement={"transaction_id": "vf_1"})) == "settlement"


def test_settlement_approval_route_requires_an_approved_decision():
    assert settlement_approval_route(state(approval={"approved": True}, settlement={"transaction_id": "vf_1"})) == "settlement"
    assert settlement_approval_route(state(approval={"approved": True}, settlement=None)) == "off"
    assert settlement_approval_route(state(approval={"approved": False}, settlement={"transaction_id": "vf_1"})) == "settlement"


def test_funding_route_waits_then_moves_to_order():
    assert settlement_funding_route(state(settlement={"funding_state": "FUNDING_PENDING"})) == "wait"
    assert settlement_funding_route(state(settlement={"funding_state": "FUNDED"})) == "order"
    assert settlement_funding_route(state(settlement={"funding_state": "FAILED"})) == "failed"


def test_release_route_is_terminal_only_after_release_or_review():
    assert settlement_release_route(state(settlement={"state": "RELEASED"})) == "done"
    assert settlement_release_route(state(settlement={"state": "REVIEW_REQUIRED"})) == "review"
    assert settlement_release_route(state(settlement={"state": "VERIFICATION_PENDING"})) == "wait"
