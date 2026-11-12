from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import update

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import OPS, accept, approve, award, award_payload, fund_and_capture, purchase_order
from tests.support.seller_auth import clerk_seller_headers, seed_seller_profile
from tests.integration.test_verifund_lifecycle import canonical_catalog

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures" / "laptop"
NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


async def _seller_headers(http):
    app = http._transport.app
    await seed_seller_profile(
        app,
        clerk_org_id="org_northwind",
        seller_id="northwind-audio",
        display_name="northwind-audio",
        clerk_user_id="user_northwind",
    )
    return clerk_seller_headers(app, sub="user_northwind", org_id="org_northwind", token="tok_northwind")


async def _buyer_headers(http, buyer_id="demo-buyer"):
    # internal buyer auth for buyer routes
    from tests.support.buyer_auth import internal_buyer_headers, seed_buyer_profile
    app = http._transport.app
    if not getattr(app.state.settings, "buyer_settlement_internal_token", None):
        app.state.settings.buyer_settlement_internal_token = "buyer-secret"
    await seed_buyer_profile(app, buyer_id=buyer_id, clerk_user_id="user_buyer")
    return internal_buyer_headers(token="buyer-secret", clerk_user_id="user_buyer", buyer_id=buyer_id)


async def _settle_scans(http, txid: str):
    app = http._transport.app
    repo = app.state.repo
    async with repo.transaction() as conn:
        await conn.execute(update(repo.evidence).where(repo.evidence.c.transaction_id == txid).values(scan_status="clean"))
    await app.state.service.verify(txid, actor="system")


async def _run_base(http, scenario: str, *, clock_now=None):
    fixture_dir = FIXTURES / scenario
    manifest = json.loads((fixture_dir / "manifest.json").read_text())
    ship = json.loads((fixture_dir / manifest["requirements"]["shipping"]).read_text())

    payload = award_payload(requirements=canonical_catalog())
    award_body = await award(http, payload)
    txid = award_body["transaction_id"]
    await accept(http, award_body)
    await approve(http, award_body)
    await fund_and_capture(http, award_body)
    headers = await _seller_headers(http)

    po = purchase_order(award_body)
    po["tracking_number"] = ship["tracking_number"]
    po["carrier"] = ship.get("carrier_key", po.get("carrier"))
    reported = await http.post(
        f"/transactions/{txid}/purchase-order",
        json=po,
        headers={**OPS, "idempotency-key": f"po:{txid}"},
    )
    assert reported.status_code == 200, reported.text

    # provenance
    issued = await http.post(f"/seller/transactions/{txid}/provenance-challenge", headers=headers)
    assert issued.status_code == 201, issued.text
    p = fixture_dir / manifest["requirements"]["provenance"]
    r = await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "provenance"}, files={"file": (p.name, p.read_bytes(), "image/jpeg")})
    assert r.status_code == 201, r.text
    # serial
    p = fixture_dir / manifest["requirements"]["serial"]
    r = await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "serial"}, files={"file": (p.name, p.read_bytes(), "image/jpeg")})
    assert r.status_code == 201, r.text
    # photos
    for view, rel in zip(manifest["requirements"]["product_photo_views"], manifest["requirements"]["product_photos"]):
        fp = fixture_dir / rel
        r = await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "product_photos", "view_label": view}, files={"file": (fp.name, fp.read_bytes(), "image/jpeg")})
        assert r.status_code == 201, r.text
    # declaration
    decl = json.loads((fixture_dir / manifest["requirements"]["condition_declaration"]).read_text())
    r = await http.post(f"/seller/transactions/{txid}/requirements/condition_declaration/declare", headers=headers, json={"values": decl})
    assert r.status_code == 200, r.text
    # compliance docs
    for rid in ("hardware", "battery", "warranty", "invoice"):
        fp = fixture_dir / manifest["requirements"][rid]
        r = await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": rid}, files={"file": (fp.name, fp.read_bytes(), "application/json")})
        assert r.status_code == 201, r.text
    # packaging
    for view, rel in zip(manifest["requirements"]["packaging_views"], manifest["requirements"]["packaging"]):
        fp = fixture_dir / rel
        r = await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "packaging", "view_label": view}, files={"file": (fp.name, fp.read_bytes(), "image/jpeg")})
        assert r.status_code == 201, r.text
    # shipping reference
    r = await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "shipping", "reference": ship["tracking_number"], "reference_type": "tracking"})
    assert r.status_code == 201, r.text
    await _settle_scans(http, txid)

    # shipment
    resp = await http.post(f"/seller/transactions/{txid}/shipment", headers=headers, json=ship)
    assert resp.status_code == 201, resp.text
    await _settle_scans(http, txid)
    return award_body, txid, headers, ship


@pytest.fixture
async def api(tmp_path):
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'verifund.db'}",
        evidence_dir=tmp_path / "evidence",
        reconciler_enabled=False,
        public_base_url="http://test",
        delivery_timeout_hours=72,
    )
    app = create_app(settings, clock=lambda: NOW)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, app


@pytest.mark.asyncio
async def test_scenario_happy_path(api):
    http, app = api
    award_body, txid, headers, _ = await _run_base(http, "happy_path")
    state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "RELEASE_PERMITTED", state.get("verification")
    blockers = state.get("blockers") or []
    assert not [b for b in blockers if b.get("severity") == "blocking"], blockers
    released = await http.post(
        f"/transactions/{txid}/release",
        json={"released_by": "demo-reviewer", "note": "ok", "override": False},
        headers=OPS,
    )
    assert released.status_code == 200, released.text
    assert released.json()["state"] == "RELEASED"
    repo = app.state.repo
    balances = await repo.ledger_balances(txid)
    assert balances.get("held_funds") == 0


