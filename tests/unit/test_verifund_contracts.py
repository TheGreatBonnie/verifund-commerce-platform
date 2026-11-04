from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx
from pydantic import ValidationError
from verifund_contracts import (
    AwardRequest,
    CheckoutDecision,
    RejectRequest,
    Requirement,
    RequirementCheck,
    RequirementResult,
    RequirementStatus,
    TransactionProjection,
    VerifundCheckpoint,
    VerifundClient,
    VerifundError,
    VerifundSkill,
    VerifundTaskResult,
)
from verifund_contracts.terms import validate_requirements

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def award_payload(**overrides):
    payload = {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "request_id": "rfq-1",
        "buyer_display_name": "Demo Buyer",
        "seller_display_name": "Northwind Audio",
        "currency": "USD",
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "tax_cents": 0,
        "fees_cents": 0,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "offer_round": 1,
        "offer_hash": "a" * 64,
        "offer_valid_until": NOW,
        "inspection_period_hours": 48,
        "inspection_starts_on": "DELIVERY_CONFIRMED",
        "evidence_required": [
            "shipment_manifest",
            "delivery_confirmation",
            "invoice",
        ],
        "remedies": {
            "non_delivery": "cancel_and_refund",
            "late_delivery": "cancel_and_refund",
            "damaged_goods": "refund_or_replacement",
        },
        "dispute_window_hours": 72,
    }
    payload.update(overrides)
    return payload


def test_award_line_item_defaults_missing_attributes():
    from verifund_contracts.models import AwardLineItem

    item = AwardLineItem(
        sku="SKU-1", name="Sensor", quantity=1, unit_price_cents=100
    )
    assert item.attributes == {}


def test_award_accepts_a_legacy_payload_without_attributes():
    payload = award_payload()
    del payload["line_items"][0]["warranty_addon_cents"]
    request = AwardRequest(**payload)
    assert request.line_items[0].attributes == {}
    assert request.binding_version == 1


def test_award_rejects_non_matching_total():
    with pytest.raises(ValidationError):
        AwardRequest(**award_payload(amount_cents=123401))


def test_award_accepts_matching_total():
    request = AwardRequest(**award_payload())
    assert request.amount_cents == 123400


def test_reject_reason_must_be_known():
    with pytest.raises(ValidationError):
        RejectRequest(
            seller_id="northwind-audio",
            agreement_hash="a" * 64,
            reason_code="made_up",
            seller_task_id="task-1",
            rejected_at=NOW,
        )


def test_projection_round_trip_has_no_extra_fields():
    projection = TransactionProjection(
        transaction_id="vf_1",
        run_id="run-1",
        state="AWARDED",
        last_seq=1,
        amount_cents=123400,
        currency="USD",
        buyer_id="demo-buyer",
        seller_id="northwind-audio",
        agreement_hash="a" * 64,
        agreement_version=1,
        seller_decision=None,
        buyer_agent_review=None,
        approval=None,
        cancellation=None,
        funding=None,
        purchase_order=None,
        evidence=None,
        verification=None,
        payout=None,
        receipt_available=False,
        deadlines={"evidence": None, "inspection": None},
        allowed_actions=["cancel"],
        updated_at=NOW,
    )
    assert projection.model_dump()["state"] == "AWARDED"


def test_checkout_checkpoint_requires_checkout_approval_type():
    result = VerifundTaskResult(
        skill=VerifundSkill.TRANSACTION_FUND,
        status="approval_required",
        checkpoint=VerifundCheckpoint.FUNDING_CHECKOUT_REQUIRED,
        approval_type="checkout",
        run_id="run-1",
    )
    assert result.approval_type == "checkout"


def test_checkout_checkpoint_rejects_funding_approval_type():
    with pytest.raises(ValidationError):
        VerifundTaskResult(
            skill=VerifundSkill.TRANSACTION_FUND,
            status="approval_required",
            checkpoint=VerifundCheckpoint.FUNDING_CHECKOUT_REQUIRED,
            approval_type="funding",
            run_id="run-1",
        )


def test_completed_checkout_decision_does_not_require_a_projection():
    # The card's projection is advisory. The verifund agent re-reads the
    # authoritative settlement, so a relayed decision may omit it.
    decision = CheckoutDecision(
        status="completed",
        transaction_id="vf_1",
        idempotency_key="checkout:vf_1",
    )
    assert decision.projection == {}

    canceled = CheckoutDecision(
        status="canceled",
        transaction_id="vf_1",
        idempotency_key="checkout:vf_1",
    )
    assert canceled.status == "canceled"


@respx.mock
async def test_client_sends_ops_headers_and_raises_structured_error():
    route = respx.post("http://control/awards").mock(
        return_value=httpx.Response(
            409,
            json={
                "error": {
                    "code": "hash_mismatch",
                    "message": "hash mismatch",
                    "retryable": False,
                    "details": {},
                    "request_id": "req-1",
                }
            },
        )
    )
    client = VerifundClient("http://control", ops_token="ops-token")
    with pytest.raises(VerifundError) as raised:
        await client.award(
            AwardRequest(**award_payload()),
            actor="buyer-agent",
            idempotency_key="award:run-1:offer-1",
        )
    assert raised.value.code == "hash_mismatch"
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer ops-token"
    assert request.headers["x-verifund-actor"] == "buyer-agent"
    assert request.headers["idempotency-key"] == "award:run-1:offer-1"


def _check(**overrides):
    data = {
        "check_id": "carrier_and_buyer_agree",
        "description": "carrier and buyer agree on delivery",
        "expected_value": None,
        "operator": "exists",
        "unit": None,
        "verification_method": "deterministic",
        "ai_derived": False,
    }
    data.update(overrides)
    return RequirementCheck(**data)


