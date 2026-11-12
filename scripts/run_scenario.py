#!/usr/bin/env python3
"""Run a deterministic laptop fulfillment scenario against the in-process control plane.

Usage:
  uv run python scripts/run_scenario.py --scenario happy_path
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in [
    ROOT,
    ROOT / "packages" / "verifund_contracts",
    ROOT / "apps" / "verifund_control_plane",
    ROOT / "apps" / "buyer_agent",
]:
    sp = str(p)
    if sp not in sys.path:
        sys.path.insert(0, sp)

import httpx
from sqlalchemy import update

from verifund_control_plane.app import create_app
from verifund_control_plane.settings import Settings

from tests.support.award_flow import NOW, OPS, accept, approve, award, award_payload, fund_and_capture, purchase_order
from tests.support.seller_auth import clerk_seller_headers, seed_seller_profile
from tests.integration.test_verifund_lifecycle import canonical_catalog

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
    app = api._transport.app
    repo = app.state.repo
    async with repo.transaction() as conn:
        await conn.execute(update(repo.evidence).where(repo.evidence.c.transaction_id == txid).values(scan_status="clean"))
    await app.state.service.verify(txid, actor="system")


async def run(scenario: str) -> dict:
    fixture_dir = FIXTURES / scenario
    manifest = json.loads((fixture_dir / "manifest.json").read_text())
    ship = json.loads((fixture_dir / manifest["requirements"]["shipping"]).read_text())

    payload = award_payload(requirements=canonical_catalog())

    with tempfile.TemporaryDirectory() as tmp:
        settings = Settings(
            _env_file=None,
            mode="fake",
            database_url=f"sqlite+aiosqlite:///{tmp}/v.db",
            evidence_dir=Path(tmp) / "ev",
            reconciler_enabled=False,
            public_base_url="http://test",
        )
        app = create_app(settings, clock=lambda: NOW)
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
                award_body = await award(http, payload)
                txid = award_body["transaction_id"]
                await accept(http, award_body)
                await approve(http, award_body)
                await fund_and_capture(http, award_body)
                headers = await seller_headers(http)

                po = purchase_order(award_body)
                po["tracking_number"] = ship["tracking_number"]
                po["carrier"] = ship.get("carrier_key", po.get("carrier"))
                reported = await http.post(
                    f"/transactions/{txid}/purchase-order",
                    json=po,
                    headers={**OPS, "idempotency-key": f"po:{txid}"},
                )
                reported.raise_for_status()

                issued = await http.post(f"/seller/transactions/{txid}/provenance-challenge", headers=headers)
                issued.raise_for_status()

                prov_path = fixture_dir / manifest["requirements"]["provenance"]
                r = await http.post(
                    f"/seller/transactions/{txid}/evidence",
                    headers=headers,
                    data={"requirement_id": "provenance"},
                    files={"file": (prov_path.name, prov_path.read_bytes(), "image/jpeg")},
                )
                r.raise_for_status()

                serial_path = fixture_dir / manifest["requirements"]["serial"]
                r = await http.post(
                    f"/seller/transactions/{txid}/evidence",
                    headers=headers,
                    data={"requirement_id": "serial"},
                    files={"file": (serial_path.name, serial_path.read_bytes(), "image/jpeg")},
                )
                r.raise_for_status()

                for view, rel in zip(manifest["requirements"]["product_photo_views"], manifest["requirements"]["product_photos"]):
                    p = fixture_dir / rel
                    r = await http.post(
                        f"/seller/transactions/{txid}/evidence",
                        headers=headers,
                        data={"requirement_id": "product_photos", "view_label": view},
                        files={"file": (p.name, p.read_bytes(), "image/jpeg")},
                    )
                    r.raise_for_status()

                decl = json.loads((fixture_dir / manifest["requirements"]["condition_declaration"]).read_text())
                r = await http.post(
                    f"/seller/transactions/{txid}/requirements/condition_declaration/declare",
                    headers=headers,
                    json={"values": decl},
                )
                r.raise_for_status()

                for rid in ("hardware", "battery", "warranty", "invoice"):
                    fp = fixture_dir / manifest["requirements"][rid]
                    r = await http.post(
                        f"/seller/transactions/{txid}/evidence",
                        headers=headers,
                        data={"requirement_id": rid},
                        files={"file": (fp.name, fp.read_bytes(), "application/json")},
                    )
                    r.raise_for_status()

                for view, rel in zip(manifest["requirements"]["packaging_views"], manifest["requirements"]["packaging"]):
                    p = fixture_dir / rel
                    r = await http.post(
                        f"/seller/transactions/{txid}/evidence",
                        headers=headers,
                        data={"requirement_id": "packaging", "view_label": view},
                        files={"file": (p.name, p.read_bytes(), "image/jpeg")},
                    )
                    r.raise_for_status()

                r = await http.post(
                    f"/seller/transactions/{txid}/evidence",
                    headers=headers,
                    data={"requirement_id": "shipping", "reference": ship["tracking_number"], "reference_type": "tracking"},
                )
                r.raise_for_status()

                await settle_scans_and_verify(http, txid)

                shipped = await http.post(f"/seller/transactions/{txid}/shipment", headers=headers, json=ship)
                shipped.raise_for_status()
                await settle_scans_and_verify(http, txid)

                if scenario in {"dispute_seller_wins", "dispute_buyer_wins"}:
                    # Open dispute as buyer (internal auth not configured in this script path; use service-level ops in test envs)
                    # Best-effort: rely on API if internal buyer headers available; else record state for inspection.
                    pass

                state = (await http.get(f"/transactions/{txid}/state", headers=OPS)).json()
                return {
                    "scenario": scenario,
                    "transaction_id": txid,
                    "state": state.get("state"),
                    "rollup": (state.get("verification") or {}).get("rollup"),
                    "blockers": state.get("blockers") or [],
                    "payout": state.get("payout"),
                }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", required=True, choices=[p.name for p in FIXTURES.iterdir() if p.is_dir()])
    args = ap.parse_args()
    result = asyncio.run(run(args.scenario))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
