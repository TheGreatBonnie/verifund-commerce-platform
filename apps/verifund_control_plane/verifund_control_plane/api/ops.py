from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from verifund_contracts import (
    AcceptRequest,
    ApproveRequest,
    AwardRequest,
    BuyerAgreementReviewRequest,
    CancelRequest,
    EvidenceList,
    FlagReviewRequest,
    FundRequest,
    PurchaseOrderReport,
    RejectRequest,
    ReleaseRequest,
    SellerTokenRequest,
)

from verifund_control_plane.errors import VerifundError

router = APIRouter(prefix="")


class AttachFundingOrderRequest(BaseModel):
    order_id: str = Field(min_length=1)


def _service(request: Request):
    return request.app.state.service


def _settings(request: Request):
    return request.app.state.settings


async def require_ops(request: Request) -> None:
    expected = _settings(request).ops_token
    provided = request.headers.get("authorization", "")
    if not provided.startswith("Bearer ") or not secrets.compare_digest(
        provided.removeprefix("Bearer "), expected
    ):
        raise VerifundError("unauthorized", "ops token is required", status_code=401)


def actor(request: Request) -> str:
    return request.headers.get("x-verifund-actor", "buyer-agent")


def idempotency_key(request: Request) -> str | None:
    return request.headers.get("idempotency-key")


