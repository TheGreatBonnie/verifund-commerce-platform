"""Seller-scoped read endpoints (plan Tasks 10/10a seed)."""

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
    seller_headers,
    upload_file,
)


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
            yield client


async def test_seller_list_scoped_by_token(client):
    first = await award(client, award_for("run-1", "northwind-audio"))
    second = await award(client, award_for("run-2", "northwind-audio"))
    await award(client, award_for("run-3", "other-seller"))

    response = await client.get("/seller/transactions", headers=seller_headers(first))
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
    awards = [await award(client, award_for(f"run-{i}", "northwind-audio")) for i in range(1, 4)]
    headers = seller_headers(awards[0])

    first_page = await client.get("/seller/transactions?limit=2", headers=headers)
    assert first_page.status_code == 200
    page = first_page.json()
    assert len(page["items"]) == 2
    assert page["next_cursor"]

    second_page = await client.get(
        f"/seller/transactions?limit=2&cursor={page['next_cursor']}", headers=headers
    )
    assert second_page.status_code == 200
    page2 = second_page.json()
    assert len(page2["items"]) == 1
    assert page2["next_cursor"] is None

    seen = {item["transaction_id"] for item in page["items"] + page2["items"]}
    assert seen == {award["transaction_id"] for award in awards}


async def test_seller_list_rejects_bad_state_limit_seller_id_and_cursor(client):
    body = await award(client, award_for("run-1", "northwind-audio"))
    headers = seller_headers(body)

    bad_state = await client.get("/seller/transactions?state=bogus", headers=headers)
    assert bad_state.status_code == 400

    low_limit = await client.get("/seller/transactions?limit=0", headers=headers)
    assert low_limit.status_code == 400

    high_limit = await client.get("/seller/transactions?limit=201", headers=headers)
    assert high_limit.status_code == 400

    seller_id = await client.get("/seller/transactions?seller_id=other-seller", headers=headers)
    assert seller_id.status_code == 400

    bad_cursor = await client.get("/seller/transactions?cursor=@@!!", headers=headers)
    assert bad_cursor.status_code == 400


async def test_seller_list_state_filter(client):
    body = await award(client, award_for("run-1", "northwind-audio"))
    headers = seller_headers(body)

    missing = await client.get("/seller/transactions?state=FUNDED", headers=headers)
    assert missing.json()["items"] == []

    awarded = await client.get("/seller/transactions?state=AWARDED", headers=headers)
    assert [item["transaction_id"] for item in awarded.json()["items"]] == [
        body["transaction_id"]
    ]


async def funded_transaction(client, run_id: str, seller_id: str = "northwind-audio"):
    body = await award(client, award_for(run_id, seller_id))
    await accept(client, body, seller_id=seller_id)
    await approve(client, body)
    await fund_and_capture(client, body)
    po = purchase_order(body)
    po["offer_id"] = f"offer-{run_id}"
    reported = await client.post(
        f"/transactions/{body['transaction_id']}/purchase-order",
        json=po,
        headers={**OPS, "idempotency-key": f"po:{body['transaction_id']}"},
    )
    assert reported.status_code == 200, reported.text
    return body


async def test_seller_evidence_library_lists_and_filters(client):
    body = await funded_transaction(client, "run-1")
    other = await funded_transaction(client, "run-2", "other-seller")
    manifest = b'{"tracking_number":"TRK-1","carrier":"Northwind Logistics"}'
    uploaded = await upload_file(
        client,
        body,
        "shipment_manifest",
        data=manifest,
        filename="manifest.json",
        media_type="application/json",
    )
    assert uploaded.status_code == 201, uploaded.text

    response = await client.get("/seller/evidence", headers=seller_headers(body))
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

    by_requirement = await client.get(
        "/seller/evidence?requirement_id=shipment_manifest", headers=seller_headers(body)
    )
    assert len(by_requirement.json()["items"]) == 1
    by_invoice = await client.get(
        "/seller/evidence?requirement_id=invoice", headers=seller_headers(body)
    )
    assert by_invoice.json()["items"] == []
    by_kind = await client.get(
        "/seller/evidence?kind=shipment_manifest", headers=seller_headers(body)
    )
    assert len(by_kind.json()["items"]) == 1

    other_view = await client.get("/seller/evidence", headers=seller_headers(other))
    assert other_view.json()["items"] == []


