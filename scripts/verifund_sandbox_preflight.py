"""Validate a PayPal Sandbox configuration before starting the control plane."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verifund_control_plane.settings import Settings

PAYPAL_SANDBOX_HOST = "https://api-m.sandbox.paypal.com"


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class PreflightReport:
    checks: tuple[PreflightCheck, ...]

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    @property
    def failures(self) -> tuple[PreflightCheck, ...]:
        return tuple(check for check in self.checks if not check.ok)

    def lines(self) -> list[str]:
        return [
            f"[{'PASS' if check.ok else 'FAIL'}] {check.name}: {check.detail}"
            for check in self.checks
        ]

    def as_dicts(self) -> list[dict[str, Any]]:
        return [
            {"name": check.name, "ok": check.ok, "detail": check.detail}
            for check in self.checks
        ]


def _json_payload(response: httpx.Response) -> dict[str, Any]:
    try:
        value = response.json()
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _error_detail(response: httpx.Response) -> str:
    payload = _json_payload(response)
    for key in ("error_description", "error", "message", "detail"):
        value = payload.get(key)
        if value:
            return str(value)[:200]
    return response.text[:200].strip() or response.reason_phrase


def _settings_check(settings: Settings) -> tuple[PreflightCheck, str | None]:
    if settings.mode != "sandbox":
        detail = "VERIFUND_MODE=sandbox is required for PayPal settings validation"
        return PreflightCheck("settings", False, detail), detail
    try:
        settings.validate_for_mode()
    except ValueError as exc:
        return PreflightCheck("settings", False, str(exc)), str(exc)
    return (
        PreflightCheck("settings", True, "required sandbox settings are present"),
        None,
    )


def _checkout_checks(
    settings: Settings, environ: Mapping[str, str]
) -> list[PreflightCheck]:
    """The embedded card needs the same client id on both sides."""
    if environ.get("VERIFUND_CHECKOUT_MODE", "redirect") != "embedded":
        return []
    public_id = environ.get("NEXT_PUBLIC_PAYPAL_CLIENT_ID", "")
    return [
        PreflightCheck(
            "checkout_client_id",
            bool(public_id) and public_id == settings.paypal_client_id,
            (
                "NEXT_PUBLIC_PAYPAL_CLIENT_ID matches PAYPAL_CLIENT_ID"
                if public_id and public_id == settings.paypal_client_id
                else (
                    "NEXT_PUBLIC_PAYPAL_CLIENT_ID must be set and equal "
                    "PAYPAL_CLIENT_ID for the embedded checkout"
                )
            ),
        ),
        PreflightCheck(
            "checkout_client_secret",
            bool(settings.paypal_client_secret),
            (
                "PAYPAL_CLIENT_SECRET is present for the server-side order calls"
                if settings.paypal_client_secret
                else "PAYPAL_CLIENT_SECRET is required for the embedded checkout"
            ),
        ),
    ]


def _account_checks(settings: Settings) -> list[PreflightCheck]:
    accounts = {
        "platform": settings.paypal_platform_email,
        "buyer": settings.paypal_buyer_email,
    }
    missing = [name for name, value in accounts.items() if not value]
    account_check = PreflightCheck(
        "paypal_accounts",
        not missing,
        (
            "platform and buyer emails are set"
            if not missing
            else f"missing: {', '.join(missing)}"
        ),
    )

    payout_emails = list(settings.seller_payout_emails.values())
    problems: list[str] = []
    if not payout_emails:
        problems.append("no seller payout emails")
    if len(payout_emails) != len(set(payout_emails)):
        problems.append("duplicate payout emails")
    if settings.paypal_platform_email and settings.paypal_platform_email in payout_emails:
        problems.append("a payout email reuses the platform account")
    if settings.paypal_buyer_email and settings.paypal_buyer_email in payout_emails:
        problems.append("a payout email reuses the buyer account")
    payout_check = PreflightCheck(
        "seller_payouts",
        not problems,
        (
            f"{len(payout_emails)} payout accounts configured"
            if not problems
            else "; ".join(problems)
        ),
    )
    return [account_check, payout_check]


def _paypal_checks(
    settings: Settings, client: httpx.Client
) -> list[PreflightCheck]:
    base = settings.paypal_api_base.rstrip("/")
    try:
        response = client.post(
            f"{base}/v1/oauth2/token",
            auth=(settings.paypal_client_id, settings.paypal_client_secret),
            data={"grant_type": "client_credentials"},
            headers={"Accept": "application/json"},
        )
    except httpx.HTTPError as exc:
        detail = f"{type(exc).__name__}: {exc}"
        return [
            PreflightCheck("paypal_oauth", False, detail),
            PreflightCheck("paypal_webhook", False, "skipped: no access token"),
        ]
    if response.status_code != 200:
        detail = f"HTTP {response.status_code}: {_error_detail(response)}"
        return [
            PreflightCheck("paypal_oauth", False, detail),
            PreflightCheck("paypal_webhook", False, "skipped: no access token"),
        ]

    payload = _json_payload(response)
    token = str(payload.get("access_token") or "")
    oauth_check = PreflightCheck(
        "paypal_oauth",
        bool(token),
        (
            f"token acquired; expires_in={payload.get('expires_in')}"
            if token
            else "response did not include access_token"
        ),
    )
    if not token:
        return [
            oauth_check,
            PreflightCheck("paypal_webhook", False, "skipped: no access token"),
        ]

    try:
        webhook = client.get(
            f"{base}/v1/notifications/webhooks/{settings.paypal_webhook_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
    except httpx.HTTPError as exc:
        return [
            oauth_check,
            PreflightCheck("paypal_webhook", False, f"{type(exc).__name__}: {exc}"),
        ]

    return [
        oauth_check,
        PreflightCheck(
            "paypal_webhook",
            webhook.status_code == 200,
            (
                f"{settings.paypal_webhook_id} resolved for this REST app"
                if webhook.status_code == 200
                else (
                    f"HTTP {webhook.status_code} for "
                    f"{settings.paypal_webhook_id}: {_error_detail(webhook)}"
                )
            ),
        ),
    ]


def _public_checks(
    settings: Settings, client: httpx.Client
) -> list[PreflightCheck]:
    base = settings.public_base_url.rstrip("/")
    checks: list[PreflightCheck] = []
    try:
        health = client.get(f"{base}/health")
    except httpx.HTTPError as exc:
        checks.append(
            PreflightCheck("public_health", False, f"{type(exc).__name__}: {exc}")
        )
    else:
        checks.append(
            PreflightCheck(
                "public_health",
                health.status_code == 200,
                f"HTTP {health.status_code} for {base}/health",
            )
        )

    try:
        webhook = client.post(
            f"{base}/webhooks/paypal",
            headers={"content-type": "application/json"},
            content=b"{}",
        )
    except httpx.HTTPError as exc:
        checks.append(
            PreflightCheck("public_webhook", False, f"{type(exc).__name__}: {exc}")
        )
    else:
        checks.append(
            PreflightCheck(
                "public_webhook",
                webhook.status_code == 401,
                (
                    f"HTTP {webhook.status_code} for {base}/webhooks/paypal; "
                    "401 proves unsigned requests reach the control plane"
                ),
            )
        )
    return checks


def preflight(
    settings: Settings,
    *,
    client: httpx.Client,
    environ: Mapping[str, str] | None = None,
) -> PreflightReport:
    checks: list[PreflightCheck] = []
    mode_ok = settings.mode == "sandbox"
    checks.append(
        PreflightCheck(
            "mode",
            mode_ok,
            f"VERIFUND_MODE is {settings.mode!r}; expected 'sandbox'",
        )
    )

    settings_check, settings_error = _settings_check(settings)
    checks.append(settings_check)

    environment_ok = (
        settings.paypal_env == "sandbox"
        and settings.paypal_api_base.rstrip("/") == PAYPAL_SANDBOX_HOST
    )
    checks.append(
        PreflightCheck(
            "paypal_environment",
            environment_ok,
            (
                f"PAYPAL_ENV={settings.paypal_env!r}, "
                f"PAYPAL_API_BASE={settings.paypal_api_base!r}"
            ),
        )
    )
    checks.extend(_account_checks(settings))
    checks.extend(_checkout_checks(settings, environ or os.environ))
    checks.append(
        PreflightCheck(
            "reconciler",
            settings.reconciler_enabled,
            (
                "reconciler enabled"
                if settings.reconciler_enabled
                else "VERIFUND_RECONCILER_ENABLED=false"
            ),
        )
    )

    if mode_ok and settings_error is None and environment_ok:
        checks.extend(_paypal_checks(settings, client))
        checks.extend(_public_checks(settings, client))

    return PreflightReport(tuple(checks))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    args = parser.parse_args(argv)

    with httpx.Client(timeout=20.0, follow_redirects=False) as client:
        report = preflight(Settings(), client=client)

    if args.json:
        print(json.dumps(report.as_dicts(), indent=2))
    else:
        for line in report.lines():
            print(line)

    if report.ok:
        print("Sandbox preflight passed.")
        return 0
    print("Sandbox preflight failed; fix the checks above.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
