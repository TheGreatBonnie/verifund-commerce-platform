from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from a2a.types.a2a_pb2 import Role
from commerce_core.a2a_parts import make_message, part_value
from commerce_core.contracts import Order, PurchaseOrderRequest
from commerce_core.extension import wrap_payload
from verifund_contracts import (
    AgreementProjection,
    AgreementReviewDecision,
    AgreementReviewRequest,
    AgreementReviewResult,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
    VerifundCheckpoint,
    VerifundResumeRequest,
    VerifundSkill,
    VerifundTaskRequest,
    VerifundTaskResult,
    parse_agreement_review_result,
    parse_verifund_task_result,
    wrap_agreement_review_request,
    wrap_agreement_review_result,
    wrap_verifund_resume_request,
    wrap_verifund_task_request,
)

from orchestrator_agent.mediation import (
    _a2a_send,
    _buyer_response,
    _inject_settlement_token,
    _redact_settlement,
    _resolve_seller_token,
    _resolve_settlement_token,
)

Sender = Callable[..., Awaitable[list]]
TokenResolver = Callable[..., str]
SettlementResolver = Callable[..., Awaitable[str]]


class VerifundProtocolError(RuntimeError):
    """A Verifund, Buyer, or Seller result broke the lifecycle binding."""


@dataclass(frozen=True)
class VerifundTaskHandle:
    task_id: str
    context_id: str
    run_id: str

    def as_dict(self) -> dict[str, str]:
        return {
            "task_id": self.task_id,
            "context_id": self.context_id,
            "run_id": self.run_id,
        }


def _base_url(card_url: str) -> str:
    return card_url.split("/.well-known", 1)[0].rstrip("/")


def _review_matches(
    result: AgreementReviewResult,
    agreement: AgreementProjection,
    party: str,
) -> bool:
    return (
        result.party == party
        and result.run_id == agreement.run_id
        and result.transaction_id == agreement.transaction_id
        and result.agreement_version == agreement.agreement_version
        and result.agreement_hash == agreement.agreement_hash
    )


def _review_summary(value: Any) -> dict[str, Any] | None:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if not isinstance(value, dict):
        return None
    status = value.get("status")
    if status not in {
        AgreementReviewDecision.ACCEPTED.value,
        AgreementReviewDecision.REJECTED.value,
    }:
        return None
    return {
        "status": status,
        "agreement_version": value.get("agreement_version"),
        "agreement_hash": value.get("agreement_hash"),
    }


