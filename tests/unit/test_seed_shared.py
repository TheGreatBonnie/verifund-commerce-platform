import pytest_asyncio
from seller_agent.shared_schema import configure_shared_engine, create_shared_schema
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from scripts.seed_shared import seed_seller_rows

PROFILE = "apps/seller_agent/seller_agent/profiles/northwind.yaml"


@pytest_asyncio.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await configure_shared_engine(engine)
    await create_shared_schema(engine)
    yield engine
    await engine.dispose()


async def test_seed_seller_rows(engine):
    count = await seed_seller_rows(
        engine,
        seller_id="northwind-audio",
        agent_id="agent_northwind-audio",
        organization_id="org-northwind",
        profile_path=PROFILE,
        public_base_url="http://127.0.0.1:9200",
    )
    async with engine.connect() as conn:
        config = (await conn.execute(text(
            "SELECT seller_id, status, card_hash, policy_hash "
            "FROM seller_configs WHERE agent_id='agent_northwind-audio'"
        ))).first()
        products = (await conn.execute(text(
            "SELECT COUNT(*) FROM products WHERE organization_id='org-northwind'"
        ))).scalar_one()
        inventory = (await conn.execute(text(
            "SELECT COUNT(*) FROM inventory WHERE organization_id='org-northwind'"
        ))).scalar_one()
    assert count == 10
    assert config.seller_id == "northwind-audio"
    assert config.status == "active"
    assert config.card_hash and config.policy_hash
    assert products == 10
    assert inventory == 10


async def test_seed_seller_rows_is_idempotent(engine):
    for _ in range(2):
        await seed_seller_rows(
            engine,
            seller_id="northwind-audio",
            agent_id="agent_northwind-audio",
            organization_id="org-northwind",
            profile_path=PROFILE,
        )
    async with engine.connect() as conn:
        configs = (await conn.execute(text(
            "SELECT COUNT(*) FROM seller_configs "
            "WHERE agent_id='agent_northwind-audio'"
        ))).scalar_one()
        products = (await conn.execute(text(
            "SELECT COUNT(*) FROM products WHERE organization_id='org-northwind'"
        ))).scalar_one()
    assert configs == 1
    assert products == 10
