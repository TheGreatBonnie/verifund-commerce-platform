import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.identity import Identity
from verifund_control_plane.tenancy.permissions import ROLE_PERMISSIONS
from verifund_control_plane.tenancy.transaction_access import require_transaction


@pytest.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'access.db'}")
    r = Repository(engine)
    await r.create_schema()
    now = "2026-11-06T00:00:00+00:00"
    async with r.transaction() as conn:
        await conn.execute(
            r.transactions.insert().values(
                transaction_id="vf_a",
                run_id="run-1",
                buyer_id="buyer-1",
                seller_id="seller-1",
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
    yield r
    await engine.dispose()


def _identity(tenant_id, role):
    return Identity(
        user_id="u",
        clerk_user_id="u",
        tenant_id=tenant_id,
        clerk_org_id=None,
        role=role,
        permissions=ROLE_PERMISSIONS.get(role, ROLE_PERMISSIONS["org:member"]),
        is_platform_admin=False,
        organization_status="active",
    )


async def test_non_participant_gets_404(repo):
    identity_b = _identity("org_b", "org:member")
    with pytest.raises(VerifundError) as exc:
        await require_transaction(identity_b, "vf_a", "read", repo)
    assert exc.value.status_code == 404


async def test_sales_role_cannot_release(repo):
    identity_sales = _identity("org_seller_a", "org:sales")
    with pytest.raises(VerifundError) as exc:
        await require_transaction(identity_sales, "vf_a", "release_funds", repo)
    assert exc.value.status_code == 403
