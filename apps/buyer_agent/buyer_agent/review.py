from __future__ import annotations

from a2a.types.a2a_pb2 import Message
from commerce_core.a2a_parts import first_envelope
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewRequest,
    AgreementReviewResult,
    parse_agreement_review_request,
    parse_agreement_review_result,
)


def parse_review_envelope(message: Message) -> AgreementReviewRequest:
    envelope = first_envelope(message)
    if envelope is None:
        raise ValueError("agreement review requires a structured envelope")
    request = parse_agreement_review_request(envelope)
    if request.party != "buyer":
        raise ValueError("buyer agent cannot accept a seller review envelope")
    if not request.buyer_task_id or not request.buyer_context_id:
        raise ValueError("buyer review requires the original task and context")
    return request


def parse_review_result_envelope(
    message: Message, agreement: AgreementProjection
) -> AgreementReviewResult:
    envelope = first_envelope(message)
    if envelope is None:
        raise ValueError("agreement review requires a structured envelope")
    return parse_agreement_review_result(
        envelope,
        expected_party="seller",
        expected_transaction_id=agreement.transaction_id,
        expected_version=agreement.agreement_version,
        expected_hash=agreement.agreement_hash,
    )


def resume_value(request: AgreementReviewRequest) -> dict:
    return {"agreement": request.agreement.model_dump(mode="json")}


def seller_resume_value(result: AgreementReviewResult) -> dict:
    return {"seller_decision": result.model_dump(mode="json")}
