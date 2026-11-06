import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.errors import VerifundError
from verifund_control_plane.repository import Repository
from verifund_control_plane.settings import Settings
from verifund_control_plane.tenancy.identity import Identity
from verifund_control_plane.tenancy.permissions import ROLE_PERMISSIONS
from verifund_control_plane.tenancy.repository import TenancyRepository
from verifund_control_plane.tenancy.transaction_access import require_transaction


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rel.db'}")
    repo = Repository(engine)
    await repo.create_schema()
    s = TenancyRepository(engine)
    await s.create_schema()
    s._repo = repo
    s._org_id = "org_seller"
    yield s
    await engine.dispose()


async def test_removed_member_cannot_release_funds(store):
    repo = store._repo
    now = "2026-11-06T00:00:00+00:00"
    async with repo.transaction() as conn:
        await conn.execute(
            repo.transactions.insert().values(
                transaction_id="vf_rel",
                run_id="run-1",
                buyer_id="buyer-1",
                seller_id="seller-1",
                buyer_organization_id="org_buyer",
                seller_organization_id="org_seller",
                offer_id="offer-1",
                state="PAYOUT_PENDING",
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
    user = await store.upsert_user("user_r", "r@example.com", "R")
    await store.upsert_organization("org_seller_clerk", "Seller", "seller")
    # rewire: org_seller is a raw id, need org entity with that id for membership
    # create org with fixed id via direct insert
    async with store.engine.begin() as conn:
        await conn.exec_driver_sql(
            "INSERT OR IGNORE INTO organizations (id, clerk_org_id, kind, name, slug, status, created_at, updated_at)"
            " VALUES ('org_seller', 'org_seller_clerk', 'business', 'Seller', 'seller', 'active', '2026-11-06T00:00:00+00:00', '2026-11-06T00:00:00+00:00')"
        )
    await store.upsert_membership("org_seller", user["id"], "org:admin", "mem_r")
    await store.set_membership_status("org_seller", user["id"], "removed")
    identity = Identity(
        user_id=user["id"],
        clerk_user_id="user_r",
        tenant_id="org_seller",
        clerk_org_id="org_seller_clerk",
        role="org:admin",
        permissions=ROLE_PERMISSIONS["org:admin"],
        is_platform_admin=False,
        organization_status="active",
    )
    with pytest.raises(VerifundError) as exc:
        await require_transaction(identity, "vf_rel", "release_funds", repo, store)
    assert exc.value.status_code == 403


async def test_suspended_seller_payout_is_held_without_release(store):
    # Direct reconciler sweep check: suspended seller => held counter.
    from verifund_control_plane.reconciler import Reconciler

    class FakeService:
        async def refresh_payout(self, txn_id, actor=None):
            raise AssertionError("should be held")

    settings = Settings(_env_file=None, mode="fake")
    rec = Reconciler(
        repo=store._repo,
        service=FakeService(),
        settings=settings,
        clock=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        tenancy=store,
    )
    # Seed suspended seller + pending txn
    repo = store._repo
    now = "2026-11-06T00:00:00+00:00"
    org = await store.upsert_organization("org_s", "Seller", "seller-s")
    await store.upsert_seller_profile(org["id"], "seller-s", "Seller")
    await store.set_verification_status("seller-s", "suspended")
    async with repo.transaction() as conn:
        await conn.execute(
            repo.transactions.insert().values(
                transaction_id="vf_susp",
                run_id="run-1",
                buyer_id="buyer-1",
                seller_id="seller-s",
                buyer_organization_id="org_buyer",
                seller_organization_id=org["id"],
                offer_id="offer-1",
                state="PAYOUT_PENDING",
                version=1,
                last_seq=0,
                amount_cents=1000,
                currency="USD",
                agreement_id="agr_s",
                agreement_hash="a" * 64,
                agreement_version=1,
                deadlines={},
                created_at=now,
                updated_at=now,
            )
        )
    stats = {"payouts_checked": 0, "payouts_held": 0}
    await rec._sweep_payouts(stats)
    assert stats.get("payouts_held") == 1


async def test_release_allows_the_payout(store, tmp_path):
    from verifund_control_plane.reconciler import Reconciler

    called = {}

    class FakeService:
        async def refresh_payout(self, txn_id, actor=None):
            called["txn"] = txn_id

    repo = store._repo
    now = "2026-11-06T00:00:00+00:00"
    org = await store.upsert_organization("org_s2", "Seller", "seller-s2")
    await store.upsert_seller_profile(org["id"], "seller-s2", "Seller")
    await store.set_verification_status("seller-s2", "suspended")
    admin = await store.upsert_user("admin_1", "a@example.com", "A")
    await store.add_platform_admin(admin["id"], granted_by="bootstrap")
    async with repo.transaction() as conn:
        await conn.execute(
            repo.transactions.insert().values(
                transaction_id="vf_susp2",
                run_id="run-1",
                buyer_id="buyer-1",
                seller_id="seller-s2",
                buyer_organization_id="org_buyer",
                seller_organization_id=org["id"],
                offer_id="offer-1",
                state="PAYOUT_PENDING",
                version=1,
                last_seq=0,
                amount_cents=1000,
                currency="USD",
                agreement_id="agr_s2",
                agreement_hash="a" * 64,
                agreement_version=1,
                deadlines={},
                created_at=now,
                updated_at=now,
            )
        )
    await store.create_payout_release("vf_susp2", org["id"], admin["id"], "delivered")
    settings = Settings(_env_file=None, mode="fake")
    rec = Reconciler(
        repo=repo,
        service=FakeService(),
        settings=settings,
        clock=lambda: __import__("datetime").datetime.now(__import__("datetime").timezone.utc),
        tenancy=store,
    )
    stats = {"payouts_checked": 0, "payouts_held": 0}
    await rec._sweep_payouts(stats)
    assert called.get("txn") == "vf_susp2"