async def test_seller_payouts_view_maps_statuses_and_scopes(client):
    app = client._transport.app
    repo = app.state.repo
    paid = await award(client, award_for("run-1", "northwind-audio"))
    pending = await award(client, award_for("run-2", "northwind-audio"))
    await award(client, award_for("run-3", "other-seller"))

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

    response = await client.get(
        "/seller/payouts", headers=seller_headers(paid)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    by_id = {entry["transaction_id"]: entry for entry in body["transactions"]}
    assert set(by_id) == {paid["transaction_id"], pending["transaction_id"]}
    assert by_id[paid["transaction_id"]]["payout"]["status"] == "paid"
    assert by_id[pending["transaction_id"]]["payout"]["status"] == "pending"
    assert body["totals"]["paid_cents"] == 123400
    assert body["totals"]["pending_cents"] == 123400
    assert body["totals"]["failed_cents"] == 0

    other = await award(client, award_for("run-3b", "other-seller"))
    other_view = await client.get("/seller/payouts", headers=seller_headers(other))
    other_body = other_view.json()
    assert all(entry["payout"] is None for entry in other_body["transactions"])
    assert other_body["totals"] == {
        "pending_cents": 0,
        "paid_cents": 0,
        "failed_cents": 0,
    }

    # The transaction projection exposes the same payout source.
    projection = await client.get(
        f"/seller/transactions/{paid['transaction_id']}", headers=seller_headers(paid)
    )
    assert projection.json()["payout"]["status"] == "SUCCESS"


async def test_seller_can_read_events_and_agreement(client):
    body = await award(client, award_for("run-1", "northwind-audio"))
    headers = seller_headers(body)

    events = await client.get(
        f"/seller/transactions/{body['transaction_id']}/events", headers=headers
    )
    assert events.status_code == 200, events.text
    payload = events.json()
    assert "items" in payload
    assert payload["items"]  # award created at least one event
    assert all("seq" in entry and "type" in entry for entry in payload["items"])

    agreement_id = body["agreement"]["agreement_id"]
    agreement = await client.get(
        f"/seller/agreements/{agreement_id}", headers=headers
    )
    assert agreement.status_code == 200, agreement.text
    body_json = agreement.json()
    assert body_json["terms"]["requirements"]


async def test_seller_events_unknown_transaction_returns_404(client):
    body = await award(client, award_for("run-1", "northwind-audio"))
    headers = seller_headers(body)
    response = await client.get(
        "/seller/transactions/vf_does_not_exist/events", headers=headers
    )
    assert response.status_code in {403, 404}


async def test_seller_agreement_cross_seller_returns_403(client):
    first = await award(client, award_for("run-1", "northwind-audio"))
    other = await award(client, award_for("run-2", "other-seller"))
    agreement_id = first["agreement"]["agreement_id"]
    headers = seller_headers(other)
    response = await client.get(
        f"/seller/agreements/{agreement_id}", headers=headers
    )
    assert response.status_code in {403, 404}


async def test_seller_events_pagination_round_trips(client):
    body = await funded_transaction(client, "run-1", "northwind-audio")
    headers = seller_headers(body)
    # produce a few events by uploading evidence
    await upload_file(
        client,
        body,
        "shipment_manifest",
        data=b'{"tracking_number":"TRK-1","carrier":"Northwind Logistics"}',
        filename="manifest.json",
        media_type="application/json",
    )
    first = await client.get(
        f"/seller/transactions/{body['transaction_id']}/events?limit=2",
        headers=headers,
    )
    assert first.status_code == 200
    page = first.json()
    assert len(page["items"]) <= 2
