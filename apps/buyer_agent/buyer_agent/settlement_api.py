from __future__ import annotations

import secrets
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request, Response
from langgraph.types import Command
from pydantic import BaseModel, Field
from verifund_contracts import (
    CancelRequest,
    FlagReviewRequest,
    ReleaseRequest,
)

router = APIRouter()
REVIEWER = "console:reviewer"


class AdvanceBody(BaseModel):
    action: Literal["refresh"] = "refresh"


class ReleaseBody(BaseModel):
    released_by: str = Field(default=REVIEWER, min_length=1)
    note: str = ""
    override: bool = False


class ReviewBody(BaseModel):
    action: Literal["flag_review", "retry_payout"]
    reason: str = "manual_flag"
    note: str = ""


class CancelBody(BaseModel):
    reason_code: Literal[
        "buyer_rejected", "buyer_cancelled", "reviewer_cancelled"
    ]
    note: str = ""


class InternalCancelBody(BaseModel):
    reason_code: Literal[
        "buyer_rejected", "buyer_cancelled", "reviewer_cancelled"
    ]
    note: str = ""


class SellerTokenBody(BaseModel):
    run_id: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    seller_id: str = Field(min_length=1)
    purpose: str = Field(min_length=1)


def _services(request: Request) -> Any:
    return request.app.state.services


def _settlement_store(request: Request):
    store = getattr(_services(request), "store", None)
    return getattr(store, "settlement", None)


def console_authorized(request: Request) -> bool:
    expected = request.app.state.settings.console_api_token
    provided = request.headers.get("x-marketmesh-console-token", "")
    return bool(expected) and secrets.compare_digest(provided, expected)


def _require_console(request: Request) -> None:
    if not console_authorized(request):
        raise HTTPException(status_code=401, detail="unauthorized")


def _require_client(request: Request):
    client = getattr(_services(request), "settlement", None)
    store = _settlement_store(request)
    if client is None or store is None:
        raise HTTPException(status_code=503, detail="settlement unavailable")
    return client, store


async def load_settlement_projection(
    request: Request,
    run_id: str,
    *,
    actor: str = REVIEWER,
    refresh: bool = True,
) -> dict[str, Any] | None:
    services = _services(request)
    client = getattr(services, "settlement", None)
    store = _settlement_store(request)
    cached = await store.get_projection(run_id) if store is not None else None
    if client is None or store is None:
        return (
            {**cached, "settlement_unavailable": True} if cached else None
        )
    if not refresh:
        return {**cached, "settlement_unavailable": False} if cached else None
    if cached is None:
        return None
    try:
        projection = await client.get_state(
            cached["transaction_id"], actor=actor
        )
    except Exception:  # noqa: BLE001
        return {**cached, "settlement_unavailable": True}
    advanced = await store.save_projection(run_id, projection)
    if advanced:
        trace = getattr(services, "trace", None)
        recorder = getattr(trace, "record", None)
        if recorder is not None:
            await recorder(
                run_id,
                direction="internal",
                method="settlement_status",
                payload={
                    "transaction_id": projection["transaction_id"],
                    "state": projection["state"],
                    "last_seq": int(projection.get("last_seq") or 0),
                },
            )
    return {**projection, "settlement_unavailable": False}


async def _cached_transaction(request: Request, run_id: str) -> str:
    store = _settlement_store(request)
    cached = await store.get_projection(run_id) if store is not None else None
    if cached is None:
        raise HTTPException(status_code=404, detail="settlement not found")
    return str(cached["transaction_id"])


def _error(exc: Exception) -> HTTPException:
    status = getattr(exc, "status_code", 0) or 502
    return HTTPException(
        status_code=status,
        detail={
            "code": getattr(exc, "code", "settlement_unavailable"),
            "message": str(exc),
        },
    )


@asynccontextmanager
async def _run_lock(
    request: Request, run_id: str
) -> AsyncGenerator[None, None]:
    coordinator = getattr(_services(request), "coordinator", None)
    if coordinator is None:
        yield
        return
    if coordinator.is_locked(run_id):
        raise HTTPException(
            status_code=409, detail="settlement action already in progress"
        )
    async with coordinator.lock(run_id):
        yield


def _public_interrupt(result: dict[str, Any] | None) -> dict[str, Any] | None:
    if not result or "__interrupt__" not in result:
        return None
    # The reference carries only run/transaction/seller IDs. The seller token
    # is resolved server-side by the orchestrator and never leaves the buyer.
    return dict(result["__interrupt__"][0].value)


async def _resume_graph(
    request: Request, run_id: str, value: dict[str, Any]
) -> dict[str, Any] | None:
    executor = getattr(request.app.state, "executor", None)
    graph = getattr(executor, "graph", None)
    if graph is None:
        return None
    config = {"configurable": {"thread_id": run_id}}
    snapshot = await graph.aget_state(config)
    if not getattr(snapshot, "next", None):
        return None
    return await graph.ainvoke(Command(resume=value), config=config)


