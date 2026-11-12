import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.reconciler import Reconciler
from verifund_control_plane.repository import Repository
from verifund_control_plane.settings import Settings
from verifund_control_plane.tenancy.repository import TenancyRepository


@pytest.fixture
async def store(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sys.db'}")
    repo = Repository(engine)
    await repo.create_schema()
    s = TenancyRepository(engine)
    await s.create_schema()
    s._repo = repo
    yield s
    await engine.dispose()


@pytest.fixture
async def reconciler(store):
    class FakeService:
        async def refresh_payout(self, transaction_id, *, actor=None):
            raise AssertionError("held payout must not be refreshed")

        async def refresh_funding(self, transaction_id, *, actor):
            raise AssertionError("held payout must not be refreshed")

        async def recover_operation(self, operation, *, actor):
            return False

        async def verify(self, transaction_id, *, actor):
            return {"state": "RELEASE_PERMITTED"}

        async def backfill_receipt(self, transaction_id, *, actor):
            return False

        async def cancel(self, transaction_id, request, *, actor, idempotency_key):
            return {"state": "CANCELED"}

        async def refresh_tracker(self, transaction_id):
            return None

        async def release(self, transaction_id, request, *, actor, idempotency_key=None):
            return {"state": "RELEASED"}

        async def _agreement_terms(self, transaction_id):
            return {}

    settings = Settings(_env_file=None, mode="fake")
    return Reconciler(
        repo=store._repo,
        service=FakeService(),
        settings=settings,
        clock=lambda: __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ),
        tenancy=store,
    )


async def test_reconciler_audit_is_system_scoped(store, reconciler):
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
    await reconciler.run_once()
    rows = await store.list_audit(scope="system")
    assert rows
    assert all(row["actor_type"] == "system" for row in rows)
    assert all(row["organization_id"] is not None for row in rows)


async def test_worker_service_audit_is_system_scoped(store):
    from verifund_control_plane.repository import AuditInput

    repo = store._repo
    now = "2026-11-06T00:00:00+00:00"
    org = await store.upsert_organization("org_w", "Seller", "seller-w")
    async with repo.transaction() as conn:
        await conn.execute(
            repo.transactions.insert().values(
                transaction_id="vf_w",
                run_id="run-1",
                buyer_id="buyer-1",
                seller_id="seller-w",
                buyer_organization_id="org_buyer",
                seller_organization_id=org["id"],
                offer_id="offer-1",
                state="AWARDED",
                version=1,
                last_seq=0,
                amount_cents=1000,
                currency="USD",
                agreement_id="agr_w",
                agreement_hash="a" * 64,
                agreement_version=1,
                deadlines={},
                created_at=now,
                updated_at=now,
            )
        )
        await repo.audit(conn, "vf_w", AuditInput("reconciler", "payout_refreshed"))
    rows = await store.list_audit(scope="system")
    worker = [r for r in rows if r["action"] == "payout_refreshed"]
    assert worker
    assert worker[0]["actor_type"] == "system"
    assert worker[0]["organization_id"] == org["id"]
    assert worker[0]["actor_user_id"] == "system"
