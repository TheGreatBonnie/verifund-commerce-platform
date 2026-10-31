from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from a2a.types.a2a_pb2 import Artifact, Message, TaskState
from commerce_core.a2a_parts import first_envelope, make_artifact
from commerce_core.contracts import (
    AcceptOffer,
    CommerceErrorCode,
    Offer,
    Order,
    PurchaseOrderRequest,
)
from commerce_core.extension import wrap_payload
from commerce_core.pricing import SellerPolicy
from google.protobuf import json_format
from verifund_contracts import parse_agreement_review_request, wrap_agreement_review_result

from seller_agent.agreement import review_agreement
from seller_agent.agreement_store import SellerAgreementReviewStore
from seller_agent.graph import (
    CommerceProtocolError,
    build_graph,
    error_artifact,
    kind_from_envelope,
)
from seller_agent.mandate import SellerMandate
from seller_agent.order_service import OrderService
from seller_agent.planner import SellerPlanner
from seller_agent.settlement import (
    SellerSettlementClient,
    SettlementError,
    build_delivery_confirmation,
    build_shipment_manifest,
    encode_payload,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from seller_agent.evidence_outbox import EvidenceOutbox
from seller_agent.store import SellerStore

SETTLEMENT_TOKEN_FIELD = "settlement_token"


def settlement_token_from(envelope: dict[str, Any]) -> str | None:
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        return None
    token = payload.get(SETTLEMENT_TOKEN_FIELD)
    return token if isinstance(token, str) and token else None


def strip_settlement_token(
    envelope: dict[str, Any],
) -> dict[str, Any]:
    cleaned = json.loads(json.dumps(envelope))
    payload = cleaned.get("payload")
    if isinstance(payload, dict):
        payload.pop(SETTLEMENT_TOKEN_FIELD, None)
    return cleaned


@dataclass
class SellerTurn:
    task_state: TaskState
    artifacts: list[Artifact]
    message: str


class SellerService:
    def __init__(
        self,
        *,
        store: SellerStore,
        policy: SellerPolicy,
        planner: SellerPlanner,
        settlement: SellerSettlementClient | None = None,
        settlement_enabled: bool = False,
        evidence_outbox: EvidenceOutbox | None = None,
        auto_evidence: bool = True,
        mandate: SellerMandate | None = None,
        review_store: SellerAgreementReviewStore | None = None,
    ) -> None:
        self.store = store
        self.policy = policy
        self.planner = planner
        self.settlement = settlement
        self.mandate = mandate or SellerMandate()
        from pathlib import Path
        self.review_store = review_store or SellerAgreementReviewStore(
            Path("data/seller_agreement_reviews.db")
        )
        self.settlement_enabled = settlement_enabled
        self.evidence_outbox = evidence_outbox
        self.auto_evidence = auto_evidence
        self.order_service = OrderService(store)
        self.graph = build_graph()

    def redact_message(self, message: Message) -> Message:
        clone = Message()
        clone.CopyFrom(message)
        for part in clone.parts:
            if not part.HasField("data"):
                continue
            value = json_format.MessageToDict(part.data)
            payload = value.get("payload")
            if (
                isinstance(payload, dict)
                and SETTLEMENT_TOKEN_FIELD in payload
            ):
                payload.pop(SETTLEMENT_TOKEN_FIELD)
                part.data.Clear()
                json_format.ParseDict(value, part.data)
        return clone

    def _require_settlement(self) -> SellerSettlementClient:
        if self.settlement is None:
            raise CommerceProtocolError("settlement is not configured")
        return self.settlement

    async def _settlement_projection(
        self, transaction_id: str, token: str
    ) -> dict[str, Any]:
        client = self._require_settlement()
        try:
            return await client.get_transaction(token, transaction_id)
        except SettlementError as exc:
            raise CommerceProtocolError(
                f"settlement token was rejected ({exc.code})"
            ) from exc

    async def validate_acceptance(
        self, accepted: AcceptOffer, *, token: str | None
    ) -> dict[str, Any] | None:
        if not self.settlement_enabled:
            return None
        if not token:
            raise CommerceProtocolError("settlement token is required")
        if (
            not accepted.settlement_transaction_id
            or not accepted.agreement_hash
        ):
            raise CommerceProtocolError("settlement fields are required")
        projection = await self._settlement_projection(
            accepted.settlement_transaction_id, token
        )
        if projection.get("state") != "AWARDED":
            raise CommerceProtocolError(
                "transaction is not awaiting seller acceptance"
            )
        if projection.get("seller_id") != self.policy.seller_id:
            raise CommerceProtocolError(
                "settlement seller does not match this seller"
            )
        if projection.get("agreement_hash") != accepted.agreement_hash:
            raise CommerceProtocolError("agreement hash mismatch")
        if int(projection.get("amount_cents", 0)) != (
            accepted.accepted_total_cents
        ):
            raise CommerceProtocolError("accepted total mismatch")
        if projection.get("currency") != "USD":
            raise CommerceProtocolError("unsupported settlement currency")
        await self.store.save_settlement_token(
            accepted.settlement_transaction_id,
            self.policy.seller_id,
            token,
        )
        return projection

    async def validate_purchase_order(
        self, po: PurchaseOrderRequest, *, token: str | None
    ) -> dict[str, Any] | None:
        if not self.settlement_enabled:
            return None
        if not token:
            raise CommerceProtocolError("settlement token is required")
        if not po.settlement_transaction_id or not po.agreement_hash:
            raise CommerceProtocolError("settlement fields are required")
        projection = await self._settlement_projection(
            po.settlement_transaction_id, token
        )
        if projection.get("state") != "FUNDED":
            raise CommerceProtocolError(
                "transaction is not funded for this purchase order"
            )
        if projection.get("seller_id") != self.policy.seller_id:
            raise CommerceProtocolError(
                "settlement seller does not match this seller"
            )
        if projection.get("agreement_hash") != po.agreement_hash:
            raise CommerceProtocolError("agreement hash mismatch")
        if int(projection.get("amount_cents", 0)) != po.expected_total_cents:
            raise CommerceProtocolError("purchase order total mismatch")
        if projection.get("currency") != "USD":
            raise CommerceProtocolError("unsupported settlement currency")
        await self.store.save_settlement_token(
            po.settlement_transaction_id, self.policy.seller_id, token
        )
        return projection

    async def queue_evidence(
        self, order: Order, po: PurchaseOrderRequest
    ) -> int:
        if not (
            self.settlement_enabled
            and self.auto_evidence
            and self.evidence_outbox is not None
            and po.settlement_transaction_id
            and po.agreement_hash
        ):
            return 0
        transaction_id = po.settlement_transaction_id
        manifest = build_shipment_manifest(
            order,
            transaction_id=transaction_id,
            agreement_hash=po.agreement_hash,
        )
        delivery = build_delivery_confirmation(
            order, transaction_id=transaction_id
        )
        try:
            await self.evidence_outbox.enqueue(
                transaction_id=transaction_id,
                seller_id=self.policy.seller_id,
                kind="shipment_manifest",
                content=encode_payload(manifest),
                media_type="application/json",
                filename="shipment-manifest.json",
                note="Auto-generated by the seller agent.",
                captured_at=manifest["shipped_at"],
            )
            await self.evidence_outbox.enqueue(
                transaction_id=transaction_id,
                seller_id=self.policy.seller_id,
                kind="delivery_confirmation",
                content=encode_payload(delivery),
                media_type="application/json",
                filename="delivery-confirmation.json",
                note="Auto-generated by the seller agent.",
                captured_at=delivery["delivered_at"],
            )
        except Exception:
            logger.exception("could not enqueue seller evidence")
            return 0
        return 2

    async def settlement_status(self) -> list[dict[str, Any]]:
        if not self.settlement_enabled or self.settlement is None:
            return []
        rows = await self.store.list_settlement_tokens(limit=5)
        statuses: list[dict[str, Any]] = []
        for row in rows:
            transaction_id = row["transaction_id"]
            token = await self.store.get_settlement_token(transaction_id)
            if not token:
                continue
            try:
                projection = await self.settlement.get_transaction(
                    token, transaction_id
                )
            except Exception:  # noqa: BLE001
                logger.warning(
                    "seller settlement status unavailable for %s",
                    transaction_id,
                )
                statuses.append(
                    {
                        "transaction_id": transaction_id,
                        "seller_id": row["seller_id"],
                        "state": "unavailable",
                        "unavailable": True,
                    }
                )
                continue
            statuses.append(
                {
                    "transaction_id": transaction_id,
                    "seller_id": row["seller_id"],
                    "state": projection.get("state"),
                    "amount_cents": projection.get("amount_cents"),
                    "currency": projection.get("currency"),
                    "agreement_hash": projection.get("agreement_hash"),
                    "deadlines": projection.get("deadlines") or {},
                    "evidence": projection.get("evidence"),
                    "purchase_order": projection.get("purchase_order"),
                    "updated_at": projection.get("updated_at"),
                    "unavailable": False,
                }
            )
        return statuses

    async def handle_turn(
        self, task_id: str, context_id: str, message: Message
    ) -> SellerTurn:
        envelope = first_envelope(message)
        if envelope is not None and str(envelope.get("schema", "")).endswith(
            "/agreement-review-request.json"
        ):
            review = parse_agreement_review_request(envelope)
            offer = await self.store.get_offer(review.agreement.offer_id)
            result = review_agreement(
                review.agreement,
                offer,
                self.mandate,
                self.review_store,
                self.policy.seller_id,
                datetime.now(UTC),
                task_id=review.seller_task_id or task_id,
                context_id=review.seller_context_id or context_id,
                change_request=review.change_request,
            )
            return SellerTurn(
                task_state=TaskState.TASK_STATE_COMPLETED,
                artifacts=[
                    make_artifact(
                        "agreement-review",
                        wrap_agreement_review_result(result),
                    )
                ],
                message=(
                    "Agreement accepted."
                    if result.status == "accepted"
                    else "Agreement rejected."
                ),
            )
        try:
            if envelope is None:
                raise CommerceProtocolError("missing DataPart")
            kind_from_envelope(envelope)
            settlement_token = settlement_token_from(envelope)
            incoming = strip_settlement_token(envelope)
        except CommerceProtocolError as exc:
            error = {
                "code": CommerceErrorCode.INVALID_REQUEST.value,
                "message": str(exc),
                "retryable": False,
                "details": {},
            }
            return SellerTurn(
                task_state=TaskState.TASK_STATE_FAILED,
                artifacts=[error_artifact(error)],
                message=str(exc),
            )

        state = {
            "task_id": task_id,
            "context_id": context_id,
            "incoming": incoming,
        }
        try:
            result = await self.graph.ainvoke(
                state,
                config={
                    "configurable": {
                        "thread_id": task_id,
                        "planner": self.planner,
                        "service": self,
                        "settlement_token": settlement_token,
                    }
                },
            )
        except Exception as exc:  # noqa: BLE001
            error = {
                "code": CommerceErrorCode.INVALID_REQUEST.value,
                "message": str(exc),
                "retryable": False,
                "details": {},
            }
            return SellerTurn(
                task_state=TaskState.TASK_STATE_FAILED,
                artifacts=[error_artifact(error)],
                message=str(exc),
            )

        if result.get("error"):
            return SellerTurn(
                task_state=TASK_STATES.get(
                    result.get("task_state", "failed"),
                    TaskState.TASK_STATE_FAILED,
                ),
                artifacts=[error_artifact(result["error"])],
                message=result.get("message", "Commerce error."),
            )
        if result.get("offer"):
            offer = Offer.model_validate(result["offer"])
            return SellerTurn(
                task_state=TASK_STATES.get(
                    result.get("task_state", "input_required"),
                    TaskState.TASK_STATE_INPUT_REQUIRED,
                ),
                artifacts=[
                    make_artifact("offer", wrap_payload("offer", offer))
                ],
                message=result.get("message", "Structured offer available."),
            )
        if result.get("order"):
            order = Order.model_validate(result["order"])
            return SellerTurn(
                task_state=TASK_STATES.get(
                    result.get("task_state", "completed"),
                    TaskState.TASK_STATE_COMPLETED,
                ),
                artifacts=[
                    make_artifact("order", wrap_payload("order", order))
                ],
                message=result.get("message", "Order confirmed."),
            )
        error = {
            "code": CommerceErrorCode.INVALID_REQUEST.value,
            "message": "Seller produced no response.",
            "retryable": False,
            "details": {},
        }
        return SellerTurn(
            task_state=TaskState.TASK_STATE_FAILED,
            artifacts=[error_artifact(error)],
            message="Seller produced no response.",
        )


TASK_STATES = {
    "working": TaskState.TASK_STATE_WORKING,
    "input_required": TaskState.TASK_STATE_INPUT_REQUIRED,
    "completed": TaskState.TASK_STATE_COMPLETED,
    "failed": TaskState.TASK_STATE_FAILED,
    "canceled": TaskState.TASK_STATE_CANCELED,
}
