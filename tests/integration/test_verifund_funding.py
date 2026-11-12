from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
import pytest
from commerce_core.binding import binding_from_award, offer_hash
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
OPS = {"authorization": "Bearer dev-verifund-ops", "x-verifund-actor": "buyer-agent"}


def award_payload() -> dict:
    payload = {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "request_id": "rfq-1",
        "buyer_display_name": "Demo Buyer",
        "seller_display_name": "Northwind Audio",
        "currency": "USD",
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "tax_cents": 0,
        "fees_cents": 0,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "offer_round": 1,
        "offer_valid_until": (NOW + timedelta(hours=1)).isoformat().replace(
            "+00:00", "Z"
        ),
    }
    payload["offer_hash"] = offer_hash(binding_from_award(payload))
    return payload


@pytest.fixture
async def api(tmp_path):
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
            yield client


async def agreed(client) -> dict:
    award = (
        await client.post(
            "/awards",
            json=award_payload(),
            headers={**OPS, "idempotency-key": "award:run-1:offer-1"},
        )
    ).json()
    txid = award["transaction_id"]
    await client.post(
        f"/transactions/{txid}/accept",
        json={
            "seller_id": "northwind-audio",
            "agreement_hash": award["agreement_hash"],
            "accepted_total_cents": 123400,
            "seller_task_id": "task-1",
            "accepted_at": NOW.isoformat(),
            "agreement_version": award["agreement_version"],
        },
        headers=OPS,
    )
    # buyer approval via BuyerPrincipal (internal service auth)
    agr_id = award["agreement"]["agreement_id"]
    from tests.support.buyer_auth import internal_buyer_headers, seed_buyer_profile

    client._transport.app = client._transport.app
    if not getattr(client._transport.app.state.settings, "buyer_settlement_internal_token", None):
        client._transport.app.state.settings.buyer_settlement_internal_token = "buyer-secret"
    await seed_buyer_profile(client._transport.app, buyer_id=award.get("buyer_id", "demo-buyer"))
    _buyer_headers = internal_buyer_headers(
        token="buyer-secret", clerk_user_id="user_buyer", buyer_id=award.get("buyer_id", "demo-buyer")
    )
    await client.post(
        f"/agreements/{agr_id}/buyer-decision",
        json={
            "agreement_version": award["agreement_version"],
            "agreement_hash": award["agreement_hash"],
            "decision": "APPROVE",
            "note": "",
            "idempotency_key": "bd:run-1",
        },
        headers={**_buyer_headers, "idempotency-key": "bd:run-1"},
    )
    await client.post(
        f"/transactions/{txid}/approve",
        json={
            "approval_id": "apr-1",
            "approved_by": "demo-reviewer",
            "approved_at": NOW.isoformat(),
            "agreement_hash": award["agreement_hash"],
            "agreement_version": award["agreement_version"],
        },
        headers=OPS,
    )
    return award


