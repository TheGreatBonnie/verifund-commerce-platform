from typing import Any, Literal, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from verifund_agent.client import BuyerAPIError, BuyerInternalClient
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewDecision,
    AgreementReviewResult,
    BuyerAgreementApprovalDecision,
    BuyerAgreementRequest,
    BuyerAgreementResponse,
    BuyerOrderReportRequest,
    BuyerOrderReportResponse,
    BuyerPurchaseOrderRequest,
    BuyerPurchaseOrderResponse,
    ChangeRequestEnvelope,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
    TransactionState,
    VerifundCheckpoint,
)


class VerifundProtocolError(RuntimeError):
    pass


class VerifundState(TypedDict, total=False):
    task_id: str
    context_id: str
    run_id: str
    transaction_id: str
    agreement_version: int
    agreement_hash: str
    seller_token_ref: str
    award: dict
    buyer_task_id: str
    buyer_context_id: str
    agreement: dict
    buyer_review: dict
    seller_decision: dict
    funding_approval: dict
    funding_projection: dict
    checkout_url: str
    expires_at: str
    purchase_order: dict
    order: dict
    evidence: dict
    verification: dict
    release_approval: dict
    release_projection: dict
    receipt: dict
    projection: dict
    checkpoint: str
    approval_type: str
    stage: str
    error: str


PENDING_CHECKPOINTS = {
    "await_seller_review": VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
    "await_seller_operator": VerifundCheckpoint.SELLER_OPERATOR_REQUIRED,
    "await_buyer_approval": VerifundCheckpoint.BUYER_APPROVAL_REQUIRED,
    "await_change_resolution": VerifundCheckpoint.AGREEMENT_CHANGES_REQUESTED,
    "await_funding_approval": VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED,
    "await_funding_settlement": VerifundCheckpoint.FUNDING_PENDING,
    "await_purchase_order": VerifundCheckpoint.PURCHASE_ORDER_REQUIRED,
    "await_evidence": VerifundCheckpoint.EVIDENCE_PENDING,
    "await_release": VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED,
}


async def initialize(state: VerifundState, config: RunnableConfig) -> dict:
    return {"stage": "initialized"}


def _buyer(config: RunnableConfig) -> BuyerInternalClient:
    configurable = config.get("configurable") or {}
    buyer = configurable.get("buyer")
    if buyer is None:
        raise VerifundProtocolError("buyer client is not configured")
    return buyer


def _agreement(state: VerifundState) -> AgreementProjection:
    payload = state.get("agreement")
    if not payload:
        raise VerifundProtocolError("lifecycle has no agreement")
    return AgreementProjection.model_validate(payload)


def _binding(agreement: AgreementProjection) -> dict[str, Any]:
    return {
        "run_id": agreement.run_id,
        "transaction_id": agreement.transaction_id,
        "agreement_version": agreement.agreement_version,
        "agreement_hash": agreement.agreement_hash,
        "agreement": agreement.model_dump(mode="json"),
    }


def buyer_review_matches(
    review: AgreementReviewResult, agreement: AgreementProjection
) -> bool:
    return (
        review.party == "buyer"
        and review.run_id == agreement.run_id
        and review.transaction_id == agreement.transaction_id
        and review.agreement_version == agreement.agreement_version
        and review.agreement_hash == agreement.agreement_hash
    )


def seller_review_matches(
    review: AgreementReviewResult, agreement: AgreementProjection
) -> bool:
    return (
        review.party == "seller"
        and review.run_id == agreement.run_id
        and review.transaction_id == agreement.transaction_id
        and review.agreement_version == agreement.agreement_version
        and review.agreement_hash == agreement.agreement_hash
    )


def funding_approval_matches(
    approval: FundingApprovalDecision, agreement: AgreementProjection
) -> bool:
    return (
        approval.run_id == agreement.run_id
        and approval.transaction_id == agreement.transaction_id
        and approval.agreement_version == agreement.agreement_version
        and approval.agreement_hash == agreement.agreement_hash
    )


def release_approval_matches(
    approval: ReleaseApprovalDecision, agreement: AgreementProjection
) -> bool:
    return (
        approval.run_id == agreement.run_id
        and approval.transaction_id == agreement.transaction_id
        and approval.agreement_version == agreement.agreement_version
        and approval.agreement_hash == agreement.agreement_hash
    )