class VerifundA2AClient:
    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        send: Sender = _a2a_send,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._send = send

    async def _exchange(
        self,
        envelope: dict[str, Any],
        *,
        task_id: str | None = None,
        context_id: str | None = None,
    ) -> tuple[str, str, VerifundTaskResult]:
        message = make_message(
            role=Role.ROLE_USER,
            text="Verifund lifecycle task.",
            context_id=context_id or "",
            task_id=task_id,
            envelope=envelope,
        )
        frames = await self._send(self.base_url, message, token=self.token)
        resolved_task = task_id or ""
        resolved_context = context_id or ""
        result: VerifundTaskResult | None = None
        for frame in frames:
            artifacts = []
            if hasattr(frame, "WhichOneof"):
                try:
                    kind = frame.WhichOneof("payload")
                except ValueError:
                    kind = None
            else:
                kind = None
            if kind == "artifact_update":
                resolved_task = frame.artifact_update.task_id or resolved_task
                resolved_context = (
                    frame.artifact_update.context_id or resolved_context
                )
                artifacts = [frame.artifact_update.artifact]
            elif kind == "task":
                resolved_task = frame.task.id or resolved_task
                resolved_context = frame.task.context_id or resolved_context
                artifacts = list(frame.task.artifacts)
            elif kind == "status_update":
                resolved_task = frame.status_update.task_id or resolved_task
                resolved_context = (
                    frame.status_update.context_id or resolved_context
                )
            # Direct event fallbacks
            if not kind:
                if hasattr(frame, "artifact_update"):
                    au = frame.artifact_update
                    resolved_task = getattr(au, "task_id", None) or resolved_task
                    resolved_context = getattr(au, "context_id", None) or resolved_context
                    artifacts = [au.artifact] if getattr(au, "artifact", None) else []
                elif hasattr(frame, "task") and getattr(frame, "task", None) is not None:
                    t = frame.task
                    resolved_task = getattr(t, "id", None) or resolved_task
                    resolved_context = getattr(t, "context_id", None) or resolved_context
                    artifacts = list(getattr(t, "artifacts", []) or [])
                elif hasattr(frame, "status_update"):
                    su = frame.status_update
                    resolved_task = getattr(su, "task_id", None) or resolved_task
                    resolved_context = getattr(su, "context_id", None) or resolved_context
                elif hasattr(frame, "artifact"):
                    resolved_task = getattr(frame, "task_id", None) or resolved_task
                    resolved_context = getattr(frame, "context_id", None) or resolved_context
                    artifacts = [frame.artifact]
            for artifact in artifacts:
                for part in getattr(artifact, "parts", []):
                    value = part_value(part)
                    if not isinstance(value, dict):
                        continue
                    try:
                        result = parse_verifund_task_result(value)
                    except ValueError:
                        continue
        if not resolved_task:
            raise VerifundProtocolError("Verifund returned no task id")
        if result is None:
            raise VerifundProtocolError(
                "Verifund returned no structured result"
            )
        return resolved_task, resolved_context or resolved_task, result

    async def start(
        self,
        *,
        run_id: str,
        award: dict[str, Any],
        buyer_task_id: str,
        buyer_context_id: str,
        idempotency_key: str,
    ) -> tuple[VerifundTaskHandle, VerifundTaskResult]:
        request = VerifundTaskRequest(
            skill=VerifundSkill.AGREEMENT_CREATE,
            run_id=run_id,
            payload={
                "award": award,
                "buyer_task_id": buyer_task_id,
                "buyer_context_id": buyer_context_id,
            },
            idempotency_key=idempotency_key,
        )
        task_id, context_id, result = await self._exchange(
            wrap_verifund_task_request(request)
        )
        return VerifundTaskHandle(task_id, context_id, run_id), result

    async def status(
        self, handle: VerifundTaskHandle, *, transaction_id: str | None = None
    ) -> VerifundTaskResult:
        request = VerifundTaskRequest(
            skill=VerifundSkill.TRANSACTION_STATUS,
            run_id=handle.run_id,
            transaction_id=transaction_id,
            idempotency_key=f"status:{handle.task_id}:{uuid.uuid4().hex}",
        )
        task_id, context_id, result = await self._exchange(
            wrap_verifund_task_request(request),
            task_id=handle.task_id,
            context_id=handle.context_id,
        )
        return self._same_task(handle, task_id, context_id, result)

    async def resume(
        self,
        handle: VerifundTaskHandle,
        *,
        checkpoint: VerifundCheckpoint,
        value: dict[str, Any],
        idempotency_key: str,
    ) -> VerifundTaskResult:
        request = VerifundResumeRequest(
            run_id=handle.run_id,
            task_id=handle.task_id,
            checkpoint=checkpoint,
            value=value,
            idempotency_key=idempotency_key,
        )
        task_id, context_id, result = await self._exchange(
            wrap_verifund_resume_request(request),
            task_id=handle.task_id,
            context_id=handle.context_id,
        )
        return self._same_task(handle, task_id, context_id, result)

    async def receipt(
        self, handle: VerifundTaskHandle, *, transaction_id: str
    ) -> VerifundTaskResult:
        request = VerifundTaskRequest(
            skill=VerifundSkill.RECEIPT_GET,
            run_id=handle.run_id,
            transaction_id=transaction_id,
            idempotency_key=f"receipt:{handle.task_id}:{uuid.uuid4().hex}",
        )
        task_id, context_id, result = await self._exchange(
            wrap_verifund_task_request(request),
            task_id=handle.task_id,
            context_id=handle.context_id,
        )
        return self._same_task(handle, task_id, context_id, result)

    async def get_agreement(self, handle: VerifundTaskHandle) -> dict[str, Any]:
        result = await self.status(handle)
        data = result.data or {}
        agreement = data.get("agreement")
        if not isinstance(agreement, dict):
            # fall back to transaction status data
            agreement = data.get("projection", {}).get("agreement")
        return agreement if isinstance(agreement, dict) else {}

    async def record_seller_operator_required(
        self, handle: VerifundTaskHandle, seller_result: Any
    ) -> VerifundTaskResult:
        value = (
            seller_result.model_dump(mode="json")
            if hasattr(seller_result, "model_dump")
            else dict(seller_result)
        )
        return await self.resume(
            handle,
            checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            value=value,
            idempotency_key=(
                f"operator:{handle.task_id}:{uuid.uuid4().hex}"
            ),
        )

    @staticmethod
    def _same_task(
        handle: VerifundTaskHandle,
        task_id: str,
        context_id: str,
        result: VerifundTaskResult,
    ) -> VerifundTaskResult:
        if task_id != handle.task_id:
            raise VerifundProtocolError(
                "Verifund created a new task during a lifecycle resume"
            )
        if context_id != handle.context_id:
            raise VerifundProtocolError(
                "Verifund changed the task context during a lifecycle resume"
            )
        return result


