from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from buyer_agent.graph import create_settlement_award
from verifund_contracts import (
    AgreementProjection,
    AwardLineItem,
    AwardRequest,
    BuyerAgreementRequest,
    RemedyPolicy,
    RemedyTerms,
)


def award_request(**overrides) -> AwardRequest:
    payload = {
        "run_id": "run-1",
        "buyer_id": "demo-buyer",
        "seller_id": "northwind-audio",
        "offer_id": "offer-1",
        "request_id": "rfq-1",
        "buyer_display_name": "Demo Buyer",
        "seller_display_name": "Northwind Audio",
        "currency": "USD",
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
                "warranty_addon_cents": 0,
                "attributes": {},
            }
        ],
        "delivery_days": 7,
        "warranty_months": 24,
        "returns_days": 30,
        "offer_round": 1,
        "offer_hash": "a" * 64,
        "offer_valid_until": (
            datetime.now(UTC) + timedelta(hours=1)
        ).isoformat(),
        "evidence_required": ["shipment_manifest", "delivery_confirmation", "invoice"],
        "remedies": {
            "non_delivery": "cancel_and_refund",
            "late_delivery": "cancel_and_refund",
            "damaged_goods": "refund_or_replacement",
        },
        "dispute_window_hours": 72,
    }
    return AwardRequest(**{**payload, **overrides})


def projection() -> dict[str, Any]:
    payload: dict[str, Any] = {
            "agreement_id": "agr_1",
            "agreement_version": 1,
            "transaction_id": "vf_1",
            "run_id": "run-1",
            "buyer_id": "demo-buyer",
            "seller_id": "northwind-audio",
            "offer_id": "offer-1",
            "offer_round": 1,
            "offer_hash": "a" * 64,
            "offer_valid_until": "2099-10-27T12:00:00Z",
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
                    "attributes": {},
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
            "evidence_required": ["shipment_manifest", "delivery_confirmation", "invoice"],
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
                "evidence_required": ["shipment_manifest", "delivery_confirmation", "invoice"],
                "remedies": {
                    "non_delivery": "cancel_and_refund",
                    "late_delivery": "cancel_and_refund",
                    "damaged_goods": "refund_or_replacement",
                },
                "dispute_window_hours": 72,
            },
            "status": "PENDING_SELLER",
            "created_at": "2099-10-27T12:00:00Z",
    }
    payload.pop("agreement_hash", None)
    probe = AgreementProjection.model_construct(**payload, agreement_hash="0" * 64)
    return AgreementProjection(**payload, agreement_hash=probe.recompute_hash()).model_dump(
        mode="json"
    )


async def test_the_buyer_refuses_an_award_that_is_not_its_own() -> None:
    from buyer_agent.agreement_service import (
        AgreementBindingError,
        BuyerAgreementService,
    )

    class Store:
        async def get_award(self, run_id: str):
            return award_request().model_dump(mode="json")

    class Client:
        async def award(self, award, *, idempotency_key=None):
            raise AssertionError("the posted award must never reach the control plane")

    service = BuyerAgreementService(Client(), store=Store())
    with pytest.raises(AgreementBindingError) as excinfo:
        await service.create_agreement(
            "run-1",
            BuyerAgreementRequest(
                award=award_request(warranty_months=36),
                buyer_task_id="buyer-task-1",
                buyer_context_id="run-1",
                idempotency_key="award:run-1:offer-1",
            ),
        )
    assert excinfo.value.status_code == 409


async def test_the_buyer_creates_the_agreement_from_its_own_award() -> None:
    from buyer_agent.agreement_service import BuyerAgreementService

    captured: dict[str, Any] = {}

    class Store:
        async def get_award(self, run_id: str):
            return award_request().model_dump(mode="json")

        async def save_secret(self, **kwargs) -> None:
            captured["secret"] = kwargs

        async def save_projection(self, run_id, projection):
            captured["projection"] = projection
            return True

    class Client:
        async def award(self, award, *, idempotency_key=None):
            captured["award"] = award
            captured["key"] = idempotency_key
            return {
                "transaction_id": "vf_1",
                "state": "AWARDED",
                "agreement": projection(),
                "agreement_version": 1,
                "agreement_hash": projection()["agreement_hash"],
                "seller_token": "v1.secret",
                "expires_at": "2099-10-27T12:00:00Z",
            }

        async def get_state(self, transaction_id):
            return {"transaction_id": transaction_id, "state": "AWARDED", "last_seq": 1}

    service = BuyerAgreementService(Client(), store=Store())
    await service.create_agreement(
        "run-1",
        BuyerAgreementRequest(
            award=None,
            buyer_task_id="buyer-task-1",
            buyer_context_id="run-1",
            idempotency_key="stale-key",
        ),
    )

    assert captured["award"].amount_cents == 123400
    assert captured["key"] == "award:run-1:offer-1"
    assert captured["secret"]["transaction_id"] == "vf_1"


