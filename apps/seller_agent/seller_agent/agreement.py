from __future__ import annotations

from datetime import UTC, datetime

from verifund_contracts import (
    AgreementReviewDecision,
    AgreementReviewRequest,
    AgreementReviewResult,
)


def _result(
    request: AgreementReviewRequest,
    *,
    status: AgreementReviewDecision,
    reason_code: str | None = None,
    note: str = "",
) -> AgreementReviewResult:
    return AgreementReviewResult(
        party="seller",
        status=status,
        run_id=request.run_id,
        transaction_id=request.transaction_id,
        agreement_version=request.agreement.agreement_version,
        agreement_hash=request.agreement.agreement_hash,
        task_id=request.seller_task_id or "",
        context_id=request.seller_context_id or "",
        reviewed_at=datetime.now(UTC),
        reason_code=reason_code,
        note=note,
    )


async def review_agreement(policy, store, request: AgreementReviewRequest) -> AgreementReviewResult:
    agreement = request.agreement
    if agreement.seller_id != policy.seller_id:
        return _result(
            request,
            status=AgreementReviewDecision.REJECTED,
            reason_code="terms_mismatch",
            note="Agreement seller does not match this seller.",
        )
    offer = await store.get_offer(agreement.offer_id)
    if offer is None:
        return _result(
            request,
            status=AgreementReviewDecision.REJECTED,
            reason_code="terms_mismatch",
            note="Offer is unknown to this seller.",
        )
    expected_lines = [
        (
            item.sku,
            item.name,
            item.quantity,
            item.unit_price_cents,
            item.warranty_addon_cents,
        )
        for item in agreement.line_items
    ]
    stored_lines = [
        (
            item.sku,
            item.name,
            item.quantity,
            item.unit_price_cents,
            item.warranty_addon_cents,
        )
        for item in offer.line_items
    ]
    if (
        offer.seller_id != policy.seller_id
        or offer.total_cents != agreement.amount_cents
        or offer.currency != agreement.currency
        or stored_lines != expected_lines
    ):
        return _result(
            request,
            status=AgreementReviewDecision.REJECTED,
            reason_code="terms_mismatch",
            note="Agreement terms do not match the stored offer.",
        )
    return _result(
        request,
        status=AgreementReviewDecision.ACCEPTED,
        note="Offer, quantity, and terms match.",
    )