class BuyerA2AAgents:
    def __init__(
        self, *, buyer_a2a_url: str, send: Sender = _a2a_send
    ) -> None:
        self.buyer_a2a_url = buyer_a2a_url.rstrip("/")
        self._send = send

    async def _send_envelope(
        self,
        *,
        task_id: str,
        context_id: str,
        envelope: dict[str, Any],
        text: str,
    ) -> dict[str, Any]:
        message = make_message(
            role=Role.ROLE_USER,
            text=text,
            context_id=context_id,
            task_id=task_id,
            envelope=envelope,
        )
        frames = await self._send(self.buyer_a2a_url, message)
        response = _buyer_response(frames)
        if response is None:
            raise VerifundProtocolError("Buyer returned no structured response")
        return response

    async def resume_buyer(
        self,
        *,
        task_id: str,
        context_id: str,
        agreement: AgreementProjection,
        idempotency_key: str,
    ) -> dict[str, Any]:
        request = AgreementReviewRequest(
            party="buyer",
            run_id=agreement.run_id,
            transaction_id=agreement.transaction_id,
            agreement=agreement,
            buyer_task_id=task_id,
            buyer_context_id=context_id,
            requested_at=datetime.now(UTC),
            idempotency_key=idempotency_key,
        )
        return await self._send_envelope(
            task_id=task_id,
            context_id=context_id,
            envelope=wrap_agreement_review_request(request),
            text="Buyer agreement review.",
        )

    async def apply_seller_decision(
        self,
        *,
        task_id: str,
        context_id: str,
        decision: AgreementReviewResult,
    ) -> dict[str, Any]:
        return await self._send_envelope(
            task_id=task_id,
            context_id=context_id,
            envelope=wrap_agreement_review_result(decision),
            text="Seller agreement review.",
        )