async def test_one_award_creates_one_transaction() -> None:
    from buyer_agent.agreement_service import BuyerAgreementService

    keys: list[str] = []

    class Store:
        async def get_award(self, run_id: str):
            return award_request().model_dump(mode="json")

        async def save_secret(self, **kwargs) -> None:
            return None

        async def save_projection(self, run_id, projection):
            return True

    class Client:
        async def award(self, award, *, idempotency_key=None):
            keys.append(idempotency_key)
            return {
                "transaction_id": "vf_1",
                "state": "AWARDED",
                "agreement": projection(),
                "agreement_version": 1,
                "agreement_hash": projection()["agreement_hash"],
                "seller_token": "v1.secret",
                "expires_at": "2099-10-27T12:00:00Z",
            }

        async def get_state(self, transaction_id):
            return {"transaction_id": transaction_id, "state": "AWARDED", "last_seq": 1}

    service = BuyerAgreementService(Client(), store=Store())
    request = BuyerAgreementRequest(
        award=None,
        buyer_task_id="buyer-task-1",
        buyer_context_id="run-1",
        idempotency_key="award:run-1:offer-1",
    )
    await service.create_agreement("run-1", request)
    await service.create_agreement("run-1", request)

    assert keys == ["award:run-1:offer-1", "award:run-1:offer-1"]


class RecordingSettlement:
    def __init__(self) -> None:
        self.awards: dict[str, dict[str, Any]] = {}

    async def save_award(self, run_id: str, award: dict[str, Any]) -> None:
        self.awards[run_id] = award


def _state() -> dict[str, Any]:
    return {
        "run_id": "run-1",
        "task_id": "task-1",
        "context_id": "run-1",
        "mandate": {"buyer_id": "demo-buyer"},
        "award": {
            "winner": {
                "seller_id": "northwind-audio",
                "seller_name": "Northwind Audio",
                "offer_id": "offer-1",
                "request_id": "rfq-1",
                "currency": "USD",
                "total_cents": 123400,
                "shipping_cents": 3400,
                "tax_cents": 0,
                "fees_cents": 0,
                "quantity": 12,
                "delivery_days": 7,
                "warranty_months": 24,
                "returns_days": 30,
                "valid_until": (
                    datetime.now(UTC) + timedelta(hours=1)
                ).isoformat(),
                "line_items": [
                    {
                        "sku": "NC-700",
                        "name": "Nimbus NC-700 ANC Headset",
                        "quantity": 12,
                        "unit_price_cents": 10000,
                        "warranty_addon_cents": 0,
                        "attributes": {},
                    }
                ],
            }
        },
        "sellers": [
            {"seller_id": "northwind-audio", "card_url": "http://seller/card"}
        ],
    }


async def test_the_buyer_persists_the_award_it_pauses_with() -> None:
    settlement = RecordingSettlement()
    services = SimpleNamespace(settlement=settlement, trace=None, registry=None)

    with pytest.raises(Exception):
        await create_settlement_award(_state(), {"configurable": {"services": services}})

    assert "run-1" in settlement.awards
    award = settlement.awards["run-1"]
    assert award["run_id"] == "run-1"
    assert award["offer_id"] == "offer-1"
    assert award["amount_cents"] == 123400
    assert award["requirements"], "the buyer must persist its obligation catalog"


async def test_the_buyer_serves_its_stored_award() -> None:
    import httpx
    from buyer_agent import settlement_api
    from fastapi import FastAPI

    class Store:
        async def get_award(self, run_id: str):
            if run_id == "run-1":
                return {"run_id": "run-1", "offer_id": "offer-1"}
            return None

    class Agreements:
        def __init__(self) -> None:
            self.store = Store()

    app = FastAPI()
    app.include_router(settlement_api.router)
    app.state.services = SimpleNamespace(agreements=Agreements())
    app.state.settings = SimpleNamespace(verifund_agent_internal_token="agent-internal")

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        found = await client.get(
            "/internal/runs/run-1/settlement/award",
            headers={"x-verifund-agent-token": "agent-internal"},
        )
        missing = await client.get(
            "/internal/runs/other/settlement/award",
            headers={"x-verifund-agent-token": "agent-internal"},
        )
        unauthorized = await client.get(
            "/internal/runs/run-1/settlement/award",
            headers={"x-verifund-agent-token": "wrong"},
        )
    assert found.status_code == 200
    assert found.json()["award"]["offer_id"] == "offer-1"
    assert missing.status_code == 404
    assert unauthorized.status_code == 401
