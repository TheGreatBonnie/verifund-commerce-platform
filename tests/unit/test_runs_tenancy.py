import pytest
from buyer_agent.store import BuyerStore
from sqlalchemy.ext.asyncio import create_async_engine


@pytest.fixture
async def buyer_store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'buyer.db'}")
    store = BuyerStore(engine)
    await store.trace.create_schema()
    yield store
    await engine.dispose()


async def test_runs_are_filtered_by_organization(buyer_store):
    await buyer_store.trace.upsert_run(
        "run_a", organization_id="org_a", user_id="u_a"
    )
    await buyer_store.trace.upsert_run(
        "run_b", organization_id="org_b", user_id="u_b"
    )
    assert [r["run_id"] for r in await buyer_store.trace.list_runs("org_a")] == [
        "run_a"
    ]
