"""Buyer and seller must agree on which counter terms are grantable."""
from __future__ import annotations

from buyer_agent.planner import CounterChoice


def test_buyer_drops_a_change_the_seller_cannot_grant() -> None:
    """Asking for shipping/delivery voids the counter on a strict seller; the
    buyer must not ask for what cannot be granted."""
    choice = CounterChoice(
        target_unit_price_cents=115000,
        requested_changes={
            "warranty_months": 24,
            "shipping_cents": 0,
            "delivery_days": 3,
        },
        rationale="x",
    )

    assert choice.requested_changes == {"warranty_months": 24}


def test_seller_drops_an_unsupported_incoming_change_instead_of_failing() -> None:
    """A counter that carries an ungrantable term must still be answered."""
    from seller_agent.graph import _filter_counter_changes

    filtered, dropped = _filter_counter_changes(
        {"warranty_months": 24, "delivery_days": 3, "shipping_cents": 0},
        allowed_warranties=[12, 24, 36],
    )

    assert filtered == {"warranty_months": 24}
    assert set(dropped) == {"delivery_days", "shipping_cents"}
