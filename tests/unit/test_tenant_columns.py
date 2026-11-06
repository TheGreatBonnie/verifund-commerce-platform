import httpx
import pytest
from sqlalchemy import select
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import NOW, award


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def test_new_award_writes_both_organization_columns(client):
    await award(client)
    repo = client._transport.app.state.repo
    async with repo.transaction() as conn:
        row = (await conn.execute(select(repo.transactions))).first()
    assert row.buyer_organization_id
    assert row.seller_organization_id
