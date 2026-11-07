"""Seller-scoped read endpoints (migrated to Clerk seller auth)."""

from __future__ import annotations

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
)
from tests.support.seller_auth import clerk_seller_headers, seed_seller_profile


def award_for(run_id: str, seller_id: str) -> dict:
    return award_payload(
        run_id=run_id,
        offer_id=f"offer-{run_id}",
        request_id=f"rfq-{run_id}",
        seller_id=seller_id,
    )


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


async def _seed_and_headers(
    app, seller_id: str, *, clerk_org_id: str, sub: str, token: str | None = None
):
    await seed_seller_profile(
        app,
        clerk_org_id=clerk_org_id,
        seller_id=seller_id,
        display_name=seller_id,
        clerk_user_id=sub,
    )
    return clerk_seller_headers(
        app, sub=sub, org_id=clerk_org_id, token=token or f"tok_{sub}"
    )


async def test_seller_list_scoped_by_identity(client):
    http, app = client
    first = await award(http, award_for("run-1", "northwind-audio"))
    second = await award(http, award_for("run-2", "northwind-audio"))
    await award(http, award_for("run-3", "other-seller"))

    headers = await _seed_and_headers(
        app, "northwind-audio", clerk_org_id="org_northwind", sub="user_nw"
    )
    response = await http.get("/seller/transactions", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    ids = {item["transaction_id"] for item in body["items"]}
    assert ids == {first["transaction_id"], second["transaction_id"]}
    assert all("seller_id" not in item for item in body["items"])
    assert all(item["state"] for item in body["items"])
    counts = body["counts_by_state"]
    assert sum(counts.values()) == 2
    assert counts.get("AWARDED") == 2


async def test_seller_list_pagination_round_trips(client):
    http, app = client
    awards = [await award(http, award_for(f"run-{i}", "northwind-audio")) for i in range(1, 4)]
    headers = await _seed_and_headers(
        app, "northwind-audio", clerk_org_id="org_northwind", sub="user_nw"
    )

    first_page = await http.get("/seller/transactions?limit=2", headers=headers)
    assert first_page.status_code == 200
    page = first_page.json()
    assert len(page["items"]) == 2
    assert page["next_cursor"]

    second_page = await http.get(
        f"/seller/transactions?limit=2&cursor={page['next_cursor']}", headers=headers
    )
    assert second_page.status_code == 200
    page2 = second_page.json()
    assert len(page2["items"]) == 1
    assert page2["next_cursor"] is None

    seen = {item["transaction_id"] for item in page["items"] + page2["items"]}
    assert seen == {award_body["transaction_id"] for award_body in awards}


async def test_seller_list_rejects_bad_state_limit_seller_id_and_cursor(client):
    http, app = client
    await award(http, award_for("run-1", "northwind-audio"))
    headers = await _seed_and_headers(
        app, "northwind-audio", clerk_org_id="org_northwind", sub="user_nw"
    )

    bad_state = await http.get("/seller/transactions?state=bogus", headers=headers)
    assert bad_state.status_code == 400

    low_limit = await http.get("/seller/transactions?limit=0", headers=headers)
    assert low_limit.status_code == 400

    high_limit = await http.get("/seller/transactions?limit=201", headers=headers)
    assert high_limit.status_code == 400

    seller_id = await http.get("/seller/transactions?seller_id=other-seller", headers=headers)
    assert seller_id.status_code == 400

    bad_cursor = await http.get("/seller/transactions?cursor=@@!!", headers=headers)
    assert bad_cursor.status_code == 400


async def test_seller_list_state_filter(client):
    http, app = client
    body = await award(http, award_for("run-1", "northwind-audio"))
    headers = await _seed_and_headers(
        app, "northwind-audio", clerk_org_id="org_northwind", sub="user_nw"
    )

    missing = await http.get("/seller/transactions?state=FUNDED", headers=headers)
    assert missing.json()["items"] == []

    awarded = await http.get("/seller/transactions?state=AWARDED", headers=headers)
    assert [item["transaction_id"] for item in awarded.json()["items"]] == [
        body["transaction_id"]
    ]


async def funded_transaction(http, run_id: str, seller_id: str = "northwind-audio"):
    body = await award(http, award_for(run_id, seller_id))
    await accept(http, body, seller_id=seller_id)
    await approve(http, body)
    await fund_and_capture(http, body)
    po = purchase_order(body)
    po["offer_id"] = f"offer-{run_id}"
    reported = await http.post(
        f"/transactions/{body['transaction_id']}/purchase-order",
        json=po,
        headers={**OPS, "idempotency-key": f"po:{body['transaction_id']}"},
    )
    assert reported.status_code == 200, reported.text
    return body


async def test_seller_evidence_library_lists_and_filters(client):
    http, app = client
    body = await funded_transaction(http, "run-1")
    other = await funded_transaction(http, "run-2", "other-seller")
    manifest = b'{"tracking_number":"TRK-1","carrier":"Northwind Logistics"}'

    nw_headers = await _seed_and_headers(
        app, "northwind-audio", clerk_org_id="org_northwind", sub="user_nw"
    )
    uploaded = await http.post(
        f"/seller/transactions/{body['transaction_id']}/evidence",
        headers=nw_headers,
        data={"requirement_id": "shipment_manifest"},
        files={"file": ("manifest.json", manifest, "application/json")},
    )
    assert uploaded.status_code == 201, uploaded.text

    response = await http.get("/seller/evidence", headers=nw_headers)
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    entry = items[0]
    assert entry["transaction_id"] == body["transaction_id"]
    assert entry["requirement_id"] == "shipment_manifest"
    assert entry["kind"] == "shipment_manifest"
    assert entry["scan_status"] == "pending"
    assert entry["transaction_state"] == "VERIFICATION_PENDING"
    assert entry["verification"]["status"] == "pending"

    by_requirement = await http.get(
        "/seller/evidence?requirement_id=shipment_manifest", headers=nw_headers
    )
    assert len(by_requirement.json()["items"]) == 1
    by_invoice = await http.get(
        "/seller/evidence?requirement_id=invoice", headers=nw_headers
    )
    assert by_invoice.json()["items"] == []
    by_kind = await http.get(
        "/seller/evidence?kind=shipment_manifest", headers=nw_headers
    )
    assert len(by_kind.json()["items"]) == 1

    other_headers = await _seed_and_headers(
        app, "other-seller", clerk_org_id="org_other", sub="user_other"
    )
    other_view = await http.get("/seller/evidence", headers=other_headers)
    assert other_view.json()["items"] == []


async def test_seller_payouts_view_maps_statuses_and_scopes(client):
    http, app = client
    repo = app.state.repo
    paid = await award(http, award_for("run-1", "northwind-audio"))
    pending = await award(http, award_for("run-2", "northwind-audio"))
    await award(http, award_for("run-3", "other-seller"))

    nw_headers = await _seed_and_headers(
        app, "northwind-audio", clerk_org_id="org_northwind", sub="user_nw"
    )
    other_headers = await _seed_and_headers(
        app, "other-seller", clerk_org_id="org_other", sub="user_other"
    )

    for award_body, status in ((paid, "SUCCESS"), (pending, "PENDING")):
        async with repo.transaction() as conn:
            current = await repo.get_transaction(award_body["transaction_id"], conn)
            await repo.update_transaction(
                conn,
                award_body["transaction_id"],
                expected_version=current.version,
                changes={
                    "payout": {
                        "status": status,
                        "batch_id": f"batch-{status}",
                        "item_id": f"item-{status}",
                        "amount_cents": 123400,
                        "updated_at": NOW.isoformat(),
                    }
                },
            )

    response = await http.get("/seller/payouts", headers=nw_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    by_id = {entry["transaction_id"]: entry for entry in body["transactions"]}
    assert set(by_id) == {paid["transaction_id"], pending["transaction_id"]}
    assert by_id[paid["transaction_id"]]["payout"]["status"] == "paid"
    assert by_id[pending["transaction_id"]]["payout"]["status"] == "pending"
    assert body["totals"]["paid_cents"] == 123400
    assert body["totals"]["pending_cents"] == 123400
    assert body["totals"]["failed_cents"] == 0

    other_award = await award(http, award_for("run-3b", "other-seller"))
    other_view = await http.get("/seller/payouts", headers=other_headers)
    other_body = other_view.json()
    # other-seller has run-3 and run-3b
    assert len(other_body["transactions"]) == 2
    assert all(entry["payout"] is None for entry in other_body["transactions"])
    assert other_body["totals"] == {
        "pending_cents": 0,
        "paid_cents": 0,
        "failed_cents": 0,
    }

    projection = await http.get(
        f"/seller/transactions/{paid['transaction_id']}", headers=nw_headers
    )
    assert projection.json()["payout"]["status"] == "SUCCESS"


async def test_seller_can_read_events_and_agreement(client):
    http, app = client
    body = await award(http, award_for("run-1", "northwind-audio"))
    headers = await _seed_and_headers(
        app, "northwind-audio", clerk_org_id="org_northwind", sub="user_nw"
    )

    events = await http.get(
        f"/seller/transactions/{body['transaction_id']}/events", headers=headers
    )
    assert events.status_code == 200, events.text
    payload = events.json()
    assert "items" in payload
    assert payload["items"]
    assert all("seq" in entry and "type" in entry for entry in payload["items"])

    agreement_id = body["agreement"]["agreement_id"]
    agreement = await http.get(f"/seller/agreements/{agreement_id}", headers=headers)
    assert agreement.status_code == 200, agreement.text
    body_json = agreement.json()
    assert body_json["terms"]["requirements"]


async def test_seller_events_unknown_transaction_returns_404(client):
    http, app = client
    await award(http, award_for("run-1", "northwind-audio"))
    headers = await _seed_and_headers(
        app, "northwind-audio", clerk_org_id="org_northwind", sub="user_nw"
    )
    missing = await http.get(
        "/seller/transactions/txn_missing/events", headers=headers
    )
    assert missing.status_code == 404


def seller_requirement_catalog() -> list[dict]:
    return [
        {
            "requirement_id": "product_photos",
            "title": "Product photos",
            "description": "Photo of the item before shipment.",
            "owner": "seller",
            "kind": "product_photos",
            "source": "file",
            "accepted_formats": ["image/jpeg", "image/webp"],
            "checks": [
                {
                    "check_id": "at_least_one_photo",
                    "description": "At least one intact photo is present.",
                    "operator": "exists",
                    "verification_method": "deterministic",
                    "ai_derived": False,
                }
            ],
            "required": True,
        },
        {
            "requirement_id": "delivery_confirmation",
            "title": "Delivery confirmation",
            "description": "System-generated from the carrier record.",
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


async def test_seller_projection_exposes_catalog_agreement_and_dispute(client):
    http, app = client
    body = await award(
        http, award_payload(requirements=seller_requirement_catalog())
    )
    txid = body["transaction_id"]
    headers = await _seed_and_headers(
        app, "northwind-audio", clerk_org_id="org_northwind", sub="user_nw"
    )
    repo = app.state.repo
    async with repo.transaction() as conn:
        current = await repo.get_transaction(txid, conn)
        await repo.update_transaction(
            conn,
            txid,
            expected_version=current.version,
            changes={
                "dispute": {
                    "status": "open",
                    "reason_code": "not_as_described",
                    "requirement_ids": ["product_photos"],
                    "claim": "arrived damaged",
                    "opened_at": NOW.isoformat(),
                    "escalation_rung": 0,
                }
            },
        )

    response = await http.get(f"/seller/transactions/{txid}", headers=headers)
    assert response.status_code == 200, response.text
    projection = response.json()
    assert projection["agreement_id"] == body["agreement"]["agreement_id"]
    assert [item["requirement_id"] for item in projection["requirements"]] == [
        "product_photos",
        "delivery_confirmation",
    ]
    assert projection["requirements"][0]["accepted_formats"] == [
        "image/jpeg",
        "image/webp",
    ]
    assert projection["dispute"]["status"] == "open"
    assert projection["dispute"]["claim"] == "arrived damaged"


async def test_seller_agreement_cross_seller_returns_not_found(client):
    http, app = client
    first = await award(http, award_for("run-1", "northwind-audio"))
    await award(http, award_for("run-2", "other-seller"))
    await _seed_and_headers(
        app, "northwind-audio", clerk_org_id="org_northwind", sub="user_nw"
    )
    other_headers = await _seed_and_headers(
        app, "other-seller", clerk_org_id="org_other", sub="user_other"
    )
    agreement_id = first["agreement"]["agreement_id"]
    response = await http.get(f"/seller/agreements/{agreement_id}", headers=other_headers)
    assert response.status_code in {403, 404}


async def test_seller_events_pagination_round_trips(client):
    http, app = client
    body = await funded_transaction(http, "run-1", "northwind-audio")
    headers = await _seed_and_headers(
        app, "northwind-audio", clerk_org_id="org_northwind", sub="user_nw"
    )
    await http.post(
        f"/seller/transactions/{body['transaction_id']}/evidence",
        headers=headers,
        data={"requirement_id": "shipment_manifest"},
        files={
            "file": (
                "manifest.json",
                b'{"tracking_number":"TRK-1","carrier":"Northwind Logistics"}',
                "application/json",
            )
        },
    )
    first = await http.get(
        f"/seller/transactions/{body['transaction_id']}/events?limit=2",
        headers=headers,
    )
    assert first.status_code == 200
    page = first.json()
    assert len(page["items"]) <= 2
    if page.get("next_cursor"):
        second = await http.get(
            f"/seller/transactions/{body['transaction_id']}/events?limit=2&cursor={page['next_cursor']}",
            headers=headers,
        )
        assert second.status_code == 200

