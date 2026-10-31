from __future__ import annotations

from typing import Any

from verifund_contracts import (
    AcceptRequest,
    ApproveRequest,
    AwardRequest,
    BuyerAgreementReviewRequest,
    CancelRequest,
    FlagReviewRequest,
    FundRequest,
    PurchaseOrderReport,
    RejectReason,
    RejectRequest,
    ReleaseRequest,
    SellerTokenRequest,
    VerifundClient,
)


class BuyerSettlementClient:
    def __init__(
        self,
        base_url: str,
        *,
        ops_token: str,
        actor: str = "buyer-agent",
        timeout_seconds: float = 20.0,
    ) -> None:
        self.actor = actor
        self._client = VerifundClient(
            base_url,
            ops_token=ops_token,
            actor=actor,
            timeout=timeout_seconds,
        )

    async def close(self) -> None:
        await self._client.close()

    def _agreement_headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {
            "authorization": f"Bearer {self._client.ops_token}",
            "x-actor-id": self.actor,
            "x-actor-type": "buyer",
        }
        if idempotency_key:
            headers["idempotency-key"] = idempotency_key
        return headers

    async def get_agreement(self, agreement_id: str) -> dict:
        response = await self._client._client.get(
            f"{self._client.base_url}/agreements/{agreement_id}",
            headers=self._agreement_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def get_agreement_by_transaction(self, transaction_id: str) -> dict:
        response = await self._client._client.get(
            f"{self._client.base_url}/agreements",
            params={"transaction_id": transaction_id},
            headers=self._agreement_headers(),
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list):
            return data[0] if data else {}
        return data

    async def get_agreement_versions(self, agreement_id: str) -> list[dict]:
        response = await self._client._client.get(
            f"{self._client.base_url}/agreements/{agreement_id}/versions",
            headers=self._agreement_headers(),
        )
        response.raise_for_status()
        return response.json()

    async def get_agreement_document(
        self, agreement_id: str, version: int | None = None
    ) -> str:
        params = {"version": version} if version is not None else None
        response = await self._client._client.get(
            f"{self._client.base_url}/agreements/{agreement_id}/document",
            params=params,
            headers=self._agreement_headers(),
        )
        response.raise_for_status()
        return response.text

    async def issue_approval_token(
        self, agreement_id: str, *, idempotency_key: str | None = None
    ) -> dict:
        response = await self._client._client.post(
            f"{self._client.base_url}/agreements/{agreement_id}/approval-token",
            headers=self._agreement_headers(idempotency_key=idempotency_key),
        )
        response.raise_for_status()
        return response.json()

    async def record_seller_decision(
        self,
        agreement_id: str,
        payload: dict,
        *,
        seller_token: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        headers = self._agreement_headers(idempotency_key=idempotency_key)
        if seller_token:
            headers["x-seller-token"] = seller_token
        response = await self._client._client.post(
            f"{self._client.base_url}/agreements/{agreement_id}/seller-decision",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    async def precheck(
        self, transaction_id: str, agreement: dict | None = None
    ) -> dict:
        body: dict[str, Any] = {}
        if agreement:
            body["agreement"] = agreement
        # non-binding buyer precheck is stored via the buyer-review endpoint
        try:
            return await self.buyer_review(
                transaction_id,
                buyer_id=str((agreement or {}).get("buyer_id") or self.actor),
                agreement_version=int(
                    (agreement or {}).get("agreement_version", 1)
                ),
                agreement_hash=str(
                    (agreement or {}).get("agreement_hash", "0" * 64)
                ),
                decision="accepted",
                buyer_task_id=str((agreement or {}).get("run_id") or transaction_id),
                reviewed_at=__import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat().replace("+00:00", "Z"),
                idempotency_key=f"precheck:{transaction_id}",
            )
        except Exception:  # noqa
            response = await self._client._client.post(
                f"{self._client.base_url}/transactions/{transaction_id}/precheck",
                json=body,
                headers=self._agreement_headers(),
            )
            response.raise_for_status()
            return response.json()

    async def buyer_decision(
        self,
        agreement_id: str,
        token: str,
        payload: dict,
        *,
        idempotency_key: str | None = None,
    ) -> dict:
        headers = self._agreement_headers(idempotency_key=idempotency_key)
        headers["x-approval-token"] = token
        response = await self._client._client.post(
            f"{self._client.base_url}/agreements/{agreement_id}/buyer-decision",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    def _actor(self, actor: str | None) -> str:
        return actor or self.actor

    async def award(self, request: AwardRequest, *, idempotency_key: str) -> dict:
        response = await self._client.award(
            request, actor=self.actor, idempotency_key=idempotency_key
        )
        return response.model_dump(mode="json")

    async def buyer_review(
        self,
        transaction_id: str,
        *,
        buyer_id: str,
        agreement_version: int,
        agreement_hash: str,
        decision: str,
        buyer_task_id: str,
        reviewed_at: str,
        reason_code: str | None = None,
        note: str = "",
        idempotency_key: str,
    ) -> dict:
        projection = await self._client.buyer_review(
            transaction_id,
            BuyerAgreementReviewRequest(
                buyer_id=buyer_id,
                agreement_version=agreement_version,
                agreement_hash=agreement_hash,
                decision=decision,
                reason_code=reason_code,
                note=note,
                buyer_task_id=buyer_task_id,
                reviewed_at=reviewed_at,
            ),
            actor=self.actor,
            idempotency_key=idempotency_key,
        )
        if isinstance(projection, dict):
            return projection
        return projection.model_dump(mode="json")

    async def accept(
        self,
        transaction_id: str,
        *,
        seller_id: str,
        agreement_hash: str,
        accepted_total_cents: int,
        seller_task_id: str,
        accepted_at: str,
        agreement_version: int | None = None,
        offer_hash: str | None = None,
    ) -> dict:
        return await self._client.accept(
            transaction_id,
            AcceptRequest(
                seller_id=seller_id,
                agreement_hash=agreement_hash,
                accepted_total_cents=accepted_total_cents,
                seller_task_id=seller_task_id,
                accepted_at=accepted_at,
                agreement_version=agreement_version,
                offer_hash=offer_hash,
            ),
            actor=self.actor,
        )

    async def reject(
        self,
        transaction_id: str,
        *,
        seller_id: str,
        agreement_hash: str,
        reason_code: str,
        note: str,
        seller_task_id: str,
        rejected_at: str,
    ) -> dict:
        return await self._client.reject(
            transaction_id,
            RejectRequest(
                seller_id=seller_id,
                agreement_hash=agreement_hash,
                reason_code=RejectReason(reason_code),
                note=note,
                seller_task_id=seller_task_id,
                rejected_at=rejected_at,
            ),
            actor=self.actor,
        )

    async def approve(
        self,
        transaction_id: str,
        *,
        approval_id: str,
        approved_by: str,
        approved_at: str,
        note: str,
        agreement_hash: str,
        agreement_version: int | None = None,
    ) -> dict:
        return await self._client.approve(
            transaction_id,
            ApproveRequest(
                approval_id=approval_id,
                approved_by=approved_by,
                approved_at=approved_at,
                note=note,
                agreement_hash=agreement_hash,
                agreement_version=agreement_version or 1,
            ),
            actor=self.actor,
        )

    async def fund(
        self, transaction_id: str, request: FundRequest, *, idempotency_key: str
    ) -> dict:
        response = await self._client.fund(
            transaction_id,
            request,
            actor=self.actor,
            idempotency_key=idempotency_key,
        )
        return response.model_dump(mode="json")

    async def refresh_funding(self, transaction_id: str) -> dict:
        return await self._client.refresh_funding(
            transaction_id, actor=self.actor
        )

    async def purchase_order(
        self,
        transaction_id: str,
        report: PurchaseOrderReport,
        *,
        idempotency_key: str,
    ) -> dict:
        return await self._client.purchase_order(
            transaction_id,
            report,
            actor=self.actor,
            idempotency_key=idempotency_key,
        )

    async def verify(self, transaction_id: str, *, note: str = "") -> dict:
        return await self._client.verify(transaction_id, actor=self.actor)

    async def release(
        self,
        transaction_id: str,
        request: ReleaseRequest,
        *,
        actor: str | None = None,
    ) -> dict:
        return await self._client.release(
            transaction_id, request, actor=self._actor(actor)
        )

    async def flag_review(
        self,
        transaction_id: str,
        request: FlagReviewRequest,
        *,
        actor: str | None = None,
    ) -> dict:
        return await self._client.flag_review(
            transaction_id, request, actor=self._actor(actor)
        )

    async def cancel(
        self,
        transaction_id: str,
        request: CancelRequest,
        *,
        actor: str | None = None,
    ) -> dict:
        return await self._client.cancel(
            transaction_id, request, actor=self._actor(actor)
        )

    async def retry_payout(
        self, transaction_id: str, *, actor: str | None = None
    ) -> dict:
        return await self._client.payout(
            transaction_id, actor=self._actor(actor)
        )

    async def get_state(
        self, transaction_id: str, *, actor: str | None = None
    ) -> dict:
        projection = await self._client.get_state(
            transaction_id, actor=self._actor(actor)
        )
        return projection.model_dump(mode="json")

    async def get_receipt(
        self, transaction_id: str, *, actor: str | None = None
    ) -> dict:
        response = await self._client.receipt(
            transaction_id, actor=self._actor(actor)
        )
        return response.model_dump(mode="json")

    async def list_evidence(
        self, transaction_id: str, *, actor: str | None = None
    ) -> list[dict]:
        items = await self._client.list_evidence(
            transaction_id, actor=self._actor(actor)
        )
        return [item.model_dump(mode="json") for item in items]

    async def get_evidence(
        self,
        transaction_id: str,
        evidence_id: str,
        *,
        actor: str | None = None,
    ) -> tuple[bytes, str, str]:
        return await self._client.get_evidence(
            transaction_id, evidence_id, actor=self._actor(actor)
        )

    async def reissue_seller_token(
        self,
        *,
        transaction_id: str,
        run_id: str,
        seller_id: str,
        purpose: str,
    ) -> dict:
        response = await self._client.seller_token(
            transaction_id,
            SellerTokenRequest(
                run_id=run_id,
                transaction_id=transaction_id,
                seller_id=seller_id,
                purpose=purpose,
            ),
            actor=self.actor,
        )
        return response.model_dump(mode="json")

    async def revoke_seller_token(self, transaction_id: str) -> dict:
        return await self._client.revoke_seller_token(
            transaction_id, actor=self.actor
        )
