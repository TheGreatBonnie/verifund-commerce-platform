from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from verifund_control_plane.domain import TransactionRecord
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.paypal.port import (
    CaptureResult,
    OrderResult,
    PayoutResult,
)

SANDBOX_HOST = "https://api-m.sandbox.paypal.com"


def _value(amount_cents: int) -> str:
    return f"{Decimal(amount_cents) / Decimal(100):.2f}"


def _cents(value: Any) -> int:
    return int((Decimal(str(value)) * 100).to_integral_value())


class PayPalSandboxPaymentPort:
    def __init__(
        self,
        *,
        base_url: str,
        client_id: str,
        client_secret: str,
        webhook_id: str,
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
        self.webhook_id = webhook_id
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

    async def create_order(
        self,
        txn: TransactionRecord,
        *,
        return_url: str,
        cancel_url: str,
        idempotency_key: str,
    ) -> OrderResult:
        data = await self._call(
            "POST",
            "/v2/checkout/orders",
            payload={
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": txn.transaction_id,
                        "custom_id": txn.transaction_id,
                        "invoice_id": txn.transaction_id,
                        "description": f"Verifund {txn.transaction_id}",
                        "amount": {
                            "currency_code": txn.currency,
                            "value": _value(txn.amount_cents),
                        },
                    }
                ],
                "payment_source": {
                    "paypal": {
                        "experience_context": {
                            "user_action": "PAY_NOW",
                            "return_url": return_url,
                            "cancel_url": cancel_url,
                        }
                    }
                },
            },
            idempotency_key=idempotency_key,
        )
        links = data.get("links") or []
        payer_url = next(
            (
                link.get("href")
                for link in links
                if link.get("rel") in {"payer-action", "approve"}
            ),
            None,
        )
        return OrderResult(
            order_id=str(data["id"]),
            status=str(data.get("status") or "CREATED"),
            payer_action_url=payer_url,
            raw=data,
        )

    def _capture(
        self, data: dict[str, Any], *, fallback_order_id: str
    ) -> CaptureResult:
        captures: list[dict[str, Any]] = []
        for unit in data.get("purchase_units") or []:
            captures.extend(
                (unit.get("payments") or {}).get("captures") or []
            )
        if not captures:
            raise VerifundError(
                "provider_ambiguous",
                "PayPal response contains no capture",
                status_code=502,
                retryable=True,
                details={"order_id": fallback_order_id},
            )
        raw = captures[0]
        amount = raw.get("amount") or {}
        related = ((raw.get("supplementary_data") or {}).get("related_ids") or {})
        return CaptureResult(
            order_id=str(related.get("order_id") or fallback_order_id),
            capture_id=str(raw["id"]),
            status=str(raw.get("status") or "UNKNOWN"),
            amount_cents=_cents(amount.get("value", "0")),
            currency=str(amount.get("currency_code") or ""),
            raw=raw,
        )

    async def capture_order(
        self, order_id: str, *, idempotency_key: str
    ) -> CaptureResult:
        data = await self._call(
            "POST",
            f"/v2/checkout/orders/{order_id}/capture",
            payload={},
            idempotency_key=idempotency_key,
        )
        return self._capture(data, fallback_order_id=order_id)

    async def get_order(self, order_id: str) -> OrderResult:
        data = await self._call("GET", f"/v2/checkout/orders/{order_id}")
        captures: tuple[CaptureResult, ...] = ()
        if any(
            (unit.get("payments") or {}).get("captures")
            for unit in data.get("purchase_units") or []
        ):
            captures = (self._capture(data, fallback_order_id=order_id),)
        return OrderResult(
            order_id=str(data.get("id") or order_id),
            status=str(data.get("status") or "UNKNOWN"),
            captures=captures,
            raw=data,
        )

    async def create_payout(
        self,
        txn: TransactionRecord,
        *,
        seller_email: str,
        batch_id: str,
        item_id: str,
    ) -> PayoutResult:
        data = await self._call(
            "POST",
            "/v1/payments/payouts",
            payload={
                "sender_batch_header": {
                    "sender_batch_id": batch_id,
                    "email_subject": "You have a payment",
                    "email_message": "You received a payment from Verifund.",
                },
                "items": [
                    {
                        "recipient_type": "EMAIL",
                        "amount": {
                            "value": _value(txn.amount_cents),
                            "currency": txn.currency,
                        },
                        "receiver": seller_email,
                        "note": f"Verifund {txn.transaction_id}",
                        "sender_item_id": item_id,
                    }
                ],
            },
            idempotency_key=batch_id,
        )
        header = data.get("batch_header") or {}
        provider_batch = str(header.get("payout_batch_id") or batch_id)
        batch = await self._call(
            "GET", f"/v1/payments/payouts/{provider_batch}"
        )
        match = next(
            (
                candidate
                for candidate in batch.get("items") or []
                if str((candidate.get("payout_item") or {}).get("sender_item_id"))
                == item_id
            ),
            None,
        )
        if match is None:
            raise VerifundError(
                "provider_ambiguous",
                "PayPal payout item is not available yet",
                status_code=503,
                retryable=True,
                details={"batch_id": provider_batch},
            )
        item = match.get("payout_item") or {}
        amount = item.get("amount") or {}
        return PayoutResult(
            batch_id=provider_batch,
            item_id=str(match["payout_item_id"]),
            status=str(
                match.get("transaction_status")
                or header.get("batch_status")
                or "PENDING"
            ),
            amount_cents=_cents(amount.get("value", "0")),
            currency=str(amount.get("currency_code") or txn.currency),
            raw={"batch_header": header, "item": match},
        )

    async def get_payout_item(self, item_id: str) -> PayoutResult:
        data = await self._call(
            "GET", f"/v1/payments/payouts-item/{item_id}"
        )
        item = data.get("payout_item") or {}
        amount = item.get("amount") or {}
        return PayoutResult(
            batch_id=str(data.get("payout_batch_id") or ""),
            item_id=str(data.get("payout_item_id") or item_id),
            status=str(
                data.get("transaction_status")
                or data.get("status")
                or "UNKNOWN"
            ),
            amount_cents=_cents(amount.get("value", "0")),
            currency=str(amount.get("currency_code") or "USD"),
            raw=data,
        )

    async def verify_webhook(
        self, headers: Mapping[str, str], raw_body: bytes
    ) -> bool:
        try:
            event = json.loads(raw_body)
        except ValueError:
            return False
        try:
            data = await self._call(
                "POST",
                "/v1/notifications/verify-webhook-signature",
                payload={
                    "auth_algo": headers.get("paypal-auth-algo", ""),
                    "cert_url": headers.get("paypal-cert-url", ""),
                    "transmission_id": headers.get(
                        "paypal-transmission-id", ""
                    ),
                    "transmission_sig": headers.get(
                        "paypal-transmission-sig", ""
                    ),
                    "transmission_time": headers.get(
                        "paypal-transmission-time", ""
                    ),
                    "webhook_id": self.webhook_id,
                    "webhook_event": event,
                },
            )
        except VerifundError as exc:
            if exc.code == "provider_rejected":
                return False
            raise
        return data.get("verification_status") == "SUCCESS"