#!/usr/bin/env python3
"""Run a deterministic laptop fulfillment scenario against the in-process control plane.

Usage:
  uv run python scripts/run_scenario.py --scenario happy_path
"""
from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import NOW, OPS, accept, approve, award, award_payload, fund_and_capture, purchase_order
from tests.support.seller_auth import clerk_seller_headers, seed_seller_profile

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures" / "laptop"


async def seller_headers(http):
    app = http._transport.app
    await seed_seller_profile(
        app,
        clerk_org_id="org_northwind",
        seller_id="northwind-audio",
        display_name="northwind-audio",
        clerk_user_id="user_northwind",
    )
    return clerk_seller_headers(app, sub="user_northwind", org_id="org_northwind", token="tok_northwind")


async def settle_scans_and_verify(api, txid):
    from sqlalchemy import update
    app = api._transport.app
    repo = app.state.repo
    async with repo.transaction() as conn:
        await conn.execute(update(repo.evidence).where(repo.evidence.c.transaction_id == txid).values(scan_status="clean"))
    await app.state.service.verify(txid, actor="system")


async def run(scenario: str) -> dict:
    fixture_dir = FIXTURES / scenario
    manifest = json.loads((fixture_dir / "manifest.json").read_text())
    # Use laptop category terms so full catalog applies
    terms = {"product": {"category": "electronics.laptop.refurbished"}}
    payload = award_payload()
    # include terms hint if supported; at minimum rely on projection
    payload["terms"] = terms

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(_env_file=None, mode="fake", database_url=f"sqlite+aiosqlite:///{tmp}/v.db", evidence_dir=Path(tmp)/"ev", reconciler_enabled=False, public_base_url="http://test")
        app = create_app(settings, clock=lambda: NOW)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                # award/accept/approve/fund
                award_body = await award(http, payload)
                txid = award_body["transaction_id"]
                await accept(http, award_body)
                await approve(http, award_body)
                await fund_and_capture(http, award_body)
                headers = await seller_headers(http)

                # report PO
                await http.post(f"/transactions/{txid}/purchase-order", json=purchase_order(award_body), headers={**OPS, "idempotency-key": f"po:{txid}"})

                # provenance
                await http.post(f"/seller/transactions/{txid}/provenance-challenge", headers=headers)
                prov_path = fixture_dir / manifest["requirements"]["provenance"]
                await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "provenance"}, files={"file": (prov_path.name, prov_path.read_bytes(), "image/jpeg")})

                # serial
                serial_path = fixture_dir / manifest["requirements"]["serial"]
                await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "serial"}, files={"file": (serial_path.name, serial_path.read_bytes(), "image/jpeg")})

                # condition photos
                for view, rel in zip(manifest["requirements"]["product_photo_views"], manifest["requirements"]["product_photos"]):
                    p = fixture_dir / rel
                    await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "product_photos", "view_label": view}, files={"file": (p.name, p.read_bytes(), "image/jpeg")})

                # declaration
                decl = json.loads((fixture_dir / manifest["requirements"]["condition_declaration"]).read_text())
                await http.post(f"/seller/transactions/{txid}/requirements/condition_declaration/declare", headers=headers, json={"values": decl})

                # hardware/battery/warranty
                hw = fixture_dir / manifest["requirements"]["hardware"]
                await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "hardware"}, files={"file": (hw.name, hw.read_bytes(), "application/json")})
                batt = fixture_dir / manifest["requirements"]["battery"]
                await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "battery"}, files={"file": (batt.name, batt.read_bytes(), "application/json")})
                war = fixture_dir / manifest["requirements"]["warranty"]
                await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "warranty"}, files={"file": (war.name, war.read_bytes(), "application/json")})

                # packaging
                for view, rel in zip(manifest["requirements"]["packaging_views"], manifest["requirements"]["packaging"]):
                    p = fixture_dir / rel
                    await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "packaging", "view_label": view}, files={"file": (p.name, p.read_bytes(), "image/jpeg")})

                # invoice
                inv = fixture_dir / manifest["requirements"]["invoice"]
                await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "invoice"}, files={"file": (inv.name, inv.read_bytes(), "application/json")})

                # shipping reference
                ship = json.loads((fixture_dir / manifest["requirements"]["shipping"]).read_text())
                await http.post(f"/seller/transactions/{txid}/evidence", headers=headers, data={"requirement_id": "shipping", "reference": ship["tracking_number"], "reference_type": "tracking"})

                await settle_scans_and_verify(http, txid)

                # register shipment (carrier will ingest events per scenario)
                await http.post(f"/seller/transactions/{txid}/shipment", headers=headers, json=ship)
                await settle_scans_and_verify(http, txid)

                # scenario-specific actions
                if scenario in {"dispute_seller_wins", "dispute_buyer_wins"}:
                    await http.post(f"/buyer/transactions/{txid}/dispute", headers={"x-verifund-internal-token": "", "authorization": "Bearer dev-verifund-ops"}, json={"reason_code": "other", "claim": "issue", "evidence": [{"type": "note"}], "requirement_ids": ["product_photos"]})
                # simple resolution hooks via ops if available - best effort
                # (tests will assert specific flows)

                state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
                return {"scenario": scenario, "state": state.get("state"), "verification": state.get("verification"), "blockers": state.get("blockers"), "payout": state.get("payout")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True, choices=[p.name for p in FIXTURES.iterdir() if p.is_dir()])
    args = ap.parse_args()
    result = asyncio.run(run(args.scenario))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
