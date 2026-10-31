from datetime import UTC, datetime, timedelta

from verifund_contracts.models import (
    AwardLineItem,
    AwardRequest,
    RemedyPolicy,
    RemedyTerms,
)
from verifund_control_plane.agreements.generator import (
    apply_change_set,
    build_terms,
    validate_terms,
)


def _award():
    return AwardRequest(
        run_id="run-1", buyer_id="buyer-1", seller_id="seller-1",
        offer_id="offer-1", request_id="rfq-1",
        buyer_display_name="Buyer", seller_display_name="Seller",
        currency="USD", amount_cents=51600, shipping_cents=2500,
        tax_cents=3600, fees_cents=500, quantity=10,
        line_items=[AwardLineItem(sku="SKU-1", name="Sensor", quantity=10,
                                 unit_price_cents=4200, warranty_addon_cents=300)],
        delivery_days=5, warranty_months=12, returns_days=30,
        offer_round=2, offer_hash="a" * 64,
        offer_valid_until=datetime.now(UTC) + timedelta(hours=1),
        remedies=RemedyTerms(
            non_delivery=RemedyPolicy.CANCEL_AND_REFUND,
            late_delivery=RemedyPolicy.CANCEL_AND_REFUND,
            damaged_goods=RemedyPolicy.REFUND_OR_REPLACEMENT,
        ),
    )


def test_build_terms_totals():
    award = _award()
    terms = build_terms(award, datetime.now(UTC))
    assert terms["totals"]["total_cents"] == 51600
    assert terms["totals"]["subtotal_cents"] == 45000
    assert terms["items"][0]["line_total_cents"] == 45000


def test_validate_terms_rejects_bad_arithmetic():
    import pytest
    award = _award()
    terms = build_terms(award, datetime.now(UTC))
    terms["totals"]["total_cents"] = 1
    with pytest.raises(ValueError):
        validate_terms(terms, award)


def test_apply_change_set_recomputes():
    from verifund_contracts.models import ChangeOperation, ChangeOperationType, ChangeSet
    award = _award()
    terms = build_terms(award, datetime.now(UTC))
    cs = ChangeSet(operations=[ChangeOperation(
        op=ChangeOperationType.SET_SHIPPING, shipping_cents=1000,
    )])
    new = apply_change_set(terms, cs)
    assert new["totals"]["shipping_cents"] == 1000
    assert new["totals"]["total_cents"] == 51600 - 2500 + 1000
