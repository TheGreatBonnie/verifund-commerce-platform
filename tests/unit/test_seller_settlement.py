from __future__ import annotations

from datetime import UTC, datetime

import httpx
import respx
from commerce_core.contracts import Fulfillment, OfferLineItem, Order, OrderStatus
from seller_agent.settlement import SellerSettlementClient, encode_payload

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)


def order() -> Order:
    return Order(
        order_id="MM-DEMO",
        offer_id="offer-1",
        seller_id="northwind-audio",
        status=OrderStatus.CONFIRMED,
        quantity=2,
        total_cents=20000,
        line_items=[
            OfferLineItem(
                sku="NC-700",
                name="Nimbus NC-700",
                quantity=2,
                unit_price_cents=10000,
                list_unit_price_cents=12000,
                warranty_addon_cents=0,
                attributes={},
            )
        ],
        reserved_at=NOW,
        eta=NOW,
        tracking_number="TRK-1",
        fulfillment=Fulfillment(carrier="Northwind Logistics", status="reserved"),
    )


@respx.mock
async def test_get_transaction_uses_internal_service_auth():
    route = respx.get(
        "http://control/seller/transactions/vf_1"
    ).mock(return_value=httpx.Response(200, json={"state": "AWARDED"}))
    client = SellerSettlementClient("http://control", internal_token="secret")
    projection = await client.get_transaction(
        "vf_1",
        organization_id="org_test",
        seller_id="northwind-audio",
    )
    assert projection["state"] == "AWARDED"
    request = route.calls[0].request
    assert request.headers["x-verifund-internal-token"] == "secret"
    assert request.headers["x-seller-org-id"] == "org_test"
    assert request.headers["x-seller-id"] == "northwind-audio"
    assert "authorization" not in request.headers
    await client.close()


@respx.mock
async def test_upload_evidence_posts_multipart_without_leaking_the_token():
    route = respx.post(
        "http://control/seller/transactions/vf_1/evidence"
    ).mock(return_value=httpx.Response(201, json={"evidence_id": "ev_1"}))
    client = SellerSettlementClient("http://control", internal_token="secret")
    response = await client.upload_evidence(
        "vf_1",
        organization_id="org_test",
        seller_id="northwind-audio",
        requirement_id="shipment_manifest",
        content=b'{"tracking_number":"TRK-1"}',
        media_type="application/json",
        filename="manifest.json",
        note="auto",
    )
    assert response["evidence_id"] == "ev_1"
    request = route.calls[0].request
    assert request.headers["x-verifund-internal-token"] == "secret"
    assert request.headers["x-seller-org-id"] == "org_test"
    assert request.headers["x-seller-id"] == "northwind-audio"
    assert "authorization" not in request.headers
    assert b'name="requirement_id"' in request.content
    assert b"shipment_manifest" in request.content
    assert b'name="kind"' not in request.content
    assert b"TRK-1" in request.content
    await client.close()


def test_encode_payload_is_key_order_stable():
    payload = {"b": 2, "a": 1}
    assert encode_payload(payload) == encode_payload(dict(reversed(list(payload.items()))))
