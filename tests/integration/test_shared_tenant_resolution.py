import pytest
import pytest_asyncio
from seller_agent.shared_runtime import (
    TenantForbidden,
    TenantResolver,
    UnknownTenant,
)
from seller_agent.shared_schema import configure_shared_engine, create_shared_schema
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine


@pytest_asyncio.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/sellers.db")
    await configure_shared_engine(engine)
    await create_shared_schema(engine)
    async with engine.begin() as conn:
        for agent_id, org, seller, status in (
            ("agent_a", "org-a", "a", "active"),
            ("agent_inactive", "org-c", "c", "draft"),
        ):
            await conn.execute(text(
                """INSERT INTO seller_configs
                       (agent_id, organization_id, seller_id, name, status)
                   VALUES (:a, :o, :s, :n, :st)"""),
                {"a": agent_id, "o": org, "s": seller,
                 "n": seller.title(), "st": status})
    yield engine
    await engine.dispose()


async def test_tenant_resolution_enforces_path(engine):
    resolver = TenantResolver(engine)
    ctx = await resolver.resolve("agent_a", path_seller_id="a")
    assert ctx.organization_id == "org-a"
    assert ctx.agent_id == "agent_a"
    assert ctx.seller_id == "a"
    assert ctx.config.status == "active"


async def test_tenant_resolution_rejects_path_mismatch(engine):
    resolver = TenantResolver(engine)
    with pytest.raises(TenantForbidden):
        await resolver.resolve("agent_a", path_seller_id="b")


async def test_unknown_and_inactive_tenants_are_unknown(engine):
    resolver = TenantResolver(engine)
    with pytest.raises(UnknownTenant):
        await resolver.resolve("agent_missing", path_seller_id="a")
    with pytest.raises(UnknownTenant):
        await resolver.resolve("agent_inactive", path_seller_id="c")


async def test_tenant_can_be_derived_from_path(engine):
    resolver = TenantResolver(engine)
    ctx = await resolver.resolve("", path_seller_id="a")
    assert ctx.agent_id == "agent_a"


async def test_tenant_is_required_without_path(engine):
    resolver = TenantResolver(engine)
    with pytest.raises(UnknownTenant):
        await resolver.resolve("")