@pytest.mark.asyncio
async def test_scenario_specs_mismatch(api):
    http, _app = api
    award_body, txid, *_ = await _run_base(http, "specs_mismatch")
    state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] in {"REMEDIATION_REQUIRED", "REVIEW_REQUIRED"}
    reqs = {r["requirement_id"]: r for r in state.get("verification", {}).get("requirements", [])}
    assert reqs["hardware"]["status"] == "fail"
    blocker_codes = {b.get("code") for b in (state.get("blockers") or [])}
    assert "REQUIREMENT_FAILED" in blocker_codes or state["state"] != "RELEASE_PERMITTED"


@pytest.mark.asyncio
async def test_scenario_packing_photo_missing(api):
    http, _app = api
    award_body, txid, *_ = await _run_base(http, "packing_photo_missing")
    state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] in {"REMEDIATION_REQUIRED", "REVIEW_REQUIRED"}
    reqs = {r["requirement_id"]: r for r in state.get("verification", {}).get("requirements", [])}
    assert reqs["packaging"]["status"] == "fail"
    blocker_codes = {b.get("code") for b in (state.get("blockers") or [])}
    assert "REQUIREMENT_FAILED" in blocker_codes


@pytest.mark.asyncio
async def test_scenario_weight_anomaly(api):
    http, _app = api
    award_body, txid, *_ = await _run_base(http, "weight_anomaly")
    state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "REVIEW_REQUIRED", state
    blockers = state.get("blockers") or []
    codes = {b.get("code") for b in blockers}
    assert "WEIGHT_ANOMALY" in codes or "REVIEW_REQUIRED" in codes
    reasons = (state.get("verification") or {}).get("reasons") or []
    assert "weight_anomaly" in reasons


@pytest.mark.asyncio
async def test_scenario_never_delivers(api, tmp_path):
    now = NOW
    settings = Settings(
        _env_file=None,
        mode="fake",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'never.db'}",
        evidence_dir=tmp_path / "ev-never",
        reconciler_enabled=False,
        public_base_url="http://test",
        delivery_timeout_hours=1,
    )
    app = create_app(settings, clock=lambda: now)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            award_body, txid, *_ = await _run_base(http, "never_delivers")
            state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
            assert state["state"] != "RELEASED"
            # advance past delivery timeout and sweep
            now = NOW + timedelta(hours=2)
            await app.state.reconciler.run_once()
            state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
            assert state["state"] == "REVIEW_REQUIRED", state
            blockers = state.get("blockers") or []
            codes = {b.get("code") for b in blockers}
            assert "DELIVERY_TIMEOUT" in codes or "REVIEW_REQUIRED" in codes
            # never auto-refunds
            assert state["state"] != "REFUNDED"


@pytest.mark.asyncio
async def test_scenario_dispute_seller_wins(api):
    http, app = api
    award_body, txid, *_ = await _run_base(http, "dispute_seller_wins")
    # reach release-permitted first
    state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "RELEASE_PERMITTED", state
    buyer_headers = await _buyer_headers(http, buyer_id=award_body.get("buyer_id", "demo-buyer"))
    opened = await http.post(
        f"/buyer/transactions/{txid}/dispute",
        headers=buyer_headers,
        json={"claim_type": "UNDISCLOSED_DAMAGE", "reason_code": "other", "claim": "alleged issue", "evidence": [{"type": "note", "text": "x"}], "requirement_ids": ["product_photos"]},
    )
    assert opened.status_code == 200, opened.text
    state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "DISPUTE_OPEN"
    resolved = await app.state.service.resolve_dispute(txid, outcome="seller_wins", actor="ops", rationale="evidence supports seller")
    assert resolved["state"] in {"RELEASE_PERMITTED", "RELEASED"}
    state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
    # if permitted, release
    if state["state"] == "RELEASE_PERMITTED":
        rel = await http.post(f"/transactions/{txid}/release", json={"released_by": "ops", "note": "seller wins", "override": False}, headers=OPS)
        assert rel.status_code == 200, rel.text
        state = rel.json()
    assert state["state"] == "RELEASED"
    balances = await app.state.repo.ledger_balances(txid)
    assert balances.get("held_funds") == 0


@pytest.mark.asyncio
async def test_scenario_dispute_buyer_wins(api):
    http, app = api
    award_body, txid, *_ = await _run_base(http, "dispute_buyer_wins")
    state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "RELEASE_PERMITTED", state
    buyer_headers = await _buyer_headers(http, buyer_id=award_body.get("buyer_id", "demo-buyer"))
    opened = await http.post(
        f"/buyer/transactions/{txid}/dispute",
        headers=buyer_headers,
        json={"claim_type": "WRONG_DEVICE", "reason_code": "other", "claim": "wrong device", "evidence": [{"type": "note", "text": "x"}], "requirement_ids": ["serial"]},
    )
    assert opened.status_code == 200, opened.text
    resolved = await app.state.service.resolve_dispute(txid, outcome="buyer_wins", actor="ops", rationale="buyer evidence accepted")
    assert resolved["state"] == "REFUNDED"
    state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
    assert state["state"] == "REFUNDED"
    # no seller payout
    balances = await app.state.repo.ledger_balances(txid)
    assert balances.get("seller_paid", 0) == 0
