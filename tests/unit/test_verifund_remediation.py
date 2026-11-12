"""Remediation loop: FAIL routing, resubmission re-entry, review reversibility.

Plan Task 16 / spec §3.5: an objective FAIL on a seller-owned requirement lands
in REMEDIATION_REQUIRED (not REVIEW_REQUIRED), a resubmission re-enters
verification, and ops can hand a reviewed transaction back to the seller.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import (
    NOW,
    OPS,
    accept,
    approve,
    award,
    award_payload,
    fund_and_capture,
    purchase_order,
    upload_reference,
)
from tests.support.seller_auth import clerk_seller_headers, seed_seller_profile

REMEDIATION_HOURS = 12


def shipping_catalog(*, tracking_method: str = "deterministic") -> list[dict]:
    """Minimal catalog whose only seller requirement can FAIL deterministically."""
    return [
        {
            "requirement_id": "shipping",
            "title": "Shipping information",
            "description": "Carrier and tracking number matching the purchase order.",
            "owner": "seller",
            "kind": "shipment_manifest",
            "source": "reference",
            "accepted_formats": [],
            "checks": [
                {
                    "check_id": "tracking_matches_po",
                    "description": "Tracking number matches the purchase order.",
                    "expected_value": "purchase_order.tracking_number",
                    "operator": "eq",
                    "verification_method": tracking_method,
                    "ai_derived": tracking_method != "deterministic",
                }
            ],
            "required": True,
        },
        {
            "requirement_id": "delivery_confirmation",
            "title": "Delivery confirmation",
            "description": "System-generated from the carrier record and buyer confirmation.",
            "owner": "system",
            "kind": "delivery_confirmation",
            "source": "reference",
            "accepted_formats": [],
            "checks": [
                {
                    "check_id": "carrier_and_buyer_agree",
                    "description": "Carrier record and buyer confirmation agree.",
                    "operator": "exists",
                    "verification_method": "deterministic",
                    "ai_derived": False,
                }
            ],
            "required": True,
        },
    ]


@pytest.fixture
async def client(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        remediation_deadline_hours=REMEDIATION_HOURS,
        public_base_url="http://test",
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, app


async def _seller_headers(app) -> dict[str, str]:
    await seed_seller_profile(
        app,
        clerk_org_id="org_northwind",
        seller_id="northwind-audio",
        display_name="northwind-audio",
        clerk_user_id="user_northwind",
    )
    return clerk_seller_headers(
        app, sub="user_northwind", org_id="org_northwind", token="tok_northwind"
    )


async def reported(client, app, catalog: list[dict]) -> dict:
    """Award, fund, and report the purchase order so uploads start verification."""
    body = await award(client, award_payload(requirements=catalog))
    await accept(client, body)
    await approve(client, body)
    await fund_and_capture(client, body)
    response = await client.post(
        f"/transactions/{body['transaction_id']}/purchase-order",
        json=purchase_order(body),
        headers={**OPS, "idempotency-key": f"po:{body['transaction_id']}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "FULFILLMENT_PENDING"
    return body


async def state_of(client, body: dict) -> dict:
    response = await client.get(
        f"/transactions/{body['transaction_id']}/state", headers=OPS
    )
    assert response.status_code == 200, response.text
    return response.json()


def _deadline_after(value: str, hours: int) -> bool:
    return datetime.fromisoformat(value) == NOW + timedelta(hours=hours)


async def test_objective_fail_lands_in_remediation(client):
    http, app = client
    body = await reported(http, app, shipping_catalog())
    headers = await _seller_headers(app)

    uploaded = await upload_reference(
        http, body, "shipping", "WRONG-TRK", "tracking", headers=headers
    )
    assert uploaded.status_code == 201, uploaded.text

    state = await state_of(http, body)
    assert state["state"] == "REMEDIATION_REQUIRED"
    assert state["verification"]["status"] == "failed"
    assert state["verification"]["rollup"] == "REMEDIATION_REQUIRED"
    assert state["deadlines"]["remediation"]
    assert _deadline_after(state["deadlines"]["remediation"], REMEDIATION_HOURS)


async def test_resubmission_reenters_verification(client):
    http, app = client
    body = await reported(http, app, shipping_catalog())
    headers = await _seller_headers(app)

    failed = await upload_reference(
        http, body, "shipping", "WRONG-TRK", "tracking", headers=headers
    )
    assert failed.status_code == 201, failed.text
    assert (await state_of(http, body))["state"] == "REMEDIATION_REQUIRED"

    corrected = await upload_reference(
        http, body, "shipping", "TRK-1", "tracking", headers=headers
    )
    assert corrected.status_code == 201, corrected.text

    state = await state_of(http, body)
    assert state["state"] == "VERIFICATION_PENDING"
    shipping = next(
        r for r in state["verification"]["requirements"] if r["requirement_id"] == "shipping"
    )
    assert shipping["status"] == "pass"


async def test_return_to_remediation_accepts_a_review_state(client):
    http, app = client
    body = await reported(http, app, shipping_catalog(tracking_method="extraction"))
    headers = await _seller_headers(app)

    reviewed = await upload_reference(
        http, body, "shipping", "TRK-1", "tracking", headers=headers
    )
    assert reviewed.status_code == 201, reviewed.text
    assert (await state_of(http, body))["state"] == "REVIEW_REQUIRED"

    response = await http.post(
        f"/transactions/{body['transaction_id']}/return-to-remediation",
        json={"note": "continue evidence collection"},
        headers=OPS,
    )
    assert response.status_code == 200, response.text

    state = await state_of(http, body)
    assert state["state"] == "REMEDIATION_REQUIRED"
    assert _deadline_after(state["deadlines"]["remediation"], REMEDIATION_HOURS)
