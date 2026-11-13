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
    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        retryable: bool,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable
        self.code = code

    @classmethod
    def from_response(cls, response: httpx.Response) -> BuyerAPIError:
        message = f"buyer returned HTTP {response.status_code}"
        retryable = response.status_code >= 500
        code: str | None = None
        try:
            body = response.json()
        except ValueError:
            body = None
        if isinstance(body, dict):
            detail = body.get("error") or body.get("detail")
            if isinstance(detail, str) and detail:
                message = detail
            elif isinstance(detail, dict):
                code = detail.get("code")
                message = str(detail.get("message") or message)
                if isinstance(detail.get("retryable"), bool):
                    retryable = detail["retryable"]
        return cls(
            message,
            status_code=response.status_code,
            retryable=retryable,
            code=code,
        )


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
        if json is not None:
            response = await self._client.request(
                method,
                self.base_url + path,
                json=json,
                headers={"content-type": "application/json"},
            )
        else:
            response = await self._client.request(method, self.base_url + path)
        if response.status_code >= 400:
            raise BuyerAPIError.from_response(response)
        return response.json()

    async def create_agreement(
        self, run_id: str, request: BuyerAgreementRequest
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/internal/runs/{run_id}/settlement/agreement",
            json=request.model_dump(mode="json"),
        )

    async def get_settlement(
        self, run_id: str, *, refresh: bool = False
    ) -> dict[str, Any]:
        suffix = "?refresh=true" if refresh else ""
        return await self._request(
            "GET", f"/internal/runs/{run_id}/settlement{suffix}"
        )

    async def get_agreement(self, run_id: str) -> dict[str, Any]:
        view = await self.get_settlement(run_id)
        agreement = view.get("agreement")
        if not isinstance(agreement, dict):
            raise BuyerAPIError(
                "buyer returned no agreement",
                status_code=404,
                retryable=False,
            )
        return agreement

    async def approve_funding(
        self,
        run_id: str,
        decision: FundingApprovalDecision,
        *,
        defer_checkout: bool = False,
    ) -> dict[str, Any]:
        suffix = "?defer_checkout=true" if defer_checkout else ""
        return await self._request(
            "POST",
            f"/internal/runs/{run_id}/settlement/approve-funding{suffix}",
            json=decision.model_dump(mode="json"),
        )

    async def prepare_funding(self, run_id: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/internal/runs/{run_id}/settlement/prepare-funding",
            json={},
        )

    async def cancel(
        self, run_id: str, *, reason_code: str, note: str = ""
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/internal/runs/{run_id}/settlement/cancel",
            json={"reason_code": reason_code, "note": note},
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
            raise BuyerAPIError.from_response(response)
        disposition = response.headers.get("content-disposition", "")
        filename = "evidence"
        if 'filename="' in disposition:
            filename = disposition.split('filename="', 1)[1].split('"', 1)[0]
        return (
            response.content,
            response.headers.get("content-type", "application/octet-stream"),
            filename,
        )
