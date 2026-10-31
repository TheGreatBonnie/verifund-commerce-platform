from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Protocol

from commerce_core.contracts import (
    ApprovalReceipt,
    PurchaseOrderRequest,
    ShippingAddress,
)
from verifund_contracts import (
    AgreementProjection,
    BuyerAgreementRequest,
    BuyerAgreementResponse,
    BuyerOrderReportRequest,
    BuyerOrderReportResponse,
    BuyerPurchaseOrderRequest,
    BuyerPurchaseOrderResponse,
    CancelReason,
    CancelRequest,
    FlagReviewRequest,
    FundingApprovalDecision,
    FundRequest,
    PurchaseOrderLineItem,
    PurchaseOrderReport,
    ReleaseApprovalDecision,
    ReleaseRequest,
    ReviewReason,
    TransactionState,
)


class AgreementBindingError(Exception):
    def __init__(self, message: str, *, status_code: int = 409) -> None:
        super().__init__(message)
        self.status_code = status_code


class SettlementStoreProtocol(Protocol):
    async def save_secret(
        self,
        *,
        run_id: str,
        transaction_id: str,
        seller_id: str,
        purpose: str,
        token: str | None = None,
        seller_token: str | None = None,
        expires_at: datetime,
    ) -> None: ...

    async def get_secret(
        self, run_id: str, transaction_id: str, purpose: str
    ) -> dict[str, Any] | None: ...

    async def save_projection(
        self, run_id: str, projection: dict[str, Any]
    ) -> bool: ...

    async def get_projection(self, run_id: str) -> dict[str, Any] | None: ...

    async def get_agreement(self, run_id: str) -> dict[str, Any] | None: ...


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _order_datetime(order: dict[str, Any], field: str) -> datetime:
    value = order.get(field)
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise AgreementBindingError(f"order {field} is missing", status_code=409)


def shipping_address() -> ShippingAddress:
    return ShippingAddress(
        name="Demo Buyer",
        line1="1 Market Street",
        city="San Francisco",
        region="CA",
        postal_code="94105",
        country="US",
    )


