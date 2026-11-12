from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine
from verifund_control_plane.repository import Repository


async def test_organization_audit_has_no_transaction(tmp_path):
    repo = Repository(create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'db.sqlite'}"))
    await repo.create_schema()
    async with repo.transaction() as conn:
        await conn.execute(
            repo.audit_log.insert().values(
                audit_id="a1",
                scope="organization",
                transaction_id=None,
                organization_id="org_1",
                actor_user_id="user_1",
                actor_type="user",
                action="seller.verification.approved",
                resource_id="acme",
                payload={},
                created_at="2026-11-06T00:00:00+00:00",
            )
        )
    async with repo.transaction() as conn:
        row = (await conn.execute(select(repo.audit_log))).first()
    assert row is not None
    assert row.organization_id == "org_1"
