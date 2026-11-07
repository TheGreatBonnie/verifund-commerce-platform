from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from verifund_control_plane.tenancy.repository import TenancyRepository


@pytest.fixture
async def repo(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    repository = TenancyRepository(engine)
    async with engine.begin() as conn:
        await conn.run_sync(repository.metadata.create_all)
    yield repository
    await engine.dispose()


async def test_update_seller_display_name(repo):
    await repo.upsert_seller_profile("org_1", "acme", "Acme")
    updated = await repo.update_seller_display_name("acme", "Acme Industrial")
    assert updated is not None
    assert updated["seller_id"] == "acme"
    assert updated["display_name"] == "Acme Industrial"


async def test_update_seller_display_name_missing(repo):
    assert await repo.update_seller_display_name("missing", "X") is None
