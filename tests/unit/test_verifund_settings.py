from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def sandbox_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "mode": "sandbox",
        "ops_token": "x" * 40,
        "seller_token_secret": "s" * 40,
        "link_secret": "l" * 40,
        "receipt_keys": {"test-1": "r" * 40},
        "receipt_active_kid": "test-1",
        "paypal_api_base": "https://api-m.sandbox.paypal.com",
        "paypal_client_id": "client",
        "paypal_client_secret": "secret",
        "paypal_webhook_id": "wh-1",
        "seller_payout_emails": {
            "northwind-audio": "northwind@example.test",
            "circuitforge": "circuitforge@example.test",
            "aurora-supply": "aurora@example.test",
            "summit-tech": "summit@example.test",
        },
        "public_base_url": "https://verifund.example.test",
    }
    values.update(overrides)
    return Settings(**values)


def test_default_mode_is_off(monkeypatch):
    monkeypatch.delenv("VERIFUND_MODE", raising=False)
    assert Settings(_env_file=None).mode == "off"


def test_sandbox_rejects_default_ops_token():
    with pytest.raises(ValueError, match="VERIFUND_OPS_TOKEN"):
        sandbox_settings(ops_token="dev-verifund-ops").validate_for_mode()


def test_sandbox_rejects_live_paypal_host():
    with pytest.raises(ValueError, match="sandbox"):
        sandbox_settings(paypal_api_base="https://api-m.paypal.com").validate_for_mode()


def test_sandbox_requires_payout_email():
    with pytest.raises(ValueError, match="payout"):
        sandbox_settings(seller_payout_emails={}).validate_for_mode()


def test_sandbox_accepts_valid_settings():
    sandbox_settings().validate_for_mode()


async def test_health_and_ready(tmp_path):
    settings = Settings(
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            assert (await client.get("/health")).json()["status"] == "ok"
            assert (await client.get("/ready")).status_code == 200
