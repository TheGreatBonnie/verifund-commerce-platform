from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import update
from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import NOW, accept, approve, award, fund_and_capture
from tests.support.seller_auth import clerk_seller_headers, seed_seller_profile


async def seller_headers(http):
    app = http._transport.app
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


@pytest.fixture
async def api(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
        provenance_ttl_minutes=60,
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, app


async def funded_transaction(http):
    award_body = await award(http)
    await accept(http, award_body)
    await approve(http, award_body)
    await fund_and_capture(http, award_body)
    return award_body


async def ensure_provenance_requirement(app, award_body: dict) -> None:
    txid = award_body["transaction_id"]
    agreement = await app.state.agreement_service.get_by_transaction(txid)
    version = agreement.current_version_record
    terms = json.loads(version.terms) if isinstance(version.terms, str) else dict(version.terms or {})
    reqs = list(terms.get("requirements") or [])
    if not any(r.get("requirement_id") == "provenance" for r in reqs):
        reqs.append(
            {
                "requirement_id": "provenance",
                "title": "Provenance challenge",
                "description": "Transaction challenge code visible on the device.",
                "owner": "seller",
                "kind": "other",
                "source": "file",
                "stage": "product_identity",
                "accepted_formats": ["image/jpeg", "image/png", "image/webp"],
                "checks": [
                    {
                        "check_id": "challenge_code",
                        "description": "Challenge code matches active challenge.",
                        "operator": "eq",
                        "expected_value": "runtime:active_provenance_challenge",
                        "verification_method": "deterministic",
                    }
                ],
                "required": True,
                "min_items": 1,
                "required_views": [],
            }
        )
        terms["requirements"] = reqs
        async with app.state.agreement_repo.engine.begin() as conn:
            await conn.execute(
                update(app.state.agreement_repo.agreement_versions)
                .where(app.state.agreement_repo.agreement_versions.c.agreement_id == agreement.agreement_id)
                .where(app.state.agreement_repo.agreement_versions.c.version == agreement.current_version)
                .values(terms=json.dumps(terms))
            )


@pytest.mark.asyncio
async def test_issue_and_get_provenance_challenge(api):
    http, app = api
    award_body = await funded_transaction(http)
    txid = award_body["transaction_id"]
    headers = await seller_headers(http)

    issued = await http.post(
        f"/seller/transactions/{txid}/provenance-challenge", headers=headers
    )
    assert issued.status_code == 201, issued.text
    body = issued.json()
    assert body["status"] == "active"
    assert body["code"]

    fetched = await http.get(
        f"/seller/transactions/{txid}/provenance-challenge", headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["code"] == body["code"]


@pytest.mark.asyncio
async def test_provenance_upload_consumes_challenge_once(api):
    http, app = api
    award_body = await funded_transaction(http)
    txid = award_body["transaction_id"]
    headers = await seller_headers(http)
    await ensure_provenance_requirement(app, award_body)

    issued = await http.post(
        f"/seller/transactions/{txid}/provenance-challenge", headers=headers
    )
    assert issued.status_code == 201, issued.text

    uploaded = await http.post(
        f"/seller/transactions/{txid}/evidence",
        headers=headers,
        data={"requirement_id": "provenance"},
        files={"file": ("prov.jpg", b"\xff\xd8\xffprov", "image/jpeg")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["reason_code"] == "CHALLENGE_MATCHED"

    fetched = await http.get(
        f"/seller/transactions/{txid}/provenance-challenge", headers=headers
    )
    assert fetched.status_code == 404, fetched.text

    record = await app.state.repo.get_transaction(txid)
    challenge = await app.state.repo.get_active_provenance_challenge(
        getattr(record, "seller_organization_id", None), txid, now=NOW
    )
    assert challenge is None


@pytest.mark.asyncio
async def test_provenance_upload_mismatch_does_not_consume(api):
    http, app = api
    award_body = await funded_transaction(http)
    txid = award_body["transaction_id"]
    headers = await seller_headers(http)
    await ensure_provenance_requirement(app, award_body)

    issued = await http.post(
        f"/seller/transactions/{txid}/provenance-challenge", headers=headers
    )
    assert issued.status_code == 201, issued.text

    from verifund_control_plane.challenge_extractor import ChallengeExtraction

    class MismatchExtractor:
        async def extract_code(self, image_bytes: bytes, *, expected_hint=None):
            return ChallengeExtraction(code="WRONG-CODE", confidence=1.0, simulated=True, provider="fixture")

    app.state.challenge_extractor = MismatchExtractor()
    app.state.service.challenge_extractor = MismatchExtractor()

    uploaded = await http.post(
        f"/seller/transactions/{txid}/evidence",
        headers=headers,
        data={"requirement_id": "provenance"},
        files={"file": ("prov-bad.jpg", b"\xff\xd8\xffprov-bad-unique", "image/jpeg")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["reason_code"] == "CHALLENGE_MISMATCH"

    fetched = await http.get(
        f"/seller/transactions/{txid}/provenance-challenge", headers=headers
    )
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["code"] == issued.json()["code"]


@pytest.mark.asyncio
async def test_provenance_upload_expired_challenge(tmp_path):
    now = NOW
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund-exp.db'}",
        evidence_dir=tmp_path / "evidence-exp",
        reconciler_enabled=False,
        public_base_url="http://test",
        provenance_ttl_minutes=1,
    )
    app = create_app(settings, clock=lambda: now)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            award_body = await funded_transaction(http)
            txid = award_body["transaction_id"]
            headers = await seller_headers(http)
            await ensure_provenance_requirement(app, award_body)

            issued = await http.post(
                f"/seller/transactions/{txid}/provenance-challenge", headers=headers
            )
            assert issued.status_code == 201, issued.text

            now = NOW + timedelta(minutes=2)
            uploaded = await http.post(
                f"/seller/transactions/{txid}/evidence",
                headers=headers,
                data={"requirement_id": "provenance"},
                files={"file": ("prov-exp.jpg", b"\xff\xd8\xffprov-exp-unique", "image/jpeg")},
            )
            assert uploaded.status_code == 201, uploaded.text
            assert uploaded.json()["reason_code"] == "CHALLENGE_EXPIRED"
