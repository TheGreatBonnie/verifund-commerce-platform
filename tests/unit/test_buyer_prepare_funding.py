from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from buyer_agent import settlement_api
from buyer_agent.agreement_service import BuyerAgreementService
from buyer_agent.settlement_client import BuyerSettlementClient
from buyer_agent.settlement_store import SettlementStore
from fastapi import FastAPI
from verifund_contracts import CancelReason

HASH = "a" * 64
HEADERS = {"x-verifund-agent-token": "agent-internal"}
SESSION = {
    "transaction_id": "vf_1",
    "amount_cents": 123400,
    "currency": "USD",
    "expires_at": "2026-10-28T12:00:00Z",
    "agreement_version": 1,
    "agreement_hash": HASH,
    "order_attempt": 0,
    "provider_order_id": None,
}


def projection() -> dict:
    return {
        "transaction_id": "vf_1",
        "run_id": "run-1",
        "state": "AGREED",
        "agreement_version": 1,
        "agreement_hash": HASH,
    }


class Store:
    def __init__(self) -> None:
        self.saved: list[dict] = []

    async def get_projection(self, run_id):
        return projection()

    async def get_agreement(self, run_id):
        return {"agreement_id": "agr_1", "transaction_id": "vf_1"}

    async def save_projection(self, run_id, value):
        self.saved.append(value)
        return True


class Client:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def prepare_funding(self, transaction_id, *, actor="buyer-agent"):
        self.calls.append(("prepare_funding", transaction_id, actor))
        return SESSION

    async def cancel(self, transaction_id, request, *, actor=None):
        self.calls.append(("cancel", transaction_id, request, actor))
        return {**projection(), "state": "CANCELED"}


def service(client: Client) -> BuyerAgreementService:
    return BuyerAgreementService(
        client=cast(BuyerSettlementClient, client),
        store=cast(SettlementStore, Store()),
        console_base_url="http://console",
    )


async def test_prepare_funding_returns_the_control_plane_session():
    client = Client()
    result = await service(client).prepare_funding("run-1")

    assert result == {"checkout_session": SESSION}
    assert client.calls == [("prepare_funding", "vf_1", "buyer-agent")]


async def test_cancel_reports_the_buyer_cancellation():
    client = Client()
    result = await service(client).cancel(
        "run-1", reason_code="buyer_cancelled", note="closed the popup"
    )

    assert result["state"] == "CANCELED"
    kind, transaction_id, request, actor = client.calls[0]
    assert kind == "cancel"
    assert transaction_id == "vf_1"
    assert request.reason_code is CancelReason.BUYER_CANCELLED
    assert request.note == "closed the popup"
    assert actor == "buyer-agent"


class Agreements:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    async def prepare_funding(self, run_id):
        self.calls.append(("prepare_funding", run_id))
        return {"checkout_session": SESSION}

    async def cancel(self, run_id, *, reason_code, note):
        self.calls.append(("cancel", run_id, reason_code, note))
        return {**projection(), "state": "CANCELED"}


def build(agreements: Any) -> FastAPI:
    app = FastAPI()
    app.state.services = SimpleNamespace(agreements=agreements)
    app.state.settings = SimpleNamespace(verifund_agent_internal_token="agent-internal")
    app.include_router(settlement_api.router)
    return app


@pytest.fixture
async def api():
    agreements = Agreements()
    app = build(agreements)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://buyer") as http:
        yield http, agreements


async def test_prepare_route_wraps_the_session_and_requires_the_agent_token(api):
    http, _ = api
    refused = await http.post("/internal/runs/run-1/settlement/prepare-funding")
    assert refused.status_code == 401

    response = await http.post(
        "/internal/runs/run-1/settlement/prepare-funding", headers=HEADERS
    )

    assert response.status_code == 200, response.text
    assert response.json()["checkout_session"]["transaction_id"] == "vf_1"


async def test_cancel_route_passes_the_reason_through(api):
    http, agreements = api
    body = {"reason_code": "buyer_cancelled", "note": "closed the popup"}

    refused = await http.post("/internal/runs/run-1/settlement/cancel", json=body)
    assert refused.status_code == 401

    response = await http.post(
        "/internal/runs/run-1/settlement/cancel", json=body, headers=HEADERS
    )

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "CANCELED"
    assert agreements.calls[-1] == (
        "cancel",
        "run-1",
        "buyer_cancelled",
        "closed the popup",
    )