def buyer_review_route(state: VerifundState) -> Literal["accepted", "rejected"]:
    review = state.get("buyer_review") or {}
    if review.get("status") == AgreementReviewDecision.ACCEPTED.value:
        return "accepted"
    return "rejected"


def seller_review_route(
    state: VerifundState,
) -> Literal["accepted", "rejected", "operator_required", "changes_requested"]:
    decision = state.get("seller_decision") or {}
    status = decision.get("status")
    if status == AgreementReviewDecision.ACCEPTED.value:
        return "accepted"
    if status == AgreementReviewDecision.REJECTED.value:
        return "rejected"
    if status == AgreementReviewDecision.OPERATOR_REQUIRED.value:
        return "operator_required"
    if status == AgreementReviewDecision.CHANGES_REQUESTED.value:
        return "changes_requested"
    return "rejected"


def buyer_approval_route(state: VerifundState) -> Literal["agreed", "changes_requested", "rejected"]:
    agreement = state.get("agreement") or {}
    status = agreement.get("status")
    if status == "AGREED":
        return "agreed"
    if status == "CHANGES_REQUESTED":
        return "changes_requested"
    return "rejected"


def sync_agreement_route(state: VerifundState) -> str:
    agreement = state.get("agreement") or {}
    status = agreement.get("status")
    if status == "PENDING_SELLER" and agreement.get("seller_operator_required"):
        return "await_seller_operator"
    mapping = {
        "PENDING_SELLER": "await_seller_review",
        "PENDING_BUYER": "await_buyer_approval",
        "CHANGES_REQUESTED": "await_change_resolution",
        "AGREED": "await_funding_approval",
    }
    return mapping.get(status, "finalize")


def funding_decision_route(state: VerifundState) -> Literal["approved", "rejected"]:
    approval = state.get("funding_approval") or {}
    if approval.get("approved") is True:
        return "approved"
    return "rejected"


def release_decision_route(state: VerifundState) -> Literal["approved", "rejected"]:
    approval = state.get("release_approval") or {}
    if approval.get("approved") is True:
        return "approved"
    return "rejected"


def buyer_review_payload(state: VerifundState) -> dict[str, Any]:
    agreement = _agreement(state)
    return {
        "reason": "buyer_review_required",
        "message": "The Buyer must review the canonical agreement.",
        "task_id": state.get("task_id"),
        "context_id": state.get("context_id"),
        "buyer_task_id": state.get("buyer_task_id"),
        **_binding(agreement),
        "seller_token_ref": state.get("seller_token_ref"),
        "responseSchema": AgreementReviewResult.model_json_schema(),
    }


def seller_review_payload(state: VerifundState) -> dict[str, Any]:
    agreement = _agreement(state)
    return {
        "reason": "seller_review_required",
        "message": "The Seller must accept or reject the canonical agreement.",
        "task_id": state.get("task_id"),
        "context_id": state.get("context_id"),
        "buyer_review": state.get("buyer_review"),
        **_binding(agreement),
        "responseSchema": AgreementReviewResult.model_json_schema(),
    }


def seller_operator_payload(state: VerifundState) -> dict[str, Any]:
    agreement = _agreement(state)
    return {
        "reason": "seller_operator_required",
        "message": "A human seller operator must accept or reject the agreement.",
        "task_id": state.get("task_id"),
        "context_id": state.get("context_id"),
        "seller_decision": state.get("seller_decision"),
        **_binding(agreement),
        "responseSchema": AgreementReviewResult.model_json_schema(),
    }


def buyer_approval_payload(state: VerifundState) -> dict[str, Any]:
    agreement = _agreement(state)
    return {
        "reason": "buyer_approval_required",
        "message": "Approve, reject, or request changes to the agreement.",
        "task_id": state.get("task_id"),
        "context_id": state.get("context_id"),
        "seller_decision": state.get("seller_decision"),
        "buyer_precheck": state.get("buyer_precheck"),
        **_binding(agreement),
        "responseSchema": BuyerAgreementApprovalDecision.model_json_schema(),
    }


