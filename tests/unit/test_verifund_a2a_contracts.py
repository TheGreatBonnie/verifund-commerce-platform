from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx
from pydantic import ValidationError

from verifund_contracts import (
    AGREEMENT_REVIEW_REQUEST_SCHEMA,
    AGREEMENT_REVIEW_RESULT_SCHEMA,
    AgreementProjection,
    AgreementReviewRequest,
    AgreementReviewResult,
    AwardRequest,
    AwardResponse,
    BuyerAgreementRequest,
    BuyerAgreementResponse,
    BuyerOrderReportRequest,
    BuyerOrderReportResponse,
    BuyerPurchaseOrderRequest,
    BuyerPurchaseOrderResponse,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
    VERIFUND_RESUME_REQUEST_SCHEMA,
    VerifundCheckpoint,
    VerifundClient,
    VerifundResumeRequest,
    VerifundSkill,
    VerifundTaskRequest,
    VerifundTaskResult,
    parse_agreement_review_result,
    parse_verifund_resume_request,
    parse_verifund_task_request,
    wrap_agreement_review_request,
    wrap_verifund_resume_request,
    wrap_verifund_task_request,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64


def agreement_payload(**overrides):
    payload = {
        "agreement_id": "agr_1",
        "agreement_version": 1,
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "offer_round": 1,
        "offer_hash": HASH,
        "offer_valid_until": NOW,
        "currency": "USD",
        "amount_cents": 123400,
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
        "shipping_cents": 3400,
        "tax_cents": 0,
        "fees_cents": 0,
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
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
        "terms": {
            "schema": "verifund.agreement.v1",
            "agreement_type": "goods",
            "terms_version": 1,
            "totals": {
                "subtotal_cents": 120000,
                "shipping_cents": 3400,
                "tax_cents": 0,
                "fees_cents": 0,
                "total_cents": 123400,
            },
            "delivery": {"delivery_days": 7},
            "warranty": {"warranty_months": 24},
            "returns": {"returns_days": 30},
            "inspection": {"period_hours": 48, "starts_on": "DELIVERY_CONFIRMED"},
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
        },
        "status": "PENDING_SELLER",
        "expires_at": None,
        "created_at": "2026-10-27T12:00:00Z",
        "agreement_hash": HASH,
    }
    payload.update(overrides)
    return payload


def projection(**overrides) -> AgreementProjection:
    body = agreement_payload(**overrides)
    body.pop("agreement_hash", None)
    probe = AgreementProjection.model_construct(**body, agreement_hash="0" * 64)
    return AgreementProjection(**body, agreement_hash=probe.recompute_hash())


def test_agreement_projection_hash_binds_every_term() -> None:
    item = projection()
    assert item.agreement_hash == item.recompute_hash()
    tampered = agreement_payload(amount_cents=123401)
    tampered.pop("agreement_hash", None)
    probe = AgreementProjection.model_construct(**tampered, agreement_hash=item.agreement_hash)
    assert probe.recompute_hash() != item.agreement_hash
    with pytest.raises(ValidationError):
        AgreementProjection(**tampered, agreement_hash=item.agreement_hash)


def test_award_response_requires_the_agreement_projection() -> None:
    with pytest.raises(ValidationError):
        AwardResponse.model_validate(
            {
                "transaction_id": "vf_1",
                "state": "AWARDED",
                "agreement_hash": HASH,
                "seller_token": "v1.token",
                "expires_at": NOW,
            }
        )


def test_funding_and_release_decisions_are_hash_bound() -> None:
    funding = FundingApprovalDecision(
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        approved=True,
        approved_by="demo-reviewer",
        note="looks good",
        decided_at=NOW,
        idempotency_key="fund:run-1:vf_1",
    )
    assert funding.agreement_hash == HASH
    with pytest.raises(ValidationError):
        FundingApprovalDecision(
            **{
                **funding.model_dump(),
                "agreement_hash": "not-a-hash",
            }
        )
    with pytest.raises(ValidationError):
        ReleaseApprovalDecision(
            run_id="run-1",
            transaction_id="vf_1",
            agreement_version=1,
            agreement_hash=HASH,
            approved=True,
            released_by="demo-reviewer",
            note="",
            override=True,
            decided_at=NOW,
            idempotency_key="release:run-1:vf_1",
        )


def test_agreement_review_envelope_round_trips_and_rejects_a_changed_hash() -> None:
    request = AgreementReviewRequest(
        party="seller",
        run_id="run-1",
        transaction_id="vf_1",
        agreement=projection(),
        seller_task_id="seller-task-1",
        seller_context_id="run-1",
        requested_at=NOW,
        idempotency_key="review:vf_1:1",
    )
    envelope = wrap_agreement_review_request(request)
    assert envelope["schema"] == AGREEMENT_REVIEW_REQUEST_SCHEMA
    assert envelope["schema_version"] == "1.0"

    decision = AgreementReviewResult(
        party="seller",
        status="accepted",
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=request.agreement.agreement_hash,
        offer_hash=request.agreement.offer_hash,
        actor_type="SELLER_AGENT",
        actor_id="northwind-audio",
        authority_ref="seller-mandate:northwind-audio:1",
        authority_snapshot={},
        verified_change_request_id=None,
        task_id="seller-task-1",
        context_id="run-1",
        reviewed_at=NOW,
    )
    assert parse_agreement_review_result(
        {
            "schema": AGREEMENT_REVIEW_RESULT_SCHEMA,
            "schema_version": "1.0",
            "payload": decision.model_dump(mode="json"),
        },
        expected_party="seller",
        expected_transaction_id="vf_1",
        expected_version=1,
        expected_hash=request.agreement.agreement_hash,
    ).status == "accepted"

    with pytest.raises(ValueError):
        parse_agreement_review_result(
            {
                "schema": AGREEMENT_REVIEW_RESULT_SCHEMA,
                "schema_version": "1.0",
                "payload": decision.model_dump(mode="json"),
            },
            expected_party="seller",
            expected_transaction_id="vf_1",
            expected_version=1,
            expected_hash="b" * 64,
        )


def test_verifund_task_envelope_round_trips_and_requires_known_skill() -> None:
    request = VerifundTaskRequest(
        skill=VerifundSkill.TRANSACTION_FUND,
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        payload={"approval": {"approved": True}},
        idempotency_key="fund:run-1:vf_1",
    )
    envelope = wrap_verifund_task_request(request)
    assert parse_verifund_task_request(envelope).skill == "verifund.transaction.fund"
    with pytest.raises(ValidationError):
        VerifundTaskRequest(
            skill="verifund.unknown",
            run_id="run-1",
            idempotency_key="x",
            payload={},
        )


def test_resume_envelope_round_trips_and_rejects_polling_checkpoints() -> None:
    resume = VerifundResumeRequest(
        run_id="run-1",
        task_id="task-1",
        checkpoint=VerifundCheckpoint.BUYER_REVIEW_REQUIRED,
        value={
            "party": "buyer",
            "status": "accepted",
            "transaction_id": "vf_1",
            "agreement_version": 1,
            "agreement_hash": HASH,
            "task_id": "buyer-task-1",
            "context_id": "run-1",
        },
        idempotency_key="resume:task-1:buyer-review",
    )
    envelope = wrap_verifund_resume_request(resume)
    assert envelope["schema"] == VERIFUND_RESUME_REQUEST_SCHEMA
    assert envelope["schema_version"] == "1.0"
    parsed = parse_verifund_resume_request(envelope)
    assert parsed.checkpoint == "buyer_review_required"
    assert parsed.value["status"] == "accepted"

    for polling in ("funding_pending", "evidence_pending"):
        with pytest.raises(ValidationError):
            VerifundResumeRequest(
                run_id="run-1",
                task_id="task-1",
                checkpoint=polling,
                value={},
                idempotency_key="resume:task-1:poll",
            )


def test_task_result_binds_status_checkpoint_and_approval_type() -> None:
    funding = VerifundTaskResult(
        skill=VerifundSkill.TRANSACTION_FUND,
        status="approval_required",
        task_id="task-1",
        checkpoint=VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED,
        approval_type="funding",
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        state="AGREED",
        data={"approval_type": "funding"},
        message="Funding requires a human decision.",
        next_action="approve_funding",
    )
    assert funding.checkpoint == "funding_approval_required"

    with pytest.raises(ValidationError):
        VerifundTaskResult.model_validate(
            {
                **funding.model_dump(),
                "checkpoint": "release_approval_required",
            }
        )
    with pytest.raises(ValidationError):
        VerifundTaskResult.model_validate(
            {
                **funding.model_dump(),
                "approval_type": None,
            }
        )
    with pytest.raises(ValidationError):
        VerifundTaskResult(
            skill=VerifundSkill.AGREEMENT_CREATE,
            status="input_required",
            task_id="task-1",
            run_id="run-1",
            approval_type="release",
        )


def test_buyer_agreement_contracts_carry_the_secret_reference_only() -> None:
    request = BuyerAgreementRequest(
        award=AwardRequest(
            run_id="run-1",
            buyer_id="demo-buyer",
            seller_id="northwind-audio",
            offer_id="offer-1",
            request_id="rfq-1",
            buyer_display_name="Demo Buyer",
            seller_display_name="Northwind Audio",
            amount_cents=123400,
            shipping_cents=3400,
            tax_cents=0,
            fees_cents=0,
            quantity=12,
            line_items=[
                {
                    "sku": "NC-700",
                    "name": "Nimbus NC-700 ANC Headset",
                    "quantity": 12,
                    "unit_price_cents": 10000,
                }
            ],
            delivery_days=7,
            warranty_months=24,
            returns_days=30,
            offer_round=1,
            offer_hash=HASH,
            offer_valid_until=NOW,
            inspection_period_hours=48,
            inspection_starts_on="DELIVERY_CONFIRMED",
            evidence_required=[
                "shipment_manifest",
                "delivery_confirmation",
                "invoice",
            ],
            remedies={
                "non_delivery": "cancel_and_refund",
                "late_delivery": "cancel_and_refund",
                "damaged_goods": "refund_or_replacement",
            },
            dispute_window_hours=72,
        ),
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        idempotency_key="agreement:run-1:offer-1",
    )
    assert request.award.run_id == "run-1"
    agreement = projection()
    response = BuyerAgreementResponse(
        transaction_id="vf_1",
        state="AWARDED",
        agreement=agreement,
        agreement_version=1,
        agreement_hash=agreement.agreement_hash,
        seller_token_ref="run:run-1:transaction:vf_1",
    )
    dumped = response.model_dump(mode="json")
    assert "seller_token" not in dumped
    assert dumped["seller_token_ref"] == "run:run-1:transaction:vf_1"


def test_buyer_purchase_order_contract_binds_and_hides_the_token() -> None:
    request = BuyerPurchaseOrderRequest(
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        idempotency_key="po:run-1:offer-1",
    )
    response = BuyerPurchaseOrderResponse(
        run_id=request.run_id,
        transaction_id=request.transaction_id,
        agreement_version=request.agreement_version,
        agreement_hash=request.agreement_hash,
        seller_id="northwind-audio",
        offer_id="offer-1",
        amount_cents=123400,
        seller_token_ref="run:run-1:transaction:vf_1",
        purchase_order={
            "request_id": "po-run-1-offer-1",
            "run_id": "run-1",
            "offer_id": "offer-1",
            "seller_id": "northwind-audio",
            "quantity": 12,
            "shipping_address": {
                "name": "Demo Buyer",
                "line1": "1 Market Street",
                "city": "San Francisco",
                "region": "CA",
                "postal_code": "94105",
                "country": "US",
            },
            "approval": {
                "approval_id": "approval-1",
                "approved_by": "demo-reviewer",
                "approved_at": NOW.isoformat(),
            },
            "idempotency_key": "run-1:offer-1",
            "expected_total_cents": 123400,
            "settlement_transaction_id": "vf_1",
            "agreement_hash": HASH,
        },
    )
    assert "settlement_token" not in response.purchase_order
    with pytest.raises(ValidationError):
        BuyerPurchaseOrderResponse.model_validate(
            {
                **response.model_dump(),
                "purchase_order": {
                    **response.purchase_order,
                    "settlement_token": "v1.secret",
                },
            }
        )
    with pytest.raises(ValidationError):
        BuyerPurchaseOrderResponse.model_validate(
            {
                **response.model_dump(),
                "purchase_order": {
                    **response.purchase_order,
                    "run_id": "run-2",
                },
            }
        )


def test_buyer_order_report_contract_binds_the_placed_order() -> None:
    request = BuyerOrderReportRequest(
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        idempotency_key="order:vf_1",
        order={
            "order_id": "ord-1",
            "offer_id": "offer-1",
            "seller_id": "northwind-audio",
            "quantity": 12,
            "total_cents": 123400,
            "currency": "USD",
            "tracking_number": "TRK-1",
            "reserved_at": NOW.isoformat(),
            "eta": "2026-11-03T12:00:00Z",
            "line_items": [],
        },
    )
    response = BuyerOrderReportResponse(
        run_id=request.run_id,
        transaction_id=request.transaction_id,
        agreement_version=1,
        agreement_hash=HASH,
        state="FULFILLMENT_PENDING",
        projection={
            "transaction_id": "vf_1",
            "state": "FULFILLMENT_PENDING",
        },
    )
    assert response.state == "FULFILLMENT_PENDING"
    with pytest.raises(ValidationError):
        BuyerOrderReportResponse(
            run_id=request.run_id,
            transaction_id="vf_other",
            agreement_version=1,
            agreement_hash=HASH,
            state="FULFILLMENT_PENDING",
            projection={
                "transaction_id": "vf_1",
                "state": "FULFILLMENT_PENDING",
            },
        )


@respx.mock
async def test_client_posts_buyer_review_with_actor_and_idempotency() -> None:
    route = respx.post(
        "http://control/transactions/vf_1/buyer-review"
    ).mock(return_value=httpx.Response(200, json={}))
    client = VerifundClient("http://control", ops_token="ops-token")
    await client.buyer_review(
        "vf_1",
        {
            "buyer_id": "demo-buyer",
            "agreement_version": 1,
            "agreement_hash": HASH,
            "decision": "accepted",
            "buyer_task_id": "buyer-task-1",
            "reviewed_at": NOW.isoformat(),
        },
        actor="buyer-agent",
        idempotency_key="buyer-review:vf_1:1",
    )
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer ops-token"
    assert request.headers["x-verifund-actor"] == "buyer-agent"
    assert request.headers["idempotency-key"] == "buyer-review:vf_1:1"
