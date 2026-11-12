from verifund_contracts.models import AgreementState
from verifund_control_plane.agreements.states import (
    is_terminal,
    next_state,
)


def test_allowed_transitions():
    assert next_state(AgreementState.PENDING_SELLER, "SELLER_ACCEPT") == AgreementState.PENDING_BUYER
    assert next_state(AgreementState.PENDING_BUYER, "BUYER_ACCEPT") == AgreementState.AGREED
    assert next_state(AgreementState.PENDING_SELLER, "SELLER_REJECT") == AgreementState.REJECTED


def test_terminal_rejects_all():
    for st in (AgreementState.REJECTED, AgreementState.EXPIRED, AgreementState.TERMINATED):
        assert is_terminal(st) is True
        try:
            next_state(st, "SELLER_ACCEPT")
            raised = False
        except ValueError:
            raised = True
        assert raised


def test_changes_reject_returns_requester_pending():
    assert next_state(
        AgreementState.CHANGES_REQUESTED, "CHANGES_REJECT", requester="seller",
    ) == AgreementState.PENDING_SELLER
    assert next_state(
        AgreementState.CHANGES_REQUESTED, "CHANGES_REJECT", requester="buyer",
    ) == AgreementState.PENDING_BUYER
