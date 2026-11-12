import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import NOW, award_payload


@pytest.fixture
async def client(tmp_path):
    # Sandbox mode with tenancy; env map only has legacy slug sellers
    settings = Settings(
        _env_file=None,
        mode="sandbox",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="https://verifund.example.com",
        tenancy_enabled=True,
        ops_token="ops-secret-1234567890-1234567890-1234",
        seller_token_secret="seller-secret-1234567890-1234567890-12",
        link_secret="link-secret-1234567890-1234567890-1234",
        receipt_keys={"k1": "receipt-key-12345678901234567890"},
        receipt_active_kid="k1",
        paypal_client_id="client-id",
        paypal_client_secret="client-secret",
        paypal_webhook_id="wh-123",
        paypal_api_base="https://api-m.sandbox.paypal.com",
        paypal_platform_email="platform@example.com",
        paypal_buyer_email="buyer@example.com",
        seller_payout_emails={"northwind-audio": "legacy@example.com"},
        host="127.0.0.1",
        allow_public_bind=True,
    )
    settings.validate_for_mode()
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_award_uses_tenancy_payout_account_for_uuid_seller(client):
    store = client._transport.app.state.tenancy  # type: ignore[attr-defined]
    seller_uuid = "33a492070e344199803b6d0f4331cee0"
    org = await store.upsert_organization(
        f"org-{seller_uuid[:8]}", "Northwind Audio", seller_uuid
    )
    await store.upsert_seller_profile(
        org["id"], seller_uuid, "Northwind Audio"
    )
    await store.set_verification_status(seller_uuid, "verified")
    # Payout account captured during onboarding (verification submit)
    await store.upsert_payment_account(
        organization_id=org["id"],
        provider="paypal",
        provider_account_id="northwind-audio@business.example.com",
        account_type="payout",
        status="active",
        credentials_reference=f"secret:{seller_uuid}",
    )

    response = await client.post(
        "/awards",
        json=award_payload(seller_id=seller_uuid, buyer_id="demo-buyer"),
        headers={"authorization": "Bearer ops-secret-1234567890-1234567890-1234", "x-verifund-actor": "buyer-agent", "idempotency-key": "award-uuid-payout"},
    )
    print(f"STATUS={response.status_code} BODY={response.text[:500]}")
    assert response.status_code == 201, response.text


async def test_award_uses_payout_account_even_when_tenancy_flag_off(tmp_path):
    """Regression: production CP runs with tenancy_enabled=False by default,
    so _payout_email must still consult the tenancy payment_accounts table
    created during onboarding, otherwise sandbox mode rejects UUID sellers."""
    settings = Settings(
        _env_file=None,
        mode="sandbox",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="https://verifund.example.com",
        tenancy_enabled=False,
        ops_token="ops-secret-1234567890-1234567890-1234",
        seller_token_secret="seller-secret-1234567890-1234567890-12",
        link_secret="link-secret-1234567890-1234567890-1234",
        receipt_keys={"k1": "receipt-key-12345678901234567890"},
        receipt_active_kid="k1",
        paypal_client_id="client-id",
        paypal_client_secret="client-secret",
        paypal_webhook_id="wh-123",
        paypal_api_base="https://api-m.sandbox.paypal.com",
        paypal_platform_email="platform@example.com",
        paypal_buyer_email="buyer@example.com",
        seller_payout_emails={"northwind-audio": "legacy@example.com"},
        host="127.0.0.1",
        allow_public_bind=True,
    )
    settings.validate_for_mode()
    import httpx as _httpx
    from verifund_control_plane.app import create_app
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = _httpx.ASGITransport(app=app)
        async with _httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            store = app.state.tenancy
            seller_uuid = "c95102b606e74a6dbe92cafa62e6216c"
            org = await store.upsert_organization(
                f"org-{seller_uuid[:8]}", "CircuitForge", seller_uuid
            )
            await store.upsert_seller_profile(
                org["id"], seller_uuid, "CircuitForge"
            )
            await store.set_verification_status(seller_uuid, "verified")
            await store.upsert_payment_account(
                organization_id=org["id"],
                provider="paypal",
                provider_account_id="circuitforge@business.example.com",
                account_type="payout",
                status="active",
                credentials_reference=f"secret:{seller_uuid}",
            )
            response = await c.post(
                "/awards",
                json=award_payload(seller_id=seller_uuid, buyer_id="demo-buyer"),
                headers={"authorization": "Bearer ops-secret-1234567890-1234567890-1234", "x-verifund-actor": "buyer-agent", "idempotency-key": "award-uuid-payout-2"},
            )
            print(f"STATUS2={response.status_code} BODY2={response.text[:500]}")
            assert response.status_code == 201, response.text
