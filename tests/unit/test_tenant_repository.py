import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.tenant_repository import (
    TenantRepository,
    TenantScope,
)


@pytest.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tenant.db'}")
    r = Repository(engine)
    await r.create_schema()
    yield r
    await engine.dispose()


@pytest.fixture
async def seeded_transactions(repo):
    now = "2026-11-06T00:00:00+00:00"
    async with repo.transaction() as conn:
        await conn.execute(
            repo.transactions.insert().values(
                transaction_id="vf_a",
                run_id="run-1",
                buyer_id="demo-buyer",
                seller_id="northwind-audio",
                buyer_organization_id="org_a",
                seller_organization_id="org_seller_a",
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
    return {"org_a_txn": "vf_a"}


async def test_cross_tenant_transaction_is_404(repo, seeded_transactions):
    tenant_repo = TenantRepository(repo)
    scope = TenantScope(
        organization_id="org_b", user_id="user_b", permissions=frozenset()
    )
    with pytest.raises(VerifundError) as exc:
        await tenant_repo.get_transaction(scope, seeded_transactions["org_a_txn"])
    assert exc.value.status_code == 404


async def test_participant_can_read(repo, seeded_transactions):
    tenant_repo = TenantRepository(repo)
    scope = TenantScope(
        organization_id="org_a", user_id="user_a", permissions=frozenset()
    )
    txn = await tenant_repo.get_transaction(scope, seeded_transactions["org_a_txn"])
    assert txn.transaction_id == seeded_transactions["org_a_txn"]
