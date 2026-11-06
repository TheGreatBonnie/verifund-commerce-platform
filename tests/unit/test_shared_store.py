import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine

from seller_agent.shared_schema import configure_shared_engine, create_shared_schema
from seller_agent.shared_store import (
    OrgScopedStore, TenantContextError, ConfigUpsert, ConfigConflict,
)


@pytest_asyncio.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await configure_shared_engine(engine)
    await create_shared_schema(engine)
    yield engine
    await engine.dispose()


async def test_store_requires_organization(engine):
    with pytest.raises(TenantContextError):
        OrgScopedStore(engine, organization_id="")


async def test_create_and_get_config(engine):
    store = OrgScopedStore(engine, organization_id="orgA", agent_id="agent_acme")
    snap = await store.upsert_config(
        "agent_acme",
        ConfigUpsert(name="Acme", instructions="hello",
                     tool_allowlist=["commerce.catalog.search"]),
        seller_id="acme", name="Acme", tagline="Test",
    )
    assert snap.config_version == 1 and snap.policy_version == 1 and snap.policy_hash
    snap2 = await store.get_config("agent_acme")
    assert snap2.instructions == "hello" and snap2.config_version == 1


async def test_org_isolation(engine):
    a = OrgScopedStore(engine, organization_id="orgA")
    b = OrgScopedStore(engine, organization_id="orgB")
    await a.upsert_config("agent_a", ConfigUpsert(instructions="A"),
                          seller_id="a", name="A", tagline="")
    assert await b.get_config("agent_a") is None


async def test_expected_config_version_mismatch(engine):
    store = OrgScopedStore(engine, organization_id="orgA")
    await store.upsert_config("agent_a", ConfigUpsert(instructions="A"),
                              seller_id="a", name="A", tagline="")
    with pytest.raises(ConfigConflict) as exc:
        await store.upsert_config(
            "agent_a", ConfigUpsert(instructions="B", expected_config_version=99),
            seller_id="a", name="A", tagline="",
        )
    assert exc.value.current_version == 1


async def test_policy_hash_only_changes_on_policy_fields(engine):
    store = OrgScopedStore(engine, organization_id="orgA")
    snap1 = await store.upsert_config("agent_x", ConfigUpsert(instructions="one"),
                                      seller_id="x", name="X", tagline="")
    snap2 = await store.upsert_config("agent_x", ConfigUpsert(instructions="one", name="Renamed"),
                                      seller_id="x", name="Renamed", tagline="")
    assert snap2.policy_version == snap1.policy_version
    assert snap2.policy_hash == snap1.policy_hash
    snap3 = await store.upsert_config("agent_x", ConfigUpsert(instructions="two"),
                                      seller_id="x", name="Renamed", tagline="")
    assert snap3.policy_version == snap1.policy_version + 1
    assert snap3.policy_hash != snap1.policy_hash


async def test_import_products_upsert_and_replace(engine):
    store = OrgScopedStore(engine, organization_id="orgA")
    p = {"sku": "S1", "name": "Prod", "category": "c",
         "list_unit_price_cents": 100, "initial_unit_price_cents": 90,
         "floor_unit_price_cents": 80, "stock_on_hand": 5}
    r1 = await store.import_products([p], replace=False)
    assert r1 == {"inserted": 1, "updated": 0, "replaced": 0}
    r2 = await store.import_products([{**p, "stock_on_hand": 9}], replace=False)
    assert r2 == {"inserted": 0, "updated": 1, "replaced": 0}
    r3 = await store.import_products([{**p, "sku": "S2"}], replace=True)
    assert r3["replaced"] == 1
    skus = {row["sku"] for row in await store.list_products()}
    assert skus == {"S2"}


async def test_load_policy_matches_yaml_fixture(engine):
    store = OrgScopedStore(engine, organization_id="orgA", agent_id="agent_x")
    await store.upsert_config(
        "agent_x",
        ConfigUpsert(instructions="i", max_discount_bps=1000,
                     autonomy_mode="policy_bounded"),
        seller_id="northwind-audio", name="Northwind Audio",
        tagline="Premium audio",
    )
    row = {"sku": "MM-T", "name": "T", "category": "Electronics",
           "list_unit_price_cents": 100, "initial_unit_price_cents": 90,
           "floor_unit_price_cents": 80, "stock_on_hand": 3,
           "concession_ladder_cents": [90, 85]}
    await store.import_products([row], replace=False)
    policy = await store.load_policy()
    assert policy.name == "Northwind Audio" and policy.catalog()[0].sku == "MM-T"


async def test_catalog_isolation_between_orgs(engine):
    a = OrgScopedStore(engine, organization_id="orgA")
    b = OrgScopedStore(engine, organization_id="orgB")
    p = {"sku": "S1", "name": "A-Widget", "category": "c",
         "list_unit_price_cents": 100, "initial_unit_price_cents": 90,
         "floor_unit_price_cents": 80, "stock_on_hand": 5}
    await a.import_products([p], replace=False)
    assert await b.list_products() == []
    assert await b.first_sku() is None
