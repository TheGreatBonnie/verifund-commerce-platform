import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import Repository
from verifund_control_plane.tenancy.repository import (
    TenancyRepository,
    resolve_payout_account,
)


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'pay.db'}")
    repo = Repository(engine)
    await repo.create_schema()
    s = TenancyRepository(engine)
    await s.create_schema()
    yield s
    await engine.dispose()


@pytest.fixture
async def verified_seller(store):
    org = await store.upsert_organization("org_1", "Acme", "acme")
    await store.upsert_seller_profile(org["id"], "acme", "Acme")
    await store.set_verification_status("acme", "verified")
    return {"organization_id": org["id"]}


@pytest.fixture
async def unverified_seller(store):
    org = await store.upsert_organization("org_2", "Beta", "beta")
    await store.upsert_seller_profile(org["id"], "beta", "Beta")
    return {"organization_id": org["id"]}


async def test_payout_uses_active_database_account(store, verified_seller):
    await store.upsert_payment_account(
        organization_id=verified_seller["organization_id"],
        provider="paypal",
        provider_account_id="pay@acme.test",
        account_type="payout",
        status="active",
        credentials_reference="secret:acme",
    )
    account = await resolve_payout_account(store, verified_seller["organization_id"])
    assert account["provider_account_id"] == "pay@acme.test"


async def test_missing_account_is_409(store, verified_seller):
    with pytest.raises(VerifundError) as exc:
        await resolve_payout_account(store, verified_seller["organization_id"])
    assert exc.value.status_code == 409
    assert exc.value.code == "payout_account_unavailable"


async def test_unverified_seller_cannot_add_a_payout_account(store, unverified_seller):
    with pytest.raises(VerifundError) as exc:
        await store.upsert_payment_account(
            organization_id=unverified_seller["organization_id"],
            provider="paypal",
            provider_account_id="pay@acme.test",
            account_type="payout",
            status="active",
            credentials_reference="secret:acme",
        )
    assert exc.value.status_code == 403
    assert exc.value.code == "seller_not_verified"