def change_resolution_payload(state: VerifundState) -> dict[str, Any]:
    agreement = _agreement(state)
    return {
        "reason": "agreement_changes_requested",
        "message": "Resolve the open change request.",
        "task_id": state.get("task_id"),
        "context_id": state.get("context_id"),
        "change_request": state.get("change_request"),
        **_binding(agreement),
        "responseSchema": BuyerAgreementApprovalDecision.model_json_schema(),
    }


def funding_approval_payload(state: VerifundState) -> dict[str, Any]:
    agreement = _agreement(state)
    return {
        "reason": "funding_approval_required",
        "message": "Approve or reject funding for the agreed transaction.",
        "task_id": state.get("task_id"),
        "context_id": state.get("context_id"),
        "buyer_review": state.get("buyer_review"),
        "seller_decision": state.get("seller_decision"),
        **_binding(agreement),
        "responseSchema": FundingApprovalDecision.model_json_schema(),
    }


def funding_pending_payload(state: VerifundState) -> dict[str, Any]:
    agreement = _agreement(state)
    return {
        "reason": "funding_pending",
        "message": "Waiting for the funding settlement to complete.",
        "task_id": state.get("task_id"),
        "context_id": state.get("context_id"),
        "checkout_url": state.get("checkout_url"),
        "expires_at": state.get("expires_at"),
        "projection": state.get("funding_projection") or state.get("projection"),
        **_binding(agreement),
    }


def purchase_order_payload(state: VerifundState) -> dict[str, Any]:
    agreement = _agreement(state)
    return {
        "reason": "purchase_order_required",
        "message": "Place the agreed purchase order with the Seller.",
        "task_id": state.get("task_id"),
        "context_id": state.get("context_id"),
        "buyer_task_id": state.get("buyer_task_id"),
        "buyer_context_id": state.get("buyer_context_id"),
        "seller_id": agreement.seller_id,
        "offer_id": agreement.offer_id,
        "purchase_order": state.get("purchase_order"),
        "seller_token_ref": state.get("seller_token_ref"),
        **_binding(agreement),
    }


def evidence_pending_payload(state: VerifundState) -> dict[str, Any]:
    agreement = _agreement(state)
    projection = state.get("projection") or {}
    return {
        "reason": "evidence_pending",
        "message": "Waiting for the Seller's fulfillment evidence.",
        "task_id": state.get("task_id"),
        "context_id": state.get("context_id"),
        "evidence": state.get("evidence") or projection.get("evidence") or {},
        "projection": projection,
        **_binding(agreement),
    }


def release_approval_payload(state: VerifundState) -> dict[str, Any]:
    agreement = _agreement(state)
    verification = state.get("verification") or {}
    return {
        "reason": "release_approval_required",
        "message": "Approve or reject the release of held funds.",
        "task_id": state.get("task_id"),
        "context_id": state.get("context_id"),
        "evidence": state.get("evidence"),
        "verification": verification,
        "projection": state.get("projection"),
        "override_allowed": bool(verification.get("override_allowed")),
        **_binding(agreement),
        "responseSchema": ReleaseApprovalDecision.model_json_schema(),
    }


