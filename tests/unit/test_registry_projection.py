import httpx
import pytest
from registry.api import create_app
from registry.settings import Settings
from registry.store import RegistryStore
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


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


async def test_create_schema_migrates_legacy_registry_tables(tmp_path):
    database_url = f"sqlite+aiosqlite:///{tmp_path / 'registry.db'}"
    engine = create_async_engine(database_url)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "CREATE TABLE sellers ("
                "seller_id VARCHAR(64) PRIMARY KEY,"
                "name VARCHAR NOT NULL,"
                "card_url VARCHAR NOT NULL,"
                "categories JSON NOT NULL,"
                "card_json JSON NOT NULL,"
                "card_hash VARCHAR(64) NOT NULL,"
                "last_seen_at VARCHAR NOT NULL,"
                "healthy BOOLEAN NOT NULL,"
                "last_error VARCHAR"
                ")"
            )
        )
        await conn.execute(
            text(
                "CREATE TABLE agents ("
                "agent_id VARCHAR(64) PRIMARY KEY,"
                "name VARCHAR NOT NULL,"
                "card_url VARCHAR NOT NULL,"
                "skills JSON NOT NULL,"
                "card_json JSON NOT NULL,"
                "card_hash VARCHAR(64) NOT NULL,"
                "last_seen_at VARCHAR NOT NULL,"
                "healthy BOOLEAN NOT NULL,"
                "last_error VARCHAR"
                ")"
            )
        )
    await engine.dispose()

    engine = create_async_engine(database_url)
    store = RegistryStore(engine)
    await store.create_schema()
    seller = await store.upsert(
        seller_id="acme",
        name="Acme",
        card_url="http://localhost/acme/a2a",
        categories=["electronics"],
        card_json={"name": "Acme"},
        card_hash="seller-hash",
        healthy=True,
        error=None,
        organization_id="org_1",
        verified=True,
    )
    agent = await store.upsert_agent(
        agent_id="agent-1",
        name="Acme Agent",
        card_url="http://localhost/agent-1/a2a",
        skills=["commerce.order"],
        card_json={"name": "Acme Agent"},
        card_hash="agent-hash",
        healthy=True,
        error=None,
        organization_id="org_1",
        published=True,
    )
    await engine.dispose()

    assert seller["organization_id"] == "org_1"
    assert seller["verified"] is True
    assert agent["organization_id"] == "org_1"
    assert agent["published"] is True


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
