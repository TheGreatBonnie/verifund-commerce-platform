from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from a2a.types.a2a_pb2 import TaskState
from google.protobuf import json_format

from buyer_agent.a2a_client import A2ATurn
from buyer_agent.registry_client import SellerEndpoint
from commerce_core.contracts import (
    CounterOffer,
    Offer,
    OfferLineItem,
    OfferStatus,
    OfferTerms,
    PurchaseOrderRequest,
    RFQ,
)
from tests.support.cards import build_test_card


def make_card(name: str, port: int, rating: float, sustainable: bool):
    raw = json_format.MessageToDict(build_test_card())
    raw["name"] = name
    raw["provider"]["organization"] = name
    raw["provider"]["url"] = f"http://127.0.0.1:{port}"
    raw["supportedInterfaces"][0]["url"] = f"http://127.0.0.1:{port}/a2a"
    raw["capabilities"]["extensions"][0]["params"] = {
        "rating": rating,
        "sustainability_certified": sustainable,
    }
    return json_format.ParseDict(raw, build_test_card().__class__())


SELLER_SPECS = {
    "northwind-audio": {
        "name": "Northwind Audio",
        "port": 9201,
        "rating": 4.8,
        "sustainable": True,
        "initial": 30300,
        "final": 28100,
        "delivery": 3,
        "warranty": 36,
        "returns": 30,
    },
    "circuitforge": {
        "name": "CircuitForge",
        "port": 9202,
        "rating": 4.6,
        "sustainable": True,
        "initial": 29900,
        "final": 26912,
        "delivery": 5,
        "warranty": 24,
        "returns": 30,
    },
    "aurora-supply": {
        "name": "Aurora Supply",
        "port": 9203,
        "rating": 4.4,
        "sustainable": False,
        "initial": 31000,
        "final": 28333,
        "delivery": 7,
        "warranty": 24,
        "returns": 30,
    },
}


def _offer(
    endpoint: SellerEndpoint,
    *,
    request_id: str,
    unit_price_cents: int,
    status: OfferStatus,
    round_number: int,
    spec: dict[str, Any],
) -> Offer:
    quantity = 12
    line_item = OfferLineItem(
        sku="NC-700-BLK",
        name="Nimbus NC-700 ANC Headset",
        quantity=quantity,
        unit_price_cents=unit_price_cents,
        list_unit_price_cents=32900,
        warranty_addon_cents=0,
        attributes={"color": "black"},
    )
    return Offer(
        offer_id=f"offer-{endpoint.seller_id}-{status.value}-{round_number}",
        request_id=request_id,
        seller_id=endpoint.seller_id,
        seller_name=endpoint.name,
        seller_rating=endpoint.rating,
        task_id=f"task-{endpoint.seller_id}",
        context_id="run-test",
        line_items=[line_item],
        subtotal_cents=unit_price_cents * quantity,
        shipping_cents=0,
        total_cents=unit_price_cents * quantity,
        delivery_days=spec["delivery"],
        warranty_months=spec["warranty"],
        returns_days=spec["returns"],
        valid_until=datetime.now(UTC) + timedelta(hours=1),
        terms=OfferTerms(
            sustainability_certified=endpoint.sustainability_certified,
            stock_confidence=1.0,
            split_shipment=False,
        ),
        status=status,
        round=round_number,
        rationale="Fake scripted negotiation offer.",
    )


class FakeTrace:
    def __init__(self) -> None:
        self.decisions: list[dict] = []
        self.runs: dict[str, dict] = {}

    async def upsert_run(self, run_id: str, **fields: Any) -> None:
        self.runs.setdefault(run_id, {}).update(fields)

    async def record(self, run_id: str, **fields: Any) -> None:
        self.decisions.append({"run_id": run_id, **fields})