class SellerA2AClient:
    def __init__(
        self,
        *,
        send: Sender = _a2a_send,
        resolve_seller_token: TokenResolver = _resolve_seller_token,
        resolve_settlement_token: SettlementResolver = (
            _resolve_settlement_token
        ),
    ) -> None:
        self._send = send
        self._resolve_seller_token = resolve_seller_token
        self._resolve_settlement_token = resolve_settlement_token

    async def review(
        self,
        card_url: str,
        request: AgreementReviewRequest,
    ) -> AgreementReviewResult:
        envelope = wrap_agreement_review_request(request)
        message = make_message(
            role=Role.ROLE_USER,
            text="Verifund agreement review.",
            context_id=request.seller_context_id or request.run_id,
            envelope=envelope,
        )
        frames = await self._send(
            _base_url(card_url),
            message,
            token=self._resolve_seller_token(
                card_url, None, request.agreement.seller_id
            ),
        )
        for frame in frames:
            kind = frame.WhichOneof("payload")
            artifacts = []
            if kind == "artifact_update":
                artifacts = [frame.artifact_update.artifact]
            elif kind == "task":
                artifacts = list(frame.task.artifacts)
            for artifact in artifacts:
                for part in artifact.parts:
                    value = part_value(part)
                    if not isinstance(value, dict):
                        continue
                    try:
                        return parse_agreement_review_result(
                            value,
                            expected_party="seller",
                            expected_transaction_id=(
                                request.agreement.transaction_id
                            ),
                            expected_version=(
                                request.agreement.agreement_version
                            ),
                            expected_hash=request.agreement.agreement_hash,
                        )
                    except ValueError:
                        continue
        raise VerifundProtocolError(
            "Seller returned no structured agreement review"
        )

    async def purchase_order(
        self,
        *,
        card_url: str,
        seller_id: str,
        run_id: str,
        purchase_order: PurchaseOrderRequest | dict[str, Any],
        buyer_internal_url: str,
        buyer_internal_token: str,
        timeout_seconds: float = 10.0,
    ) -> dict[str, Any]:
        if isinstance(purchase_order, dict):
            purchase_order = PurchaseOrderRequest.model_validate(purchase_order)
        if not purchase_order.settlement_transaction_id:
            raise VerifundProtocolError(
                "purchase order has no settlement transaction"
            )
        token = await self._resolve_settlement_token(
            buyer_internal_url,
            buyer_internal_token,
            {
                "run_id": run_id,
                "transaction_id": purchase_order.settlement_transaction_id,
                "seller_id": seller_id,
                "purpose": "purchase_order",
            },
            timeout_seconds=timeout_seconds,
        )
        envelope = _inject_settlement_token(
            wrap_payload("purchase_order", purchase_order), token
        )
        message = make_message(
            role=Role.ROLE_USER,
            text="Purchase order.",
            context_id=run_id,
            envelope=envelope,
        )
        frames = await self._send(
            _base_url(card_url),
            message,
            token=self._resolve_seller_token(card_url, None, seller_id),
        )
        order = self._order_from_frames(frames)
        parsed = Order.model_validate(order)
        if parsed.seller_id != seller_id:
            raise VerifundProtocolError(
                "Seller order does not match the selected seller"
            )
        if parsed.offer_id != purchase_order.offer_id:
            raise VerifundProtocolError(
                "Seller order does not match the purchase order offer"
            )
        if parsed.quantity != purchase_order.quantity:
            raise VerifundProtocolError(
                "Seller order quantity does not match the purchase order"
            )
        if parsed.total_cents != purchase_order.expected_total_cents:
            raise VerifundProtocolError(
                "Seller order total does not match the purchase order"
            )
        return _redact_settlement(parsed.model_dump(mode="json"), token)

    @staticmethod
    def _order_from_frames(frames: list) -> dict[str, Any]:
        for frame in frames:
            artifacts = []
            # Unwrap ClientEvent-style payloads
            if hasattr(frame, "WhichOneof"):
                try:
                    kind = frame.WhichOneof("payload")
                except ValueError:
                    kind = None
                if kind == "artifact_update":
                    artifacts = [frame.artifact_update.artifact]
                elif kind == "task":
                    artifacts = list(getattr(frame.task, "artifacts", []))
                elif kind == "status_update":
                    artifacts = []
            # Direct artifact update event
            if not artifacts and hasattr(frame, "artifact"):
                artifacts = [frame.artifact]
            if not artifacts and hasattr(frame, "artifacts"):
                artifacts = list(frame.artifacts or [])
            # Task object
            if not artifacts and hasattr(frame, "task") and getattr(frame.task, "artifacts", None):
                artifacts = list(frame.task.artifacts)
            for artifact in artifacts:
                for part in getattr(artifact, "parts", []):
                    value = part_value(part)
                    if not isinstance(value, dict):
                        continue
                    payload = value.get("payload")
                    candidate = payload if isinstance(payload, dict) else value
                    if isinstance(candidate, dict) and candidate.get("order_id"):
                        return candidate
        raise VerifundProtocolError("Seller returned no order")


