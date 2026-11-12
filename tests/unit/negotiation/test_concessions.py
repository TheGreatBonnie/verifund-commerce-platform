from commerce_core.negotiation.concessions import (
    constrain_buyer_counter,
    validate_requested_changes,
)


def test_validate_requested_changes_typed_allowlist():
    ok, err = validate_requested_changes({"warranty_months": 24}, [12, 24], True)
    assert err is None
    assert ok == {"warranty_months": 24}

    ok, err = validate_requested_changes({"unknown": 1}, [12, 24], True)
    assert ok is None
    assert err is not None

    ok, err = validate_requested_changes({"warranty_months": 36}, [12, 24], True)
    assert ok is None
    assert "warranty" in (err or "").lower()


def test_constrain_buyer_counter_requires_allowed_target():
    decision, reject = constrain_buyer_counter(
        target_unit_price_cents=18500,
        allowed_targets=[18300],
        requested_changes={},
        allowed_warranty_months=[12, 24],
        allow_split=True,
    )
    assert decision is None
    assert reject is not None

    decision, reject = constrain_buyer_counter(
        target_unit_price_cents=18300,
        allowed_targets=[18300],
        requested_changes={"split_shipment": True},
        allowed_warranty_months=[12, 24],
        allow_split=True,
    )
    assert reject is None
    assert decision is not None
    assert decision.target_unit_price_cents == 18300
