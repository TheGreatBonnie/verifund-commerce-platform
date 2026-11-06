import pytest
from seller_agent.shared_schema import configure_shared_engine, create_shared_schema
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await configure_shared_engine(engine)
    await create_shared_schema(engine)
    yield engine
    await engine.dispose()


async def test_tables_exist(engine):
    async with engine.connect() as conn:
        names = {row[0] for row in (await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ))).all()}
    assert {"seller_configs", "products", "inventory", "task_ownership",
            "offers", "orders"} <= names


async def test_products_pk_is_org_scoped(engine):
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO products (organization_id, sku, name, list_unit_price_cents, "
            "initial_unit_price_cents, floor_unit_price_cents, stock_on_hand) "
            "VALUES ('orgA', 'SKU-1', 'A', 100, 90, 80, 3)"
        ))
        await conn.execute(text(
            "INSERT INTO products (organization_id, sku, name, list_unit_price_cents, "
            "initial_unit_price_cents, floor_unit_price_cents, stock_on_hand) "
            "VALUES ('orgB', 'SKU-1', 'B', 100, 90, 80, 7)"
        ))
    async with engine.connect() as conn:
        rows = (await conn.execute(
            text("SELECT organization_id, stock_on_hand FROM products"))).all()
    assert {(r[0], r[1]) for r in rows} == {("orgA", 3), ("orgB", 7)}


async def test_seller_configs_unique_seller_id(engine):
    with pytest.raises(IntegrityError):
        async with engine.begin() as conn:
            for org in ("orgA", "orgB"):
                await conn.execute(text(
                    "INSERT INTO seller_configs (agent_id, organization_id, seller_id, name) "
                    f"VALUES ('{org}_a', '{org}', 'acme', 'Acme')"
                ))


async def test_inventory_pk_is_org_scoped(engine):
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO inventory (organization_id, sku, on_hand) VALUES ('orgA', 'S', 1)"
        ))
        await conn.execute(text(
            "INSERT INTO inventory (organization_id, sku, on_hand) VALUES ('orgB', 'S', 2)"
        ))
    async with engine.connect() as conn:
        rows = (await conn.execute(text("SELECT organization_id, on_hand FROM inventory"))).all()
    assert {(r[0], r[1]) for r in rows} == {("orgA", 1), ("orgB", 2)}