@router.post("/awards", status_code=201, dependencies=[Depends(require_ops)])
async def create_award(body: AwardRequest, request: Request) -> dict[str, Any]:
    return await _service(request).award(
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.post(
    "/transactions/{transaction_id}/buyer-review",
    dependencies=[Depends(require_ops)],
)
async def buyer_review(
    transaction_id: str, body: BuyerAgreementReviewRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).record_buyer_review(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.get("/transactions", dependencies=[Depends(require_ops)])
async def list_transactions(
    request: Request,
    run_id: str | None = None,
    state: str | None = None,
    seller_id: str | None = None,
) -> list[dict[str, Any]]:
    return await _service(request).list_transactions(
        actor=actor(request),
        run_id=run_id,
        state=state,
        seller_id=seller_id,
    )


@router.get("/transactions/{transaction_id}", dependencies=[Depends(require_ops)])
async def get_transaction(transaction_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).get_transaction(
        transaction_id, actor=actor(request)
    )


@router.get(
    "/transactions/{transaction_id}/state", dependencies=[Depends(require_ops)]
)
async def get_state(transaction_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).get_transaction(
        transaction_id, actor=actor(request)
    )


@router.get(
    "/transactions/{transaction_id}/events", dependencies=[Depends(require_ops)]
)
async def get_events(
    transaction_id: str, request: Request, after_seq: int = 0
) -> list[dict[str, Any]]:
    return await _service(request).events(transaction_id, after_seq=after_seq)


@router.post(
    "/transactions/{transaction_id}/accept", dependencies=[Depends(require_ops)]
)
async def accept(
    transaction_id: str, body: AcceptRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).accept(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.post(
    "/transactions/{transaction_id}/reject", dependencies=[Depends(require_ops)]
)
async def reject(
    transaction_id: str, body: RejectRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).reject(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.post(
    "/transactions/{transaction_id}/approve", dependencies=[Depends(require_ops)]
)
async def approve(
    transaction_id: str, body: ApproveRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).approve(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.post(
    "/transactions/{transaction_id}/cancel", dependencies=[Depends(require_ops)]
)
async def cancel(
    transaction_id: str, body: CancelRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).cancel(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.post(
    "/transactions/{transaction_id}/fund", dependencies=[Depends(require_ops)]
)
async def fund(
    transaction_id: str, body: FundRequest, request: Request
) -> dict[str, Any]:
    result = await _service(request).fund(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )
    return result.model_dump(mode="json")


@router.get(
    "/transactions/{transaction_id}/evidence", dependencies=[Depends(require_ops)]
)
async def list_evidence(transaction_id: str, request: Request) -> dict[str, Any]:
    await _service(request).repo.get_transaction(transaction_id)
    items = await _service(request).repo.list_evidence(transaction_id)
    return EvidenceList(items=items).model_dump(mode="json")


@router.get(
    "/transactions/{transaction_id}/evidence/{evidence_id}",
    dependencies=[Depends(require_ops)],
)
async def download_evidence(
    transaction_id: str, evidence_id: str, request: Request
) -> Response:
    item = await _service(request).repo.get_evidence(transaction_id, evidence_id)
    return Response(
        content=request.app.state.evidence_store.read(item.sha256, item.storage_key),
        media_type=item.media_type,
        headers={
            "content-disposition": f'attachment; filename="{item.original_filename}"'
        },
    )


@router.post(
    "/transactions/{transaction_id}/purchase-order",
    dependencies=[Depends(require_ops)],
)
async def report_purchase_order(
    transaction_id: str, body: PurchaseOrderReport, request: Request
) -> dict[str, Any]:
    return await _service(request).report_purchase_order(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.post(
    "/transactions/{transaction_id}/verify",
    dependencies=[Depends(require_ops)],
)
async def verify(transaction_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).verify(
        transaction_id, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/flag-review",
    dependencies=[Depends(require_ops)],
)
async def flag_review(
    transaction_id: str, body: FlagReviewRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).flag_review(
        transaction_id,
        body,
        actor=actor(request),
        idempotency_key=idempotency_key(request),
    )


@router.post(
    "/transactions/{transaction_id}/release",
    dependencies=[Depends(require_ops)],
)
async def release(
    transaction_id: str, body: ReleaseRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).release(
        transaction_id, body, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/payout",
    dependencies=[Depends(require_ops)],
)
async def retry_payout(transaction_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).retry_payout(
        transaction_id, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/payout/refresh",
    dependencies=[Depends(require_ops)],
)
async def refresh_payout(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    return await _service(request).refresh_payout(
        transaction_id, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/funding/prepare",
    dependencies=[Depends(require_ops)],
)
async def prepare_funding(transaction_id: str, request: Request) -> dict[str, Any]:
    return await _service(request).prepare_funding(transaction_id, actor=actor(request))


@router.post(
    "/transactions/{transaction_id}/funding/attach-order",
    dependencies=[Depends(require_ops)],
)
async def attach_funding_order(
    transaction_id: str, body: AttachFundingOrderRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).attach_funding_order(
        transaction_id, body.order_id, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/funding/refresh",
    dependencies=[Depends(require_ops)],
)
async def refresh_funding(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    return await _service(request).refresh_funding(
        transaction_id, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/seller-token",
    dependencies=[Depends(require_ops)],
)
async def reissue_seller_token(
    transaction_id: str, body: SellerTokenRequest, request: Request
) -> dict[str, Any]:
    return await _service(request).reissue_seller_token(
        transaction_id, body, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/seller-token/revoke",
    dependencies=[Depends(require_ops)],
)
async def revoke_seller_token(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    return await _service(request).revoke_seller_token(
        transaction_id, actor=actor(request)
    )


@router.post(
    "/transactions/{transaction_id}/issue-buyer-token",
    dependencies=[Depends(require_ops)],
)
async def issue_buyer_token(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    raise VerifundError(
        "gone",
        "buyer bearer tokens are not used; authenticate via Clerk or internal service auth",
        status_code=410,
    )


@router.post(
    "/transactions/{transaction_id}/issue-invitation",
    dependencies=[Depends(require_ops)],
)
async def issue_invitation(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    token = await _service(request).issue_invitation(
        transaction_id, actor=actor(request)
    )
    return {"token": token}


@router.get(
    "/transactions/{transaction_id}/dispute-context",
    dependencies=[Depends(require_ops)],
)
async def dispute_context(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    return await _service(request).dispute_decision_context(transaction_id)


@router.post(
    "/transactions/{transaction_id}/dispute-decision",
    dependencies=[Depends(require_ops)],
)
async def dispute_decision(transaction_id: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    return await _service(request).dispute_decision(
        transaction_id,
        decision=body.get("decision"),
        remedy=body.get("remedy"),
        reviewer=body.get("reviewer"),
        actor=actor(request),
    )


@router.post(
    "/transactions/{transaction_id}/resolve-system-failure",
    dependencies=[Depends(require_ops)],
)
async def resolve_system_failure(transaction_id: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    return await _service(request).resolve_system_failure(
        transaction_id,
        resolution=body.get("resolution", "release"),
        actor=actor(request),
    )


@router.post(
    "/transactions/{transaction_id}/return-to-remediation",
    dependencies=[Depends(require_ops)],
)
async def return_to_remediation(transaction_id: str, request: Request) -> dict[str, Any]:
    body = await request.json()
    return await _service(request).return_to_remediation(
        transaction_id,
        note=body.get("note", ""),
        actor=actor(request),
    )


@router.get(
    "/transactions/{transaction_id}/receipt",
    dependencies=[Depends(require_ops)],
)
async def get_receipt(
    transaction_id: str, request: Request
) -> dict[str, Any]:
    return await _service(request).get_receipt(
        transaction_id, actor=actor(request)
    )


@router.post("/reconciler/run", dependencies=[Depends(require_ops)])
async def run_reconciler(request: Request) -> dict[str, Any]:
    return await request.app.state.reconciler.run_once()
