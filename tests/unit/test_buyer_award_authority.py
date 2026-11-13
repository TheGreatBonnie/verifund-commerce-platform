from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from buyer_agent.graph import create_settlement_award


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
