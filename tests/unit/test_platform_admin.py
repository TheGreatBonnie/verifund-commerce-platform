import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc))
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
    # pending seller profile for verification decision
    await store.upsert_seller_profile(org["id"], "acme", "Acme")
    await store.set_verification_status("acme", "pending")
    app.state.clerk_authenticator = lambda request: _payload(request)
    member_headers = {"authorization": "Bearer member"}
    admin_headers = {"authorization": "Bearer admin"}

    def _payload(request):
        provided = request.headers.get("authorization", "")
        if provided == "Bearer admin":
            return {"sub": "admin_1", "org_id": "org_acme", "org_role": "org:admin"}
        return {"sub": "member_1", "org_id": "org_acme", "org_role": "org:member"}

    app.state.clerk_authenticator = lambda request: _payload(request)
    return {
        "member_headers": member_headers,
        "admin_headers": admin_headers,
        "org_id": org["id"],
    }


async def test_member_cannot_decide_verification(client, identities):
    response = await client.post(
        "/ops/sellers/acme/verification",
        json={"decision": "verified", "note": "ok"},
        headers=identities["member_headers"],
    )
    assert response.status_code == 403


async def test_platform_admin_can_verify_and_is_audited(client, identities):
    response = await client.post(
        "/ops/sellers/acme/verification",
        json={"decision": "verified", "note": "ok"},
        headers=identities["admin_headers"],
    )
    assert response.status_code == 200
    assert response.json()["verification_status"] == "verified"
    audit = await client._transport.app.state.tenancy.list_audit(
        organization_id=identities["org_id"]
    )
    assert audit[-1]["action"] == "seller.verification.approved"
