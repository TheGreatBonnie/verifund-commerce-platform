from __future__ import annotations

from verifund_contracts.models import AgreementState

TERMINAL_STATES = {
    AgreementState.REJECTED, AgreementState.EXPIRED, AgreementState.TERMINATED,
}


def is_terminal(state: AgreementState) -> bool:
    return state in TERMINAL_STATES


def next_state(state: AgreementState, event: str, *, requester: str | None = None) -> AgreementState:
    if is_terminal(state):
        raise ValueError(f"no transitions from terminal state {state}")
    table = {
        (AgreementState.PENDING_SELLER, "SELLER_ACCEPT"): AgreementState.PENDING_BUYER,
        (AgreementState.PENDING_SELLER, "SELLER_REJECT"): AgreementState.REJECTED,
        (AgreementState.PENDING_SELLER, "SELLER_OPERATOR_REQUIRED"): AgreementState.PENDING_SELLER,
        (AgreementState.PENDING_SELLER, "SELLER_REQUEST_CHANGES"): AgreementState.CHANGES_REQUESTED,
        (AgreementState.PENDING_BUYER, "BUYER_ACCEPT"): AgreementState.AGREED,
        (AgreementState.PENDING_BUYER, "BUYER_REJECT"): AgreementState.REJECTED,
        (AgreementState.PENDING_BUYER, "BUYER_REQUEST_CHANGES"): AgreementState.CHANGES_REQUESTED,
        (AgreementState.CHANGES_REQUESTED, "CHANGES_ACCEPT"): AgreementState.PENDING_SELLER,
        (AgreementState.CHANGES_REQUESTED, "EXPIRE"): AgreementState.EXPIRED,
    }
    if (state, event) == (AgreementState.CHANGES_REQUESTED, "CHANGES_REJECT"):
        if requester == "seller":
            return AgreementState.PENDING_SELLER
        if requester == "buyer":
            return AgreementState.PENDING_BUYER
        raise ValueError("requester is required for changes_reject")
    if (state, event) == (AgreementState.AGREED, "TERMINATE"):
        return AgreementState.TERMINATED
    if (state, event) not in table:
        raise ValueError(f"invalid transition {state} --{event}--> ?")
    return table[(state, event)]


def assert_transition(state: AgreementState, event: str, *, requester: str | None = None) -> AgreementState:
    return next_state(state, event, requester=requester)
