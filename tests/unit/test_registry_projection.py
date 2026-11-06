import httpx
import pytest
from registry.api import create_app
from registry.settings import Settings


@pytest.fixture
async def registry_client(tmp_path):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}",
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as c:
            c.headers["authorization"] = f"Bearer {settings.admin_token}"
            yield c


async def test_registry_hides_unpublished_agents(registry_client):
    await registry_client.post(
        "/v1/agents",
        json={
            "agent_id": "a1",
            "name": "A",
            "card_url": "http://localhost:9200/a1",
            "skills": [],
            "card_json": {},
            "organization_id": "org_1",
            "published": False,
        },
    )
    listing = await registry_client.get("/v1/agents")
    assert listing.json()["items"] == []


async def test_card_url_must_match_seller_path(registry_client):
    response = await registry_client.post(
        "/v1/sellers",
        json={
            "seller_id": "acme",
            "card_url": "http://localhost:9200/other/a2a",
            "categories": ["electronics"],
            "organization_id": "org_1",
        },
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "card_url_not_owned"
