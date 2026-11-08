from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
import respx
from buyer_agent.registry_client import RegistryClient
from buyer_agent.trace import TraceStore
from commerce_core.cards import parse_agent_card, validate_agent_card
from google.protobuf import json_format
from sqlalchemy.ext.asyncio import create_async_engine

from tests.support.cards import build_test_card


@dataclass
class BuyerServices:
    registry: RegistryClient
    trace: TraceStore


@pytest.fixture
def seller_cards() -> dict[str, dict]:
    base = json_format.MessageToDict(
        build_test_card(), preserving_proto_field_name=False
    )
    cards = {}
    for seller_id, name, port in (
        ("northwind-audio", "Northwind Audio", 9201),
        ("circuitforge", "CircuitForge", 9202),
        ("aurora-supply", "Aurora Supply", 9203),
    ):
        card = copy.deepcopy(base)
        card["name"] = name
        card["provider"]["organization"] = name
        card["provider"]["url"] = f"http://127.0.0.1:{port}"
        card["supportedInterfaces"][0]["url"] = (
            f"http://127.0.0.1:{port}/a2a"
        )
        cards[seller_id] = card
    return cards


@pytest.fixture
async def buyer_services(tmp_path: Path, seller_cards: dict[str, dict]):
    with respx.mock(assert_all_called=False) as mock:
        mock.post("http://registry.test/v1/discover").mock(
            return_value=httpx.Response(
                200,
                json={
                    "sellers": [
                        {
                            "seller_id": seller_id,
                            "card_url": (
                                f"http://127.0.0.1:{port}"
                                "/.well-known/agent-card.json"
                            ),
                        }
                        for seller_id, port in (
                            ("northwind-audio", 9201),
                            ("circuitforge", 9202),
                            ("aurora-supply", 9203),
                        )
                    ]
                },
            )
        )
        for seller_id, port in (
            ("northwind-audio", 9201),
            ("circuitforge", 9202),
            ("aurora-supply", 9203),
        ):
            mock.get(
                f"http://127.0.0.1:{port}/.well-known/agent-card.json"
            ).mock(
                side_effect=lambda request, sid=seller_id: httpx.Response(
                    200, json=seller_cards[sid]
                )
            )
        engine = create_async_engine(
            f"sqlite+aiosqlite:///{tmp_path / 'buyer.db'}"
        )
        trace = TraceStore(engine)
        await trace.create_schema()
        for seller_id in ("northwind-audio", "circuitforge", "aurora-supply"):
            mock.post("http://cp.test/v1/internal/agent-token").mock(
                return_value=httpx.Response(
                    200,
                    json={
                        "agent_id": f"agent_{seller_id}",
                        "token": f"{seller_id}-token",
                        "scopes": ["a2a:call"],
                    },
                )
            )
        client = httpx.AsyncClient()
        registry = RegistryClient(
            registry_url="http://registry.test",
            allowed_card_hosts=("127.0.0.1",),
            control_plane_url="http://cp.test",
            buyer_internal_token="dev-buyer-internal",
            trace=trace,
            client=client,
        )
        try:
            yield BuyerServices(registry=registry, trace=trace)
        finally:
            await registry.close()
            await engine.dispose()


async def test_buyer_validates_cards_independently(
    buyer_services, seller_cards
):
    sellers = await buyer_services.registry.discover("consumer-electronics")
    assert len(sellers) == 3
    for seller in sellers:
        assert seller.card.name
        assert validate_agent_card(seller.card) == []
        assert validate_agent_card(
            parse_agent_card(seller_cards[seller.seller_id])
        ) == []
    assert buyer_services.registry.fetch_calls == 3
    cached = buyer_services.registry.endpoint("northwind-audio")
    assert cached.seller_id == "northwind-audio"
    assert cached.name == "Northwind Audio"


async def test_invalid_card_is_excluded(
    buyer_services, seller_cards, monkeypatch
):
    seller_cards["circuitforge"]["capabilities"]["streaming"] = False
    sellers = await buyer_services.registry.discover("consumer-electronics")
    assert {seller.seller_id for seller in sellers} == {
        "northwind-audio",
        "aurora-supply",
    }
