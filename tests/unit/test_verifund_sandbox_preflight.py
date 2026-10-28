from __future__ import annotations

import httpx
from verifund_control_plane.settings import Settings

from scripts.verifund_sandbox_preflight import preflight


def sandbox_settings(**overrides):
    values = {
        "_env_file": None,
        "mode": "sandbox",
        "host": "127.0.0.1",
        "public_base_url": "https://verifund.example.com",
        "console_base_url": "https://console.example.com",
        "ops_token": "o" * 32,
        "seller_token_secret": "s" * 32,
        "link_secret": "l" * 32,
        "receipt_keys": {"test-1": "r" * 32},
        "receipt_active_kid": "test-1",
        "paypal_env": "sandbox",
        "paypal_api_base": "https://api-m.sandbox.paypal.com",
        "paypal_client_id": "client-id",
        "paypal_client_secret": "client-secret",
        "paypal_webhook_id": "WH-1",
        "paypal_platform_email": "platform@example.com",
        "paypal_buyer_email": "buyer@example.com",
        "seller_payout_emails": {"northwind-audio": "northwind@example.com"},
    }
    values.update(overrides)
    return Settings(**values)


def paypal_handler(requests: list[str] | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(f"{request.method} {request.url}")
        host = request.url.host
        if host == "api-m.sandbox.paypal.com":
            if request.url.path == "/v1/oauth2/token":
                assert request.headers["authorization"].startswith("Basic ")
                return httpx.Response(
                    200,
                    json={"access_token": "A21.test", "expires_in": 32400},
                )
            if request.url.path == "/v1/notifications/webhooks/WH-1":
                assert request.headers["authorization"] == "Bearer A21.test"
                return httpx.Response(200, json={"id": "WH-1"})
        if host == "verifund.example.com":
            if request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            if request.url.path == "/webhooks/paypal":
                return httpx.Response(401, json={"detail": "signature"})
        return httpx.Response(404)

    return handler


def test_preflight_passes_a_complete_sandbox_configuration():
    requests: list[str] = []
    with httpx.Client(
        transport=httpx.MockTransport(paypal_handler(requests))
    ) as client:
        report = preflight(sandbox_settings(), client=client)

    assert report.ok, report.lines()
    assert [check.name for check in report.checks] == [
        "mode",
        "settings",
        "paypal_environment",
        "paypal_accounts",
        "seller_payouts",
        "reconciler",
        "paypal_oauth",
        "paypal_webhook",
        "public_health",
        "public_webhook",
    ]
    assert any(
        item == "POST https://verifund.example.com/webhooks/paypal"
        for item in requests
    )


def test_preflight_rejects_non_sandbox_mode_without_network():
    called: list[str] = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                called.append(str(request.url))
                or httpx.Response(500)
            )
        )
    ) as client:
        report = preflight(sandbox_settings(mode="fake"), client=client)

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["mode"].ok is False
    assert called == []


def test_preflight_stops_before_network_when_settings_fail():
    called: list[str] = []
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                called.append(str(request.url))
                or httpx.Response(500)
            )
        )
    ) as client:
        report = preflight(
            sandbox_settings(seller_payout_emails={}), client=client
        )

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["settings"].ok is False
    assert "VERIFUND_SELLER_PAYOUT_EMAILS" in checks["settings"].detail
    assert called == []


def test_preflight_rejects_payout_email_overlap():
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(500)
        )
    ) as client:
        report = preflight(
            sandbox_settings(
                seller_payout_emails={"northwind-audio": "buyer@example.com"}
            ),
            client=client,
        )

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["settings"].ok is False
    assert checks["seller_payouts"].ok is False
    assert "buyer account" in checks["seller_payouts"].detail


def test_preflight_reports_paypal_oauth_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                401,
                json={
                    "error": "invalid_client",
                    "error_description": "Client Authentication failed",
                },
            )
        return httpx.Response(404)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = preflight(sandbox_settings(), client=client)

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["paypal_oauth"].ok is False
    assert "HTTP 401" in checks["paypal_oauth"].detail
    assert "Client Authentication failed" in checks["paypal_oauth"].detail
    assert checks["paypal_webhook"].ok is False
    assert "skipped" in checks["paypal_webhook"].detail


def test_preflight_reports_an_unreachable_public_url():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/oauth2/token":
            return httpx.Response(
                200, json={"access_token": "A21.test", "expires_in": 32400}
            )
        if request.url.path == "/v1/notifications/webhooks/WH-1":
            return httpx.Response(200, json={"id": "WH-1"})
        raise httpx.ConnectError("tunnel is down", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        report = preflight(sandbox_settings(), client=client)

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["public_health"].ok is False
    assert "ConnectError" in checks["public_health"].detail
    assert checks["public_webhook"].ok is False


def test_preflight_requires_the_reconciler():
    with httpx.Client(
        transport=httpx.MockTransport(paypal_handler())
    ) as client:
        report = preflight(
            sandbox_settings(reconciler_enabled=False), client=client
        )

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["reconciler"].ok is False
    assert "VERIFUND_RECONCILER_ENABLED" in checks["reconciler"].detail


def test_preflight_rejects_the_live_paypal_host():
    with httpx.Client(
        transport=httpx.MockTransport(paypal_handler())
    ) as client:
        report = preflight(
            sandbox_settings(
                paypal_api_base="https://api-m.paypal.com",
                public_base_url="https://verifund.example.com",
            ),
            client=client,
        )

    checks = {check.name: check for check in report.checks}
    assert report.ok is False
    assert checks["paypal_environment"].ok is False
    assert checks["settings"].ok is False