class VerifundLifecycle:
    def __init__(
        self,
        *,
        verifund: VerifundA2AClient,
        buyer: BuyerA2AAgents,
        seller: SellerA2AClient,
        buyer_internal_url: str,
        buyer_internal_token: str,
        buyer_internal_timeout_seconds: float = 10.0,
    ) -> None:
        self.verifund = verifund
        self.buyer = buyer
        self.seller = seller
        self.buyer_internal_url = buyer_internal_url
        self.buyer_internal_token = buyer_internal_token
        self.buyer_internal_timeout_seconds = buyer_internal_timeout_seconds

    async def start(
        self,
        *,
        run_id: str,
        award: dict[str, Any],
        buyer_task_id: str,
        buyer_context_id: str,
        seller_card_url: str,
        seller_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        handle, result = await self.verifund.start(
            run_id=run_id,
            award=award,
            buyer_task_id=buyer_task_id,
            buyer_context_id=buyer_context_id,
            idempotency_key=idempotency_key,
        )
        self._require(
            result,
            status="input_required",
            checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
        )
        agreement = self._agreement(result)
        seller_token_ref = str(result.data.get("seller_token_ref") or "")
        if not seller_token_ref:
            raise VerifundProtocolError(
                "Verifund returned no seller token reference"
            )
        buyer_response = await self.buyer.resume_buyer(
            task_id=buyer_task_id,
            context_id=buyer_context_id,
            agreement=agreement,
            idempotency_key=(
                f"review:buyer:{agreement.transaction_id}:"
                f"{agreement.agreement_version}"
            ),
        )
        buyer_status = buyer_response.get("status")
        if buyer_status not in {"seller_review_required", "rejected"}:
            raise VerifundProtocolError(
                "Buyer did not review the canonical agreement"
            )
        seller_task_id = (
            f"agreement-review:{agreement.transaction_id}:"
            f"{agreement.agreement_version}"
        )
        seller_decision = await self.seller.review(
            seller_card_url,
            AgreementReviewRequest(
                party="seller",
                run_id=agreement.run_id,
                transaction_id=agreement.transaction_id,
                agreement=agreement,
                seller_task_id=seller_task_id,
                seller_context_id=agreement.run_id,
                requested_at=datetime.now(UTC),
                idempotency_key=(
                    f"review:seller:{agreement.transaction_id}:"
                    f"{agreement.agreement_version}"
                ),
            ),
        )
        if not _review_matches(seller_decision, agreement, "seller"):
            raise VerifundProtocolError(
                "Seller review does not match the agreement"
            )
        buyer_response = await self.buyer.apply_seller_decision(
            task_id=buyer_task_id,
            context_id=buyer_context_id,
            decision=seller_decision,
        )
        if seller_decision.status == AgreementReviewDecision.OPERATOR_REQUIRED:
            await self.verifund.record_seller_operator_required(
                handle, seller_decision
            )
            view = self._view(handle, await self.verifund.status(handle))
            view["buyer_review"] = None
            view["seller_decision"] = _review_summary(seller_decision)
            view["agreement_review"] = {
                "review_url": f"/agreements/{agreement.agreement_id}",
                "version": agreement.agreement_version,
                "digest": agreement.agreement_hash,
                "seller_decision": _review_summary(seller_decision),
                "precheck": None,
            }
            return view
        expected = (
            "agreed"
            if seller_decision.status == AgreementReviewDecision.ACCEPTED
            else "rejected"
        )
        if seller_decision.status not in {
            AgreementReviewDecision.ACCEPTED,
            AgreementReviewDecision.REJECTED,
            AgreementReviewDecision.CHANGES_REQUESTED,
        }:
            raise VerifundProtocolError("unsupported seller decision")
        if buyer_response.get("status") not in {expected, "rejected", "agreed"}:
            raise VerifundProtocolError(
                "Buyer did not record the Seller agreement decision"
            )
        result = await self.verifund.resume(
            handle,
            checkpoint=VerifundCheckpoint.SELLER_REVIEW_REQUIRED,
            value=seller_decision.model_dump(mode="json"),
            idempotency_key=(
                f"review:seller-resume:{handle.task_id}:"
                f"{seller_decision.agreement_hash}"
            ),
        )
        view = self._view(handle, result)
        view["buyer_review"] = None
        view["seller_decision"] = _review_summary(seller_decision)
        view["agreement_review"] = {
            "review_url": f"/agreements/{agreement.agreement_id}",
            "version": agreement.agreement_version,
            "digest": agreement.agreement_hash,
            "seller_decision": _review_summary(seller_decision),
            "precheck": result.data.get("buyer_precheck")
            if isinstance(result.data, dict)
            else None,
        }
        return view

    async def advance(
        self,
        handle: VerifundTaskHandle,
        *,
        seller_card_url: str,
    ) -> dict[str, Any]:
        result = await self.verifund.status(handle)
        if result.checkpoint is VerifundCheckpoint.PURCHASE_ORDER_REQUIRED:
            order = await self._place_purchase_order(
                handle, result, seller_card_url
            )
            result = await self.verifund.resume(
                handle,
                checkpoint=VerifundCheckpoint.PURCHASE_ORDER_REQUIRED,
                value={"order": order},
                idempotency_key=(
                    f"order:{handle.run_id}:{order['order_id']}"
                ),
            )
        return self._view(handle, result)

    async def resume_agreement(
        self,
        handle: VerifundTaskHandle,
        decision: Any,
    ) -> dict[str, Any]:
        value = (
            decision.model_dump(mode="json")
            if hasattr(decision, "model_dump")
            else dict(decision)
        )
        result = await self.verifund.resume(
            handle,
            checkpoint=VerifundCheckpoint.BUYER_APPROVAL_REQUIRED,
            value=value,
            idempotency_key=(
                value.get("idempotency_key")
                if isinstance(value, dict)
                else getattr(decision, "idempotency_key", None)
            )
            or f"buyer-approval:{handle.task_id}",
        )
        agreement = await self.verifund.get_agreement(handle)
        if agreement.get("status") != "AGREED":
            raise VerifundProtocolError("agreement is not agreed")
        return self._view(handle, result)

    async def resume_seller_operator(
        self,
        handle: VerifundTaskHandle,
        decision: Any,
    ) -> dict[str, Any]:
        value = (
            decision.model_dump(mode="json")
            if hasattr(decision, "model_dump")
            else dict(decision)
        )
        result = await self.verifund.resume(
            handle,
            checkpoint=VerifundCheckpoint.SELLER_OPERATOR_REQUIRED,
            value=value,
            idempotency_key=f"seller-operator:{handle.task_id}",
        )
        return self._view(handle, result)

    async def resume_change_resolution(
        self,
        handle: VerifundTaskHandle,
        change_request_id: str,
        accept: bool,
        note: str = "",
    ) -> dict[str, Any]:
        result = await self.verifund.resume(
            handle,
            checkpoint=VerifundCheckpoint.AGREEMENT_CHANGES_REQUESTED,
            value={
                "change_request_id": change_request_id,
                "accept": accept,
                "note": note,
            },
            idempotency_key=f"change-resolution:{handle.task_id}",
        )
        return self._view(handle, result)

    async def resume_funding(
        self,
        handle: VerifundTaskHandle,
        decision: FundingApprovalDecision,
    ) -> dict[str, Any]:
        if decision.run_id != handle.run_id:
            raise VerifundProtocolError(
                "funding decision belongs to another run"
            )
        result = await self.verifund.resume(
            handle,
            checkpoint=VerifundCheckpoint.FUNDING_APPROVAL_REQUIRED,
            value=decision.model_dump(mode="json"),
            idempotency_key=decision.idempotency_key,
        )
        return self._view(handle, result)

    async def resume_release(
        self,
        handle: VerifundTaskHandle,
        decision: ReleaseApprovalDecision,
    ) -> dict[str, Any]:
        if decision.run_id != handle.run_id:
            raise VerifundProtocolError(
                "release decision belongs to another run"
            )
        result = await self.verifund.resume(
            handle,
            checkpoint=VerifundCheckpoint.RELEASE_APPROVAL_REQUIRED,
            value=decision.model_dump(mode="json"),
            idempotency_key=decision.idempotency_key,
        )
        return self._view(handle, result)

    async def status(self, handle: VerifundTaskHandle) -> dict[str, Any]:
        return self._view(handle, await self.verifund.status(handle))

    async def receipt(
        self, handle: VerifundTaskHandle, *, transaction_id: str
    ) -> dict[str, Any]:
        result = await self.verifund.receipt(
            handle, transaction_id=transaction_id
        )
        return self._view(handle, result)

    async def _place_purchase_order(
        self,
        handle: VerifundTaskHandle,
        result: VerifundTaskResult,
        seller_card_url: str,
    ) -> dict[str, Any]:
        data = result.data or {}
        payload = data.get("purchase_order")
        if not isinstance(payload, dict):
            raise VerifundProtocolError(
                "purchase order checkpoint has no purchase order"
            )
        purchase_order = PurchaseOrderRequest.model_validate(payload)
        seller_id = str(data.get("seller_id") or purchase_order.seller_id)
        if seller_id != purchase_order.seller_id:
            raise VerifundProtocolError(
                "purchase order seller does not match the agreement"
            )
        if not data.get("seller_token_ref"):
            raise VerifundProtocolError(
                "purchase order checkpoint has no seller token reference"
            )
        return await self.seller.purchase_order(
            card_url=seller_card_url,
            seller_id=seller_id,
            run_id=handle.run_id,
            purchase_order=purchase_order.model_dump(),
            buyer_internal_url=self.buyer_internal_url,
            buyer_internal_token=self.buyer_internal_token,
            timeout_seconds=self.buyer_internal_timeout_seconds,
        )

    def _view(
        self, handle: VerifundTaskHandle, result: VerifundTaskResult
    ) -> dict[str, Any]:
        data = result.data or {}
        view: dict[str, Any] = {
            "status": result.status,
            "checkpoint": (
                result.checkpoint.value if result.checkpoint else None
            ),
            "state": result.state.value if result.state else None,
            "handle": handle.as_dict(),
            "message": result.message,
            "data": data,
            "result": result.model_dump(mode="json"),
        }
        if result.status == "approval_required":
            if result.approval_type == "funding":
                view["hitl"] = {
                    "tool": "request_verifund_funding_approval",
                    "args": self._funding_args(handle, result),
                }
            elif result.approval_type == "release":
                view["hitl"] = {
                    "tool": "request_verifund_release_approval",
                    "args": self._release_args(handle, result),
                }
        elif result.checkpoint is VerifundCheckpoint.PURCHASE_ORDER_REQUIRED:
            view["status"] = "input_required"
        elif result.checkpoint in {
            VerifundCheckpoint.FUNDING_PENDING,
            VerifundCheckpoint.EVIDENCE_PENDING,
        }:
            projection = data.get("projection") or {}
            view["status"] = "working"
            view["checkout_url"] = data.get("checkout_url")
            view["evidence"] = data.get("evidence") or projection.get("evidence")
            view["verification"] = (
                data.get("verification") or projection.get("verification")
            )
        elif result.status == "completed":
            view["status"] = "completed"
            view["receipt"] = data.get("receipt")
        return view

    @staticmethod
    def _funding_args(
        handle: VerifundTaskHandle, result: VerifundTaskResult
    ) -> dict[str, Any]:
        data = result.data or {}
        return {
            "run_id": data.get("run_id") or handle.run_id,
            "transaction_id": data.get("transaction_id"),
            "agreement_version": data.get("agreement_version"),
            "agreement_hash": data.get("agreement_hash"),
            "agreement": data.get("agreement"),
            "buyer_review": _review_summary(data.get("buyer_review")),
            "seller_decision": _review_summary(data.get("seller_decision")),
            "message": result.message or "Approve funding for this agreement.",
        }

    @staticmethod
    def _release_args(
        handle: VerifundTaskHandle, result: VerifundTaskResult
    ) -> dict[str, Any]:
        data = result.data or {}
        return {
            "run_id": data.get("run_id") or handle.run_id,
            "transaction_id": data.get("transaction_id"),
            "agreement_version": data.get("agreement_version"),
            "agreement_hash": data.get("agreement_hash"),
            "projection": data.get("projection"),
            "message": result.message or "Release this transaction.",
        }

    @staticmethod
    def _require(
        result: VerifundTaskResult,
        *,
        status: str,
        checkpoint: VerifundCheckpoint,
    ) -> None:
        if result.status != status or result.checkpoint is not checkpoint:
            raise VerifundProtocolError(
                result.message
                or f"Verifund did not reach {checkpoint.value}"
            )

    @staticmethod
    def _agreement(result: VerifundTaskResult) -> AgreementProjection:
        payload = result.data.get("agreement")
        if not isinstance(payload, dict):
            raise VerifundProtocolError(
                "Verifund checkpoint has no canonical agreement"
            )
        agreement = AgreementProjection.model_validate(payload)
        if (
            result.transaction_id
            and result.transaction_id != agreement.transaction_id
        ):
            raise VerifundProtocolError(
                "agreement transaction does not match the lifecycle result"
            )
        if (
            result.agreement_version
            and result.agreement_version != agreement.agreement_version
        ):
            raise VerifundProtocolError(
                "agreement version does not match the lifecycle result"
            )
        if (
            result.agreement_hash
            and result.agreement_hash != agreement.agreement_hash
        ):
            raise VerifundProtocolError(
                "agreement hash does not match the lifecycle result"
            )
        return agreement

    @staticmethod
    def _buyer_review(
        agreement: AgreementProjection,
        response: dict[str, Any],
        *,
        buyer_task_id: str,
        buyer_context_id: str,
    ) -> AgreementReviewResult:
        review = response.get("buyer_agent_review")
        if not isinstance(review, dict):
            raise VerifundProtocolError(
                "Buyer returned no structured agreement review"
            )
        status = review.get("status")
        if status not in {
            AgreementReviewDecision.ACCEPTED.value,
            AgreementReviewDecision.REJECTED.value,
        }:
            raise VerifundProtocolError(
                "Buyer agreement review is not a decision"
            )
        if review.get("agreement_hash") != agreement.agreement_hash:
            raise VerifundProtocolError(
                "Buyer review hash does not match the agreement"
            )
        if int(review.get("agreement_version") or 0) != (
            agreement.agreement_version
        ):
            raise VerifundProtocolError(
                "Buyer review version does not match the agreement"
            )
        reviewed_at = review.get("reviewed_at")
        try:
            reviewed = (
                datetime.fromisoformat(str(reviewed_at))
                if reviewed_at
                else datetime.now(UTC)
            )
        except ValueError:
            reviewed = datetime.now(UTC)
        return AgreementReviewResult(
            party="buyer",
            status=status,
            run_id=agreement.run_id,
            transaction_id=agreement.transaction_id,
            agreement_version=agreement.agreement_version,
            agreement_hash=agreement.agreement_hash,
            offer_hash=str(review.get("offer_hash") or agreement.offer_hash),
            actor_type=str(review.get("actor_type") or "BUYER_AGENT"),
            actor_id=str(review.get("actor_id") or agreement.buyer_id),
            authority_ref=review.get("authority_ref"),
            authority_snapshot=review.get("authority_snapshot") or {},
            verified_change_request_id=review.get("verified_change_request_id"),
            task_id=str(response.get("task_id") or buyer_task_id),
            context_id=str(
                response.get("buyer_context_id") or buyer_context_id
            ),
            reviewed_at=reviewed,
            reason_code=review.get("reason_code"),
            note=str(review.get("note") or ""),
        )
