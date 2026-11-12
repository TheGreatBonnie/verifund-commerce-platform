import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.backfill import backfill_tenancy
from verifund_control_plane.tenancy.repository import TenancyRepository


@pytest.fixture
async def repo_store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'backfill.db'}")
    repo = Repository(engine)
    await repo.create_schema()
    store = TenancyRepository(engine)
    await store.create_schema()
    yield repo, store
    await engine.dispose()


async def seed_legacy_award(repo, seller_id="northwind-audio", buyer_id="demo-buyer"):
    now = "2026-11-06T00:00:00+00:00"
    async with repo.transaction() as conn:
        await conn.execute(
            repo.transactions.insert().values(
                transaction_id="vf_legacy",
                run_id="run-1",
                buyer_id=buyer_id,
                seller_id=seller_id,
                offer_id="offer-1",
                state="AWARDED",
                version=1,
                last_seq=0,
                amount_cents=1000,
                currency="USD",
                agreement_id="agr_1",
                agreement_hash="a" * 64,
                agreement_version=1,
                deadlines={},
                created_at=now,
                updated_at=now,
            )
        )


async def test_backfill_maps_demo_sellers_and_buyer(repo_store):
    repo, store = repo_store
    await seed_legacy_award(repo, seller_id="northwind-audio", buyer_id="demo-buyer")
    await backfill_tenancy(repo, store)
    async with repo.transaction() as conn:
        row = (await conn.execute(select(repo.transactions))).first()
    assert row.seller_organization_id
    assert row.buyer_organization_id
    seller = await store.get_seller_profile("northwind-audio")
    assert seller["verification_status"] == "verified"