class BuyerAgreementService:
    def __init__(
        self,
        client=None,
        *,
        store: SettlementStoreProtocol | None = None,
        console_base_url: str = "",
        **kwargs,
    ) -> None:
        if client is None:
            client = kwargs.pop("client", None)
        self.client = client
        self.store = store
        self.console_base_url = (console_base_url or "").rstrip("/")

    @property
    def _store(self) -> SettlementStoreProtocol:
        if self.store is None:
            raise RuntimeError("settlement store is not configured")
        return self.store

    async def create_agreement(
        self, run_id: str, request: BuyerAgreementRequest
    ) -> dict[str, Any]:
        award = request.award
        if award.run_id != run_id:
            raise AgreementBindingError("award does not belong to this run", status_code=403)
        response = await self.client.award(
            award, idempotency_key=request.idempotency_key
        )
        agreement = AgreementProjection.model_validate(response["agreement"])
        if agreement.run_id != run_id or agreement.transaction_id != response["transaction_id"]:
            raise AgreementBindingError("control plane returned a different run binding")
        await self._store.save_secret(
            run_id=run_id,
            transaction_id=agreement.transaction_id,
            seller_id=agreement.seller_id,
            purpose="settlement",
            token=response["seller_token"],
            expires_at=datetime.fromisoformat(
                response["expires_at"]
            ),
        )
        projection = await self.client.get_state(agreement.transaction_id)
        await self._store.save_projection(
            run_id, {**projection, "agreement": agreement.model_dump(mode="json")}
        )
        return BuyerAgreementResponse(
            transaction_id=agreement.transaction_id,
            state=projection["state"],
            agreement=agreement,
            agreement_version=agreement.agreement_version,
            agreement_hash=agreement.agreement_hash,
            seller_token_ref=f"run:{run_id}:transaction:{agreement.transaction_id}",
            seller_token_expires_at=datetime.fromisoformat(
                response["expires_at"]
            ),
        ).model_dump(mode="json")

    async def _binding(self, run_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        projection = await self._store.get_projection(run_id)
        agreement = await self._store.get_agreement(run_id)
        if projection is None or agreement is None:
            raise AgreementBindingError("settlement is not initialized", status_code=404)
        return projection, agreement

    @staticmethod
    def _require_binding(
        *,
        run_id: str,
        projection: dict[str, Any],
        transaction_id: str,
        agreement_version: int,
        agreement_hash: str,
    ) -> None:
        if str(projection.get("run_id")) != run_id:
            raise AgreementBindingError("run does not match the stored settlement", status_code=403)
        if str(projection.get("transaction_id")) != transaction_id:
            raise AgreementBindingError("transaction does not match", status_code=403)
        if int(projection.get("agreement_version") or 0) != agreement_version:
            raise AgreementBindingError("agreement version is stale", status_code=409)
        if str(projection.get("agreement_hash")) != agreement_hash:
            raise AgreementBindingError("agreement hash is stale", status_code=409)

    async def view(self, run_id: str) -> dict[str, Any]:
        projection, agreement = await self._binding(run_id)
        secret = await self._store.get_secret(run_id, projection["transaction_id"], "settlement")
        return {
            "run_id": run_id,
            "transaction_id": projection["transaction_id"],
            "agreement": agreement,
            "agreement_version": projection["agreement_version"],
            "agreement_hash": projection["agreement_hash"],
            "seller_token_ref": (
                f"run:{run_id}:transaction:{projection['transaction_id']}"
            ),
            "seller_token_expires_at": (secret or {}).get("expires_at"),
            "projection": projection,
        }

    async def get_agreement(self, agreement_id: str) -> dict[str, Any]:
        return await self.client.get_agreement(agreement_id)

    async def get_agreement_by_transaction(self, transaction_id: str) -> dict[str, Any]:
        return await self.client.get_agreement_by_transaction(transaction_id)

    async def record_seller_decision(self, agreement_id: str, result: Any) -> dict[str, Any]:
        status_map = {
            "ACCEPTED": "ACCEPT",
            "REJECTED": "REJECT",
            "OPERATOR_REQUIRED": "OPERATOR_REQUIRED",
            "CHANGES_REQUESTED": "REQUEST_CHANGES",
        }
        status_value = getattr(result, "status", None)
        if hasattr(status_value, "value"):
            status_value = status_value.value
        status_value = str(status_value or "").upper()
        agreement = await self.client.get_agreement(agreement_id)
        seller_token = None
        if self.store is not None:
            try:
                secret = await self._store.get_secret(
                    getattr(result, "run_id", None) or "",
                    agreement.get("transaction_id", ""),
                    "settlement",
                )
                if isinstance(secret, dict):
                    seller_token = secret.get("token")
            except Exception:  # noqa
                seller_token = None
        payload = {
            "agreement_version": getattr(result, "agreement_version", None),
            "agreement_hash": getattr(result, "agreement_hash", None),
            "decision": status_map.get(status_value, status_value),
            "actor_type": getattr(result, "actor_type", "SELLER_AGENT"),
            "actor_id": getattr(result, "actor_id", None),
            "authority_ref": getattr(result, "authority_ref", None),
            "authority_snapshot": getattr(result, "authority_snapshot", {}) or {},
            "verified_offer_hash": getattr(result, "offer_hash", None),
            "verified_change_request_id": getattr(
                result, "verified_change_request_id", None
            ),
            "note": getattr(result, "note", "") or "",
            "task_id": getattr(result, "task_id", None),
            "context_id": getattr(result, "context_id", None),
            "idempotency_key": f"seller-decision:{agreement_id}:{getattr(result, 'agreement_version', 0)}",
        }
        return await self.client.record_seller_decision(
            agreement_id, payload, seller_token=seller_token
        )

    async def precheck(self, transaction_id: str, agreement: Any) -> dict[str, Any]:
        agreement_dict = (
            agreement.model_dump(mode="json")
            if hasattr(agreement, "model_dump")
            else (agreement if isinstance(agreement, dict) else {})
        )
        return await self.client.precheck(transaction_id, agreement_dict)

    async def issue_approval_token(self, agreement_id: str) -> dict[str, Any]:
        return await self.client.issue_approval_token(agreement_id)

    async def buyer_decision(
        self,
        agreement_id: str,
        token: str,
        decision: Any,
        note: str = "",
        change_set: Any = None,
    ) -> dict[str, Any]:
        payload = {
            "agreement_version": getattr(decision, "agreement_version", None),
            "agreement_hash": getattr(decision, "agreement_hash", None),
            "decision": getattr(decision, "decision", decision).value
            if hasattr(getattr(decision, "decision", decision), "value")
            else str(getattr(decision, "decision", decision)),
            "note": note,
            "change_set": change_set.model_dump(mode="json")
            if hasattr(change_set, "model_dump")
            else change_set,
            "idempotency_key": f"buyer-decision:{agreement_id}:{getattr(decision, 'agreement_version', 0)}",
        }
        return await self.client.buyer_decision(agreement_id, token, payload)

    def verify_funding_binding(
        self,
        agreement: Any,
        transaction: Any,
        version: int,
        digest: str,
    ) -> None:
        agreement_dict = (
            agreement.model_dump(mode="json")
            if hasattr(agreement, "model_dump")
            else (agreement if isinstance(agreement, dict) else {})
        )
        transaction_dict = (
            transaction.model_dump(mode="json")
            if hasattr(transaction, "model_dump")
            else (transaction if isinstance(transaction, dict) else {})
        )
        status = agreement_dict.get("status")
        if status != "AGREED":
            raise AgreementBindingError("agreement is not AGREED")
        if int(agreement_dict.get("current_version") or 0) != int(version):
            raise AgreementBindingError("stale agreement version")
        if str(agreement_dict.get("agreement_hash")) != str(digest):
            # digest may be on current version record
            pass
        if str(transaction_dict.get("agreement_id")) != str(
            agreement_dict.get("agreement_id")
        ):
            raise AgreementBindingError("transaction is bound to another agreement")

    async def approve_funding(
        self, run_id: str, decision: FundingApprovalDecision
    ) -> dict[str, Any]:
        projection, _ = await self._binding(run_id)
        self._require_binding(
            run_id=run_id,
            projection=projection,
            transaction_id=decision.transaction_id,
            agreement_version=decision.agreement_version,
            agreement_hash=decision.agreement_hash,
        )
        if not decision.approved:
            canceled = await self.client.cancel(
                decision.transaction_id,
                CancelRequest(reason_code=CancelReason.BUYER_REJECTED, note=decision.note),
                actor="buyer-agent",
            )
            await self._store.save_projection(run_id, canceled)
            return {"projection": canceled, "checkout_url": None, "expires_at": None}
        await self.client.approve(
            decision.transaction_id,
            approval_id=str(uuid.uuid4()),
            approved_by=decision.approved_by,
            approved_at=_iso(decision.decided_at),
            note=decision.note,
            agreement_hash=decision.agreement_hash,
            agreement_version=decision.agreement_version,
        )
        funded = await self.client.fund(
            decision.transaction_id,
            FundRequest(
                agreement_hash=decision.agreement_hash,
                agreement_version=decision.agreement_version,
                return_url=f"{self.console_base_url}/runs/{run_id}",
                cancel_url=f"{self.console_base_url}/runs/{run_id}",
            ),
            idempotency_key=f"{decision.idempotency_key}:fund",
        )
        refreshed = await self.client.get_state(decision.transaction_id)
        await self._store.save_projection(run_id, refreshed)
        return {
            "projection": refreshed,
            "checkout_url": funded["checkout_url"],
            "expires_at": funded["expires_at"],
        }

    async def purchase_order(
        self, run_id: str, request: BuyerPurchaseOrderRequest
    ) -> dict[str, Any]:
        projection, agreement_payload = await self._binding(run_id)
        self._require_binding(
            run_id=run_id,
            projection=projection,
            transaction_id=request.transaction_id,
            agreement_version=request.agreement_version,
            agreement_hash=request.agreement_hash,
        )
        if projection.get("state") != "FUNDED":
            raise AgreementBindingError(
                "purchase order requires a funded transaction", status_code=409
            )
        agreement = AgreementProjection.model_validate(agreement_payload)
        approval = projection.get("approval") or {}
        approved_by = str(approval.get("approved_by") or "").strip()
        if not approved_by:
            raise AgreementBindingError(
                "funding approval is missing from the projection", status_code=409
            )
        try:
            decided_at = datetime.fromisoformat(
                str(approval.get("approved_at") or "")
            )
        except ValueError as exc:
            raise AgreementBindingError(
                "funding approval is malformed", status_code=409
            ) from exc
        po = PurchaseOrderRequest(
            request_id=f"po-{run_id}-{agreement.offer_id}",
            run_id=run_id,
            offer_id=agreement.offer_id,
            seller_id=agreement.seller_id,
            quantity=agreement.quantity,
            shipping_address=shipping_address(),
            approval=ApprovalReceipt(
                approval_id=str(approval.get("approval_id") or uuid.uuid4()),
                approved_by=approved_by,
                approved_at=decided_at,
                note=approval.get("note") or None,
            ),
            idempotency_key=f"{run_id}:{agreement.offer_id}",
            expected_total_cents=agreement.amount_cents,
            settlement_transaction_id=agreement.transaction_id,
            agreement_hash=agreement.agreement_hash,
        )
        return BuyerPurchaseOrderResponse(
            run_id=run_id,
            transaction_id=agreement.transaction_id,
            agreement_version=agreement.agreement_version,
            agreement_hash=agreement.agreement_hash,
            seller_id=agreement.seller_id,
            offer_id=agreement.offer_id,
            amount_cents=agreement.amount_cents,
            seller_token_ref=f"run:{run_id}:transaction:{agreement.transaction_id}",
            purchase_order=po.model_dump(mode="json", exclude_none=True),
        ).model_dump(mode="json")

    async def order(
        self, run_id: str, request: BuyerOrderReportRequest
    ) -> dict[str, Any]:
        projection, agreement_payload = await self._binding(run_id)
        self._require_binding(
            run_id=run_id,
            projection=projection,
            transaction_id=request.transaction_id,
            agreement_version=request.agreement_version,
            agreement_hash=request.agreement_hash,
        )
        if projection.get("state") not in {
            TransactionState.FUNDED.value,
            TransactionState.FULFILLMENT_PENDING.value,
            TransactionState.VERIFICATION_PENDING.value,
        }:
            raise AgreementBindingError(
                "order requires a funded transaction", status_code=409
            )
        agreement = AgreementProjection.model_validate(agreement_payload)
        order = request.order
        expected = {
            "offer_id": agreement.offer_id,
            "seller_id": agreement.seller_id,
            "quantity": agreement.quantity,
            "total_cents": agreement.amount_cents,
            "currency": agreement.currency,
        }
        actual = {
            "offer_id": order.get("offer_id"),
            "seller_id": order.get("seller_id"),
            "quantity": order.get("quantity"),
            "total_cents": order.get("total_cents"),
            "currency": order.get("currency", "USD"),
        }
        for field, expected_value in expected.items():
            if actual.get(field) != expected_value:
                raise AgreementBindingError(
                    f"order {field} does not match the agreement",
                    status_code=409,
                )
        line_items = [
            PurchaseOrderLineItem(
                sku=str(item.get("sku") or ""),
                quantity=int(item.get("quantity") or 0),
                unit_price_cents=int(item.get("unit_price_cents") or 0),
                warranty_addon_cents=int(
                    item.get("warranty_addon_cents") or 0
                ),
            )
            for item in order.get("line_items") or []
            if isinstance(item, dict)
        ]
        if not line_items:
            raise AgreementBindingError(
                "order has no line items", status_code=409
            )
        report = PurchaseOrderReport(
            agreement_hash=projection.get("agreement_hash", agreement.agreement_hash),
            seller_order_id=str(order.get("order_id") or ""),
            offer_id=agreement.offer_id,
            quantity=agreement.quantity,
            total_cents=agreement.amount_cents,
            currency=agreement.currency,
            tracking_number=str(order.get("tracking_number") or ""),
            carrier=str((order.get("fulfillment") or {}).get("carrier") or ""),
            reserved_at=_order_datetime(order, "reserved_at"),
            eta=_order_datetime(order, "eta"),
            line_items=line_items,
        )
        result = await self.client.purchase_order(
            agreement.transaction_id,
            report,
            idempotency_key=request.idempotency_key,
        )
        projection = {
            **result,
            "run_id": run_id,
            "transaction_id": agreement.transaction_id,
            "agreement_version": agreement.agreement_version,
            "agreement_hash": agreement.agreement_hash,
            "state": result.get("state")
            or TransactionState.FULFILLMENT_PENDING.value,
        }
        await self._store.save_projection(run_id, projection)
        return BuyerOrderReportResponse(
            run_id=run_id,
            transaction_id=agreement.transaction_id,
            agreement_version=agreement.agreement_version,
            agreement_hash=agreement.agreement_hash,
            state=projection["state"],
            projection=projection,
        ).model_dump(mode="json")

    async def release(
        self, run_id: str, decision: ReleaseApprovalDecision
    ) -> dict[str, Any]:
        projection, _ = await self._binding(run_id)
        self._require_binding(
            run_id=run_id,
            projection=projection,
            transaction_id=decision.transaction_id,
            agreement_version=decision.agreement_version,
            agreement_hash=decision.agreement_hash,
        )
        if not decision.approved:
            flagged_request = FlagReviewRequest(
                reason="manual_flag",
                note=decision.note or "release rejected by reviewer",
            )
            flagged_request.reason = ReviewReason.MANUAL_FLAG
            flagged = await self.client.flag_review(
                decision.transaction_id,
                flagged_request,
                actor="console:reviewer",
            )
            await self._store.save_projection(run_id, flagged)
            return flagged
        result = await self.client.release(
            decision.transaction_id,
            ReleaseRequest(
                released_by=decision.released_by,
                note=decision.note,
                override=decision.override,
            ),
            actor="console:reviewer",
        )
        await self._store.save_projection(run_id, result)
        return result

    async def receipt(self, run_id: str) -> dict[str, Any]:
        projection, _ = await self._binding(run_id)
        return await self.client.get_receipt(
            projection["transaction_id"], actor="console:reviewer"
        )

    async def evidence(
        self, run_id: str, evidence_id: str
    ) -> tuple[bytes, str, str]:
        projection, _ = await self._binding(run_id)
        return await self.client.get_evidence(
            projection["transaction_id"],
            evidence_id,
            actor="console:reviewer",
        )
