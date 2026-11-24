import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import NOW, award, award_payload


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
        paypal_platform_email="platform@example.com",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def _award_a_transaction(client) -> dict:
    return await award(client, award_payload(run_id="run-platform-owner"))


async def test_transaction_is_stamped_with_platform_email(client):
    body = await _award_a_transaction(client)
    txn = await client._transport.app.state.repo.get_transaction(
        body["transaction_id"]
    )
    assert txn.platform_account_email == "platform@example.com"


async def test_platform_owner_accepts_matching_email(client):
    from verifund_control_plane.api.platform_auth import authorize_platform_transaction

    body = await _award_a_transaction(client)
    txn = await client._transport.app.state.repo.get_transaction(
        body["transaction_id"]
    )
    assert authorize_platform_transaction(txn, "platform@example.com") is txn


async def test_platform_owner_mismatch_raises_404(client):
    from verifund_control_plane.api.platform_auth import authorize_platform_transaction

    body = await _award_a_transaction(client)
    txn = await client._transport.app.state.repo.get_transaction(
        body["transaction_id"]
    )
    with pytest.raises(Exception) as exc:
        authorize_platform_transaction(txn, "other@example.com")
    assert getattr(exc.value, "status_code", None) == 404


async def test_platform_owner_blank_email_raises_404(client):
    from verifund_control_plane.api.platform_auth import authorize_platform_transaction

    body = await _award_a_transaction(client)
    txn = await client._transport.app.state.repo.get_transaction(
        body["transaction_id"]
    )
    with pytest.raises(Exception) as exc:
        authorize_platform_transaction(txn, "")
    assert getattr(exc.value, "status_code", None) == 404