def _requirement(**overrides):
    data = {
        "requirement_id": "product_photos",
        "title": "Product photographs",
        "description": "Clear photographs of the product",
        "owner": "seller",
        "kind": "other",
        "source": "file",
        "accepted_formats": ["image/jpeg"],
        "checks": [_check(check_id="photo_integrity")],
        "required": True,
    }
    data.update(overrides)
    return Requirement(**data)


def _delivery_requirement(**overrides):
    data = {
        "requirement_id": "delivery_confirmation",
        "title": "Delivery confirmation",
        "description": "System-generated from carrier record and buyer confirmation",
        "owner": "system",
        "kind": "delivery_confirmation",
        "source": "reference",
        "accepted_formats": [],
        "checks": [_check()],
        "required": True,
    }
    data.update(overrides)
    return Requirement(**data)


def _valid_requirements():
    return [_requirement(), _delivery_requirement()]


def test_requirement_floors_accept_canonical_catalog():
    assert validate_requirements(_valid_requirements()) is None


def test_requirement_floor_rejects_empty_list():
    with pytest.raises(ValueError):
        validate_requirements([])


def test_requirement_floor_rejects_duplicate_requirement_id():
    catalog = [_requirement(), _requirement(), _delivery_requirement()]
    with pytest.raises(ValueError):
        validate_requirements(catalog)


def test_requirement_floor_rejects_duplicate_check_id_within_requirement():
    requirement = _requirement(
        checks=[_check(check_id="photo_integrity"), _check(check_id="photo_integrity")]
    )
    with pytest.raises(ValueError):
        validate_requirements([requirement, _delivery_requirement()])


def test_requirement_floor_allows_same_check_id_across_requirements():
    first = _requirement(checks=[_check(check_id="shared")])
    second = _delivery_requirement(checks=[_check(check_id="shared")])
    assert validate_requirements([first, second]) is None


def test_requirement_floor_rejects_empty_checks():
    with pytest.raises(ValueError):
        validate_requirements([Requirement(
            requirement_id="product_photos",
            title="Product photographs",
            description="...",
            owner="seller",
            kind="other",
            source="file",
            accepted_formats=["image/jpeg"],
            checks=[],
        ), _delivery_requirement()])


def test_requirement_floor_rejects_file_source_without_accepted_formats():
    requirement = _requirement(accepted_formats=[])
    with pytest.raises(ValueError):
        validate_requirements([requirement, _delivery_requirement()])


def test_requirement_floor_rejects_missing_owner():
    requirement = _requirement(owner="")
    with pytest.raises(ValueError):
        validate_requirements([requirement, _delivery_requirement()])


def test_requirement_floor_rejects_missing_expected_value():
    requirement = _requirement(
        checks=[_check(check_id="invoice_total", operator="eq", expected_value=None,
                       ai_derived=False)]
    )
    with pytest.raises(ValueError):
        validate_requirements([requirement, _delivery_requirement()])


def test_requirement_floor_allows_missing_expected_value_when_exists():
    requirement = _requirement(
        checks=[_check(check_id="photo_integrity", operator="exists", expected_value=None,
                       ai_derived=False)]
    )
    assert validate_requirements([requirement, _delivery_requirement()]) is None


def test_requirement_floor_allows_missing_expected_value_when_ai_derived():
    requirement = _requirement(
        checks=[_check(check_id="invoice_total", operator="eq", expected_value=None,
                       ai_derived=True)]
    )
    assert validate_requirements([requirement, _delivery_requirement()]) is None


def test_requirement_floor_allows_falsy_expected_value():
    requirement = _requirement(
        checks=[_check(check_id="min_ram", operator="gte", expected_value=0,
                       verification_method="deterministic")]
    )
    assert validate_requirements([requirement, _delivery_requirement()]) is None


def test_requirement_floor_rejects_missing_delivery_confirmation():
    with pytest.raises(ValueError):
        validate_requirements([_requirement()])


def test_requirement_floor_rejects_seller_owned_delivery_confirmation():
    catalog = [_requirement(), _delivery_requirement(owner="seller")]
    with pytest.raises(ValueError):
        validate_requirements(catalog)


def test_requirement_and_result_types_construct():
    req = Requirement(
        requirement_id="hardware",
        title="Hardware diagnostic report",
        description="...",
        owner="seller",
        kind="other",
        source="file",
        accepted_formats=["application/pdf"],
        checks=[
            RequirementCheck(check_id="ram", description="RAM", expected_value=32,
                             operator="gte", unit="GB",
                             verification_method="deterministic", ai_derived=False)
        ],
        required=True,
    )
    result = RequirementResult(
        requirement_id="hardware",
        kind="other",
        owner="seller",
        source="file",
        status=RequirementStatus.PASS,
        checks=[],
        submissions=[],
        declared_at=None,
        declared_by=None,
        attempt=None,
        reasons=[],
        checked_at=None,
        remediation=None,
    )
    assert req.requirement_id == result.requirement_id


def test_requirement_types_round_trip_json():
    req = Requirement(
        requirement_id="hardware",
        title="Hardware diagnostic report",
        description="...",
        owner="seller",
        kind="other",
        source="file",
        accepted_formats=["application/pdf"],
        checks=[RequirementCheck(check_id="ram", description="RAM", expected_value=32,
                                 operator="gte", unit="GB",
                                 verification_method="deterministic", ai_derived=False)],
    )
    dumped = req.model_dump(mode="json")
    assert Requirement.model_validate(dumped) == req
