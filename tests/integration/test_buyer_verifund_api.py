from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from buyer_agent import settlement_api
from buyer_agent.agreement_service import AgreementBindingError, BuyerAgreementService
from buyer_agent.settlement_client import BuyerSettlementClient
from buyer_agent.settlement_store import SettlementStore
from fastapi import FastAPI
from verifund_contracts import (
    AgreementProjection,
    BuyerOrderReportRequest,
    BuyerPurchaseOrderRequest,
    ReleaseApprovalDecision,
)

NOW = datetime(2026, 10, 27, 12, 0, tzinfo=UTC)
HASH = "a" * 64
HEADERS = {"x-verifund-agent-token": "agent-internal"}


def projection(state: str = "AWARDED") -> dict:
    return {
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "state": state,
        "last_seq": 4,
        "amount_cents": 123400,
        "currency": "USD",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "agreement_hash": HASH,
        "agreement_version": 1,
        "buyer_agent_review": {"status": "accepted"},
        "seller_decision": {"status": "accepted"},
        "approval": None,
        "cancellation": None,
        "funding": None,
        "purchase_order": None,
        "evidence": None,
        "verification": None,
        "payout": None,
        "receipt_available": False,
        "deadlines": {"evidence": None, "inspection": None},
        "allowed_actions": [],
        "updated_at": "2026-10-27T12:00:00Z",
    }


def agreement() -> dict:
    return {
        "agreement_id": "agr_1",
        "agreement_version": 1,
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "offer_round": 1,
        "offer_hash": "a" * 64,
        "offer_valid_until": "2026-10-28T12:00:00Z",
        "currency": "USD",
        "amount_cents": 123400,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
                "warranty_addon_cents": 0,
            }
        ],
        "shipping_cents": 3400,
        "tax_cents": 0,
        "fees_cents": 0,
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "inspection_period_hours": 48,
        "inspection_starts_on": "DELIVERY_CONFIRMED",
        "evidence_required": [
            "shipment_manifest",
            "delivery_confirmation",
            "invoice",
        ],
        "remedies": {
            "non_delivery": "cancel_and_refund",
            "late_delivery": "cancel_and_refund",
            "damaged_goods": "refund_or_replacement",
        },
        "dispute_window_hours": 72,
        "terms": {
            "schema": "verifund.agreement.v1",
            "agreement_type": "goods",
            "terms_version": 1,
            "totals": {
                "subtotal_cents": 120000,
                "shipping_cents": 3400,
                "tax_cents": 0,
                "fees_cents": 0,
                "total_cents": 123400,
            },
            "delivery": {"delivery_days": 7},
            "warranty": {"warranty_months": 24},
            "returns": {"returns_days": 30},
            "inspection": {"period_hours": 48, "starts_on": "DELIVERY_CONFIRMED"},
            "evidence_required": [
                "shipment_manifest",
                "delivery_confirmation",
                "invoice",
            ],
            "remedies": {
                "non_delivery": "cancel_and_refund",
                "late_delivery": "cancel_and_refund",
                "damaged_goods": "refund_or_replacement",
            },
            "dispute_window_hours": 72,
        },
        "status": "PENDING_SELLER",
        "expires_at": None,
        "created_at": "2026-10-27T12:00:00Z",
        "agreement_hash": HASH,
    }


