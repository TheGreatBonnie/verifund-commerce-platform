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
async def test_get_transaction_uses_the_seller_bearer_token():
    route = respx.get(
        "http://control/seller/transactions/vf_1"
    ).mock(return_value=httpx.Response(200, json={"state": "AWARDED"}))
    client = SellerSettlementClient("http://control")
    projection = await client.get_transaction("v1.secret", "vf_1")
    assert projection["state"] == "AWARDED"
    assert route.calls[0].request.headers["authorization"] == "Bearer v1.secret"
    await client.close()


@respx.mock
async def test_upload_evidence_posts_multipart_without_leaking_the_token():
    route = respx.post(
        "http://control/seller/transactions/vf_1/evidence"
    ).mock(return_value=httpx.Response(201, json={"evidence_id": "ev_1"}))
    client = SellerSettlementClient("http://control")
    response = await client.upload_evidence(
        "v1.secret",
        "vf_1",
        kind="shipment_manifest",
        content=b'{"tracking_number":"TRK-1"}',
        media_type="application/json",
        filename="manifest.json",
        note="auto",
    )
    assert response["evidence_id"] == "ev_1"
    request = route.calls[0].request
    assert request.headers["authorization"] == "Bearer v1.secret"
    assert b'name="kind"' in request.content
    assert b"shipment_manifest" in request.content
    assert b"TRK-1" in request.content
    await client.close()


def test_encode_payload_is_key_order_stable():
    payload = {"b": 2, "a": 1}
    assert encode_payload(payload) == encode_payload(dict(reversed(list(payload.items()))))
