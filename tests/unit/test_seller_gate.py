import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import NOW, OPS, award_payload


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
        tenancy_enabled=True,
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def unverified_seller(client):
    store = client._transport.app.state.tenancy
    org = await store.upsert_organization("org_new", "New Seller", "new-seller")
    await store.upsert_seller_profile(org["id"], "new-seller", "New Seller")
    return "new-seller"


async def test_unverified_seller_cannot_be_awarded(client, unverified_seller):
    response = await client.post(
        "/awards",
        json=award_payload(seller_id="new-seller"),
        headers={**OPS, "idempotency-key": "a1"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "seller_not_verified"
    repo = client._transport.app.state.repo
    assert await repo.count_transactions() == 0
