import json

import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import NOW, award, award_payload


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
        paypal_platform_email="platform@example.com",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def identities(client):
    app = client._transport.app
    store = app.state.tenancy
    member = await store.upsert_user("member_1", "m@example.com", "M")
    admin = await store.upsert_user("admin_1", "a@example.com", "A")
    org = await store.upsert_organization("org_acme", "Acme", "acme")
    await store.upsert_membership(org["id"], member["id"], "org:member", "mem_1")
    await store.upsert_membership(org["id"], admin["id"], "org:admin", "mem_2")
    await store.add_platform_admin(admin["id"], granted_by="bootstrap")
    app.state.clerk_authenticator = lambda request: (
        {"sub": "admin_1", "org_id": "org_acme", "org_role": "org:admin"}
        if request.headers.get("authorization") == "Bearer admin"
        else {"sub": "member_1", "org_id": "org_acme", "org_role": "org:member"}
    )
    return {
        "member_headers": {"authorization": "Bearer member"},
        "admin_headers": {"authorization": "Bearer admin"},
    }


async def _award_platform_transaction(client) -> str:
    body = await award(client, award_payload(run_id="run-admin-routes"))
    return body["transaction_id"]


async def test_member_cannot_read_admin_overview(client, identities):
    response = await client.get(
        "/v1/admin/overview", headers=identities["member_headers"]
    )
    assert response.status_code == 403


async def test_admin_reads_only_platform_transactions(client, identities):
    transaction_id = await _award_platform_transaction(client)
    response = await client.get(
        "/v1/admin/transactions", headers=identities["admin_headers"]
    )
    assert response.status_code == 200
    rows = response.json()
    assert [row["transaction_id"] for row in rows] == [transaction_id]
    assert all(
        row["platform_account_email"] == "platform@example.com" for row in rows
    )


async def test_admin_transaction_rows_include_participant_display_names(
    client, identities
):
    transaction_id = await _award_platform_transaction(client)
    response = await client.get(
        "/v1/admin/transactions", headers=identities["admin_headers"]
    )
    assert response.status_code == 200
    row = next(
        row for row in response.json() if row["transaction_id"] == transaction_id
    )
    assert row["buyer_id"] == "demo-buyer"
    assert row["seller_id"] == "northwind-audio"
    assert row["buyer_name"] == "Demo Buyer"
    assert row["seller_name"] == "Northwind Audio"


async def test_admin_transaction_detail_includes_participant_display_names(
    client, identities
):
    transaction_id = await _award_platform_transaction(client)
    response = await client.get(
        f"/v1/admin/transactions/{transaction_id}", headers=identities["admin_headers"]
    )
    assert response.status_code == 200
    detail = response.json()
    assert detail["buyer_name"] == "Demo Buyer"
    assert detail["seller_name"] == "Northwind Audio"


async def test_admin_transaction_names_fall_back_when_agreement_lookup_fails(
    client, identities, monkeypatch
):
    transaction_id = await _award_platform_transaction(client)

    class BrokenAgreementService:
        async def get_by_transaction(self, transaction_id):
            raise RuntimeError("agreement store unavailable")

        async def build_projection(self, agreement):
            raise AssertionError("should not be reached")

    monkeypatch.setattr(
        client._transport.app.state, "agreement_service", BrokenAgreementService()
    )
    response = await client.get(
        "/v1/admin/transactions", headers=identities["admin_headers"]
    )
    assert response.status_code == 200
    row = next(
        row for row in response.json() if row["transaction_id"] == transaction_id
    )
    assert row["buyer_name"] is None
    assert row["seller_name"] is None


async def test_admin_cannot_read_foreign_platform_transaction(client, identities):
    transaction_id = await _award_platform_transaction(client)
    app = client._transport.app
    async with app.state.repo.engine.begin() as conn:
        await conn.exec_driver_sql(
            "UPDATE transactions SET platform_account_email = 'other@example.com' "
            "WHERE transaction_id = ?",
            (transaction_id,),
        )
    response = await client.get(
        f"/v1/admin/transactions/{transaction_id}", headers=identities["admin_headers"]
    )
    assert response.status_code == 404


async def test_admin_payout_release_is_audited_with_human_actor(client, identities):
    transaction_id = await _award_platform_transaction(client)
    response = await client.post(
        f"/v1/admin/transactions/{transaction_id}/payout-release",
        json={"reason": "approved by admin"},
        headers=identities["admin_headers"],
    )
    assert response.status_code == 201
    audit = await client._transport.app.state.tenancy.list_audit(
        resource_id=transaction_id
    )
    release_events = [row for row in audit if row["action"] == "payout.release_approved"]
    assert len(release_events) == 1
    payload = json.loads(release_events[0]["payload"])
    assert (
        payload["actor"]
        == "user:admin_1 acting for platform:platform@example.com"
    )


async def test_admin_settings_redacts_platform_email(client, identities):
    response = await client.get(
        "/v1/admin/settings", headers=identities["admin_headers"]
    )
    assert response.status_code == 200
    assert response.json()["platform_account_email"] == "pl***@example.com"


async def test_admin_reads_global_audit_log(client, identities):
    response = await client.get("/v1/admin/audit", headers=identities["admin_headers"])
    assert response.status_code == 200
    assert isinstance(response.json(), list)