async def _after_action(
    request: Request, run_id: str, result: dict[str, Any]
) -> dict[str, Any]:
    store = _settlement_store(request)
    await store.save_projection(run_id, result)
    await _resume_graph(request, run_id, {"action": "refresh"})
    return {"run_id": run_id, "settlement": result}


@router.get("/api/runs/{run_id}/settlement")
async def get_settlement(run_id: str, request: Request) -> dict[str, Any]:
    _require_console(request)
    projection = await load_settlement_projection(request, run_id)
    if projection is None:
        if getattr(_services(request), "settlement", None) is None:
            raise HTTPException(
                status_code=503, detail="settlement unavailable"
            )
        raise HTTPException(status_code=404, detail="settlement not found")
    return projection


@router.post("/api/runs/{run_id}/settlement/advance")
async def advance_settlement(
    run_id: str, body: AdvanceBody, request: Request
) -> dict[str, Any]:
    _require_console(request)
    async with _run_lock(request, run_id):
        result = await _resume_graph(
            request, run_id, body.model_dump(mode="json")
        )
        if result is None:
            raise HTTPException(
                status_code=409, detail="no settlement interrupt is pending"
            )
        projection = await load_settlement_projection(request, run_id)
        return {
            "run_id": run_id,
            "settlement": projection,
            "interrupt": _public_interrupt(result),
        }


@router.post("/api/runs/{run_id}/settlement/release")
async def release_settlement(
    run_id: str, body: ReleaseBody, request: Request
) -> dict[str, Any]:
    _require_console(request)
    client, _ = _require_client(request)
    async with _run_lock(request, run_id):
        transaction_id = await _cached_transaction(request, run_id)
        try:
            result = await client.release(
                transaction_id,
                ReleaseRequest(
                    released_by=body.released_by,
                    note=body.note,
                    override=body.override,
                ),
                actor=REVIEWER,
            )
        except Exception as exc:
            raise _error(exc) from exc
        return await _after_action(request, run_id, result)


@router.post("/api/runs/{run_id}/settlement/review")
async def review_settlement(
    run_id: str, body: ReviewBody, request: Request
) -> dict[str, Any]:
    _require_console(request)
    client, _ = _require_client(request)
    async with _run_lock(request, run_id):
        transaction_id = await _cached_transaction(request, run_id)
        try:
            if body.action == "flag_review":
                result = await client.flag_review(
                    transaction_id,
                    FlagReviewRequest(reason=body.reason, note=body.note),
                    actor=REVIEWER,
                )
            else:
                result = await client.retry_payout(
                    transaction_id, actor=REVIEWER
                )
        except Exception as exc:
            raise _error(exc) from exc
        return await _after_action(request, run_id, result)


@router.post("/api/runs/{run_id}/settlement/cancel")
async def cancel_settlement(
    run_id: str, body: CancelBody, request: Request
) -> dict[str, Any]:
    _require_console(request)
    client, _ = _require_client(request)
    async with _run_lock(request, run_id):
        transaction_id = await _cached_transaction(request, run_id)
        try:
            result = await client.cancel(
                transaction_id,
                CancelRequest(reason_code=body.reason_code, note=body.note),
                actor=REVIEWER,
            )
        except Exception as exc:
            raise _error(exc) from exc
        return await _after_action(request, run_id, result)


@router.get("/api/runs/{run_id}/settlement/receipt")
async def get_receipt(run_id: str, request: Request) -> dict[str, Any]:
    _require_console(request)
    client, _ = _require_client(request)
    transaction_id = await _cached_transaction(request, run_id)
    try:
        return await client.get_receipt(transaction_id, actor=REVIEWER)
    except Exception as exc:
        raise _error(exc) from exc


@router.get("/api/runs/{run_id}/settlement/evidence/{evidence_id}")
async def get_evidence(
    run_id: str, evidence_id: str, request: Request
) -> Response:
    _require_console(request)
    client, _ = _require_client(request)
    transaction_id = await _cached_transaction(request, run_id)
    try:
        content, media_type, filename = await client.get_evidence(
            transaction_id, evidence_id, actor=REVIEWER
        )
    except Exception as exc:
        raise _error(exc) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "content-disposition": f'attachment; filename="{filename}"'
        },
    )


@router.post("/internal/settlement/seller-token")
async def get_seller_token(
    body: SellerTokenBody, request: Request
) -> dict[str, Any]:
    expected = request.app.state.settings.internal_api_token
    provided = request.headers.get("x-marketmesh-internal-token", "")
    if not expected or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="unauthorized")
    store = _settlement_store(request)
    if store is None:
        raise HTTPException(status_code=503, detail="settlement unavailable")
    secret = await store.get_secret_by_transaction(body.transaction_id)
    if secret is None:
        raise HTTPException(status_code=404, detail="seller token not found")
    if (
        str(secret["run_id"]) != body.run_id
        or str(secret["seller_id"]) != body.seller_id
    ):
        raise HTTPException(status_code=403, detail="seller token mismatch")
    expires_at = datetime.fromisoformat(
        str(secret["expires_at"])
    )
    if expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=409, detail="seller token expired")
    return {
        "seller_token": secret["seller_token"],
        "expires_at": secret["expires_at"],
    }
