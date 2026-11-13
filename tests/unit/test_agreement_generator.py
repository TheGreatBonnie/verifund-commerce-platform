from datetime import UTC, datetime, timedelta

import pytest

from verifund_contracts.models import (
    AwardLineItem,
    AwardRequest,
    RemedyPolicy,
    RemedyTerms,
)
from verifund_control_plane.agreements.generator import (
    apply_change_set,
    build_terms,
    validate_award,
    validate_terms,
)
from verifund_control_plane.agreements.models import AgreementError


def _requirements():
    from verifund_contracts import Requirement, RequirementCheck

    return [
        Requirement(
            requirement_id="hardware",
            title="Hardware diagnostic report",
            description="Diagnostic report showing at least 32 GB of RAM.",
            owner="seller",
            kind="other",
            source="file",
            accepted_formats=["text/csv"],
            checks=[
                RequirementCheck(
                    check_id="ram_gte_32gb",
                    description="At least 32 GB of RAM.",
                    expected_value=32,
                    operator="gte",
                    unit="GB",
                    verification_method="deterministic",
                ),
            ],
            required=True,
        ),
        Requirement(
            requirement_id="delivery_confirmation",
            title="Delivery confirmation",
            description="System-generated from carrier record and buyer confirmation.",
            owner="system",
            kind="delivery_confirmation",
            source="reference",
            checks=[
                RequirementCheck(
                    check_id="carrier_and_buyer_agree",
                    description="Carrier record and buyer confirmation agree on delivery.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
            required=True,
        ),
    ]


def _award():
    return AwardRequest(
        run_id="run-1", buyer_id="buyer-1", seller_id="seller-1",
        offer_id="offer-1", request_id="rfq-1",
        buyer_display_name="Buyer", seller_display_name="Seller",
        currency="USD", amount_cents=51600, shipping_cents=2500,
        tax_cents=3600, fees_cents=500, quantity=10,
        line_items=[AwardLineItem(sku="SKU-1", name="Sensor", quantity=10,
                                 unit_price_cents=4200, warranty_addon_cents=300,
                                 attributes={"color": "blue", "condition": "new"})],
        delivery_days=5, warranty_months=12, returns_days=30,
        offer_round=2, offer_hash="a" * 64,
        offer_valid_until=datetime.now(UTC) + timedelta(hours=1),
        requirements=_requirements(),
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
    assert terms["items"][0]["attributes"] == {"color": "blue", "condition": "new"}


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


def _requirements():
    from verifund_contracts import Requirement, RequirementCheck

    return [
        Requirement(
            requirement_id="hardware",
            title="Hardware diagnostic report",
            description="Diagnostic report showing at least 32 GB of RAM.",
            owner="seller",
            kind="other",
            source="file",
            accepted_formats=["text/csv"],
            checks=[
                RequirementCheck(
                    check_id="ram_gte_32gb",
                    description="At least 32 GB of RAM.",
                    expected_value=32,
                    operator="gte",
                    unit="GB",
                    verification_method="deterministic",
                ),
            ],
            required=True,
        ),
        Requirement(
            requirement_id="delivery_confirmation",
            title="Delivery confirmation",
            description="System-generated from carrier record and buyer confirmation.",
            owner="system",
            kind="delivery_confirmation",
            source="reference",
            checks=[
                RequirementCheck(
                    check_id="carrier_and_buyer_agree",
                    description="Carrier record and buyer confirmation agree on delivery.",
                    operator="exists",
                    verification_method="deterministic",
                ),
            ],
            required=True,
        ),
    ]


def test_generator_copies_requirements():
    award = _award().model_copy(update={"requirements": _requirements()})
    terms = build_terms(award, datetime.now(UTC))
    assert [r["requirement_id"] for r in terms["requirements"]] == [
        "hardware",
        "delivery_confirmation",
    ]
    ram = terms["requirements"][0]["checks"][0]
    assert ram["check_id"] == "ram_gte_32gb"
    assert ram["operator"] == "gte"
    validate_terms(terms, award)


def test_generator_rejects_an_award_without_a_requirement_catalog():
    award = _award().model_copy(update={"requirements": []})
    with pytest.raises(AgreementError) as excinfo:
        build_terms(award, datetime.now(UTC))
    assert excinfo.value.code == "invalid_requirements"


def test_generator_rejects_floor_violating_catalog():
    import pytest
    from verifund_contracts import Requirement

    bad = [
        Requirement(
            requirement_id="hardware",
            title="Hardware diagnostic report",
            description="No checks at all.",
            owner="seller",
            kind="other",
            source="file",
            accepted_formats=["text/csv"],
            checks=[],
            required=True,
        )
    ]
    award = _award().model_copy(update={"requirements": bad})
    with pytest.raises(ValueError):
        build_terms(award, datetime.now(UTC))


def test_validate_award_rejects_expired_offers_with_a_domain_error():
    import pytest

    now = datetime.now(UTC)
    award = _award().model_copy(
        update={"offer_valid_until": now - timedelta(minutes=1)}
    )

    with pytest.raises(AgreementError) as excinfo:
        validate_award(award, now)

    assert excinfo.value.code == "offer_expired"
    assert "expired" in excinfo.value.message.lower()
