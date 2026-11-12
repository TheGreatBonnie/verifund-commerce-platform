"""Requirement declaration endpoints (plan Task 10b)."""

from __future__ import annotations

import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import (
    NOW,
    OPS,
    award,
    award_payload,
    purchase_order,
    upload_file,
)
from tests.support.seller_auth import clerk_seller_headers, seed_seller_profile
from tests.unit.test_verifund_upload import (
    funded as _funded,
)
from tests.unit.test_verifund_upload import (
    requirement_catalog,
)


async def funded(client, app) -> dict:
    body = await _funded(client, app)
    reported = await client.post(
        f"/transactions/{body['transaction_id']}/purchase-order",
        json=purchase_order(body),
        headers={**OPS, "idempotency-key": f"po:{body['transaction_id']}"},
    )
    assert reported.status_code == 200, reported.text
    return body


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
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, app


async def _seller_headers(app, seller_id: str = "northwind-audio") -> dict[str, str]:
    suffix = seller_id.replace("-", "_")
    await seed_seller_profile(
        app,
        clerk_org_id=f"org_{suffix}",
        seller_id=seller_id,
        display_name=seller_id,
        clerk_user_id=f"user_{suffix}",
    )
    return clerk_seller_headers(
        app,
        sub=f"user_{suffix}",
        org_id=f"org_{suffix}",
        token=f"tok_{suffix}",
    )


async def test_declare_completes_requirement_and_records_attempt(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    uploaded = await upload_file(
        http,
        body,
        "hardware",
        data=b"ram_gb,32\n",
        filename="diag.csv",
        media_type="text/csv",
        headers=headers,
    )
    assert uploaded.status_code == 201, uploaded.text

    response = await http.post(
        f"/seller/transactions/{body['transaction_id']}/requirements/hardware/declare",
        headers=headers,
        json={},
    )
    assert response.status_code == 200, response.text
    declared = response.json()
    assert declared["declared_at"]
    assert declared["attempt"] == 1

    trail = await http.get(
        f"/seller/transactions/{body['transaction_id']}/requirements/hardware/declarations",
        headers=headers,
    )
    assert trail.status_code == 200, trail.text
    assert [row["attempt"] for row in trail.json()["items"]] == [1]


async def test_declare_with_zero_submissions_is_rejected(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    response = await http.post(
        f"/seller/transactions/{body['transaction_id']}/requirements/hardware/declare",
        headers=headers,
        json={},
    )
    assert response.status_code == 400, response.text


async def test_declare_unknown_requirement_returns_422(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    uploaded = await upload_file(
        http,
        body,
        "hardware",
        data=b"ram_gb,32\n",
        filename="diag.csv",
        media_type="text/csv",
        headers=headers,
    )
    assert uploaded.status_code == 201
    response = await http.post(
        f"/seller/transactions/{body['transaction_id']}/requirements/not_a_thing/declare",
        headers=headers,
        json={},
    )
    assert response.status_code == 422, response.text


async def test_declaration_after_fail_starts_new_attempt(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    # first attempt: failing value
    await upload_file(
        http,
        body,
        "hardware",
        data=b"ram_gb,16\n",
        filename="diag.csv",
        media_type="text/csv",
        headers=headers,
    )
    first = await http.post(
        f"/seller/transactions/{body['transaction_id']}/requirements/hardware/declare",
        headers=headers,
        json={},
    )
    assert first.status_code == 200, first.text
    assert first.json()["attempt"] == 1

    # second submission starts a new attempt; declaration closes it
    await upload_file(
        http,
        body,
        "hardware",
        data=b"ram_gb,64\n",
        filename="diag2.csv",
        media_type="text/csv",
        headers=headers,
    )
    second = await http.post(
        f"/seller/transactions/{body['transaction_id']}/requirements/hardware/declare",
        headers=headers,
        json={},
    )
    assert second.status_code == 200, second.text
    assert second.json()["attempt"] == 2

    trail = await http.get(
        f"/seller/transactions/{body['transaction_id']}/requirements/hardware/declarations",
        headers=headers,
    )
    assert [row["attempt"] for row in trail.json()["items"]] == [2, 1]


async def test_declaration_cross_seller_returns_403(client):
    http, app = client
    body = await funded(http, app)
    other_headers = await _seller_headers(app, seller_id="other-seller")
    await upload_file(
        http, body, "hardware", data=b"ram_gb,32\n",
        filename="diag.csv", media_type="text/csv",
        headers=await _seller_headers(app),
    )
    response = await http.post(
        f"/seller/transactions/{body['transaction_id']}/requirements/hardware/declare",
        headers=other_headers,
        json={},
    )
    assert response.status_code in {403, 404}