from verifund_contracts import (
    BuyerAgreementRequest,
    BuyerOrderReportRequest,
    BuyerPurchaseOrderRequest,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
)

from buyer_agent.agreement_service import AgreementBindingError


def verifund_agent_authorized(request: Request) -> bool:
    expected = request.app.state.settings.verifund_agent_internal_token
    provided = request.headers.get("x-verifund-agent-token", "")
    return bool(expected) and secrets.compare_digest(provided, expected)


def _require_verifund_agent(request: Request) -> None:
    if not verifund_agent_authorized(request):
        raise HTTPException(status_code=401, detail="unauthorized")


def _agreements(request: Request):
    value = getattr(_services(request), "agreements", None)
    if value is None:
        raise HTTPException(status_code=503, detail="agreement service unavailable")
    return value


def _binding_error(exc: AgreementBindingError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": "binding_mismatch", "message": str(exc)},
    )


@router.get("/internal/runs/{run_id}/settlement")
async def internal_get_settlement(run_id: str, request: Request) -> dict[str, Any]:
    _require_verifund_agent(request)
    try:
        return await _agreements(request).view(run_id)
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.post("/internal/runs/{run_id}/settlement/agreement")
async def internal_create_agreement(
    run_id: str, body: BuyerAgreementRequest, request: Request
) -> dict[str, Any]:
    _require_verifund_agent(request)
    if body.award.run_id != run_id:
        raise HTTPException(status_code=403, detail="run does not match the award")
    try:
        return await _agreements(request).create_agreement(run_id, body)
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.post("/internal/runs/{run_id}/settlement/approve-funding")
async def internal_approve_funding(
    run_id: str,
    body: FundingApprovalDecision,
    request: Request,
    defer_checkout: bool = False,
) -> dict[str, Any]:
    _require_verifund_agent(request)
    if body.run_id != run_id:
        raise HTTPException(status_code=403, detail="run does not match the decision")
    try:
        return await _agreements(request).approve_funding(
            run_id, body, defer_checkout=defer_checkout
        )
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.post("/internal/runs/{run_id}/settlement/prepare-funding")
async def internal_prepare_funding(run_id: str, request: Request) -> dict[str, Any]:
    _require_verifund_agent(request)
    try:
        return await _agreements(request).prepare_funding(run_id)
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.post("/internal/runs/{run_id}/settlement/cancel")
async def internal_cancel(
    run_id: str, body: InternalCancelBody, request: Request
) -> dict[str, Any]:
    _require_verifund_agent(request)
    try:
        return await _agreements(request).cancel(
            run_id, reason_code=body.reason_code, note=body.note
        )
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.post("/internal/runs/{run_id}/settlement/purchase-order")
async def internal_purchase_order(
    run_id: str, body: BuyerPurchaseOrderRequest, request: Request
) -> dict[str, Any]:
    _require_verifund_agent(request)
    if body.run_id != run_id:
        raise HTTPException(status_code=403, detail="run does not match the request")
    try:
        return await _agreements(request).purchase_order(run_id, body)
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.post("/internal/runs/{run_id}/settlement/order")
async def internal_order(
    run_id: str, body: BuyerOrderReportRequest, request: Request
) -> dict[str, Any]:
    _require_verifund_agent(request)
    if body.run_id != run_id:
        raise HTTPException(status_code=403, detail="run does not match the request")
    try:
        return await _agreements(request).order(run_id, body)
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.post("/internal/runs/{run_id}/settlement/release")
async def internal_release(
    run_id: str, body: ReleaseApprovalDecision, request: Request
) -> dict[str, Any]:
    _require_verifund_agent(request)
    if body.run_id != run_id:
        raise HTTPException(status_code=403, detail="run does not match the decision")
    try:
        return await _agreements(request).release(run_id, body)
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.get("/internal/runs/{run_id}/settlement/receipt")
async def internal_receipt(run_id: str, request: Request) -> dict[str, Any]:
    _require_verifund_agent(request)
    try:
        return await _agreements(request).receipt(run_id)
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc


@router.get("/internal/runs/{run_id}/settlement/evidence/{evidence_id}")
async def internal_evidence(
    run_id: str, evidence_id: str, request: Request
) -> Response:
    _require_verifund_agent(request)
    try:
        content, media_type, filename = await _agreements(request).evidence(
            run_id, evidence_id
        )
    except AgreementBindingError as exc:
        raise _binding_error(exc) from exc
    return Response(
        content=content,
        media_type=media_type,
        headers={"content-disposition": f'attachment; filename="{filename}"'},
    )