def award_body(**overrides) -> dict:
    award = {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "request_id": "rfq-1",
        "buyer_display_name": "Demo Buyer",
        "seller_display_name": "Northwind Audio",
        "amount_cents": 123400,
        "shipping_cents": 3400,
        "tax_cents": 0,
        "fees_cents": 0,
        "quantity": 12,
        "line_items": [
            {
                "sku": "NC-700",
                "name": "Nimbus NC-700 ANC Headset",
                "quantity": 12,
                "unit_price_cents": 10000,
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "offer_round": 1,
        "offer_hash": HASH,
        "offer_valid_until": "2026-10-28T12:00:00Z",
    }
    award.update(overrides)
    return award


def valid_agreement() -> dict:
    body = {key: value for key, value in agreement().items() if key != "agreement_hash"}
    probe = AgreementProjection.model_construct(**body, agreement_hash="0" * 64)
    return AgreementProjection(
        **body, agreement_hash=probe.recompute_hash()
    ).model_dump(mode="json")


class Agreements:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.current = projection()

    async def create_agreement(self, run_id, request):
        self.calls.append(("create", run_id, request))
        return {
            "transaction_id": "vf_1",
            "state": "AWARDED",
            "agreement": agreement(),
            "agreement_version": 1,
            "agreement_hash": HASH,
            "seller_token_ref": "run:run-1:transaction:vf_1",
        }

    async def view(self, run_id):
        self.calls.append(("view", run_id))
        return {
            "run_id": run_id,
            "transaction_id": "vf_1",
            "agreement": agreement(),
            "agreement_version": 1,
            "agreement_hash": HASH,
            "seller_token_ref": "run:run-1:transaction:vf_1",
            "projection": self.current,
        }

    async def approve_funding(self, run_id, decision, *, defer_checkout=False):
        self.calls.append(("approve_funding", run_id, decision))
        return {
            "projection": projection("FUNDING_PENDING"),
            "checkout_url": "http://paypal.test/checkout/1",
            "expires_at": "2026-10-27T12:30:00Z",
        }

    async def purchase_order(self, run_id, request):
        self.calls.append(("purchase_order", run_id, request))
        return {
            "run_id": run_id,
            "transaction_id": "vf_1",
            "agreement_version": 1,
            "agreement_hash": HASH,
            "seller_id": "northwind-audio",
            "offer_id": "offer-1",
            "amount_cents": 123400,
            "seller_token_ref": "run:run-1:transaction:vf_1",
            "purchase_order": {
                "request_id": "po-run-1-offer-1",
                "run_id": run_id,
                "offer_id": "offer-1",
                "seller_id": "northwind-audio",
                "quantity": 12,
                "expected_total_cents": 123400,
                "settlement_transaction_id": "vf_1",
                "agreement_hash": HASH,
            },
        }

    async def order(self, run_id, request):
        self.calls.append(("order", run_id, request))
        return {
            "run_id": run_id,
            "transaction_id": "vf_1",
            "agreement_version": 1,
            "agreement_hash": HASH,
            "state": "FULFILLMENT_PENDING",
            "projection": {
                "transaction_id": "vf_1",
                "state": "FULFILLMENT_PENDING",
            },
        }

    async def release(self, run_id, decision):
        self.calls.append(("release", run_id, decision))
        return projection("PAYOUT_PENDING")

    async def receipt(self, run_id):
        self.calls.append(("receipt", run_id))
        return {"payload": {}, "signature": "sig", "kid": "k1", "verified": True}

    async def evidence(self, run_id, evidence_id):
        self.calls.append(("evidence", run_id, evidence_id))
        return b"manifest", "text/plain", "manifest.txt"


class Settings:
    verifund_agent_internal_token = "agent-internal"
    console_api_token = "console-token"
    internal_api_token = "internal-token"


class Store:
    async def get_projection(self, run_id):
        return projection()

    async def get_agreement(self, run_id):
        return agreement()


def build():
    services = SimpleNamespace(
        agreements=Agreements(),
        settings=Settings(),
        store=SimpleNamespace(settlement=Store()),
    )
    app = FastAPI()
    app.state.services = services
    app.state.settings = services.settings
    app.include_router(settlement_api.router)
    return app, services


@pytest.fixture
async def api():
    app, services = build()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://buyer") as http:
        yield http, services


async def test_internal_routes_require_the_agent_token(api):
    http, _ = api
    for path in (
        "/internal/runs/run-1/settlement",
        "/internal/runs/run-1/settlement/receipt",
    ):
        refused = await http.get(path)
        assert refused.status_code == 401
        wrong = await http.get(
            path, headers={"x-verifund-agent-token": "wrong"}
        )
        assert wrong.status_code == 401


async def test_agreement_route_rejects_a_run_mismatch(api):
    http, services = api
    body = {
        "award": award_body(run_id="run-2"),
        "buyer_task_id": "buyer-task-1",
        "buyer_context_id": "run-1",
        "idempotency_key": "agreement:run-1:offer-1",
    }
    response = await http.post(
        "/internal/runs/run-1/settlement/agreement",
        headers=HEADERS,
        json=body,
    )
    assert response.status_code == 403
    assert services.agreements.calls == []


async def test_agreement_route_returns_the_canonical_projection_without_a_token(api):
    http, services = api
    body = {
        "award": award_body(),
        "buyer_task_id": "buyer-task-1",
        "buyer_context_id": "run-1",
        "idempotency_key": "agreement:run-1:offer-1",
    }
    response = await http.post(
        "/internal/runs/run-1/settlement/agreement",
        headers=HEADERS,
        json=body,
    )
    assert response.status_code == 200, response.text
    dumped = response.json()
    assert dumped["seller_token_ref"] == "run:run-1:transaction:vf_1"
    assert "seller_token" not in dumped
    assert dumped["agreement"]["agreement_hash"] == HASH
    assert services.agreements.calls[0][0] == "create"


async def test_approve_funding_forwards_the_structured_decision(api):
    http, services = api
    body = {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "approved": True,
        "approved_by": "demo-reviewer",
        "note": "approved",
        "decided_at": "2026-10-27T12:00:00Z",
        "idempotency_key": "fund:run-1:vf_1",
    }
    response = await http.post(
        "/internal/runs/run-1/settlement/approve-funding",
        headers=HEADERS,
        json=body,
    )
    assert response.status_code == 200, response.text
    assert response.json()["checkout_url"].startswith("http://paypal.test/")
    call = services.agreements.calls[-1]
    assert call[0] == "approve_funding"
    assert call[2].approved is True


def po_request(**overrides) -> BuyerPurchaseOrderRequest:
    payload = {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "idempotency_key": "po:run-1:offer-1",
    }
    payload.update(overrides)
    return BuyerPurchaseOrderRequest(**payload)


class PurchaseOrderStore:
    def __init__(self, state: str = "FUNDED") -> None:
        self.projection = {
            **projection(state),
            "approval": {
                "approval_id": "approval-1",
                "approved_by": "demo-reviewer",
                "approved_at": "2026-10-27T12:00:00Z",
                "note": "approved",
            },
        }
        self.agreement = valid_agreement()

    async def get_projection(self, run_id):
        return self.projection if run_id == "run-1" else None

    async def get_agreement(self, run_id):
        return self.agreement if run_id == "run-1" else None

    async def save_projection(self, run_id, projection):
        self.projection = projection
        return True


async def test_purchase_order_builds_the_exact_request_from_the_funded_agreement():
    service = BuyerAgreementService(
        client=cast(BuyerSettlementClient, None),
        store=cast(SettlementStore, PurchaseOrderStore()),
        console_base_url="http://console",
    )
    response = await service.purchase_order("run-1", po_request())
    po = response["purchase_order"]
    assert po["request_id"] == "po-run-1-offer-1"
    assert po["run_id"] == "run-1"
    assert po["offer_id"] == "offer-1"
    assert po["seller_id"] == "northwind-audio"
    assert po["quantity"] == 12
    assert po["expected_total_cents"] == 123400
    assert po["settlement_transaction_id"] == "vf_1"
    assert po["agreement_hash"] == response["agreement_hash"]
    assert po["approval"]["approved_by"] == "demo-reviewer"
    assert "settlement_token" not in po
    assert response["seller_token_ref"] == "run:run-1:transaction:vf_1"


async def test_purchase_order_requires_a_funded_agreement():
    service = BuyerAgreementService(
        client=cast(BuyerSettlementClient, None),
        store=cast(SettlementStore, PurchaseOrderStore(state="AGREED")),
        console_base_url="http://console",
    )
    with pytest.raises(AgreementBindingError) as raised:
        await service.purchase_order("run-1", po_request())
    assert raised.value.status_code == 409


async def test_purchase_order_route_returns_the_buyer_built_order(api):
    http, services = api
    response = await http.post(
        "/internal/runs/run-1/settlement/purchase-order",
        headers=HEADERS,
        json=po_request().model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    dumped = response.json()
    assert dumped["purchase_order"]["settlement_transaction_id"] == "vf_1"
    assert "settlement_token" not in dumped
    assert services.agreements.calls[-1][0] == "purchase_order"


async def test_purchase_order_route_requires_the_agent_token(api):
    http, _ = api
    refused = await http.post(
        "/internal/runs/run-1/settlement/purchase-order",
        json=po_request().model_dump(mode="json"),
    )
    assert refused.status_code == 401


def order_request(**overrides) -> BuyerOrderReportRequest:
    payload = {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "idempotency_key": "order:vf_1",
        "order": {
            "order_id": "ord-1",
            "offer_id": "offer-1",
            "seller_id": "northwind-audio",
            "quantity": 12,
            "total_cents": 123400,
            "currency": "USD",
            "tracking_number": "TRK-1",
            "reserved_at": "2026-10-27T12:00:00Z",
            "eta": "2026-11-03T12:00:00Z",
            "fulfillment": {"carrier": "UPS", "status": "confirmed"},
            "line_items": [
                {
                    "sku": "NC-700",
                    "quantity": 12,
                    "unit_price_cents": 10000,
                    "warranty_addon_cents": 0,
                }
            ],
        },
    }
    payload.update(overrides)
    return BuyerOrderReportRequest.model_validate(payload)


class OrderClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def purchase_order(self, transaction_id, report, *, idempotency_key):
        self.calls.append((transaction_id, report, idempotency_key))
        return {
            "transaction_id": transaction_id,
            "state": "FULFILLMENT_PENDING",
            "agreement_hash": report.agreement_hash,
        }


async def test_order_report_records_the_sellers_confirmation():
    client = OrderClient()
    service = BuyerAgreementService(
        client=cast(BuyerSettlementClient, client),
        store=cast(SettlementStore, PurchaseOrderStore()),
        console_base_url="http://console",
    )
    response = await service.order("run-1", order_request())
    assert response["state"] == "FULFILLMENT_PENDING"
    assert "seller_token" not in response
    transaction_id, report, key = client.calls[0]
    assert transaction_id == "vf_1"
    assert report.seller_order_id == "ord-1"
    assert report.agreement_hash == HASH
    assert report.carrier == "UPS"
    assert key == "order:vf_1"


async def test_order_report_must_match_the_agreed_terms():
    service = BuyerAgreementService(
        client=cast(BuyerSettlementClient, OrderClient()),
        store=cast(SettlementStore, PurchaseOrderStore()),
        console_base_url="http://console",
    )
    broken = order_request()
    broken.order["total_cents"] = 1
    with pytest.raises(AgreementBindingError) as raised:
        await service.order("run-1", broken)
    assert raised.value.status_code == 409


async def test_order_route_records_the_sellers_confirmation(api):
    http, services = api
    response = await http.post(
        "/internal/runs/run-1/settlement/order",
        headers=HEADERS,
        json=order_request().model_dump(mode="json"),
    )
    assert response.status_code == 200, response.text
    assert response.json()["state"] == "FULFILLMENT_PENDING"
    assert services.agreements.calls[-1][0] == "order"


async def test_order_route_requires_the_agent_token(api):
    http, _ = api
    refused = await http.post(
        "/internal/runs/run-1/settlement/order",
        json=order_request().model_dump(mode="json"),
    )
    assert refused.status_code == 401


class ReleaseClient:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def flag_review(self, transaction_id, request, *, actor):
        self.calls.append(("flag_review", transaction_id, request, actor))
        return projection("REVIEW_REQUIRED")


async def test_release_rejection_flags_manual_review():
    client = ReleaseClient()
    service = BuyerAgreementService(
        client=cast(BuyerSettlementClient, client),
        store=cast(SettlementStore, PurchaseOrderStore()),
        console_base_url="http://console",
    )
    decision = ReleaseApprovalDecision(
        run_id="run-1",
        transaction_id="vf_1",
        agreement_version=1,
        agreement_hash=HASH,
        approved=False,
        released_by="demo-reviewer",
        note="evidence missing",
        decided_at=NOW,
        idempotency_key="release:run-1:vf_1",
    )
    response = await service.release("run-1", decision)
    assert response["state"] == "REVIEW_REQUIRED"
    assert [call[0] for call in client.calls] == ["flag_review"]
    assert client.calls[0][2].reason.value == "manual_flag"
    assert client.calls[0][2].note == "evidence missing"


async def test_release_requires_an_override_note(api):
    http, _ = api
    body = {
        "run_id": "run-1",
        "transaction_id": "vf_1",
        "agreement_version": 1,
        "agreement_hash": HASH,
        "approved": True,
        "released_by": "demo-reviewer",
        "note": "",
        "override": True,
        "decided_at": "2026-10-27T12:00:00Z",
        "idempotency_key": "release:run-1:vf_1",
    }
    response = await http.post(
        "/internal/runs/run-1/settlement/release",
        headers=HEADERS,
        json=body,
    )
    assert response.status_code == 422


async def test_receipt_and_evidence_are_proxied(api):
    http, _ = api
    receipt = await http.get(
        "/internal/runs/run-1/settlement/receipt", headers=HEADERS
    )
    assert receipt.status_code == 200
    assert receipt.json()["verified"] is True

    evidence = await http.get(
        "/internal/runs/run-1/settlement/evidence/ev_1", headers=HEADERS
    )
    assert evidence.status_code == 200
    assert evidence.content == b"manifest"
    assert "manifest.txt" in evidence.headers["content-disposition"]
