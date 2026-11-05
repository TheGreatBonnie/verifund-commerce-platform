from __future__ import annotations

import pytest
from seller_agent.mandate import SellerMandate
from seller_agent.settlement import validate_mandate
from verifund_contracts import Requirement, RequirementCheck


def make_requirement(
    check: RequirementCheck, *, owner: str = "seller"
) -> Requirement:
    return Requirement(
        requirement_id="hardware",
        title="Hardware diagnostic report",
        description="Diagnostic report.",
        owner=owner,
        kind="other",
        source="file",
        accepted_formats=["text/csv"],
        checks=[check],
        required=True,
    )


def test_seller_rejects_unobservable_eq_requirement():
    # Exact literal equality through AI extraction, not flagged ai_derived:
    # the deterministic pipeline would hard-compare OCR/AI output to the
    # literal, which can never settle -> unsatisfiable for the seller.
    requirement = make_requirement(
        RequirementCheck(
            check_id="serial_exact",
            description="Extracted serial equals an exact literal.",
            expected_value="SN-99112233",
            operator="eq",
            verification_method="extraction",
            ai_derived=False,
        )
    )
    with pytest.raises(ValueError, match="unsatisfiable"):
        validate_mandate([requirement])


def test_seller_rejects_check_with_no_evaluator():
    requirement = make_requirement(
        RequirementCheck(
            check_id="mystery",
            description="Check with an unknown verification method.",
            expected_value=1,
            operator="gte",
            verification_method="oracle",
            ai_derived=False,
        )
    )
    with pytest.raises(ValueError, match="no evaluator"):
        validate_mandate([requirement])


def test_seller_accepts_deterministic_gte_and_exists():
    requirements = [
        make_requirement(
            RequirementCheck(
                check_id="ram_gte_32gb",
                description="At least 32 GB of RAM.",
                expected_value=32,
                operator="gte",
                unit="GB",
                verification_method="deterministic",
            )
        ),
        make_requirement(
            RequirementCheck(
                check_id="photo_integrity",
                description="Photo is present and passes intake.",
                operator="exists",
                verification_method="deterministic",
            )
        ),
    ]
    validate_mandate(requirements)  # does not raise


def test_seller_accepts_ai_derived_and_agreement_derived_eq():
    requirements = [
        make_requirement(
            RequirementCheck(
                check_id="serial_matches_device",
                description="Extracted serial matches the device.",
                operator="eq",
                verification_method="extraction",
                ai_derived=True,
            )
        ),
        make_requirement(
            RequirementCheck(
                check_id="invoice_total_matches",
                description="Invoice total matches the agreement total.",
                expected_value=80000,
                operator="eq",
                unit="cents",
                verification_method="extraction",
                ai_derived=True,
            )
        ),
    ]
    validate_mandate(requirements)  # does not raise


def test_system_owned_delivery_requirement_is_not_the_sellers_to_satisfy():
    requirement = make_requirement(
        RequirementCheck(
            check_id="carrier_and_buyer_agree",
            description="Carrier record and buyer confirmation agree.",
            operator="exists",
            verification_method="deterministic",
        ),
        owner="system",
    )
    validate_mandate([requirement])  # does not raise


def test_mandate_still_gates_economics():
    mandate = SellerMandate(max_total_cents=100)
    assert not mandate.allows(total_cents=101)
