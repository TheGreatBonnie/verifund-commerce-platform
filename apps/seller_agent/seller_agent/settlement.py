from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from commerce_core.contracts import Order


class SettlementError(Exception):
    def __init__(
        self, code: str, message: str, *, status_code: int = 0
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def build_shipment_manifest(
    order: Order,
    *,
    transaction_id: str,
    agreement_hash: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    return {
        "transaction_id": transaction_id,
        "seller_id": order.seller_id,
        "agreement_hash": agreement_hash,
        "tracking_number": order.tracking_number,
        "carrier": order.fulfillment.carrier,
        "shipped_at": _iso(now - timedelta(hours=2)),
        "line_items": [
            {"sku": item.sku, "quantity": item.quantity}
            for item in order.line_items
        ],
    }


def build_delivery_confirmation(
    order: Order,
    *,
    transaction_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    return {
        "transaction_id": transaction_id,
        "tracking_number": order.tracking_number,
        "delivered_at": _iso(now - timedelta(hours=1)),
        "recipient": "Demo Buyer",
    }


def encode_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


class SellerSettlementClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(timeout=timeout_seconds)

    async def close(self) -> None:
        await self._client.aclose()

    def _headers(self, token: str) -> dict[str, str]:
        return {"authorization": f"Bearer {token}"}

    async def get_transaction(
        self, token: str, transaction_id: str
    ) -> dict[str, Any]:
        response = await self._client.get(
            f"{self.base_url}/seller/transactions/{transaction_id}",
            headers=self._headers(token),
        )
        if response.status_code >= 400:
            raise SettlementError(
                "unauthorized" if response.status_code == 401 else "invalid_request",
                "seller transaction lookup failed",
                status_code=response.status_code,
            )
        return response.json()

    async def upload_evidence(
        self,
        token: str,
        transaction_id: str,
        *,
        kind: str,
        content: bytes,
        media_type: str,
        filename: str,
        note: str = "",
        captured_at: str | None = None,
    ) -> dict[str, Any]:
        data = {"kind": kind}
        if note:
            data["note"] = note
        if captured_at:
            data["captured_at"] = captured_at
        response = await self._client.post(
            f"{self.base_url}/seller/transactions/{transaction_id}/evidence",
            headers=self._headers(token),
            data=data,
            files={"file": (filename, content, media_type)},
        )
        if response.status_code >= 400:
            raise SettlementError(
                "invalid_request",
                "evidence upload failed",
                status_code=response.status_code,
            )
        return response.json()

    async def get_evidence(
        self, token: str, transaction_id: str, evidence_id: str
    ) -> tuple[bytes, str]:
        response = await self._client.get(
            f"{self.base_url}/seller/transactions/{transaction_id}/evidence/{evidence_id}",
            headers=self._headers(token),
        )
        if response.status_code >= 400:
            raise SettlementError(
                "not_found",
                "evidence not found",
                status_code=response.status_code,
            )
        return response.content, response.headers.get(
            "content-type", "application/octet-stream"
        )
