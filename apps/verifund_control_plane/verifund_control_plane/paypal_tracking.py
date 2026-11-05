"""Outbound PayPal tracker sync (plan Tasks 28/29).

PayPal Tracking is outbound-only here: trackers are registered after capture
when a shipping reference or purchase order reports a tracking number, and the
persisted tracker is read back for ops/dispute display. Tracker state never
enters verification, rollup, remediation routing, or the release gate.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from urllib.parse import quote

import httpx

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.paypal.sandbox import SANDBOX_HOST

# PayPal Orders v2 accepts a fixed carrier enum. Anything outside the mapped
# names is sent as OTHER with the merchant's carrier name.
CARRIER_BY_NAME: dict[str, str] = {
    "fedex": "FEDEX",
    "ups": "UPS",
    "usps": "USPS",
    "dhl": "DHL",
    "dhl ecommerce": "DHL_ECOMMERCE",
    "dhl_ecommerce": "DHL_ECOMMERCE",
    "canada post": "CANADA_POST",
    "canada_post": "CANADA_POST",
    "royal mail": "ROYAL_MAIL",
    "royal_mail": "ROYAL_MAIL",
    "purolator": "PUROLATOR",
    "gls": "GLS",
    "dpd": "DPD",
}
KNOWN_CARRIERS = frozenset(CARRIER_BY_NAME.values()) | {"OTHER"}


def normalize_carrier(carrier: str | None) -> tuple[str, str | None]:
    """Return ``(paypal_carrier, carrier_name_other)``.

    Known carriers map to the enum. Unknown carriers use ``OTHER`` and keep
    their human-readable name in ``carrier_name_other``.
    """
    raw = (carrier or "").strip()
    if not raw:
        return "OTHER", None
    key = raw.lower().strip()
    if key in CARRIER_BY_NAME:
        return CARRIER_BY_NAME[key], None
    upper = raw.upper().replace(" ", "_")
    if upper in KNOWN_CARRIERS:
        return upper, None
    return "OTHER", raw


class PayPalTrackingClient(Protocol):
    async def sync(
        self,
        *,
        transaction_id: str,
        capture_id: str,
        tracking_number: str,
        carrier: str,
        items: list[dict[str, Any]],
        carrier_name_other: str | None = None,
    ) -> str: ...

    async def fetch(self, tracker_id: str) -> dict[str, Any] | None: ...


class FakePayPalTracking:
    """In-memory idempotent tracker used by tests and local development."""

    def __init__(self) -> None:
        self._ids: dict[tuple[str, str], str] = {}
        self._statuses: dict[str, str] = {}

    async def sync(
        self,
        *,
        transaction_id: str,
        capture_id: str,
        tracking_number: str,
        carrier: str = "OTHER",
        items: list[dict[str, Any]] | None = None,
        carrier_name_other: str | None = None,
    ) -> str:
        key = (capture_id, tracking_number)
        if key not in self._ids:
            self._ids[key] = f"{capture_id}-{tracking_number}"
            self._statuses[self._ids[key]] = "SHIPPED"
        return self._ids[key]

    async def fetch(self, tracker_id: str) -> dict[str, Any] | None:
        if tracker_id not in self._statuses:
            return None
        return {
            "tracker_id": tracker_id,
            "last_status": self._statuses[tracker_id],
            "status_source": "merchant_push",
        }

    def set_status(self, tracker_id: str, status: str) -> None:
        self._statuses[tracker_id] = status


class PayPalTrackingHttpClient:
    """Minimal OAuth client for Orders v2 track and Tracking v1 read-back."""

    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if base_url.rstrip("/") != SANDBOX_HOST:
            raise VerifundError(
                "invalid_request",
                "only the PayPal sandbox host is allowed",
                status_code=400,
            )
        self.base_url = SANDBOX_HOST
        self.client_id = client_id
        self.client_secret = client_secret
        self.timeout = timeout
        self.transport = transport
        self.clock = clock or (lambda: datetime.now(UTC))
        self._token: str | None = None
        self._token_expires_at = datetime.min.replace(tzinfo=UTC)

    def _now(self) -> datetime:
        return self.clock().astimezone(UTC)

    def _checked(self, response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 429 or response.status_code >= 500:
            raise VerifundError(
                "provider_unavailable",
                "PayPal is temporarily unavailable",
                status_code=503,
                retryable=True,
                details={"status": response.status_code},
            )
        if response.status_code >= 400:
            raise VerifundError(
                "provider_rejected",
                "PayPal rejected the request",
                status_code=502,
                details={"status": response.status_code},
            )
        if response.status_code == 204 or not response.content:
            return {}
        try:
            data = response.json()
        except ValueError as exc:
            raise VerifundError(
                "provider_ambiguous",
                "PayPal returned a non-JSON response",
                status_code=502,
                retryable=True,
            ) from exc
        if not isinstance(data, dict):
            raise VerifundError(
                "provider_ambiguous",
                "PayPal returned an unexpected payload",
                status_code=502,
                retryable=True,
            )
        return data

    async def _access_token(self) -> str:
        if self._token and self._now() < self._token_expires_at - timedelta(
            seconds=60
        ):
            return self._token
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport
        ) as client:
            response = await client.post(
                f"{self.base_url}/v1/oauth2/token",
                auth=(self.client_id, self.client_secret),
                data={"grant_type": "client_credentials"},
                headers={"accept": "application/json"},
            )
        data = self._checked(response)
        token = data.get("access_token")
        if not token:
            raise VerifundError(
                "provider_unavailable",
                "PayPal did not return an access token",
                status_code=503,
                retryable=True,
            )
        self._token = str(token)
        expires_in = int(data.get("expires_in") or 300)
        self._token_expires_at = self._now() + timedelta(seconds=expires_in)
        return self._token

    async def _call(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        token = await self._access_token()
        headers = {
            "authorization": f"Bearer {token}",
            "accept": "application/json",
        }
        if idempotency_key:
            headers["paypal-request-id"] = idempotency_key
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport
        ) as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                json=payload,
            )
        return self._checked(response)

    async def sync(
        self,
        *,
        transaction_id: str,
        capture_id: str,
        tracking_number: str,
        carrier: str,
        items: list[dict[str, Any]],
        carrier_name_other: str | None = None,
    ) -> str:
        carrier_code, fallback_name = normalize_carrier(carrier)
        payload: dict[str, Any] = {
            "capture_id": capture_id,
            "tracking_number": tracking_number,
            "carrier": carrier_code,
            "items": items,
            "notify_payer": True,
        }
        if carrier_code == "OTHER":
            payload["carrier_name_other"] = (
                carrier_name_other or fallback_name or carrier or "Other"
            )
        data = await self._call(
            "POST",
            f"/v2/checkout/orders/{quote(capture_id)}/track",
            payload=payload,
            idempotency_key=f"{capture_id}-{tracking_number}",
        )
        tracker_id = data.get("tracker_id")
        return str(tracker_id or f"{capture_id}-{tracking_number}")

    async def fetch(self, tracker_id: str) -> dict[str, Any] | None:
        data = await self._call(
            "GET", f"/v1/shipping/trackers/{quote(tracker_id)}"
        )
        trackers = data.get("trackers")
        record = trackers[0] if isinstance(trackers, list) and trackers else data
        if not isinstance(record, dict):
            return None
        return {
            "tracker_id": str(record.get("tracker_id") or tracker_id),
            "last_status": record.get("status") or record.get("last_status"),
            "status_source": "merchant_push",
        }