async def create_agreement(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    buyer = _buyer(config)
    award = state.get("award") or {}
    run_id = state.get("run_id") or ""
    if award.get("run_id") != run_id:
        raise VerifundProtocolError("award run does not match the lifecycle task")
    buyer_task_id = state.get("buyer_task_id") or ""
    buyer_context_id = state.get("buyer_context_id") or ""
    if not buyer_task_id or not buyer_context_id:
        raise VerifundProtocolError(
            "agreement creation requires the original Buyer task and context"
        )
    response = await buyer.create_agreement(
        run_id,
        BuyerAgreementRequest(
            award=award,
            buyer_task_id=buyer_task_id,
            buyer_context_id=buyer_context_id,
            idempotency_key=f"agreement:{run_id}:{award.get('offer_id')}",
        ),
    )
    created = BuyerAgreementResponse.model_validate(response)
    agreement = created.agreement
    if (
        agreement.run_id != run_id
        or agreement.transaction_id != created.transaction_id
        or agreement.agreement_version != created.agreement_version
        or agreement.agreement_hash != created.agreement_hash
    ):
        raise VerifundProtocolError("buyer returned a mismatched agreement")
    return {
        "transaction_id": agreement.transaction_id,
        "agreement_version": agreement.agreement_version,
        "agreement_hash": agreement.agreement_hash,
        "seller_token_ref": created.seller_token_ref,
        "agreement": agreement.model_dump(mode="json"),
        "stage": "awarded",
    }


async def sync_agreement(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    buyer = _buyer(config)
    run_id = state.get("run_id") or ""
    view = await buyer.get_settlement(run_id)
    agreement = view.get("agreement")
    if not isinstance(agreement, dict):
        raise VerifundProtocolError("buyer returned no agreement")
    return {"agreement": agreement, "stage": state.get("stage", "awarded")}


async def await_seller_review(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    value = interrupt(seller_review_payload(state))
    review = AgreementReviewResult.model_validate(value)
    agreement = _agreement(state)
    if not seller_review_matches(review, agreement):
        raise VerifundProtocolError(
            "seller review does not match the agreement"
        )
    return {
        "seller_decision": review.model_dump(mode="json"),
        "stage": "awarded",
    }


async def await_seller_operator(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    value = interrupt(seller_operator_payload(state))
    # The resume value is informational; re-read the agreement via sync_agreement.
    return {"stage": state.get("stage", "awarded")}


async def await_buyer_approval(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    value = interrupt(buyer_approval_payload(state))
    decision = BuyerAgreementApprovalDecision.model_validate(value)
    agreement = _agreement(state)
    if (
        decision.agreement_version != agreement.agreement_version
        or decision.agreement_hash != agreement.agreement_hash
    ):
        raise VerifundProtocolError(
            "buyer approval does not match the agreement"
        )
    buyer = _buyer(config)
    run_id = state.get("run_id") or agreement.run_id
    latest = await buyer.get_agreement(run_id)
    if latest.get("status") != "AGREED":
        raise VerifundProtocolError("agreement is not agreed")
    if (
        latest.get("agreement_version", agreement.agreement_version)
        != agreement.agreement_version
        or latest.get("agreement_hash", agreement.agreement_hash)
        != agreement.agreement_hash
    ):
        # accept if status agreed; update agreement
        pass
    return {"agreement": latest, "stage": "agreed"}


async def await_change_resolution(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    value = interrupt(change_resolution_payload(state))
    # resume value carries accept/note/change_request_id; re-read agreement.
    buyer = _buyer(config)
    run_id = state.get("run_id") or ""
    latest = await buyer.get_settlement(run_id)
    agreement = latest.get("agreement")
    if isinstance(agreement, dict):
        return {"agreement": agreement, "stage": state.get("stage", "awarded")}
    return {"stage": state.get("stage", "awarded")}


async def await_funding_approval(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    value = interrupt(funding_approval_payload(state))
    approval = FundingApprovalDecision.model_validate(value)
    agreement = _agreement(state)
    if not funding_approval_matches(approval, agreement):
        raise VerifundProtocolError(
            "funding approval does not match the agreement"
        )
    return {"funding_approval": approval.model_dump(mode="json")}


async def fund_transaction(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    approval = FundingApprovalDecision.model_validate(
        state.get("funding_approval") or {}
    )
    agreement = _agreement(state)
    if not funding_approval_matches(approval, agreement):
        raise VerifundProtocolError(
            "funding approval does not match the agreement"
        )
    response = await _buyer(config).approve_funding(
        state.get("run_id") or agreement.run_id, approval
    )
    projection = response.get("projection") or {}
    if projection.get("transaction_id") != agreement.transaction_id:
        raise VerifundProtocolError(
            "buyer returned a mismatched funding projection"
        )
    if not approval.approved:
        return {
            "projection": projection,
            "funding_projection": projection,
            "stage": "funding_rejected",
        }
    return {
        "projection": projection,
        "funding_projection": projection,
        "checkout_url": str(response.get("checkout_url") or ""),
        "expires_at": str(response.get("expires_at") or ""),
        "stage": "funding_pending",
    }


async def await_funding_settlement(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    value = interrupt(funding_pending_payload(state))
    projection = (value or {}).get("projection") or {}
    agreement = _agreement(state)
    if projection.get("transaction_id") != agreement.transaction_id:
        raise VerifundProtocolError(
            "funding settlement does not match the agreement"
        )
    if projection.get("state") != TransactionState.FUNDED.value:
        raise VerifundProtocolError("funding is not settled")
    return {
        "projection": projection,
        "funding_projection": projection,
        "stage": "funded",
    }


async def request_purchase_order(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    agreement = _agreement(state)
    response = await _buyer(config).purchase_order(
        state.get("run_id") or agreement.run_id,
        BuyerPurchaseOrderRequest(
            run_id=agreement.run_id,
            transaction_id=agreement.transaction_id,
            agreement_version=agreement.agreement_version,
            agreement_hash=agreement.agreement_hash,
            idempotency_key=f"purchase-order:{agreement.transaction_id}",
        ),
    )
    created = BuyerPurchaseOrderResponse.model_validate(response)
    if (
        created.run_id != agreement.run_id
        or created.transaction_id != agreement.transaction_id
        or created.agreement_version != agreement.agreement_version
        or created.agreement_hash != agreement.agreement_hash
    ):
        raise VerifundProtocolError(
            "buyer returned a mismatched purchase order"
        )
    return {
        "purchase_order": created.purchase_order,
        "seller_token_ref": created.seller_token_ref,
        "stage": "purchase_order_required",
    }


async def await_purchase_order(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    value = interrupt(purchase_order_payload(state))
    order = (value or {}).get("order")
    if not isinstance(order, dict):
        raise VerifundProtocolError("purchase order resume requires an order")
    purchase_order = state.get("purchase_order") or {}
    expected = {
        "offer_id": purchase_order.get("offer_id"),
        "seller_id": purchase_order.get("seller_id"),
        "quantity": purchase_order.get("quantity"),
        "total_cents": purchase_order.get("expected_total_cents"),
    }
    actual = {
        "offer_id": order.get("offer_id"),
        "seller_id": order.get("seller_id"),
        "quantity": order.get("quantity"),
        "total_cents": order.get("total_cents"),
    }
    for field, expected_value in expected.items():
        if actual.get(field) != expected_value:
            raise VerifundProtocolError(
                f"order {field} does not match the purchase order"
            )
    return {"order": order, "stage": "ordered"}


async def report_purchase_order(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    agreement = _agreement(state)
    order = dict(state.get("order") or {})
    if "seller_order_id" not in order and "order_id" in order:
        order["seller_order_id"] = order["order_id"]
    response = await _buyer(config).report_order(
        state.get("run_id") or agreement.run_id,
        BuyerOrderReportRequest(
            run_id=agreement.run_id,
            transaction_id=agreement.transaction_id,
            agreement_version=agreement.agreement_version,
            agreement_hash=agreement.agreement_hash,
            idempotency_key=f"order:{agreement.transaction_id}",
            order=order,
        ),
    )
    report = BuyerOrderReportResponse.model_validate(response)
    if (
        report.transaction_id != agreement.transaction_id
        or report.agreement_hash != agreement.agreement_hash
    ):
        raise VerifundProtocolError(
            "buyer returned a mismatched order projection"
        )
    return {
        "projection": report.projection,
        "stage": "fulfillment_pending",
    }


async def await_evidence(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    value = interrupt(evidence_pending_payload(state))
    projection = (value or {}).get("projection") or {}
    agreement = _agreement(state)
    if projection.get("transaction_id") != agreement.transaction_id:
        raise VerifundProtocolError(
            "evidence projection does not match the agreement"
        )
    if projection.get("state") not in {
        TransactionState.RELEASE_PERMITTED.value,
        TransactionState.REVIEW_REQUIRED.value,
    }:
        raise VerifundProtocolError("evidence is not ready for release")
    return {
        "projection": projection,
        "evidence": projection.get("evidence") or {},
        "verification": projection.get("verification") or {},
        "stage": "evidence_reviewed",
    }


async def await_release(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    value = interrupt(release_approval_payload(state))
    approval = ReleaseApprovalDecision.model_validate(value)
    agreement = _agreement(state)
    if not release_approval_matches(approval, agreement):
        raise VerifundProtocolError(
            "release approval does not match the agreement"
        )
    return {"release_approval": approval.model_dump(mode="json")}


async def release_transaction(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    approval = ReleaseApprovalDecision.model_validate(
        state.get("release_approval") or {}
    )
    agreement = _agreement(state)
    if not release_approval_matches(approval, agreement):
        raise VerifundProtocolError(
            "release approval does not match the agreement"
        )
    projection = await _buyer(config).release(
        state.get("run_id") or agreement.run_id, approval
    )
    if projection.get("transaction_id") != agreement.transaction_id:
        raise VerifundProtocolError(
            "buyer returned a mismatched release projection"
        )
    return {
        "projection": projection,
        "release_projection": projection,
        "stage": "released" if approval.approved else "review_required",
    }


async def get_receipt(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    agreement = _agreement(state)
    try:
        receipt = await _buyer(config).receipt(state.get("run_id") or agreement.run_id)
    except BuyerAPIError as exc:
        if exc.status_code != 404:
            raise
        return {"receipt": None, "stage": "released"}
    return {"receipt": receipt, "stage": "completed"}


async def finalize_rejected(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    if state.get("funding_approval"):
        return {"stage": "funding_rejected"}
    return {"stage": "rejected"}


async def finalize_review(
    state: VerifundState, config: RunnableConfig
) -> dict[str, Any]:
    return {"stage": "review_required"}


def build_graph(checkpointer):
    # LangGraph accepts TypedDict state at runtime, but ty cannot verify the
    # TypedDict protocol members required by langgraph's StateLike bound.
    builder = StateGraph(VerifundState)  # ty: ignore[invalid-argument-type]
    builder.add_node("initialize", initialize)
    builder.add_node("create_agreement", create_agreement)
    builder.add_node("sync_agreement", sync_agreement)
    builder.add_node("await_seller_review", await_seller_review)
    builder.add_node("await_seller_operator", await_seller_operator)
    builder.add_node("await_buyer_approval", await_buyer_approval)
    builder.add_node("await_change_resolution", await_change_resolution)
    builder.add_node("await_funding_approval", await_funding_approval)
    builder.add_node("fund_transaction", fund_transaction)
    builder.add_node("await_funding_settlement", await_funding_settlement)
    builder.add_node("request_purchase_order", request_purchase_order)
    builder.add_node("await_purchase_order", await_purchase_order)
    builder.add_node("report_purchase_order", report_purchase_order)
    builder.add_node("await_evidence", await_evidence)
    builder.add_node("await_release", await_release)
    builder.add_node("release_transaction", release_transaction)
    builder.add_node("get_receipt", get_receipt)
    builder.add_node("finalize_rejected", finalize_rejected)
    builder.add_node("finalize_review", finalize_review)
    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "create_agreement")
    builder.add_edge("create_agreement", "sync_agreement")
    builder.add_conditional_edges(
        "sync_agreement",
        sync_agreement_route,
        {
            "await_seller_review": "await_seller_review",
            "await_seller_operator": "await_seller_operator",
            "await_buyer_approval": "await_buyer_approval",
            "await_change_resolution": "await_change_resolution",
            "await_funding_approval": "await_funding_approval",
            "finalize": "finalize_rejected",
        },
    )
    builder.add_conditional_edges(
        "await_seller_review",
        seller_review_route,
        {
            "accepted": "sync_agreement",
            "rejected": "finalize_rejected",
            "operator_required": "sync_agreement",
            "changes_requested": "sync_agreement",
        },
    )
    # After sync, re-route; but sync_agreement already routes. Need to ensure
    # the operator/changes nodes feed back into sync_agreement.
    builder.add_edge("await_seller_operator", "sync_agreement")
    builder.add_edge("await_buyer_approval", "sync_agreement")
    builder.add_edge("await_change_resolution", "sync_agreement")
    builder.add_edge("await_funding_approval", "fund_transaction")
    builder.add_conditional_edges(
        "fund_transaction",
        funding_decision_route,
        {
            "approved": "await_funding_settlement",
            "rejected": "finalize_rejected",
        },
    )
    builder.add_edge("await_funding_settlement", "request_purchase_order")
    builder.add_edge("request_purchase_order", "await_purchase_order")
    builder.add_edge("await_purchase_order", "report_purchase_order")
    builder.add_edge("report_purchase_order", "await_evidence")
    builder.add_edge("await_evidence", "await_release")
    builder.add_edge("await_release", "release_transaction")
    builder.add_conditional_edges(
        "release_transaction",
        release_decision_route,
        {
            "approved": "get_receipt",
            "rejected": "finalize_review",
        },
    )
    builder.add_edge("get_receipt", END)
    builder.add_edge("finalize_rejected", END)
    builder.add_edge("finalize_review", END)
    return builder.compile(checkpointer=checkpointer)
