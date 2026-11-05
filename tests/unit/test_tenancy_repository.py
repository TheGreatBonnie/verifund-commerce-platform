from __future__ import annotations

from sqlalchemy.ext.asyncio import create_async_engine


async def test_organization_membership_and_seller_profile_round_trip(tmp_path):
    from verifund_control_plane.tenancy.repository import TenancyRepository

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tenancy.db'}")
    store = TenancyRepository(engine)
    await store.create_schema()
    try:
        user = await store.upsert_user("user_1", "a@example.com", "A")
        org = await store.upsert_organization("org_1", "Acme", "acme")
        await store.upsert_membership(org["id"], user["id"], "org:admin", "mem_1")
        membership = await store.get_membership(org["id"], user["id"])
        assert membership["role"] == "org:admin"
        assert membership["status"] == "active"

        seller = await store.upsert_seller_profile(org["id"], "acme", "Acme")
        assert seller["verification_status"] == "unverified"
        assert await store.get_seller_profile("acme") is not None
    finally:
        await engine.dispose()
