"""Requirement-addressed seller evidence upload (plan Task 9a)."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import (
    NOW,
    accept,
    approve,
    award,
    award_payload,
    fund_and_capture,
    upload_file,
    upload_json,
    upload_reference,
)
from tests.support.seller_auth import clerk_seller_headers, seed_seller_profile


def requirement_catalog() -> list[dict]:
    return [
        {
            "requirement_id": "hardware",
            "title": "Hardware diagnostic report",
            "description": "Diagnostic report showing at least 32 GB of RAM.",
            "owner": "seller",
            "kind": "other",
            "source": "file",
            "accepted_formats": ["text/csv"],
            "checks": [
                {
                    "check_id": "ram_gte_32gb",
                    "description": "At least 32 GB of RAM.",
                    "expected_value": 32,
                    "operator": "gte",
                    "unit": "GB",
                    "verification_method": "deterministic",
                    "ai_derived": False,
                }
            ],
            "required": True,
        },
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
                    "verification_method": "deterministic",
                    "ai_derived": False,
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


def catalog_award_payload() -> dict:
    return award_payload(requirements=requirement_catalog())


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


async def _seller_headers(app, *, seller_id: str = "northwind-audio") -> dict[str, str]:
    await seed_seller_profile(
        app,
        clerk_org_id=f"org_{seller_id.replace('-', '_')}",
        seller_id=seller_id,
        display_name=seller_id,
        clerk_user_id=f"user_{seller_id.replace('-', '_')}",
    )
    return clerk_seller_headers(
        app,
        sub=f"user_{seller_id.replace('-', '_')}",
        org_id=f"org_{seller_id.replace('-', '_')}",
        token=f"tok_{seller_id.replace('-', '_')}",
    )


async def funded(client, app) -> dict:
    body = await award(client, catalog_award_payload())
    await accept(client, body)
    await approve(client, body)
    await fund_and_capture(client, body)
    return body


async def test_upload_addressed_by_requirement_id_returns_receipt(client):
    http, app = client
    body = await funded(http, app)
    captured_at = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)
    headers = await _seller_headers(app)
    response = await upload_file(
        http,
        body,
        "hardware",
        data=b"ram_gb,32\n",
        filename="diag.csv",
        media_type="text/csv",
        captured_at=captured_at,
        headers=headers,
    )
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["requirement_id"] == "hardware"
    assert receipt["submission_id"].startswith("sub_")
    assert receipt["receipt_id"].startswith("rcpt_")
    assert receipt["evidence_id"].startswith("ev_")
    assert receipt["attempt"] == 1
    assert receipt["artifact_type"] == "file"
    assert receipt["scan_status"] == "pending"

    items = await app.state.repo.list_evidence(body["transaction_id"])
    assert [item.requirement_id for item in items] == ["hardware"]
    assert items[0].scan_status == "pending"
    assert items[0].captured_at == captured_at
    assert items[0].submission_attempt == 1
    assert items[0].agreement_version == body["agreement_version"]

    submissions = await app.state.repo.list_submissions(body["transaction_id"], "hardware")
    assert [row["submission_id"] for row in submissions] == [receipt["submission_id"]]
    assert submissions[0]["attempt"] == 1


async def test_requirement_catalog_is_stamped_on_the_agreement_terms(client):
    http, app = client
    body = await award(http, catalog_award_payload())
    agreement = await app.state.service.agreement_service.get_by_transaction(
        body["transaction_id"]
    )
    terms = agreement.current_version_record.terms
    assert terms["policy_version"] == 2
    ids = [requirement["requirement_id"] for requirement in terms["requirements"]]
    assert ids == ["hardware", "shipping", "delivery_confirmation"]


async def test_legacy_kind_is_rejected_with_422(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    response = await http.post(
        f"/seller/transactions/{body['transaction_id']}/evidence",
        headers=headers,
        data={"kind": "shipment_manifest"},
        files={"file": ("manifest.json", b"{}", "application/json")},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_request"
    assert "requirement_id" in response.json()["error"]["message"]


async def test_kind_and_requirement_id_together_are_rejected(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    response = await http.post(
        f"/seller/transactions/{body['transaction_id']}/evidence",
        headers=headers,
        data={"kind": "other", "requirement_id": "hardware"},
        files={"file": ("diag.csv", b"ram_gb,32\n", "text/csv")},
    )
    assert response.status_code == 422


async def test_missing_requirement_id_is_rejected(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    response = await http.post(
        f"/seller/transactions/{body['transaction_id']}/evidence",
        headers=headers,
        files={"file": ("diag.csv", b"ram_gb,32\n", "text/csv")},
    )
    assert response.status_code == 422
    assert "requirement_id" in response.json()["error"]["message"]


async def test_unknown_requirement_is_rejected(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    response = await upload_json(
        http, body, "not_a_requirement", {"x": 1}, headers=headers
    )
    assert response.status_code == 422
    assert "not_a_requirement" in response.json()["error"]["message"]


async def test_system_owned_requirement_is_rejected(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    response = await upload_json(
        http,
        body,
        "delivery_confirmation",
        {"delivered_at": "2026-10-26T12:00:00Z"},
        headers=headers,
    )
    assert response.status_code == 422
    assert "seller-owned" in response.json()["error"]["message"]


async def test_reference_requirement_accepts_a_tracking_reference(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    response = await upload_reference(
        http, body, "shipping", "TRK-1", "tracking", headers=headers
    )
    assert response.status_code == 201, response.text
    receipt = response.json()
    assert receipt["artifact_type"] == "reference"
    assert receipt["scan_status"] == "clean"
    assert receipt["requirement_id"] == "shipping"


async def test_reference_requirement_rejects_a_file(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    response = await upload_json(
        http, body, "shipping", {"tracking_number": "TRK-1"}, headers=headers
    )
    assert response.status_code == 422


async def test_file_requirement_rejects_a_reference(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    response = await upload_reference(
        http, body, "hardware", "TRK-1", "tracking", headers=headers
    )
    assert response.status_code == 422


async def test_file_requirement_rejects_media_outside_the_catalog(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    response = await upload_file(
        http,
        body,
        "hardware",
        data=b"%PDF-1.4",
        filename="report.pdf",
        media_type="application/pdf",
        headers=headers,
    )
    assert response.status_code == 415
    assert "text/csv" in response.json()["error"]["message"]


async def test_agreement_version_mismatch_is_rejected_with_409(client):
    http, app = client
    body = await funded(http, app)
    headers = await _seller_headers(app)
    response = await upload_file(
        http,
        body,
        "hardware",
        data=b"ram_gb,32\n",
        filename="diag.csv",
        media_type="text/csv",
        agreement_version=body["agreement_version"] + 1,
        headers=headers,
    )
    assert response.status_code == 409


async def test_upload_before_funding_is_rejected_with_409(client):
    http, app = client
    body = await award(http, catalog_award_payload())
    headers = await _seller_headers(app)
    response = await upload_file(
        http,
        body,
        "hardware",
        data=b"ram_gb,32\n",
        filename="diag.csv",
        media_type="text/csv",
        headers=headers,
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_state"
