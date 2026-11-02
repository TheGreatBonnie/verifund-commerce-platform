from __future__ import annotations

from typing import Any

import httpx

from verifund_contracts.models import (
    AcceptRequest,
    ApproveRequest,
    AwardRequest,
    AwardResponse,
    BuyerAgreementReviewRequest,
    CancelRequest,
    ErrorEnvelope,
    EvidenceItem,
    FlagReviewRequest,
    FundRequest,
    FundResponse,
    PurchaseOrderReport,
    ReceiptResponse,
    RejectRequest,
    ReleaseRequest,
    SellerProjection,
    SellerTokenRequest,
    SellerTokenResponse,
    TransactionEvent,
    TransactionProjection,
)


class VerifundError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 0,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.details = details or {}
        self.request_id = request_id


class VerifundClient:
    def __init__(
        self,
        base_url: str,
        *,
        ops_token: str,
        actor: str = "buyer-agent",
        httpx_client: httpx.AsyncClient | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.ops_token = ops_token
        self.actor = actor
        self._client = httpx_client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = httpx_client is None

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        actor: str | None = None,
        idempotency_key: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        headers = {
            "authorization": f"Bearer {self.ops_token}",
            "x-verifund-actor": actor or self.actor,
        }
        if idempotency_key:
            headers["idempotency-key"] = idempotency_key
        response = await self._client.request(
            method,
            self.base_url + path,
            headers=headers,
            json=body,
            params=params,
        )
        if response.status_code >= 400:
            try:
                envelope = ErrorEnvelope.model_validate(response.json())
                detail = envelope.error
            except Exception:  # noqa: BLE001
                raise VerifundError(
                    "internal",
                    f"control plane returned HTTP {response.status_code}",
                    status_code=response.status_code,
                ) from None
            raise VerifundError(
                detail.code,
                detail.message,
                status_code=response.status_code,
                retryable=detail.retryable,
                details=detail.details,
                request_id=detail.request_id,
            )
        if response.status_code == 204:
            return None
        return response.json()

    async def award(
        self,
        request: AwardRequest,
        *,
        actor: str,
        idempotency_key: str,
    ) -> AwardResponse:
        return AwardResponse.model_validate(
            await self._request(
                "POST",
                "/awards",
                body=request.model_dump(mode="json"),
                actor=actor,
                idempotency_key=idempotency_key,
            )
        )

    async def buyer_review(
        self,
        transaction_id: str,
        request: BuyerAgreementReviewRequest | dict[str, Any],
        *,
        actor: str,
        idempotency_key: str | None = None,
    ) -> TransactionProjection | dict[str, Any]:
        body = (
            request.model_dump(mode="json")
            if isinstance(request, BuyerAgreementReviewRequest)
            else request
        )
        data = await self._request(
            "POST",
            f"/transactions/{transaction_id}/buyer-review",
            body=body,
            actor=actor,
            idempotency_key=idempotency_key,
        )
        if isinstance(data, dict) and {"transaction_id", "state"} <= data.keys():
            return TransactionProjection.model_validate(data)
        return data

    async def get_transaction(
        self, transaction_id: str, *, actor: str = "buyer-agent"
    ) -> dict:
        return await self._request(
            "GET", f"/transactions/{transaction_id}", actor=actor
        )

    async def get_state(
        self, transaction_id: str, *, actor: str = "buyer-agent"
    ) -> TransactionProjection:
        return TransactionProjection.model_validate(
            await self._request(
                "GET", f"/transactions/{transaction_id}/state", actor=actor
            )
        )

    async def list_transactions(
        self, *, run_id: str | None = None, state: str | None = None
    ) -> list[dict]:
        params = {
            k: v
            for k, v in {"run_id": run_id, "state": state}.items()
            if v
        }
        return await self._request(
            "GET", "/transactions", actor="buyer-agent", params=params
        )

    async def accept(
        self,
        transaction_id: str,
        request: AcceptRequest,
        *,
        actor: str,
        idempotency_key: str | None = None,
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/accept",
            body=request.model_dump(mode="json"),
            actor=actor,
            idempotency_key=idempotency_key,
        )

    async def reject(
        self,
        transaction_id: str,
        request: RejectRequest,
        *,
        actor: str,
        idempotency_key: str | None = None,
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/reject",
            body=request.model_dump(mode="json"),
            actor=actor,
            idempotency_key=idempotency_key,
        )

    async def approve(
        self,
        transaction_id: str,
        request: ApproveRequest,
        *,
        actor: str,
        idempotency_key: str | None = None,
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/approve",
            body=request.model_dump(mode="json"),
            actor=actor,
            idempotency_key=idempotency_key,
        )

    async def fund(
        self,
        transaction_id: str,
        request: FundRequest,
        *,
        actor: str,
        idempotency_key: str | None = None,
    ) -> FundResponse:
        return FundResponse.model_validate(
            await self._request(
                "POST",
                f"/transactions/{transaction_id}/fund",
                body=request.model_dump(mode="json"),
                actor=actor,
                idempotency_key=idempotency_key,
            )
        )

    async def prepare_funding(
        self, transaction_id: str, *, actor: str = "buyer-agent"
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/funding/prepare",
            body={},
            actor=actor,
        )

    async def refresh_funding(
        self, transaction_id: str, *, actor: str = "buyer-agent"
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/funding/refresh",
            body={},
            actor=actor,
        )

    async def purchase_order(
        self,
        transaction_id: str,
        request: PurchaseOrderReport,
        *,
        actor: str,
        idempotency_key: str | None = None,
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/purchase-order",
            body=request.model_dump(mode="json"),
            actor=actor,
            idempotency_key=idempotency_key,
        )

    async def verify(
        self, transaction_id: str, *, actor: str = "buyer-agent"
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/verify",
            body={},
            actor=actor,
        )

    async def release(
        self,
        transaction_id: str,
        request: ReleaseRequest,
        *,
        actor: str,
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/release",
            body=request.model_dump(mode="json"),
            actor=actor,
        )

    async def payout(
        self, transaction_id: str, *, actor: str = "buyer-agent"
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/payout",
            body={},
            actor=actor,
        )

    async def refresh_payout(
        self, transaction_id: str, *, actor: str = "buyer-agent"
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/payout/refresh",
            body={},
            actor=actor,
        )

    async def cancel(
        self,
        transaction_id: str,
        request: CancelRequest,
        *,
        actor: str,
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/cancel",
            body=request.model_dump(mode="json"),
            actor=actor,
        )

    async def flag_review(
        self,
        transaction_id: str,
        request: FlagReviewRequest,
        *,
        actor: str,
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/flag-review",
            body=request.model_dump(mode="json"),
            actor=actor,
        )

    async def seller_token(
        self,
        transaction_id: str,
        request: SellerTokenRequest,
        *,
        actor: str = "buyer-agent",
    ) -> SellerTokenResponse:
        return SellerTokenResponse.model_validate(
            await self._request(
                "POST",
                f"/transactions/{transaction_id}/seller-token",
                body=request.model_dump(mode="json"),
                actor=actor,
            )
        )

    async def revoke_seller_token(
        self, transaction_id: str, *, actor: str = "buyer-agent"
    ) -> dict:
        return await self._request(
            "POST",
            f"/transactions/{transaction_id}/seller-token/revoke",
            body={},
            actor=actor,
        )

    async def events(
        self, transaction_id: str, *, after_seq: int = 0
    ) -> list[TransactionEvent]:
        rows = await self._request(
            "GET",
            f"/transactions/{transaction_id}/events",
            actor="buyer-agent",
            params={"after_seq": after_seq},
        )
        return [TransactionEvent.model_validate(row) for row in rows]

    async def receipt(
        self, transaction_id: str, *, actor: str = "buyer-agent"
    ) -> ReceiptResponse:
        return ReceiptResponse.model_validate(
            await self._request(
                "GET", f"/transactions/{transaction_id}/receipt", actor=actor
            )
        )

    async def list_evidence(
        self, transaction_id: str, *, actor: str = "buyer-agent"
    ) -> list[EvidenceItem]:
        rows = await self._request(
            "GET",
            f"/transactions/{transaction_id}/evidence",
            actor=actor,
        )
        return [EvidenceItem.model_validate(row) for row in rows]

    async def get_evidence(
        self,
        transaction_id: str,
        evidence_id: str,
        *,
        actor: str = "buyer-agent",
    ) -> tuple[bytes, str, str]:
        response = await self._client.get(
            f"{self.base_url}/transactions/{transaction_id}/evidence/{evidence_id}",
            headers={
                "authorization": f"Bearer {self.ops_token}",
                "x-verifund-actor": actor,
            },
        )
        if response.status_code >= 400:
            raise VerifundError(
                "not_found",
                "evidence not found",
                status_code=response.status_code,
            )
        disposition = response.headers.get("content-disposition", "")
        filename = "evidence"
        if 'filename="' in disposition:
            filename = disposition.split('filename="', 1)[1].split('"', 1)[0]
        return (
            response.content,
            response.headers.get("content-type", "application/octet-stream"),
            filename,
        )

    async def seller_projection(
        self, transaction_id: str, token: str
    ) -> SellerProjection:
        response = await self._client.get(
            f"{self.base_url}/seller/transactions/{transaction_id}",
            headers={"authorization": f"Bearer {token}"},
        )
        if response.status_code >= 400:
            raise VerifundError(
                "unauthorized",
                "seller token rejected",
                status_code=response.status_code,
            )
        return SellerProjection.model_validate(response.json())