class FakeRegistry:
    def __init__(self) -> None:
        self._endpoints: dict[str, SellerEndpoint] = {}
        for seller_id, spec in SELLER_SPECS.items():
            card = make_card(
                spec["name"],
                spec["port"],
                spec["rating"],
                spec["sustainable"],
            )
            self._endpoints[seller_id] = SellerEndpoint(
                seller_id=seller_id,
                name=spec["name"],
                card_url=(
                    f"http://127.0.0.1:{spec['port']}"
                    "/.well-known/agent-card.json"
                ),
                card=card,
                token=f"{seller_id}-token",
                rating=spec["rating"],
                sustainability_certified=spec["sustainable"],
            )

    async def discover(self, category: str) -> list[SellerEndpoint]:
        return list(self._endpoints.values())

    def endpoint(self, seller_id: str) -> SellerEndpoint:
        return self._endpoints[seller_id]


class FakeSession:
    def __init__(self, endpoint: SellerEndpoint, a2a: "ScriptedA2AClient") -> None:
        self.endpoint = endpoint
        self.a2a = a2a
        self.task_id: str | None = None
        self.request_id: str | None = None

    async def send_rfq(self, rfq: RFQ, context_id: str) -> A2ATurn:
        self.request_id = rfq.request_id
        self.task_id = f"task-{self.endpoint.seller_id}-{uuid.uuid4().hex[:6]}"
        self.a2a.sent_rfqs.append(rfq)
        self.a2a.sent_rfq_texts.append(rfq.message or "")
        spec = SELLER_SPECS[self.endpoint.seller_id]
        offer = _offer(
            self.endpoint,
            request_id=rfq.request_id,
            unit_price_cents=spec["initial"],
            status=OfferStatus.PROPOSED,
            round_number=1,
            spec=spec,
        ).model_copy(update={"task_id": self.task_id, "context_id": context_id})
        return A2ATurn(
            task_id=self.task_id,
            context_id=context_id,
            state=TaskState.TASK_STATE_INPUT_REQUIRED,
            offers=[offer],
        )

    async def send_counter(
        self, task_id: str, context_id: str, counter: CounterOffer
    ) -> A2ATurn:
        self.a2a.counters.append((self.endpoint.seller_id, counter))
        spec = SELLER_SPECS[self.endpoint.seller_id]
        final = _offer(
            self.endpoint,
            request_id=self.request_id or "rfq-missing",
            unit_price_cents=spec["final"],
            status=OfferStatus.FINAL,
            round_number=counter.negotiation_round,
            spec=spec,
        ).model_copy(
            update={"task_id": task_id, "context_id": context_id}
        )
        return A2ATurn(
            task_id=task_id,
            context_id=context_id,
            state=TaskState.TASK_STATE_INPUT_REQUIRED,
            offers=[final],
        )

    async def send_accept(self, task_id: str, context_id: str, accept):
        self.a2a.accepted.append((self.endpoint.seller_id, accept))
        return A2ATurn(
            task_id=task_id,
            context_id=context_id,
            state=TaskState.TASK_STATE_COMPLETED,
        )

    async def send_order(
        self, po: PurchaseOrderRequest, context_id: str
    ) -> A2ATurn:
        self.a2a.orders.append((self.endpoint.seller_id, po))
        return A2ATurn(
            task_id=f"task-order-{self.endpoint.seller_id}",
            context_id=context_id,
            state=TaskState.TASK_STATE_COMPLETED,
        )

    async def cancel(self, task_id: str):
        self.a2a.cancelled.append((self.endpoint.seller_id, task_id))
        return None

    async def close(self) -> None:
        return None


class ScriptedA2AClient:
    def __init__(self) -> None:
        self.sent_rfqs: list[RFQ] = []
        self.sent_rfq_texts: list[str] = []
        self.counters: list[tuple[str, CounterOffer]] = []
        self.accepted: list[tuple[str, Any]] = []
        self.orders: list[tuple[str, PurchaseOrderRequest]] = []
        self.cancelled: list[tuple[str, str]] = []

    async def open_session(
        self, endpoint: SellerEndpoint, run_id: str
    ) -> FakeSession:
        return FakeSession(endpoint, self)


@dataclass
class FakeServices:
    registry: FakeRegistry = field(default_factory=FakeRegistry)
    a2a: ScriptedA2AClient = field(default_factory=ScriptedA2AClient)
    trace: FakeTrace = field(default_factory=FakeTrace)
