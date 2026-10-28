from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

import httpx
import pytest

from verifund_control_plane.domain import TransactionRecord
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.paypal.sandbox import PayPalSandboxPaymentPort

TXN = cast(
    TransactionRecord,
    SimpleNamespace(
        transaction_id="vf_1",
        amount_cents=123400,
        currency="USD",
        seller_id="northwind-audio",
        run_id="run-1",
    ),
)


def port(handler) -> PayPalSandboxPaymentPort:
    return PayPalSandboxPaymentPort(
        base_url="https://api-m.sandbox.paypal.com",
        client_id="client",
        client_secret="secret",
        webhook_id="WH-1",
        transport=httpx.MockTransport(handler),
    )


def token_response() -> httpx.Response:
    return httpx.Response(
        200, json={"access_token": "tok", "expires_in": 3600}
    )


async def test_create_order_uses_request_id_and_payer_action():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            assert request.headers["authorization"].startswith("Basic ")
            return token_response()
        assert request.url.path == "/v2/checkout/orders"
        assert request.headers["paypal-request-id"] == "fund:vf_1:v1"
        assert request.headers["authorization"] == "Bearer tok"
        body = json.loads(request.content)
        assert body["intent"] == "CAPTURE"
        unit = body["purchase_units"][0]
        assert unit["custom_id"] == "vf_1"
        assert unit["amount"] == {"currency_code": "USD", "value": "1234.00"}
        context = body["payment_source"]["paypal"]["experience_context"]
        assert context["user_action"] == "PAY_NOW"
        assert context["return_url"] == "https://console.test/return/t"
        assert context["cancel_url"] == "https://console.test/cancel/t"
        return httpx.Response(
            201,
            json={
                "id": "ORDER-1",
                "status": "PAYER_ACTION_REQUIRED",
                "links": [
                    {"rel": "self", "href": "https://api.test/orders/ORDER-1"},
                    {"rel": "payer-action", "href": "https://paypal.test/approve"},
                ],
            },
        )

    order = await port(handler).create_order(
        TXN,
        return_url="https://console.test/return/t",
        cancel_url="https://console.test/cancel/t",
        idempotency_key="fund:vf_1:v1",
    )
    assert order.order_id == "ORDER-1"
    assert order.status == "PAYER_ACTION_REQUIRED"
    assert order.payer_action_url == "https://paypal.test/approve"


async def test_capture_order_parses_amount():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response()
        assert request.url.path == "/v2/checkout/orders/ORDER-1/capture"
        assert request.headers["paypal-request-id"] == "capture:vf_1:v1"
        return httpx.Response(
            201,
            json={
                "id": "ORDER-1",
                "status": "COMPLETED",
                "purchase_units": [
                    {
                        "payments": {
                            "captures": [
                                {
                                    "id": "CAP-1",
                                    "status": "COMPLETED",
                                    "amount": {
                                        "value": "1234.00",
                                        "currency_code": "USD",
                                    },
                                    "supplementary_data": {
                                        "related_ids": {"order_id": "ORDER-1"}
                                    },
                                }
                            ]
                        }
                    }
                ],
            },
        )

    capture = await port(handler).capture_order(
        "ORDER-1", idempotency_key="capture:vf_1:v1"
    )
    assert capture.capture_id == "CAP-1"
    assert capture.status == "COMPLETED"
    assert capture.amount_cents == 123400
    assert capture.currency == "USD"


async def test_verify_webhook_posts_transmission_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response()
        assert request.url.path == "/v1/notifications/verify-webhook-signature"
        body = json.loads(request.content)
        assert body["webhook_id"] == "WH-1"
        assert body["transmission_id"] == "t-1"
        assert body["transmission_sig"] == "sig"
        assert body["webhook_event"]["id"] == "WH-EVT-1"
        return httpx.Response(200, json={"verification_status": "SUCCESS"})

    raw = json.dumps({"id": "WH-EVT-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"}).encode()
    verified = await port(handler).verify_webhook(
        {
            "paypal-auth-algo": "SHA256withRSA",
            "paypal-cert-url": "https://api.test/cert",
            "paypal-transmission-id": "t-1",
            "paypal-transmission-sig": "sig",
            "paypal-transmission-time": "2026-10-27T12:00:00Z",
        },
        raw,
    )
    assert verified is True


async def test_verify_webhook_returns_false_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response()
        return httpx.Response(200, json={"verification_status": "FAILURE"})

    assert (
        await port(handler).verify_webhook({}, b'{"id":"WH-EVT-1"}') is False
    )


async def test_provider_errors_are_classified():
    def unavailable(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response()
        return httpx.Response(503, json={"name": "SERVICE_UNAVAILABLE"})

    with pytest.raises(VerifundError) as raised:
        await port(unavailable).get_order("ORDER-1")
    assert raised.value.code == "provider_unavailable"
    assert raised.value.retryable

    def rejected(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response()
        return httpx.Response(422, json={"name": "UNPROCESSABLE_ENTITY"})

    with pytest.raises(VerifundError) as raised:
        await port(rejected).get_order("ORDER-1")
    assert raised.value.code == "provider_rejected"
    assert not raised.value.retryable


async def test_create_payout_resolves_provider_item_id():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return token_response()
        if request.url.path == "/v1/payments/payouts" and request.method == "POST":
            body = json.loads(request.content)
            header = body["sender_batch_header"]
            item = body["items"][0]
            assert header["sender_batch_id"] == "batch-vf_1"
            assert item["sender_item_id"] == "item-vf_1"
            assert item["receiver"] == "seller@example.test"
            assert item["amount"] == {"value": "1234.00", "currency": "USD"}
            return httpx.Response(
                201,
                json={
                    "batch_header": {
                        "payout_batch_id": "BATCH-1",
                        "batch_status": "PENDING",
                    }
                },
            )
        assert request.url.path == "/v1/payments/payouts/BATCH-1"
        return httpx.Response(
            200,
            json={
                "batch_header": {
                    "payout_batch_id": "BATCH-1",
                    "batch_status": "PENDING",
                },
                "items": [
                    {
                        "payout_item_id": "ITEM-1",
                        "transaction_status": "PENDING",
                        "payout_item": {
                            "sender_item_id": "item-vf_1",
                            "receiver": "seller@example.test",
                            "amount": {"value": "1234.00", "currency": "USD"},
                        },
                    }
                ],
            },
        )

    payout = await port(handler).create_payout(
        TXN,
        seller_email="seller@example.test",
        batch_id="batch-vf_1",
        item_id="item-vf_1",
    )
    assert payout.batch_id == "BATCH-1"
    assert payout.item_id == "ITEM-1"
    assert payout.status == "PENDING"
    assert payout.amount_cents == 123400