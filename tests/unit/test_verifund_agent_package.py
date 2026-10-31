from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import respx
from langgraph.checkpoint.memory import MemorySaver
from verifund_agent.card import build_card
from verifund_agent.client import BuyerInternalClient
from verifund_agent.graph import VerifundState, build_graph
from verifund_agent.settings import Settings
from verifund_contracts import (
    AwardRequest,
    BuyerAgreementRequest,
    BuyerOrderReportRequest,
    BuyerPurchaseOrderRequest,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)

REQUIRED_SKILLS = {
    "verifund.agreement.create",
    "verifund.transaction.status",
    "verifund.transaction.fund",
    "verifund.evidence.review",
    "verifund.transaction.release",
    "verifund.receipt.get",
}


def test_card_exposes_all_verifund_skills_without_commerce_extension() -> None:
    card = build_card("http://127.0.0.1:9301")
    assert {skill.id for skill in card.skills} == REQUIRED_SKILLS
    assert all(
        extension.uri != "https://marketmesh.example/extensions/commerce/v1"
        for extension in card.capabilities.extensions
    )
    assert card.capabilities.streaming is True
    assert "bearer" in card.security_schemes


def test_settings_hold_no_control_plane_seller_or_paypal_credentials() -> None:
    settings = Settings()
    forbidden = {
        "ops_token",
        "verifund_ops_token",
        "seller_token_secret",
        "paypal_client_id",
        "paypal_client_secret",
    }
    assert forbidden.isdisjoint(settings.model_dump())
    assert settings.buyer_internal_token
    assert settings.a2a_token
    assert settings.a2a_token != settings.buyer_internal_token


def test_graph_compiles_with_a_durable_checkpointer() -> None:
    saver = MemorySaver()
    graph = build_graph(saver)
    assert graph.checkpointer is saver
    assert "initialize" in graph.get_graph().nodes
    assert {"run_id", "task_id", "checkpoint", "agreement"} <= set(
        VerifundState.__annotations__
    )


@respx.mock
async def test_buyer_client_uses_only_the_agent_internal_header() -> None:
    route = respx.get("http://buyer/internal/runs/run-1/settlement").mock(
        return_value=httpx.Response(200, json={"projection": {"state": "AGREED"}})
    )
    client = BuyerInternalClient(
        "http://buyer",
        internal_token="agent-internal",
    )
    await client.get_settlement("run-1")
    request = route.calls[0].request
    assert request.headers["x-verifund-agent-token"] == "agent-internal"
    assert "authorization" not in request.headers
    assert "ops-token" not in str(request.headers)


@respx.mock
async def test_buyer_client_creates_an_agreement_with_the_exact_award() -> None:
    route = respx.post(
        "http://buyer/internal/runs/run-1/settlement/agreement"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "transaction_id": "vf_1",
                "state": "AWARDED",
                "agreement": {},
                "agreement_version": 1,
                "agreement_hash": "a" * 64,
                "seller_token_ref": "run:run-1:transaction:vf_1",
            },
        )
    )
    client = BuyerInternalClient(
        "http://buyer",
        internal_token="agent-internal",
    )
    request = BuyerAgreementRequest(
        award=AwardRequest(
            run_id="run-1",
            buyer_id="demo-buyer",
            seller_id="northwind-audio",
            offer_id="offer-1",
            request_id="rfq-1",
            buyer_display_name="Demo Buyer",
            seller_display_name="Northwind Audio",
            amount_cents=123400,
            shipping_cents=3400,
            tax_cents=0,
            fees_cents=0,
            quantity=12,
            line_items=[
                {
                    "sku": "NC-700",
                    "name": "Nimbus NC-700 ANC Headset",
                    "quantity": 12,
                    "unit_price_cents": 10000,
                }
            ],
            delivery_days=7,
            warranty_months=24,
            returns_days=30,
            offer_round=1,
            offer_hash="a" * 64,
            offer_valid_until=NOW,
        ),
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        idempotency_key="agreement:run-1:offer-1",
    )
    await client.create_agreement("run-1", request)
    body = json.loads(route.calls[0].request.read())
    assert body["award"]["run_id"] == "run-1"
    assert body["buyer_task_id"] == "buyer-task-1"
    assert route.calls[0].request.headers["x-verifund-agent-token"] == "agent-internal"


@respx.mock
async def test_buyer_client_requests_the_exact_purchase_order() -> None:
    route = respx.post(
        "http://buyer/internal/runs/run-1/settlement/purchase-order"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "run_id": "run-1",
                "transaction_id": "vf_1",
                "agreement_version": 1,
                "agreement_hash": "a" * 64,
                "seller_id": "northwind-audio",
                "offer_id": "offer-1",
                "amount_cents": 123400,
                "seller_token_ref": "run:run-1:transaction:vf_1",
                "purchase_order": {},
            },
        )
    )
    client = BuyerInternalClient(
        "http://buyer",
        internal_token="agent-internal",
    )
    request = BuyerPurchaseOrderRequest(
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash="a" * 64,
        idempotency_key="po:run-1:offer-1",
    )
    await client.purchase_order("run-1", request)
    body = json.loads(route.calls[0].request.read())
    assert body["idempotency_key"] == "po:run-1:offer-1"
    assert route.calls[0].request.headers["x-verifund-agent-token"] == "agent-internal"


@respx.mock
async def test_buyer_client_reports_the_sellers_confirmed_order() -> None:
    route = respx.post(
        "http://buyer/internal/runs/run-1/settlement/order"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "run_id": "run-1",
                "transaction_id": "vf_1",
                "agreement_version": 1,
                "agreement_hash": "a" * 64,
                "state": "FULFILLMENT_PENDING",
                "projection": {
                    "transaction_id": "vf_1",
                    "state": "FULFILLMENT_PENDING",
                },
            },
        )
    )
    client = BuyerInternalClient(
        "http://buyer",
        internal_token="agent-internal",
    )
    request = BuyerOrderReportRequest(
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash="a" * 64,
        idempotency_key="order:vf_1",
        order={"order_id": "ord-1", "offer_id": "offer-1"},
    )
    await client.report_order("run-1", request)
    body = json.loads(route.calls[0].request.read())
    assert body["order"]["order_id"] == "ord-1"
    assert body["idempotency_key"] == "order:vf_1"
    assert route.calls[0].request.headers["x-verifund-agent-token"] == "agent-internal"


def test_server_requires_the_a2a_bearer_token() -> None:
    from fastapi.testclient import TestClient
    from verifund_agent.server import create_app

    app = create_app(
        Settings(
            a2a_token="a2a-secret",
            database_url="sqlite+aiosqlite:///:memory:",
        ),
        MemorySaver(),
    )
    assert app.state.task_store.__class__.__name__ == "DatabaseTaskStore"
    with TestClient(app) as http:
        refused = http.post("/a2a", json={})
        assert refused.status_code == 401
        allowed = http.post(
            "/a2a",
            headers={"authorization": "Bearer a2a-secret"},
            json={},
        )
        assert allowed.status_code != 401