async def fund(client, award) -> dict:
    response = await client.post(
        f"/transactions/{award['transaction_id']}/fund",
        json={
            "agreement_hash": award["agreement_hash"],
            "agreement_version": award["agreement_version"],
            "return_url": "http://127.0.0.1:3000/runs/run-1",
            "cancel_url": "http://127.0.0.1:3000/runs/run-1",
        },
        headers={**OPS, "idempotency-key": f"fund:{award['transaction_id']}"},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def test_fund_returns_checkout_and_capture_funds(api):
    award = await agreed(api)
    financed = await fund(api, award)
    assert financed["state"] == "FUNDING_PENDING"
    assert "/checkout/fake/" in financed["checkout_url"]

    page = await api.get(financed["checkout_url"].replace("http://test", ""))
    assert page.status_code == 200
    assert "1234.00" in page.text

    approved = await api.post(
        financed["checkout_url"].replace("http://test", ""),
        data={"action": "approve"},
        follow_redirects=False,
    )
    assert approved.status_code == 303

    state = (
        await api.get(
            f"/transactions/{award['transaction_id']}/state", headers=OPS
        )
    ).json()
    assert state["state"] == "FUNDED"
    assert state["funding"]["status"] == "captured"
    assert state["funding"]["capture_id"].startswith("FAKE-CAP-")


async def test_fund_is_idempotent(api):
    award = await agreed(api)
    first = await fund(api, award)
    second = await fund(api, award)
    assert first["checkout_url"] == second["checkout_url"]
    state = (
        await api.get(f"/transactions/{award['transaction_id']}/state", headers=OPS)
    ).json()
    assert state["funding"]["provider_order_id"] == state["funding"].get(
        "provider_order_id"
    )


async def test_fund_rejects_external_return_url(api):
    award = await agreed(api)
    response = await api.post(
        f"/transactions/{award['transaction_id']}/fund",
        json={
            "agreement_hash": award["agreement_hash"],
            "agreement_version": award["agreement_version"],
            "return_url": "https://evil.example/steal",
            "cancel_url": "http://127.0.0.1:3000/runs/run-1",
        },
        headers=OPS,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"


async def test_checkout_cancel_no_ledger(api):
    award = await agreed(api)
    financed = await fund(api, award)
    canceled = await api.post(
        financed["checkout_url"].replace("http://test", ""),
        data={"action": "cancel"},
        follow_redirects=False,
    )
    assert canceled.status_code == 303
    state = (
        await api.get(f"/transactions/{award['transaction_id']}/state", headers=OPS)
    ).json()
    assert state["state"] == "CANCELED"
    assert state["cancellation"]["reason_code"] == "buyer_cancelled"


async def _issue_link(app, transaction_id: str, kind: str):
    link = app.state.links.issue(kind, transaction_id)
    async with app.state.repo.transaction() as conn:
        await app.state.repo.create_checkout_link(
            conn, link.jti, transaction_id, kind, link.expires_at
        )
    return link


async def test_paypal_return_redirects_to_the_console_run(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
        console_base_url="http://console.test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            award = await agreed(client)
            financed = await fund(client, award)
            await client.post(
                financed["checkout_url"].replace("http://test", ""),
                data={"action": "approve"},
                follow_redirects=False,
            )
            link = await _issue_link(
                app, award["transaction_id"], "return"
            )
            response = await client.get(
                f"/return/{link.token}", follow_redirects=False
            )
            assert response.status_code == 303
            assert response.headers["location"] == (
                "http://console.test/runs/run-1?funding=complete"
            )


async def test_paypal_return_captures_an_approved_order(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
        console_base_url="http://console.test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            award = await agreed(client)
            await fund(client, award)
            state = (
                await client.get(
                    f"/transactions/{award['transaction_id']}/state", headers=OPS
                )
            ).json()
            order_id = state["funding"]["provider_order_id"]
            async with app.state.repo.transaction() as conn:
                await app.state.repo.update_fake_order(
                    conn, order_id, status="APPROVED"
                )
            link = await _issue_link(app, award["transaction_id"], "return")
            response = await client.get(
                f"/return/{link.token}", follow_redirects=False
            )
            assert response.status_code == 303
            assert response.headers["location"] == (
                "http://console.test/runs/run-1?funding=complete"
            )
            state = (
                await client.get(
                    f"/transactions/{award['transaction_id']}/state", headers=OPS
                )
            ).json()
            assert state["state"] == "FUNDED"
            assert state["funding"]["status"] == "captured"
            assert state["funding"]["capture_id"].startswith("FAKE-CAP-")


async def test_paypal_cancel_cancels_pending_funding(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
        console_base_url="http://console.test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            award = await agreed(client)
            await fund(client, award)
            link = await _issue_link(
                app, award["transaction_id"], "cancel"
            )
            response = await client.get(
                f"/cancel/{link.token}", follow_redirects=False
            )
            assert response.status_code == 303
            assert response.headers["location"] == (
                "http://console.test/runs/run-1?funding=canceled"
            )
            state = (
                await client.get(
                    f"/transactions/{award['transaction_id']}/state",
                    headers=OPS,
                )
            ).json()
            assert state["state"] == "CANCELED"
            assert state["cancellation"]["reason_code"] == "buyer_cancelled"


async def test_capture_amount_mismatch_requires_review(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        fake_payment_scenario="amount_mismatch",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            award = await agreed(client)
            financed = await fund(client, award)
            await client.post(
                financed["checkout_url"].replace("http://test", ""),
                data={"action": "approve"},
                follow_redirects=False,
            )
            state = (
                await client.get(
                    f"/transactions/{award['transaction_id']}/state", headers=OPS
                )
            ).json()
            assert state["state"] == "REVIEW_REQUIRED"
            assert "funding_mismatch" in state["verification"]["reasons"]