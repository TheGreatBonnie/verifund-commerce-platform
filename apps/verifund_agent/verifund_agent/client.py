from __future__ import annotations

from typing import Any

import httpx

from verifund_contracts import (
    BuyerAgreementRequest,
    BuyerOrderReportRequest,
    BuyerPurchaseOrderRequest,
    FundingApprovalDecision,
    ReleaseApprovalDecision,
)


class BuyerAPIError(Exception):
    def __init__(self, message: str, *, status_code: int, retryable: bool) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class BuyerInternalClient:
    def __init__(
        self,
        base_url: str,
        *,
        internal_token: str,
        timeout: float = 20.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"x-verifund-agent-token": internal_token},
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def _request(self, method: str, path: str, *, json: Any = None) -> Any:
        kwargs = {}
        if json is not None:
            kwargs["content"] = __import__("json").dumps(json).encode("utf-8")
            kwargs["headers"] = {"content-type": "application/json"}
        response = await self._client.request(method, self.base_url + path, **kwargs)
        if response.status_code >= 400:
            raise BuyerAPIError(
                f"buyer returned HTTP {response.status_code}",
                status_code=response.status_code,
                retryable=response.status_code >= 500,
            )
        return response.json()

    async def create_agreement(
        self, run_id: str, request: BuyerAgreementRequest
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/internal/runs/{run_id}/settlement/agreement",
            json=request.model_dump(mode="json"),
        )

    async def get_settlement(self, run_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/internal/runs/{run_id}/settlement"
        )

    async def approve_funding(
        self, run_id: str, decision: FundingApprovalDecision
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/internal/runs/{run_id}/settlement/approve-funding",
            json=decision.model_dump(mode="json"),
        )

    async def purchase_order(
        self, run_id: str, request: BuyerPurchaseOrderRequest
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/internal/runs/{run_id}/settlement/purchase-order",
            json=request.model_dump(mode="json"),
        )

    async def report_order(
        self, run_id: str, request: BuyerOrderReportRequest
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/internal/runs/{run_id}/settlement/order",
            json=request.model_dump(mode="json"),
        )

    async def release(
        self, run_id: str, decision: ReleaseApprovalDecision
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/internal/runs/{run_id}/settlement/release",
            json=decision.model_dump(mode="json"),
        )

    async def receipt(self, run_id: str) -> dict[str, Any]:
        return await self._request(
            "GET", f"/internal/runs/{run_id}/settlement/receipt"
        )

    async def evidence(
        self, run_id: str, evidence_id: str
    ) -> tuple[bytes, str, str]:
        response = await self._client.get(
            f"{self.base_url}/internal/runs/{run_id}/settlement/evidence/{evidence_id}"
        )
        if response.status_code >= 400:
            raise BuyerAPIError(
                f"buyer returned HTTP {response.status_code}",
                status_code=response.status_code,
                retryable=response.status_code >= 500,
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
